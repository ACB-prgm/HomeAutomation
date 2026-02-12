# speech_engine.py
from __future__ import annotations

import enum
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .audio import AudioConfig, AudioInput
from .vad import SherpaVAD, VadBackend
from .wakeword import SherpaWakeword, WakewordConfig


SPEECH_DIR = Path(__file__).resolve().parent
MODELS_DIR = SPEECH_DIR / "models"


class _State(enum.Enum):
	LISTEN_WAKEWORD = 1
	CAPTURE_UTTERANCE = 2


class SpeechEngine:
	def __init__(
		self,
		wakeword: SherpaWakeword = None,
		audio_in: AudioInput = None,
		vad: VadBackend = None,
		sample_rate: int = 16000,
		max_utterance_s: float = 10.0,
		debug: bool = False,
		input_gain: float = 1.0,
		wake_rms_gate: float = 0.0035,
		wake_gate_hold_frames: int = 8,
	):
		self.sample_rate = sample_rate
		self.debug = debug
		self.input_gain = float(input_gain)
		self.wake_rms_gate = float(wake_rms_gate)
		self.wake_gate_hold_frames = max(0, int(wake_gate_hold_frames))
		self._wake_gate_open_frames = 0

		self._on_wakeword: Optional[Callable[[dict], None]] = print
		self._on_utterance_ended: Optional[Callable[[np.ndarray, int], None]] = print
		self.max_utterance_s = max_utterance_s
		self._state = _State.LISTEN_WAKEWORD
		self._utt_buf: list[np.ndarray] = []
		self._utt_start_t: float = 0.0

		if wakeword:
			self.wakeword = wakeword
		else:
			cfg = WakewordConfig(sample_rate=self.sample_rate)
			self.wakeword = SherpaWakeword(cfg=cfg)

		if audio_in:
			self.audio_in = audio_in
		else:
			cfg = AudioConfig(sample_rate=self.sample_rate)
			self.audio_in = AudioInput(cfg=cfg)

		if vad:
			self.vad = vad
		else:
			self.vad = SherpaVAD(
				sample_rate=self.sample_rate,
				max_speech_duration=max_utterance_s,
			)

	def start(self) -> None:
		self.audio_in.start()
		self._state = _State.LISTEN_WAKEWORD

		frame_n = int(self.sample_rate * 0.02)
		for frame in self.audio_in.frames():
			if len(frame) < frame_n:
				frame = np.pad(frame, (0, frame_n - len(frame)))
			if self.input_gain != 1.0:
				frame = np.clip(frame * self.input_gain, -1.0, 1.0)

			match self._state:
				case _State.LISTEN_WAKEWORD:
					if self._wake_gate_is_open(frame):
						self.listen_wakeword(frame)
				case _State.CAPTURE_UTTERANCE:
					self.vad.accept_audio(frame)
					self._utt_buf.append(frame)
					self.capture_utterance()

	def _wake_gate_is_open(self, frame: np.ndarray) -> bool:
		# Avoid wakeword decode work on pure silence.
		if self.wake_rms_gate <= 0:
			return True
		rms = float(np.sqrt(np.mean(frame * frame) + 1e-12))
		if rms >= self.wake_rms_gate:
			self._wake_gate_open_frames = self.wake_gate_hold_frames
			return True
		if self._wake_gate_open_frames > 0:
			self._wake_gate_open_frames -= 1
			return True
		return False

	def listen_wakeword(self, frame: np.ndarray) -> None:
		evt = self.wakeword.process(frame)
		if evt:
			if self.debug:
				print("Wakeword detected")

			if self._on_wakeword:
				self._on_wakeword(evt)

			self.vad.reset()
			self._utt_buf = [frame]
			self._state = _State.CAPTURE_UTTERANCE
			self._utt_start_t = time.time()
		else:
			self.vad.clear()

	def capture_utterance(self) -> None:
		timeout = (time.time() - self._utt_start_t) >= self.max_utterance_s
		if self.vad.speech_captured or timeout:
			reason = "vad" if self.vad.speech_captured else "timeout"
			segments = self.vad.get_samples(flush=True)
			if isinstance(segments, list):
				audio = np.concatenate(segments) if segments else np.zeros((0,), dtype=np.float32)
			else:
				audio = np.asarray(segments, dtype=np.float32).reshape(-1)
			if audio.size == 0 and self._utt_buf:
				audio = np.concatenate(self._utt_buf)

			if self._on_utterance_ended:
				self._on_utterance_ended(audio, reason)
			self.vad.reset()
			self._utt_buf = []
			self._state = _State.LISTEN_WAKEWORD

			if self.debug:
				if timeout:
					print("Timeout reached")
				else:
					print("VAD Segment finished")
