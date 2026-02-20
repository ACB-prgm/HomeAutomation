from __future__ import annotations

from typing import Any, Dict, Optional, Union
from sherpa_onnx import KeywordSpotter
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import time
import json


MODELS_DIR = Path(__file__).resolve().parent / "models"
WW_DIR = MODELS_DIR / "wakeword"
KW_DIR = MODELS_DIR / "wakeword_keywords"


PathLike = Union[str, Path]


@dataclass(frozen=True)
class WakewordModelPaths:
	# Transducer KWS model files
	encoder: PathLike = WW_DIR / "encoder-epoch-12-avg-2-chunk-16-left-64.onnx"
	decoder: PathLike = WW_DIR / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"
	joiner: PathLike = WW_DIR / "joiner-epoch-12-avg-2-chunk-16-left-64.onnx"

	# Token file and tokenized keywords file
	tokens: PathLike = WW_DIR / "tokens.txt"
	keywords_file: PathLike = KW_DIR / "keywords.txt"


@dataclass(frozen=True)
class WakewordConfig:
	sample_rate: int = 16000
	feature_dim: int = 80
	num_threads: int = 4
	provider: str = "cpu"

	# KWS tuning knobs (tradeoff: miss vs false alarm)
	keywords_score: float = 2.5
	keywords_threshold: float = 0.02
	max_active_paths: int = 8
	num_trailing_blanks: int = 1

	# Optional decode guardrails
	max_decode_loops_per_chunk: int = 50  # prevents pathological infinite loops in some builds

def create_keywords_from_raw(
	tokens: str | Path,
	bpe_model: str | Path | None,
	keywords_raw: str | Path,
	keywords_out: str | Path,
	tokens_type: str = "bpe",
	cwd: str | Path | None = None
) -> None:
	import subprocess

	def _p(x: str | Path | None, name: str, check_file: bool = True) -> Path | None:
		assert x is not None
		path = Path(str(x).strip()).expanduser().resolve()
		if check_file and not path.is_file():
			raise FileNotFoundError(f"not found: {name} @ {x}")

		return path

	tokens_p = _p(tokens, "tokens")
	raw_p = _p(keywords_raw, "keywords_raw")
	out_p = _p(keywords_out, "keywords_out", False)
	bpe_p = _p(bpe_model, "bpe_model")
	cwd_p = _p(cwd, "cwd", False) if cwd is not None else None

	cmd = [
		"sherpa-onnx-cli",
		"text2token",
		"--tokens", str(tokens_p),
		"--tokens-type", tokens_type,
		"--bpe-model", str(bpe_p),
		str(raw_p), str(out_p)
	]

	out_p.parent.mkdir(parents=True, exist_ok=True)
	subprocess.run(cmd, check=True, cwd=str(cwd_p) if cwd_p else None)

class SherpaWakeword:
	"""
	Wrapper around sherpa_onnx.KeywordSpotter.

	- process(): feed audio chunk (float32 mono [-1, 1]) and get a normalized event dict or None
	- finalize()/flush(): useful for wav/offline tests to drain final hypotheses
	"""

	def __init__(
		self,
		paths: WakewordModelPaths = WakewordModelPaths(),
		cfg: WakewordConfig = WakewordConfig(),
	):
		self.paths = paths
		self.cfg = cfg

		self._validate_paths()

		self._kws = self._create_keyword_spotter()
		self._stream = self._kws.create_stream()

	def _validate_paths(self) -> None:
		kwp = Path(self.paths.keywords_file)

		if not (kwp.exists() and kwp.is_file()):
			create_keywords_from_raw(
				self.paths.tokens,
				WW_DIR / "bpe.model",
				KW_DIR / "keywords_raw.txt",
				self.paths.keywords_file,
				cwd=KW_DIR
			)

		missing = []
		for p in (self.paths.encoder, self.paths.decoder, self.paths.joiner, self.paths.tokens, self.paths.keywords_file):
			pp = Path(p)
			if not pp.exists():
				missing.append(str(pp))

		if missing:
			raise FileNotFoundError("Missing wakeword asset(s):\n\t" + "\n\t".join(missing))

	def _create_keyword_spotter(self) -> KeywordSpotter:
		# Build a superset of kwargs; we’ll strip unsupported ones if needed.
		kwargs = dict(
			sample_rate=int(self.cfg.sample_rate),
			feature_dim=int(self.cfg.feature_dim),
			keywords_file=str(self.paths.keywords_file),
			encoder=str(self.paths.encoder),
			decoder=str(self.paths.decoder),
			joiner=str(self.paths.joiner),
			tokens=str(self.paths.tokens),
			num_trailing_blanks=int(self.cfg.num_trailing_blanks),
			keywords_threshold=float(self.cfg.keywords_threshold),
			keywords_score=float(self.cfg.keywords_score),
			max_active_paths=int(self.cfg.max_active_paths),
			num_threads=int(self.cfg.num_threads),
			provider=str(self.cfg.provider),
		)

		return KeywordSpotter(**kwargs)

	def reset(self) -> None:
		# API name varies across versions; handle both
		if hasattr(self._kws, "reset_stream"):
			self._kws.reset_stream(self._stream)
		elif hasattr(self._kws, "reset"):
			self._kws.reset(self._stream)
		else:
			self._stream = self._kws.create_stream()

	def process(self, audio_f32: np.ndarray, sample_rate: Optional[int] = None) -> Optional[Dict[str, Any]]:
		"""
		Feed a chunk. Returns a dict if a keyword triggered, else None.

		audio_f32: mono float32 [-1, 1], arbitrary chunk length
		sample_rate: if provided, passed through to accept_waveform; otherwise cfg.sample_rate
		"""
		x = np.asarray(audio_f32, dtype=np.float32).reshape(-1)
		if x.size == 0:
			return None

		sr = float(sample_rate or self.cfg.sample_rate)
		self._stream.accept_waveform(sr, x.tolist())

		self._decode_available()
		result = self._get_result()
		if not result:
			return None
		else:
			self.reset()
			return result

	def _decode_available(self) -> None:
		loops = 0
		while self._kws.is_ready(self._stream):
			self._kws.decode_stream(self._stream)
			loops += 1
			if loops >= self.cfg.max_decode_loops_per_chunk:
				break

	def finalize(self) -> None:
		"""
		Signal end-of-input (useful for wav tests).
		"""
		if hasattr(self._stream, "input_finished"):
			self._stream.input_finished()

	def flush(self, timeout_s: float = 0.25) -> None:
		"""
		Try to drain any remaining decodes after finalize().
		"""
		t0 = time.time()
		while time.time() - t0 < timeout_s:
			if hasattr(self._kws, "is_ready"):
				if not self._kws.is_ready(self._stream):
					break
			self._kws.decode_stream(self._stream)

	def _get_result(self) -> Optional[Dict[str, Any]]:
		# Option 1: JSON string
		if hasattr(self._kws, "get_result"):
			res = self._kws.get_result(self._stream)
		elif hasattr(self._stream, "result"):
			res = self._stream.result
		else:
			return None

		if res in (None, "", {}):
			return None
		
		try:
			obj = json.loads(res) if isinstance(res, str) else res
		except Exception:
			obj = res
		
		return obj
