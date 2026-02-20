from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

VALID_VAD_MODES = {"sherpa", "xvf", "hybrid"}
VALID_RESPEAKER_BACKENDS = {"pyusb", "xvf_host"}
VALID_GATE_MODES = {"rms", "xvf", "hybrid"}
VALID_CHANNEL_STRATEGIES = {"left_processed", "right_asr"}


def _repo_satellites_dir() -> Path:
	return Path(__file__).resolve().parents[1]


def _default_config_path() -> Path:
	return _repo_satellites_dir() / "config" / "satellite.json"


def _default_identity_path() -> Path:
	production_path = Path("/var/lib/satellite/identity.json")
	if os.geteuid() == 0:
		return production_path

	if production_path.parent.exists() and os.access(production_path.parent, os.W_OK):
		return production_path

	return _repo_satellites_dir() / "identity.json"


def _resolve_path(value: Any, default: Path, base_dir: Optional[Path]) -> Path:
	if value in (None, ""):
		return default

	path = Path(str(value)).expanduser()
	if not path.is_absolute() and base_dir is not None:
		path = (base_dir / path).resolve()

	return path


def _load_yaml_or_none():
	try:  # Optional dependency
		import yaml
	except ImportError:
		return None

	return yaml


@dataclass(frozen=True)
class IdentityConfig:
	path: Path = field(default_factory=_default_identity_path)
	friendly_name: str = "Home Satellite"
	room: str = "unassigned"


@dataclass(frozen=True)
class AudioSettings:
	sample_rate: int = 16000
	channels: int = 1
	block_size: int = 512
	input_device: Optional[str | int] = None
	output_device: Optional[str | int] = None
	volume: float = 0.8


@dataclass(frozen=True)
class VadSettings:
	mode: str = "sherpa"
	threshold: float = 0.25
	min_silence_duration: float = 0.5
	min_speech_duration: float = 0.01
	max_utterance_s: float = 10.0


@dataclass(frozen=True)
class SpeechSettings:
	debug: bool = False
	input_gain: float = 1.0
	wake_rms_gate: float = 0.0035
	wake_gate_hold_frames: int = 8
	wake_preroll_enabled: bool = True
	wake_preroll_ms: int = 400
	wakeword_threads: int = 1
	vad_threads: int = 1


@dataclass(frozen=True)
class ReSpeakerSettings:
	enabled: bool = True
	control_backend: str = "xvf_host"
	poll_interval_ms: int = 50
	gate_mode: str = "hybrid"
	speech_energy_high: float = 0.001
	speech_energy_low: float = 0.0001
	open_consecutive_polls: int = 2
	close_consecutive_polls: int = 5
	led_enabled: bool = True
	led_listening_effect: int = 3
	led_listening_color: str = "#00FF00"
	led_idle_effect: str = "off"
	channel_strategy: str = "left_processed"


@dataclass(frozen=True)
class RuntimeSettings:
	log_level: str = "INFO"
	reconnect_min_s: float = 1.0
	reconnect_max_s: float = 30.0


