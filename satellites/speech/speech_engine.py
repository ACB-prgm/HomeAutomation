# speech_engine.py
from __future__ import annotations
from pathlib import Path

import enum
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .audio import AudioInput, AudioConfig
from .wakeword import SherpaWakeword, WakewordConfig
from .vad import EnergyVad, SherpaVAD, VadBackend


SPEECH_DIR = Path(__file__).resolve().parent
MODELS_DIR = SPEECH_DIR / "models"


class _State(enum.Enum):
	LISTEN_WAKEWORD = 1
	CAPTURE_UTTERANCE = 2


@dataclass
class SpeechEngineCallbacks:
	on_wakeword: Optional[Callable[[dict], None]] = print
	on_utterance_ended: Optional[Callable[[np.ndarray, int], None]] = print


class SpeechEngine:
	def __init__(
		self,
		wakeword: SherpaWakeword = None,
		audio_in: AudioInput = None,
		vad: VadBackend = None,
		sample_rate: int = 16000,
		callbacks: SpeechEngineCallbacks = SpeechEngineCallbacks(),
		max_utterance_s: float = 10.0,
		debug: bool = False
	):	
		self.sample_rate = sample_rate
		self.debug = debug
		self.callbacks = callbacks
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
				max_speech_duration=max_utterance_s
			)
	
	def start(self) -> None:
		self.audio_in.start()
		self._state = _State.LISTEN_WAKEWORD

		frame_n = int(self.sample_rate * 0.02)
		for frame in self.audio_in.frames():
			if len(frame) < frame_n:
				frame = np.pad(frame, (0, frame_n - len(frame)))
			frame = np.clip(frame * 5.0, -1.0, 1.0)

			self.vad.accept_audio(frame)
			match self._state:
				case _State.LISTEN_WAKEWORD:
					self.listen_wakeword(frame)
				case _State.CAPTURE_UTTERANCE:
					self.capture_utterance()
	
	def listen_wakeword(self, frame):
		evt = self.wakeword.process(frame)
		if evt:
			if self.debug:
				print("wakeword detected")

			if self.callbacks.on_wakeword:
				self.callbacks.on_wakeword(evt)

			self._utt_buf = [frame]
			self._state = _State.CAPTURE_UTTERANCE
			self._utt_start_t = time.time()
		else:
			self.vad.clear()
	
	def capture_utterance(self):
		timeout = (time.time() - self._utt_start_t) >= self.max_utterance_s
		if self.vad.speech_captured or timeout:
			reason = "vad" if self.vad.speech_captured else "timeout"
			audio = np.concatenate(self.vad.get_samples(flush=True))

			if self.callbacks.on_utterance_ended:
				self.callbacks.on_utterance_ended(audio, reason)
			self.vad.reset()
			self._state = _State.LISTEN_WAKEWORD

			if self.debug:
				if timeout:
					print("Timeout reached.")
				else:
					print("VAD Segment finished. Capturing...")