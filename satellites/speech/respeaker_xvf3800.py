from __future__ import annotations

import logging
import math
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


def _parse_numbers(raw: str) -> list[float]:
	values: list[float] = []
	for token in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw):
		try:
			values.append(float(token))
		except ValueError:
			continue
	return values


def _extract_command_line(raw: str, command: str) -> str:
	lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
	for line in reversed(lines):
		if line.startswith(command):
			return line
	return lines[-1] if lines else raw.strip()


class _XvfHostBackend:
	def __init__(self, tools_dir: Optional[str | Path] = None):
		base = Path(tools_dir).expanduser().resolve() if tools_dir else _default_tools_dir().resolve()
		self._xvf_host = base / "xvf_host"
		if not self._xvf_host.is_file():
			raise FileNotFoundError(f"xvf_host not found at {self._xvf_host}")
		if not os_access_exec(self._xvf_host):
			raise PermissionError(f"xvf_host is not executable: {self._xvf_host}")

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

	def _try_variants(self, variants: list[list[str]]) -> bool:
		for argv in variants:
			try:
				self._run(*argv)
				return True
			except Exception:
				continue
		return False

	def _read_vector(self, command: str) -> list[float]:
		raw = self._run(command)
		line = _extract_command_line(raw, command)
		payload = line[len(command) :].strip() if line.startswith(command) else line
		values = _parse_numbers(payload)
		if not values:
			raise RuntimeError(f"No numeric payload for command '{command}'. Raw='{raw}'")
		return values

	def read_speech_energy(self) -> float:
		# AEC_SPENERGY_VALUES returns 4 beam energies:
		# 0 beam1, 1 beam2, 2 free-running, 3 auto-select.
		values = self._read_vector("AEC_SPENERGY_VALUES")
		if len(values) >= 4:
			return float(values[3])
		return float(max(values))

	def read_doa(self) -> Optional[int]:
		try:
			raw = self._run("AUDIO_MGR_SELECTED_AZIMUTHS")
		except Exception:
			return None

		line = _extract_command_line(raw, "AUDIO_MGR_SELECTED_AZIMUTHS")
		deg_match = re.search(r"\(([-+]?\d*\.?\d+)\s*deg\)", line)
		if deg_match:
			try:
				return int(round(float(deg_match.group(1))))
			except ValueError:
				return None

		values = _parse_numbers(line)
		if not values:
			return None
		# Fallback: first value is radians.
		return int(round(math.degrees(values[0])))

	def set_led_off(self) -> None:
		self._run("LED_EFFECT", "0")
		self.set_led_power(False)

	def set_led_power(self, enabled: bool) -> None:
		self._run("GPO_WRITE_VALUE", "33", "1" if enabled else "0")

	def set_led_effect(self, effect: int) -> None:
		self._run("LED_EFFECT", str(int(effect)))

	def set_led_color(self, color_hex: str) -> None:
		color = color_hex.strip().lstrip("#")
		if len(color) != 6:
			raise ValueError(f"Invalid hex color: {color_hex}")
		packed = int(color, 16)
		self._run("LED_COLOR", str(packed))

	def set_led_brightness(self, brightness: int) -> None:
		self._run("LED_BRIGHTNESS", str(max(0, min(int(brightness), 255))))

	def configure_audio_route(self, channel_strategy: str) -> None:
		# Keep ASR processing enabled for voice pipeline output.
		self._run("AEC_ASROUTONOFF", "1")
		# Keep chosen channels on auto-select beam by default.
		self._run("AUDIO_MGR_SELECTED_CHANNELS", "3", "3")
		# Route left output to user-chosen channel 0.
		self._run("AUDIO_MGR_OP_L", "8", "0")
		if channel_strategy == "right_asr":
			# Route right output to user-chosen channel 1.
			self._run("AUDIO_MGR_OP_R", "8", "1")
		else:
			# Default behavior: left is user chosen, right is residual.
			self._run("AUDIO_MGR_OP_R", "7", "3")


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
		if hasattr(self._impl, "set_led_power"):
			self._impl.set_led_power(True)
		self._impl.set_led_effect(effect)

	def set_led_listening(self, effect: int = 1, color_hex: str = "#00AEEF") -> None:
		if not self._impl:
			return
		if hasattr(self._impl, "set_led_power"):
			self._impl.set_led_power(True)
		self._impl.set_led_effect(effect)
		try:
			self._impl.set_led_brightness(255)
		except Exception as exc:
			self.logger.debug("Unable to set LED brightness: %s", exc)
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
		# Backward compatibility: old configs used tiny normalized defaults.
		if self.speech_energy_high <= 1.0 and self.speech_energy_low <= 1.0:
			self.speech_energy_high = 50000.0
			self.speech_energy_low = 5000.0
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
			energy_ready = self._last_energy is not None
		if self.mode == "rms":
			result = rms_open
		elif self.mode == "xvf":
			result = xvf_open if self._xvf_enabled else rms_open
		else:
			# Hybrid policy: use RMS only until XVF energy is available,
			# then rely on XVF gate state.
			if self._xvf_enabled:
				result = xvf_open if energy_ready else rms_open
			else:
				result = rms_open
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
