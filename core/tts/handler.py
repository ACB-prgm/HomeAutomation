import io
import logging
import wave
from typing import Dict, Optional

from wyoming.audio import AudioStop, wav_to_chunks
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler
from wyoming.tts import (
    Synthesize,
    SynthesizeChunk,
    SynthesizeStart,
    SynthesizeStop,
    SynthesizeStopped,
    SynthesizeVoice,
)

from .tts import TTS
from .tts_manager import TTSManager

_LOGGER = logging.getLogger(__name__)


class PiperEventHandler(AsyncEventHandler):
    def __init__(
        self,
        wyoming_info: Info,
        args,
        voices_info: Dict[str, dict],
        tts_manager: TTSManager,
        reader,
        writer,
    ) -> None:
        super().__init__(reader, writer)
        self.wyoming_info = wyoming_info
        self.args = args
        self.voices_info = voices_info
        self.tts_manager = tts_manager
        self._tts_cache: Dict[str, TTS] = {}
        self._voice_by_display = {
            info.get("display_name", "").casefold(): voice_id
            for voice_id, info in voices_info.items()
            if info.get("display_name")
        }
        self._stream_voice_id: Optional[str] = None
        self._stream_text_parts: list[str] = []
        self._stream_audio_started = False

    async def handle_event(self, event: Event) -> bool:
        try:
            if Describe.is_type(event.type):
                await self.write_event(self.wyoming_info.event())
                return True

            if Synthesize.is_type(event.type):
                synth = Synthesize.from_event(event)
                await self._handle_synthesize(synth)
                return True

            if SynthesizeStart.is_type(event.type):
                start = SynthesizeStart.from_event(event)
                self._handle_synthesize_start(start)
                return True

            if SynthesizeChunk.is_type(event.type):
                chunk = SynthesizeChunk.from_event(event)
                await self._handle_synthesize_chunk(chunk)
                return True

            if SynthesizeStop.is_type(event.type):
                await self._handle_synthesize_stop()
                return True
        except Exception:
            _LOGGER.exception("Error while handling event: %s", event.type)

        return True

    async def _handle_synthesize(self, synth: Synthesize) -> None:
        voice_id = self._select_voice_id(synth.voice)
        wav_bytes = self._get_tts(voice_id).synthesize(synth.text)
        await self._send_wav(wav_bytes, start_event=True, stop_event=True)

    def _handle_synthesize_start(self, start: SynthesizeStart) -> None:
        self._stream_voice_id = self._select_voice_id(start.voice)
        self._stream_text_parts = []
        self._stream_audio_started = False

    async def _handle_synthesize_chunk(self, chunk: SynthesizeChunk) -> None:
        if self._stream_voice_id is None:
            self._stream_voice_id = self.args.voice

        if self.args.no_streaming:
            self._stream_text_parts.append(chunk.text)
            return

        text = chunk.text.strip()
        if not text:
            return

        wav_bytes = self._get_tts(self._stream_voice_id).synthesize(text)
        await self._send_wav(
            wav_bytes,
            start_event=not self._stream_audio_started,
            stop_event=False,
        )
        self._stream_audio_started = True

    async def _handle_synthesize_stop(self) -> None:
        if self._stream_voice_id is None:
            await self.write_event(SynthesizeStopped().event())
            return

        if self.args.no_streaming:
            text = "".join(self._stream_text_parts).strip()
            if text:
                wav_bytes = self._get_tts(self._stream_voice_id).synthesize(text)
                await self._send_wav(wav_bytes, start_event=True, stop_event=True)
        else:
            if self._stream_audio_started:
                await self.write_event(AudioStop(timestamp=None).event())

        await self.write_event(SynthesizeStopped().event())
        self._stream_voice_id = None
        self._stream_text_parts = []
        self._stream_audio_started = False

    def _select_voice_id(self, voice: Optional[SynthesizeVoice]) -> str:
        voice_id: Optional[str] = None

        if voice is not None:
            if voice.name:
                voice_id = self.voices_info.get(voice.name) and voice.name
                if voice_id is None:
                    voice_id = self._voice_by_display.get(voice.name.casefold())
            elif voice.language:
                voice_id = self._find_voice_by_language(voice.language)

        if not voice_id:
            voice_id = self.args.voice

        if voice_id not in self.voices_info:
            voice_id = next(iter(self.voices_info.keys()))

        return voice_id

    def _find_voice_by_language(self, language: str) -> Optional[str]:
        language = language.casefold()
        for voice_id, info in self.voices_info.items():
            locale = str(info.get("locale", "")).casefold()
            if not locale:
                continue
            if locale == language or locale.startswith(language) or language.startswith(
                locale
            ):
                return voice_id
        return None

    def _get_tts(self, voice_id: str) -> TTS:
        tts = self._tts_cache.get(voice_id)
        if tts is None:
            tts = self.tts_manager.initialize_tts(voice_id)
            self._tts_cache[voice_id] = tts
        return tts

    async def _send_wav(
        self,
        wav_bytes: bytes,
        *,
        start_event: bool,
        stop_event: bool,
    ) -> None:
        with io.BytesIO(wav_bytes) as wav_io:
            with wave.open(wav_io, "rb") as wav_file:
                for chunk_event in wav_to_chunks(
                    wav_file,
                    self.args.samples_per_chunk,
                    start_event=start_event,
                    stop_event=stop_event,
                ):
                    await self.write_event(chunk_event.event())
