# speech_engine.py
from __future__ import annotations

import enum
import logging
import time
from pathlib import Path
from typing import Callable, Optional, Protocol

import numpy as np

from utils.runtime_logging import context_extra

from .audio import AudioConfig, AudioInput
from .vad import SherpaVAD, VadBackend
from .wakeword import SherpaWakeword, WakewordConfig


SPEECH_DIR = Path(__file__).resolve().parent
MODELS_DIR = SPEECH_DIR / "models"


class _State(enum.Enum):
	LISTEN_WAKEWORD = 1
	CAPTURE_UTTERANCE = 2


class WakeGate(Protocol):
	def is_open(self, frame: np.ndarray) -> bool: ...
	def metrics(self) -> dict[str, str | bool | float]: ...
	def close(self) -> None: ...


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
		gate: Optional[WakeGate] = None,
		state_listener: Optional[Callable[[str], None]] = None,
	):
		self.logger = logging.getLogger("satellite.speech_engine")
		self.sample_rate = sample_rate
		self.debug = debug
		self.input_gain = float(input_gain)
		self.wake_rms_gate = float(wake_rms_gate)
		self.wake_gate_hold_frames = max(0, int(wake_gate_hold_frames))
		self._wake_gate_open_frames = 0
		self._last_gate_open: Optional[bool] = None

		self._on_wakeword: Optional[Callable[[dict], None]] = print
		self._on_utterance_ended: Optional[Callable[[np.ndarray, str], None]] = print
		self._state_listener = state_listener
		self.max_utterance_s = max_utterance_s
		self._state = _State.LISTEN_WAKEWORD
		self._utt_buf: list[np.ndarray] = []
		self._utt_start_t: float = 0.0
		self._gate = gate

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
		self._emit_state("idle")

		frame_n = int(self.sample_rate * 0.02)
		try:
			for frame in self.audio_in.frames():
				if len(frame) < frame_n:
					frame = np.pad(frame, (0, frame_n - len(frame)))
				if self.input_gain != 1.0:
					frame = np.clip(frame * self.input_gain, -1.0, 1.0)

				match self._state:
					case _State.LISTEN_WAKEWORD:
						if self._gate_is_open(frame):
							self.listen_wakeword(frame)
					case _State.CAPTURE_UTTERANCE:
						self.vad.accept_audio(frame)
						self._utt_buf.append(frame)
						self.capture_utterance()
		finally:
			self.audio_in.stop()
			if self._gate and hasattr(self._gate, "close"):
				self._gate.close()
			self._emit_state("idle")

	def _emit_state(self, state: str) -> None:
		if self._state_listener:
			try:
				self._state_listener(state)
			except Exception:
				self.logger.exception("State listener failed for state=%s", state)

	def _rms_gate_is_open(self, frame: np.ndarray) -> bool:
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

	def _gate_is_open(self, frame: np.ndarray) -> bool:
		metrics: dict[str, str | bool | float] = {
			"gate_mode": "rms",
			"speech_energy": "-",
		}
		if self._gate is not None:
			gate_open = bool(self._gate.is_open(frame))
			try:
				metrics = self._gate.metrics()
			except Exception:
				pass
		else:
			gate_open = self._rms_gate_is_open(frame)

		if self._last_gate_open is None or self._last_gate_open != gate_open:
			self.logger.info(
				"Wake gate transition",
				extra=context_extra(
					gate_mode=str(metrics.get("gate_mode", "rms")),
					gate_open=gate_open,
					speech_energy=metrics.get("speech_energy", "-"),
				),
			)
			self._last_gate_open = gate_open
		return gate_open

	def listen_wakeword(self, frame: np.ndarray) -> None:
		evt = self.wakeword.process(frame)
		if evt:
			if self.debug:
				self.logger.info("Wakeword detected")

			if self._on_wakeword:
				self._on_wakeword(evt)

			self.vad.reset()
			self._utt_buf = [frame]
			self._state = _State.CAPTURE_UTTERANCE
			self._utt_start_t = time.time()
			self._emit_state("wake_detected")
			self._emit_state("capturing_utterance")
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
			self._emit_state("utterance_timeout" if timeout else "utterance_complete")
			self._emit_state("idle")

			if self.debug:
				if timeout:
					self.logger.info("Timeout reached")
				else:
					self.logger.info("VAD segment finished")
