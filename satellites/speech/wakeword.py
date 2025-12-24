# wakeword.py
from __future__ import annotations
from typing import Any, Dict, Optional
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from sherpa_onnx import FeatureExtractorConfig, OnlineTransducerModelConfig, \
	OnlineModelConfig, KeywordSpotterConfig, KeywordSpotter



WW_DIR = Path(__file__).resolve().parent / "models/wakeword"


@dataclass(frozen=True)
class WakewordModelPaths:
	# Transducer KWS model files
	encoder: str | Path = WW_DIR / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx "
	decoder: str | Path = WW_DIR / "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
	joiner: str | Path = WW_DIR / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
	# Tokenized keywords
	tokens: str | Path = WW_DIR / "tokens.txt"
	# Only needed for BPE tokenization models (some KWS models require it)
	bpe_model: Optional[str] = None
	# Tokenized keywords file (see sherpa-onnx KWS docs)
	keywords_file: str = "keywords.txt"


@dataclass(frozen=True)
class WakewordConfig:
	sample_rate: int = 16000
	feature_dim: int = 80
	num_threads: int = 2
	provider: str = "cpu"			# "cpu", "cuda", "coreml", etc (depending on build)
	# KWS tuning knobs (tradeoff: miss vs false alarm)
	keywords_score: float = 1.5
	keywords_threshold: float = 0.25
	max_active_paths: int = 4
	num_trailing_blanks: int = 1


class SherpaWakeword:
	"""
	Robust wrapper around sherpa_onnx KeywordSpotter. Normalizes result to a dict.

	Important: KWS in sherpa-onnx is "open vocabulary keyword spotting" driven by a
	tokenized keywords file (see docs). :contentReference[oaicite:3]{index=3}
	"""
	def __init__(
			self, 
			paths: WakewordModelPaths = WakewordModelPaths(), 
			cfg: WakewordConfig = WakewordConfig()
		):

		self.paths = paths
		self.cfg = cfg

		feat_config = FeatureExtractorConfig(
			sampling_rate=cfg.sample_rate,
			feature_dim=cfg.feature_dim,
		)

		transducer = OnlineTransducerModelConfig(
			encoder=paths.encoder,
			decoder=paths.decoder,
			joiner=paths.joiner,
		)

		model_config = OnlineModelConfig(
			transducer=transducer,
			tokens=paths.tokens,
			num_threads=cfg.num_threads,
			provider=cfg.provider,
		)

		# Some builds expose bpe_model on OnlineModelConfig; set if present
		if paths.bpe_model is not None and hasattr(model_config, "bpe_model"):
			setattr(model_config, "bpe_model", paths.bpe_model)

		kws_config = KeywordSpotterConfig(
			feat_config=feat_config,
			model_config=model_config,
			keywords_file=paths.keywords_file,
			max_active_paths=cfg.max_active_paths,
			num_trailing_blanks=cfg.num_trailing_blanks,
			keywords_score=cfg.keywords_score,
			keywords_threshold=cfg.keywords_threshold,
		)

		self._kws = KeywordSpotter(kws_config)
		self._stream = self._kws.create_stream()

	def reset(self) -> None:
		# API name varies across versions; handle both
		if hasattr(self._kws, "reset_stream"):
			self._kws.reset_stream(self._stream)
		elif hasattr(self._kws, "reset"):
			self._kws.reset(self._stream)
		else:
			# recreate stream as last resort
			self._stream = self._kws.create_stream()

	def process(self, audio_f32: np.ndarray) -> Optional[Dict[str, Any]]:
		"""
		Feed a chunk. Returns a dict if a keyword triggered, else None.

		audio_f32: mono float32 [-1,1], arbitrary chunk length
		"""
		x = np.asarray(audio_f32, dtype=np.float32).reshape(-1)

		# pybind signature accepts Sequence[float]; list is the safest interop
		self._stream.accept_waveform(float(self.cfg.sample_rate), x.tolist())

		# Some versions gate decoding with is_ready()
		if hasattr(self._kws, "is_ready"):
			while self._kws.is_ready(self._stream):
				self._kws.decode_stream(self._stream)
		else:
			self._kws.decode_stream(self._stream)

		result = self._get_result()
		if result is None:
			return None

		# Clear state so it can trigger again cleanly
		self.reset()
		return result

	def _get_result(self) -> Optional[Dict[str, Any]]:
		# Common APIs observed in sherpa-onnx builds:
		# - get_result(stream) -> object w/ keyword + timestamps, etc
		# - get_result_as_json(stream) -> str
		# - stream.result (less common for KWS)
		if hasattr(self._kws, "get_result_as_json"):
			s = self._kws.get_result_as_json(self._stream)
			if not s:
				return None
			try:
				import json
				obj = json.loads(s)
			except Exception:
				return {"raw": s}
			kw = obj.get("keyword") or obj.get("text") or ""
			return obj if kw else None

		if hasattr(self._kws, "get_result"):
			r = self._kws.get_result(self._stream)
			if r is None:
				return None

			kw = getattr(r, "keyword", None) or getattr(r, "text", None) or ""
			if not kw:
				return None

			out: Dict[str, Any] = {"keyword": kw}
			for k in ("start_time", "end_time", "timestamps"):
				if hasattr(r, k):
					out[k] = getattr(r, k)
			return out

		# Fallback: try stream.result
		if hasattr(self._stream, "result"):
			r = self._stream.result
			kw = getattr(r, "keyword", None) or getattr(r, "text", None) or ""
			return {"keyword": kw} if kw else None

		return None
