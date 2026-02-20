# audio.py
from __future__ import annotations

import wave
import queue
import threading
import subprocess
import numpy as np
import sounddevice as sd
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class AudioConfig:
	channels: int = 1
	block_size: int = 512			# 20ms @ 16k
	sample_rate: int = 16000
	device: Optional[int | str] = None	# sounddevice device id/name, or None=default
	channel_select: int = 0		# which channel to use when channels > 1


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
				ch_idx = min(max(int(self.cfg.channel_select), 0), x.shape[1] - 1)
				x = x[:, ch_idx] # Select one channel and keep mono
			else:
				x = x.reshape(-1)

			# Best-effort enqueue (drop oldest on backpressure)
			try:
				self._q.put_nowait(x.copy())
			except queue.Full:
				print("WARNING: Audio buffer overflow! Dropping frames.")
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


class ArecordInput:
	"""
	Microphone input using arecord (ALSA) as float32 mono frames in [-1, 1].
	Useful when PulseAudio defaults are mis-routed.
	"""

	def __init__(self, cfg: AudioConfig, alsa_device: str):
		self.cfg = cfg
		self.alsa_device = alsa_device
		self._proc: Optional[subprocess.Popen] = None
		self._running = threading.Event()
		self._thread: Optional[threading.Thread] = None
		self._q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=50)
		self.frame_length_ms = cfg.block_size / cfg.sample_rate * 1000

	def start(self) -> None:
		if self._running.is_set():
			return

		cmd = [
			"arecord",
			"-q",
			"-D",
			self.alsa_device,
			"-f",
			"S16_LE",
			"-r",
			str(int(self.cfg.sample_rate)),
			"-c",
			str(max(1, int(self.cfg.channels))),
			"-t",
			"raw",
		]
		self._proc = subprocess.Popen(
			cmd,
			stdout=subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			bufsize=0,
		)
		self._running.set()
		self._thread = threading.Thread(target=self._reader_loop, name="arecord-input", daemon=True)
		self._thread.start()

	def _reader_loop(self) -> None:
		if self._proc is None or self._proc.stdout is None:
			return

		bytes_per_sample = 2
		channels = max(1, int(self.cfg.channels))
		frame_bytes = int(self.cfg.block_size) * channels * bytes_per_sample

		while self._running.is_set():
			data = self._proc.stdout.read(frame_bytes)
			if not data or len(data) < frame_bytes:
				break
			x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
			if channels > 1:
				x = x.reshape(-1, channels)
				ch_idx = min(max(int(self.cfg.channel_select), 0), channels - 1)
				x = x[:, ch_idx]
			else:
				x = x.reshape(-1)

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

		self._running.clear()

	def stop(self) -> None:
		self._running.clear()
		if self._proc is not None:
			try:
				self._proc.terminate()
			except Exception:
				pass
			try:
				self._proc.wait(timeout=1.0)
			except Exception:
				try:
					self._proc.kill()
				except Exception:
					pass
			self._proc = None
		if self._thread and self._thread.is_alive():
			self._thread.join(timeout=1.0)

	def frames(self, timeout_s: float = 1.0) -> Iterator[np.ndarray]:
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
