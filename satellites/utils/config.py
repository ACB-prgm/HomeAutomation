from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

VALID_VAD_MODES = {"sherpa", "xvf", "hybrid"}


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

	@classmethod
	def from_dict(cls, data: dict[str, Any], base_dir: Optional[Path] = None) -> "SatelliteConfig":
		identity_raw = data.get("identity", {}) or {}
		audio_raw = data.get("audio", {}) or {}
		vad_raw = data.get("vad", {}) or {}
		speech_raw = data.get("speech", {}) or {}
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
