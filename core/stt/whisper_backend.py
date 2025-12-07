"""Thin wrapper around the optional Whisper dependency."""

from __future__ import annotations

import logging
import platform
from pathlib import Path
from faster_whisper import WhisperModel as whisper

logger = logging.getLogger(__name__)

def define_whisper_settings() -> dict:
    machine = platform.machine().lower()

    # Apple Silicon → arm64
    if "arm" in machine or "aarch" in machine:
        return {
            "model_size": "tiny.en",
            "device": "cpu",
            "compute_type": "float32",
        }

    # Intel Macs / Linux x86_64
    return {
        "model_size": "tiny.en",
        "device": "cpu",
        "compute_type": "int8",
    }

class STT:
    """Lazy Whisper loader that exposes a simple transcribe API."""

    def __init__(self):
        self.whisper_settings = define_whisper_settings()
        self.model = None
        self.available = False
        self._load()

    def _load(self) -> None:
        if whisper is None:
            logger.warning("openai-whisper is not installed; transcription disabled")
            return

        try:
            self.model = whisper(**self.whisper_settings)
            self.available = True
            logger.info("Loaded Whisper model '%s'", self.model_name)
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to load Whisper model '%s': %s", self.model_name, exc)
            self.model = None
            self.available = False

    def transcribe(self, audio_path: Path) -> str:
        if not self.model:
            logger.error("Whisper unavailable; returning empty transcript for %s", audio_path)
            return ""

        try:
            segments, info = self.model.transcribe(
                str(audio_path),
                language="en",
                multilingual=False,
                beam_size=1,
                best_of=1,
                temperature=0
            )
            text = " ".join(segment.text for segment in segments).split()
            return text, info
        except Exception as exc:  # pragma: no cover
            logger.exception("Whisper failed on %s: %s", audio_path, exc)
            return ""


__all__ = ["Whisper"]
