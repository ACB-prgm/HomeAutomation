from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

def _sat_dir() -> Path:
	return Path(__file__).resolve().parents[1]


def _default_tools_dir() -> Path:
	return _sat_dir() / "tools" / "respeaker_xvf3800" / "host_control" / "rpi_64bit"


def _parse_first_number(raw: str) -> Optional[float]:
	m = re.search(r"[-+]?\d*\.?\d+", raw)
	if not m:
		return None
	try:
		return float(m.group(0))
	except ValueError:
		return None


class _XvfHostBackend:
	def __init__(self, tools_dir: Optional[str | Path] = None):
		base = Path(tools_dir).expanduser().resolve() if tools_dir else _default_tools_dir().resolve()
		self._xvf_host = base / "xvf_host"
		if not self._xvf_host.is_file():
			raise FileNotFoundError(f"xvf_host not found at {self._xvf_host}")
		if not os_access_exec(self._xvf_host):
			raise PermissionError(f"xvf_host is not executable: {self._xvf_host}")

		self._energy_cmd: Optional[str] = None
		self._doa_cmd: Optional[str] = None

	def _run(self, *args: str, timeout_s: float = 0.8) -> str:
		proc = subprocess.run(
			[str(self._xvf_host), *args],
			check=False,
			capture_output=True,
			text=True,
			timeout=timeout_s,
		)
		if proc.returncode != 0:
			err = (proc.stderr or proc.stdout or "").strip()
			raise RuntimeError(err or f"xvf_host exited with code {proc.returncode}")
		return (proc.stdout or "").strip()

	def _read_number_with_candidates(
		self,
		cache_attr: str,
		candidates: list[str],
	) -> float:
		cmd = getattr(self, cache_attr)
		if cmd:
			out = self._run(cmd)
			val = _parse_first_number(out)
			if val is not None:
				return val
			setattr(self, cache_attr, None)

		for candidate in candidates:
			try:
				out = self._run(candidate)
				val = _parse_first_number(out)
				if val is None:
					continue
				setattr(self, cache_attr, candidate)
				return val
			except Exception:
				continue

		raise RuntimeError(f"No supported command found among: {candidates}")

	def _try_variants(self, variants: list[list[str]]) -> bool:
		for argv in variants:
			try:
				self._run(*argv)
				return True
			except Exception:
				continue
		return False

	def read_speech_energy(self) -> float:
		candidates = [
			"SPEECH_ENERGY",
			"VOICE_ENERGY",
			"VOICEACTIVITY",
			"VOICE_ACTIVITY",
			"VAD",
		]
		return self._read_number_with_candidates("_energy_cmd", candidates)

	def read_doa(self) -> Optional[int]:
		candidates = [
			"DOA",
			"DOA_ANGLE",
			"DIRECTION",
		]
		try:
			val = self._read_number_with_candidates("_doa_cmd", candidates)
		except Exception:
			return None
		return int(round(val))

	def set_led_off(self) -> None:
		# Legacy fallback command used in existing LED-off script.
		self._try_variants([["LED_EFFECT", "0"], ["GPO_WRITE_VALUE", "33", "0"]])

	def set_led_effect(self, effect: int) -> None:
		self._run("LED_EFFECT", str(int(effect)))

	def set_led_color(self, color_hex: str) -> None:
		color = color_hex.strip().lstrip("#")
		if len(color) != 6:
			raise ValueError(f"Invalid hex color: {color_hex}")
		r = int(color[0:2], 16)
		g = int(color[2:4], 16)
		b = int(color[4:6], 16)
		if self._try_variants([["LED_COLOR", str(r), str(g), str(b)], ["LED_RGB", str(r), str(g), str(b)]]):
			return
		raise RuntimeError("No supported LED color command found")

	def configure_audio_route(self, channel_strategy: str) -> None:
		channel = 0 if channel_strategy == "left_processed" else 1
		variants = [
			["AUDIO_OUTPUT_CHANNEL", str(channel)],
			["MIC_OUTPUT_CHANNEL", str(channel)],
			["ASR_CHANNEL_SELECT", str(channel)],
			["HOST_AUDIO_CHANNEL", str(channel)],
		]
		if not self._try_variants(variants):
			raise RuntimeError("No supported audio route command found")


