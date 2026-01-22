"""Configuration helpers for the voice-assistant server."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class ServerConfig:
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None

    mqtt_topic_inbound: str = "voice/inbound"
    mqtt_topic_outbound: str = "voice/outbound"

    mqtt_client_id: str = field(default_factory=lambda: f"voice-core-{uuid.uuid4().hex[:8]}")
    mqtt_keepalive: int = 30

    download_base_url: str = "http://raspi.local:5000/audio"
    public_base_url: str = "http://localhost:5000"

    http_timeout_seconds: int = 20
    max_workers: int = 2

    # Storage path for downloaded & generated audio
    storage_root: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "audio"
    )


    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Construct from os.environ with sensible defaults."""

        return cls(
            mqtt_broker_host=os.getenv("MQTT_BROKER_HOST", "localhost"),
            mqtt_broker_port=int(os.getenv("MQTT_BROKER_PORT", "1883")),
            mqtt_username=os.getenv("MQTT_USERNAME"),
            mqtt_password=os.getenv("MQTT_PASSWORD"),
            mqtt_topic_inbound=os.getenv("MQTT_TOPIC_SATELLITE", "voice/inbound"),
            mqtt_topic_outbound=os.getenv("MQTT_TOPIC_RESPONSES", "voice/outbound"),
            mqtt_client_id=os.getenv("MQTT_CLIENT_ID", f"voice-core-{uuid.uuid4().hex[:8]}"),
            mqtt_keepalive=int(os.getenv("MQTT_KEEPALIVE", "30")),
            download_base_url=os.getenv("SATELLITE_AUDIO_BASE_URL", "http://raspi.local:5000/audio"),
            public_base_url=os.getenv("VOICE_SERVER_PUBLIC_URL", "http://localhost:5000"),
            whisper_model=os.getenv("WHISPER_MODEL", "base"),
            http_timeout_seconds=int(os.getenv("HTTP_TIMEOUT_SECONDS", "20")),
            max_workers=int(os.getenv("VOICE_MAX_WORKERS", "2")),
            storage_root=Path(os.getenv(
                "VOICE_SERVER_STORAGE",
                str(Path(__file__).resolve().parent / "audio"),
            )),
        )

    @property
    def incoming_dir(self) -> Path:
        return self.storage_root / "incoming"

    @property
    def responses_dir(self) -> Path:
        return self.storage_root / "responses"

    def ensure_directories(self) -> None:
        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)


__all__ = ["ServerConfig"]
