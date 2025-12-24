# speech_engine.py
from __future__ import annotations
from pathlib import Path

import enum
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

import numpy as np

from .audio import AudioInput, AudioConfig
from .asr import ASR
from wakeword import SherpaWakeword

SPEECH_DIR = Path(__file__).resolve().parent
MODELS_DIR = SPEECH_DIR / "models"


class VadBackend(Protocol):
	def reset(self) -> None: ...
	def accept_audio(self, audio_f32: np.ndarray, sample_rate: int) -> None: ...
	def in_speech(self) -> bool: ...
	def utterance_ended(self) -> bool: ...



class _State(enum.Enum):
	LISTEN_WAKEWORD = 1
	CAPTURE_UTTERANCE = 2


@dataclass
class SpeechEngineCallbacks:
	on_wakeword: Optional[Callable[[dict], None]] = None
	on_utterance_audio: Optional[Callable[[np.ndarray, int], None]] = None
	on_transcript: Optional[Callable[[str], None]] = None


class EnergyVad:
	"""
	Ultra-simple VAD fallback so the pipeline runs before you wire sherpa's VAD.
	Not robust, but good enough to validate the state machine.
	"""
	def __init__(self, rms_threshold: float = 0.015, hangover_ms: int = 400, frame_ms: int = 20):
		self.rms_threshold = rms_threshold
		self.hangover_frames = max(1, int(hangover_ms / frame_ms))
		self._speech = False
		self._silence_run = 0

	def reset(self) -> None:
		self._speech = False
		self._silence_run = 0

	def accept_audio(self, audio_f32: np.ndarray, sample_rate: int) -> None:
		x = np.asarray(audio_f32, dtype=np.float32).reshape(-1)
		rms = float(np.sqrt(np.mean(x * x) + 1e-12))
		is_speech = rms >= self.rms_threshold

		if is_speech:
			self._speech = True
			self._silence_run = 0
		else:
			if self._speech:
				self._silence_run += 1

	def in_speech(self) -> bool:
		return self._speech

	def utterance_ended(self) -> bool:
		# ended after some silence following speech
		return self._speech and self._silence_run >= self.hangover_frames


class SpeechEngine:
	def __init__(
		self,
		wakeword: SherpaWakeword,
		vad: VadBackend,
		audio_in: AudioInput = AudioInput(AudioConfig()),
		asr: ASR = ASR(),
		cb: SpeechEngineCallbacks = SpeechEngineCallbacks(),
		max_utterance_s: float = 12.0,
	):
		self.audio_in = audio_in
		self.wakeword = wakeword
		self.vad = vad
		self.asr = asr
		self.cb = cb
		self.max_utterance_s = max_utterance_s
		self._state = _State.LISTEN_WAKEWORD

		self._utt_buf: list[np.ndarray] = []
		self._utt_start_t: float = 0.0

	def run_forever(self) -> None:
		self.audio_in.start()
		self._state = _State.LISTEN_WAKEWORD

		for frame in self.audio_in.frames():
			if self._state == _State.LISTEN_WAKEWORD:
				evt = self.wakeword.process(frame)
				if evt:
					if self.cb.on_wakeword:
						self.cb.on_wakeword(evt)

					self._utt_buf = []
					self._utt_start_t = time.time()
					self.vad.reset()
					self._state = _State.CAPTURE_UTTERANCE

			elif self._state == _State.CAPTURE_UTTERANCE:
				self._utt_buf.append(frame)
				self.vad.accept_audio(frame, self.audio_in.cfg.sample_rate)

				too_long = (time.time() - self._utt_start_t) >= self.max_utterance_s
				if self.vad.utterance_ended() or too_long:
					audio = np.concatenate(self._utt_buf) if self._utt_buf else np.zeros((0,), dtype=np.float32)
					sr = self.audio_in.cfg.sample_rate

					if self.cb.on_utterance_audio:
						self.cb.on_utterance_audio(audio, sr)

					text = self.asr.transcribe_audio(audio, sr).strip()
					if self.cb.on_transcript:
						self.cb.on_transcript(text)

					self._state = _State.LISTEN_WAKEWORD
					self._utt_buf = []