@dataclass(frozen=True)
class SatelliteConfig:
	identity: IdentityConfig = field(default_factory=IdentityConfig)
	audio: AudioSettings = field(default_factory=AudioSettings)
	vad: VadSettings = field(default_factory=VadSettings)
	speech: SpeechSettings = field(default_factory=SpeechSettings)
	respeaker: ReSpeakerSettings = field(default_factory=ReSpeakerSettings)
	runtime: RuntimeSettings = field(default_factory=RuntimeSettings)

	def validate(self) -> None:
		if self.audio.sample_rate <= 0:
			raise ValueError("audio.sample_rate must be > 0")
		if self.audio.channels <= 0:
			raise ValueError("audio.channels must be > 0")
		if self.audio.block_size <= 0:
			raise ValueError("audio.block_size must be > 0")
		if not (0.0 <= self.audio.volume <= 1.0):
			raise ValueError("audio.volume must be between 0.0 and 1.0")

		if self.vad.mode not in VALID_VAD_MODES:
			raise ValueError(f"vad.mode must be one of {sorted(VALID_VAD_MODES)}")
		if self.vad.max_utterance_s <= 0:
			raise ValueError("vad.max_utterance_s must be > 0")
		if self.vad.min_silence_duration < 0:
			raise ValueError("vad.min_silence_duration must be >= 0")
		if self.vad.min_speech_duration < 0:
			raise ValueError("vad.min_speech_duration must be >= 0")
		if self.runtime.reconnect_min_s <= 0:
			raise ValueError("runtime.reconnect_min_s must be > 0")
		if self.runtime.reconnect_max_s < self.runtime.reconnect_min_s:
			raise ValueError("runtime.reconnect_max_s must be >= runtime.reconnect_min_s")
		if self.speech.input_gain <= 0:
			raise ValueError("speech.input_gain must be > 0")
		if self.speech.wake_rms_gate < 0:
			raise ValueError("speech.wake_rms_gate must be >= 0")
		if self.speech.wake_gate_hold_frames < 0:
			raise ValueError("speech.wake_gate_hold_frames must be >= 0")
		if self.speech.wake_preroll_ms < 0:
			raise ValueError("speech.wake_preroll_ms must be >= 0")
		if self.speech.wakeword_threads <= 0:
			raise ValueError("speech.wakeword_threads must be > 0")
		if self.speech.vad_threads <= 0:
			raise ValueError("speech.vad_threads must be > 0")
		if self.respeaker.control_backend not in VALID_RESPEAKER_BACKENDS:
			raise ValueError(f"respeaker.control_backend must be one of {sorted(VALID_RESPEAKER_BACKENDS)}")
		if self.respeaker.poll_interval_ms <= 0:
			raise ValueError("respeaker.poll_interval_ms must be > 0")
		if self.respeaker.gate_mode not in VALID_GATE_MODES:
			raise ValueError(f"respeaker.gate_mode must be one of {sorted(VALID_GATE_MODES)}")
		if self.respeaker.speech_energy_high < 0:
			raise ValueError("respeaker.speech_energy_high must be >= 0")
		if self.respeaker.speech_energy_low < 0:
			raise ValueError("respeaker.speech_energy_low must be >= 0")
		if self.respeaker.speech_energy_low > self.respeaker.speech_energy_high:
			raise ValueError("respeaker.speech_energy_low must be <= respeaker.speech_energy_high")
		if self.respeaker.open_consecutive_polls <= 0:
			raise ValueError("respeaker.open_consecutive_polls must be > 0")
		if self.respeaker.close_consecutive_polls <= 0:
			raise ValueError("respeaker.close_consecutive_polls must be > 0")
		if self.respeaker.channel_strategy not in VALID_CHANNEL_STRATEGIES:
			raise ValueError(f"respeaker.channel_strategy must be one of {sorted(VALID_CHANNEL_STRATEGIES)}")

	@classmethod
	def from_dict(cls, data: dict[str, Any], base_dir: Optional[Path] = None) -> "SatelliteConfig":
		identity_raw = data.get("identity", {}) or {}
		audio_raw = data.get("audio", {}) or {}
		vad_raw = data.get("vad", {}) or {}
		speech_raw = data.get("speech", {}) or {}
		respeaker_raw = data.get("respeaker", {}) or {}
		runtime_raw = data.get("runtime", {}) or {}

		config = cls(
			identity=IdentityConfig(
				path=_resolve_path(identity_raw.get("path"), _default_identity_path(), base_dir),
				friendly_name=str(identity_raw.get("friendly_name", IdentityConfig.friendly_name)),
				room=str(identity_raw.get("room", IdentityConfig.room)),
			),
			audio=AudioSettings(
				sample_rate=int(audio_raw.get("sample_rate", AudioSettings.sample_rate)),
				channels=int(audio_raw.get("channels", AudioSettings.channels)),
				block_size=int(audio_raw.get("block_size", AudioSettings.block_size)),
				input_device=audio_raw.get("input_device", AudioSettings.input_device),
				output_device=audio_raw.get("output_device", AudioSettings.output_device),
				volume=float(audio_raw.get("volume", AudioSettings.volume)),
			),
			vad=VadSettings(
				mode=str(vad_raw.get("mode", VadSettings.mode)),
				threshold=float(vad_raw.get("threshold", VadSettings.threshold)),
				min_silence_duration=float(vad_raw.get("min_silence_duration", VadSettings.min_silence_duration)),
				min_speech_duration=float(vad_raw.get("min_speech_duration", VadSettings.min_speech_duration)),
				max_utterance_s=float(vad_raw.get("max_utterance_s", VadSettings.max_utterance_s)),
			),
			speech=SpeechSettings(
				debug=bool(speech_raw.get("debug", SpeechSettings.debug)),
				input_gain=float(speech_raw.get("input_gain", SpeechSettings.input_gain)),
				wake_rms_gate=float(speech_raw.get("wake_rms_gate", SpeechSettings.wake_rms_gate)),
				wake_gate_hold_frames=int(speech_raw.get("wake_gate_hold_frames", SpeechSettings.wake_gate_hold_frames)),
				wake_preroll_enabled=bool(speech_raw.get("wake_preroll_enabled", SpeechSettings.wake_preroll_enabled)),
				wake_preroll_ms=max(0, int(speech_raw.get("wake_preroll_ms", SpeechSettings.wake_preroll_ms))),
				wakeword_threads=max(1, int(speech_raw.get("wakeword_threads", SpeechSettings.wakeword_threads))),
				vad_threads=max(1, int(speech_raw.get("vad_threads", SpeechSettings.vad_threads))),
			),
			respeaker=ReSpeakerSettings(
				enabled=bool(respeaker_raw.get("enabled", ReSpeakerSettings.enabled)),
				control_backend=str(respeaker_raw.get("control_backend", ReSpeakerSettings.control_backend)),
				poll_interval_ms=max(1, int(respeaker_raw.get("poll_interval_ms", ReSpeakerSettings.poll_interval_ms))),
				gate_mode=str(respeaker_raw.get("gate_mode", ReSpeakerSettings.gate_mode)),
				speech_energy_high=float(respeaker_raw.get("speech_energy_high", ReSpeakerSettings.speech_energy_high)),
				speech_energy_low=float(respeaker_raw.get("speech_energy_low", ReSpeakerSettings.speech_energy_low)),
				open_consecutive_polls=max(1, int(respeaker_raw.get("open_consecutive_polls", ReSpeakerSettings.open_consecutive_polls))),
				close_consecutive_polls=max(1, int(respeaker_raw.get("close_consecutive_polls", ReSpeakerSettings.close_consecutive_polls))),
				led_enabled=bool(respeaker_raw.get("led_enabled", ReSpeakerSettings.led_enabled)),
				led_listening_effect=int(respeaker_raw.get("led_listening_effect", ReSpeakerSettings.led_listening_effect)),
				led_listening_color=str(respeaker_raw.get("led_listening_color", ReSpeakerSettings.led_listening_color)),
				led_idle_effect=str(respeaker_raw.get("led_idle_effect", ReSpeakerSettings.led_idle_effect)),
				channel_strategy=str(respeaker_raw.get("channel_strategy", ReSpeakerSettings.channel_strategy)),
			),
			runtime=RuntimeSettings(
				log_level=str(runtime_raw.get("log_level", RuntimeSettings.log_level)),
				reconnect_min_s=float(runtime_raw.get("reconnect_min_s", RuntimeSettings.reconnect_min_s)),
				reconnect_max_s=float(runtime_raw.get("reconnect_max_s", RuntimeSettings.reconnect_max_s)),
			),
		)
		config.validate()
		return config

	def to_dict(self) -> dict[str, Any]:
		payload = asdict(self)
		payload["identity"]["path"] = str(self.identity.path)
		return payload


