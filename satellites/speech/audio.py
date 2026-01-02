# audio.py
from __future__ import annotations

import wave
import queue
import threading
import numpy as np
import sounddevice as sd
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class AudioConfig:
	channels: int = 1
	block_size: int = 320			# 20ms @ 16k
	sample_rate: int = 16000
	device: Optional[int] = None	# sounddevice device id, or None=default


class AudioInput:
	"""
	Microphone input as float32 mono frames in [-1, 1].
	Uses a PortAudio callback (sounddevice). Consumer pulls frames from a queue.
	"""
	def __init__(self, cfg: AudioConfig):
		self.cfg = cfg
		self._stream = None
		self._running = threading.Event()
		self.frame_length_ms = cfg.block_size / cfg.sample_rate * 1000
		self._q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=50)

	def start(self) -> None:
		if self._running.is_set():
			return

		def _cb(indata, frames, time_info, status):
			# indata: (frames, channels) float32
			if status:
				# drop frames on overflow/underflow; keep system alive
				pass

			x = np.asarray(indata, dtype=np.float32)
			if x.ndim == 2 and x.shape[1] > 1:
				x = np.mean(x, axis=1)
			else:
				x = x.reshape(-1)

			# Best-effort enqueue (drop oldest on backpressure)
			try:
				self._q.put_nowait(x.copy())
			except queue.Full:
				try:
					_ = self._q.get_nowait()
				except queue.Empty:
					pass
				try:
					self._q.put_nowait(x.copy())
				except queue.Full:
					pass

		self._stream = sd.InputStream(
			samplerate=self.cfg.sample_rate,
			blocksize=self.cfg.block_size,
			channels=self.cfg.channels,
			device=self.cfg.device,
			dtype="float32",
			callback=_cb,
		)
		self._stream.start()
		self._running.set()

	def stop(self) -> None:
		self._running.clear()
		if self._stream is not None:
			try:
				self._stream.stop()
			finally:
				self._stream.close()
				self._stream = None

	def frames(self, timeout_s: float = 1.0) -> Iterator[np.ndarray]:
		"""
		Yields frames until stopped.
		"""
		while self._running.is_set():
			try:
				yield self._q.get(timeout=timeout_s)
			except queue.Empty:
				continue


def write_wav_mono_16bit(path: str, audio_f32: np.ndarray, sample_rate: int) -> None:
	"""
	Write float32 mono [-1, 1] to 16-bit PCM WAV.
	"""
	x = np.asarray(audio_f32, dtype=np.float32).reshape(-1)
	x = np.clip(x, -1.0, 1.0)
	pcm16 = (x * 32767.0).astype(np.int16)

	with wave.open(path, "wb") as wf:
		wf.setnchannels(1)
		wf.setsampwidth(2)  # int16
		wf.setframerate(int(sample_rate))
		wf.writeframes(pcm16.tobytes())
