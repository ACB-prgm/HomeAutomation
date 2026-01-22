from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

import numpy as np
from sherpa_onnx import SileroVadModelConfig, VadModelConfig, VoiceActivityDetector


MODELS_DIR = Path(__file__).resolve().parent / "models"

class VadBackend(Protocol):
	def reset(self) -> None: ...
	def accept_audio(self, audio_f32: np.ndarray, sample_rate: int) -> None: ...
	def in_speech(self) -> bool: ...
	def utterance_ended(self) -> bool: ...

class EnergyVad(VadBackend):
	"""
	Ultra-simple VAD fallback so the pipeline runs before you wire sherpa's VAD.
	Not robust, but good enough to validate the state machine.
	"""
	def __init__(
			self, 
			rms_threshold: float = 0.015,
			frame_length_ms: float = 20, 
			silence_length_ms: float = 1000
	):
		self.rms_threshold = rms_threshold
		self.hangover_frames = max(1, int(silence_length_ms / frame_length_ms))
		self._speech = False
		self._silence_run = 0

	def reset(self, speech: bool = False) -> None:
		self._speech = speech
		self._silence_run = 0

	def accept_audio(self, audio_f32: np.ndarray) -> None:
		x = np.asarray(audio_f32, dtype=np.float32).reshape(-1)
		rms = self._rms(x)
		is_speech = rms >= self.rms_threshold

		if is_speech:
			self._speech = True
			self._silence_run = 0
		else:
			if self._speech:
				self._silence_run += 1
	
	def _rms(self, audio_f32: np.array):
		return float(np.sqrt(np.mean(audio_f32 * audio_f32) + 1e-12))

	def in_speech(self) -> bool:
		return self._speech

	def utterance_ended(self) -> bool:
		# ended after some silence following speech
		return self._speech and self._silence_run >= self.hangover_frames

class SherpaVAD(VadBackend):
	def __init__(
		self,
		model_path: Optional[str | Path] = None,
		sample_rate: int = 16000,
		threshold: float = 0.25,
		min_silence_duration: float = 0.5,
		min_speech_duration: float = 0.01,
		max_speech_duration: float = 10.0,
		window_size: int = 512,
		num_threads: int = 2,
		provider: str = "cpu",
	):
		model = Path(model_path) if model_path else (MODELS_DIR / "vad.int8.onnx")
		vad_config = SileroVadModelConfig(
			model=str(model),
			threshold=float(threshold),
			min_silence_duration=float(min_silence_duration),
			min_speech_duration=float(min_speech_duration),
			max_speech_duration=float(max_speech_duration),
			window_size=int(window_size),
		)
		cfg = VadModelConfig(
			silero_vad=vad_config,
			sample_rate=int(sample_rate),
			num_threads=int(num_threads),
			provider=str(provider),
		)
		self.vad = VoiceActivityDetector(cfg)

		self._window_size : int = int(window_size)
		self._sample_rate : int = int(sample_rate)
		self.reset()

	def reset(self) -> None:
		self.vad.reset()
		self.speech_captured = False
		self._buffer = np.zeros((0,), dtype=np.float32)

	def flush(self) -> None:
		self.vad.flush()
		self.speech_captured = not self.vad.empty()
	
	def clear(self, flush: bool= False) -> None:
		if flush:
			self.vad.flush()
		while not self.vad.empty():
			self.vad.pop()
		self.speech_captured = False

	def accept_audio(self, audio_f32: np.ndarray) -> None:
		# Append new audio to our internal buffer
		self._buffer = np.concatenate([self._buffer, audio_f32])

		# While we have enough data for a window step
		while self._buffer.size >= self._window_size:
			# Take the first window_size samples
			window = self._buffer[:self._window_size]
			# Remove them from buffer
			self._buffer = self._buffer[self._window_size:]
			
			# Feed to VAD
			self.vad.accept_waveform(window.tolist())
		
		# Check if VAD has produced any segments
		self.speech_captured = not self.vad.empty()

	def get_samples(self, flush: bool = False) -> np.ndarray:
		if flush:
			self.vad.flush()
		
		# Extract all ready segments
		chunks = []
		while not self.vad.empty():
			chunks.append(self.vad.front.samples)
			self.vad.pop()
		
		if not chunks:
			return np.zeros((0,), dtype=np.float32)
		return chunks