class ConfigManager:
	def __init__(self, path: Optional[str | Path] = None):
		self.path = Path(path).expanduser().resolve() if path else _default_config_path()
		self._config: Optional[SatelliteConfig] = None

	@property
	def config(self) -> SatelliteConfig:
		if self._config is None:
			raise RuntimeError("Config not loaded yet. Call load().")
		return self._config

	def load(self, create_if_missing: bool = True) -> SatelliteConfig:
		if self.path.exists():
			raw = self._read_raw()
			if not isinstance(raw, dict):
				raise ValueError(f"Config file must contain an object: {self.path}")
			self._config = SatelliteConfig.from_dict(raw, base_dir=self.path.parent)
			return self._config

		self._config = SatelliteConfig()
		if create_if_missing:
			self.save(self._config)
		return self._config

	def save(self, config: Optional[SatelliteConfig] = None) -> None:
		cfg = config or self.config
		self.path.parent.mkdir(parents=True, exist_ok=True)
		payload = cfg.to_dict()
		if self.path.suffix.lower() in (".yaml", ".yml"):
			yaml = _load_yaml_or_none()
			if yaml is None:
				raise RuntimeError("YAML config requested but PyYAML is not installed.")
			with open(self.path, "w", encoding="utf-8") as f:
				yaml.safe_dump(payload, f, sort_keys=False)
			return

		with open(self.path, "w", encoding="utf-8") as f:
			json.dump(payload, f, indent=2)
			f.write("\n")

	def _read_raw(self) -> dict[str, Any]:
		ext = self.path.suffix.lower()
		with open(self.path, "r", encoding="utf-8") as f:
			if ext in (".yaml", ".yml"):
				yaml = _load_yaml_or_none()
				if yaml is None:
					raise RuntimeError("YAML config found but PyYAML is not installed.")
				return yaml.safe_load(f) or {}
			return json.load(f)
