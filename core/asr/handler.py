import logging
from typing import Optional

import numpy as np
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler

from .asr import ASR

_LOGGER = logging.getLogger(__name__)


class AsrEventHandler(AsyncEventHandler):
    def __init__(
        self,
        wyoming_info: Info,
        asr: ASR,
        default_language: str,
        reader,
        writer,
    ) -> None:
        super().__init__(reader, writer)
        self.wyoming_info = wyoming_info
        self.asr = asr
        self.default_language = default_language
        self._reset_request_state()

    async def handle_event(self, event: Event) -> bool:
        try:
            if Describe.is_type(event.type):
                await self.write_event(self.wyoming_info.event())
                return True

            if Transcribe.is_type(event.type):
                transcribe = Transcribe.from_event(event)
                self._request_context = transcribe.context
                self._request_language = transcribe.language or self.default_language
                self._audio_buffer.clear()
                self._converter = AudioChunkConverter(rate=16000, width=2, channels=1)
                return True

            if AudioStart.is_type(event.type):
                self._audio_buffer.clear()
                self._converter = AudioChunkConverter(rate=16000, width=2, channels=1)
                return True

            if AudioChunk.is_type(event.type):
                chunk = AudioChunk.from_event(event)
                converted = self._converter.convert(chunk)
                self._audio_buffer.extend(converted.audio)
                return True

            if AudioStop.is_type(event.type):
                await self._emit_transcript()
                self._reset_request_state()
                return True
        except Exception:
            _LOGGER.exception("Error while handling ASR event: %s", event.type)
            await self._write_empty_transcript()
            self._reset_request_state()

        return True

    async def disconnect(self) -> None:
        self._reset_request_state()

    def _reset_request_state(self) -> None:
        self._request_context: Optional[dict] = None
        self._request_language = self.default_language
        self._audio_buffer = bytearray()
        self._converter = AudioChunkConverter(rate=16000, width=2, channels=1)

    async def _emit_transcript(self) -> None:
        text = ""
        try:
            audio = self._bytes_to_float32_mono(self._audio_buffer)
            if audio.size > 0:
                text = self.asr.transcribe_samples(sample_rate=16000, audio=audio)
        except Exception:
            _LOGGER.exception("ASR decode failed")

        await self.write_event(
            Transcript(
                text=text,
                context=self._request_context,
                language=self._request_language,
            ).event()
        )

    async def _write_empty_transcript(self) -> None:
        await self.write_event(
            Transcript(
                text="",
                context=self._request_context,
                language=self._request_language,
            ).event()
        )

    @staticmethod
    def _bytes_to_float32_mono(audio_bytes: bytearray) -> np.ndarray:
        if not audio_bytes:
            return np.zeros((0,), dtype=np.float32)

        raw = bytes(audio_bytes)
        if len(raw) % 2 != 0:
            raw = raw[:-1]
        if not raw:
            return np.zeros((0,), dtype=np.float32)

        samples_i16 = np.frombuffer(raw, dtype=np.int16)
        return (samples_i16.astype(np.float32) / 32768.0).reshape(-1)