class _PyUsbBackend:
	"""
	Placeholder for direct USB control. This intentionally fails closed until
	command mappings are validated on hardware.
	"""

	def __init__(self):
		try:
			import usb.core  # noqa: F401
			import usb.util  # noqa: F401
		except Exception as exc:
			raise RuntimeError(f"pyusb unavailable: {exc}") from exc

		raise RuntimeError("pyusb backend is not yet mapped for XVF control commands")


class ReSpeakerXVF3800Control:
	def __init__(
		self,
		backend: str = "pyusb",
		tools_dir: Optional[str | Path] = None,
	):
		self.logger = logging.getLogger("satellite.respeaker.control")
		self.backend = backend
		self._impl = None
		self._backend_name = "none"

		self._init_backend(backend=backend, tools_dir=tools_dir)

	def _init_backend(self, backend: str, tools_dir: Optional[str | Path]) -> None:
		if backend == "pyusb":
			try:
				self._impl = _PyUsbBackend()
				self._backend_name = "pyusb"
				return
			except Exception as exc:
				self.logger.warning("pyusb backend unavailable: %s", exc)
				self.logger.info("Falling back to xvf_host backend")
				backend = "xvf_host"

		if backend == "xvf_host":
			self._impl = _XvfHostBackend(tools_dir=tools_dir)
			self._backend_name = "xvf_host"
			return

		raise ValueError(f"Unsupported ReSpeaker backend: {backend}")

	@property
	def available(self) -> bool:
		return self._impl is not None

	@property
	def backend_name(self) -> str:
		return self._backend_name

	def read_speech_energy(self) -> float:
		if not self._impl:
			raise RuntimeError("ReSpeaker control backend unavailable")
		return float(self._impl.read_speech_energy())

	def read_doa(self) -> Optional[int]:
		if not self._impl:
			return None
		return self._impl.read_doa()

	def set_led_idle(self, effect: int = 0) -> None:
		if not self._impl:
			return
		self._impl.set_led_effect(effect)

	def set_led_listening(self, effect: int = 1, color_hex: str = "#00AEEF") -> None:
		if not self._impl:
			return
		self._impl.set_led_effect(effect)
		try:
			self._impl.set_led_color(color_hex)
		except Exception as exc:
			self.logger.debug("Unable to set LED color: %s", exc)

	def set_led_off(self) -> None:
		if not self._impl:
			return
		self._impl.set_led_off()

	def configure_audio_route(self, channel_strategy: str) -> None:
		if not self._impl:
			return
		self._impl.configure_audio_route(channel_strategy)


class ReSpeakerGate:
	def __init__(
		self,
		control: Optional[ReSpeakerXVF3800Control],
		mode: str = "hybrid",
		poll_interval_ms: int = 50,
		speech_energy_high: float = 0.45,
		speech_energy_low: float = 0.25,
		open_consecutive_polls: int = 2,
		close_consecutive_polls: int = 5,
		rms_threshold: float = 0.0035,
		rms_hold_frames: int = 8,
	):
		self.logger = logging.getLogger("satellite.respeaker.gate")
		self.control = control
		self.mode = mode
		self.poll_interval_s = max(0.01, float(poll_interval_ms) / 1000.0)
		self.speech_energy_high = float(speech_energy_high)
		self.speech_energy_low = float(speech_energy_low)
		self.open_consecutive_polls = max(1, int(open_consecutive_polls))
		self.close_consecutive_polls = max(1, int(close_consecutive_polls))
		self.rms_threshold = max(0.0, float(rms_threshold))
		self.rms_hold_frames = max(0, int(rms_hold_frames))

		self._lock = threading.Lock()
		self._xvf_open = False
		self._xvf_open_hits = 0
		self._xvf_close_hits = 0
		self._last_energy: Optional[float] = None
		self._last_gate_open: bool = False
		self._rms_hold = 0
		self._running = threading.Event()
		self._thread: Optional[threading.Thread] = None

		self._xvf_enabled = self.mode in {"xvf", "hybrid"} and self.control is not None and self.control.available
		if self._xvf_enabled:
			self._running.set()
			self._thread = threading.Thread(target=self._poll_loop, name="respeaker-gate", daemon=True)
			self._thread.start()
		elif self.mode in {"xvf", "hybrid"}:
			self.logger.warning("ReSpeaker control unavailable; falling back to RMS-only gating")

	def _poll_loop(self) -> None:
		while self._running.is_set():
			try:
				energy = float(self.control.read_speech_energy())  # type: ignore[union-attr]
				with self._lock:
					self._last_energy = energy
					if energy >= self.speech_energy_high:
						self._xvf_open_hits += 1
						self._xvf_close_hits = 0
						if self._xvf_open_hits >= self.open_consecutive_polls:
							self._xvf_open = True
					elif energy <= self.speech_energy_low:
						self._xvf_close_hits += 1
						self._xvf_open_hits = 0
						if self._xvf_close_hits >= self.close_consecutive_polls:
							self._xvf_open = False
					else:
						self._xvf_open_hits = 0
						self._xvf_close_hits = 0
			except Exception as exc:
				self.logger.debug("ReSpeaker speech-energy poll failed: %s", exc)
			time.sleep(self.poll_interval_s)

	def _rms_open(self, frame: np.ndarray) -> bool:
		if self.rms_threshold <= 0:
			return True
		rms = float(np.sqrt(np.mean(frame * frame) + 1e-12))
		if rms >= self.rms_threshold:
			self._rms_hold = self.rms_hold_frames
			return True
		if self._rms_hold > 0:
			self._rms_hold -= 1
			return True
		return False

	def is_open(self, frame: np.ndarray) -> bool:
		rms_open = self._rms_open(frame)
		with self._lock:
			xvf_open = bool(self._xvf_open)
		if self.mode == "rms":
			result = rms_open
		elif self.mode == "xvf":
			result = xvf_open if self._xvf_enabled else rms_open
		else:
			result = (xvf_open or rms_open) if self._xvf_enabled else rms_open
		with self._lock:
			self._last_gate_open = bool(result)
		return result

	def metrics(self) -> dict[str, str | bool | float]:
		with self._lock:
			energy = self._last_energy
			xvf_open = self._xvf_open
			gate_open = self._last_gate_open
		return {
			"gate_mode": self.mode,
			"gate_open": gate_open,
			"xvf_open": xvf_open,
			"speech_energy": energy if energy is not None else "-",
		}

	def close(self) -> None:
		self._running.clear()
		if self._thread and self._thread.is_alive():
			self._thread.join(timeout=1.0)


class ReSpeakerLedController:
	def __init__(
		self,
		control: Optional[ReSpeakerXVF3800Control],
		enabled: bool = True,
		listening_effect: int = 1,
		listening_color: str = "#00AEEF",
		idle_effect: str = "off",
	):
		self.logger = logging.getLogger("satellite.respeaker.led")
		self.control = control
		self.enabled = bool(enabled)
		self.listening_effect = int(listening_effect)
		self.listening_color = str(listening_color)
		self.idle_effect = str(idle_effect)
		self.state = "off"

	def set_idle(self) -> None:
		if not self.enabled or self.control is None or not self.control.available:
			self.state = "off"
			return
		try:
			if self.idle_effect.lower() == "off":
				self.control.set_led_off()
				self.state = "off"
			else:
				self.control.set_led_idle(effect=int(self.idle_effect))
				self.state = "idle"
		except Exception as exc:
			self.logger.debug("Failed to set idle LED state: %s", exc)

	def set_listening(self) -> None:
		if not self.enabled or self.control is None or not self.control.available:
			self.state = "off"
			return
		try:
			self.control.set_led_listening(
				effect=self.listening_effect,
				color_hex=self.listening_color,
			)
			self.state = "listening"
		except Exception as exc:
			self.logger.debug("Failed to set listening LED state: %s", exc)

	def set_off(self) -> None:
		if not self.enabled or self.control is None or not self.control.available:
			self.state = "off"
			return
		try:
			self.control.set_led_off()
			self.state = "off"
		except Exception as exc:
			self.logger.debug("Failed to set LED off: %s", exc)

	def handle_state(self, state: str) -> None:
		if state in {"wake_detected", "capturing_utterance"}:
			self.set_listening()
		elif state in {"idle", "utterance_complete", "utterance_timeout"}:
			self.set_idle()


def os_access_exec(path: Path) -> bool:
	return path.exists() and path.is_file() and os.access(path, os.X_OK)
