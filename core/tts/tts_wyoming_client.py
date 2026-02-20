import io
import socket
import time
import wave
from typing import Optional
from urllib.parse import urlparse

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import read_event, write_event
from wyoming.tts import Synthesize, SynthesizeVoice


class WyomingTtsClient:
    def __init__(self, uri: str, timeout: float = 5.0) -> None:
        self.uri = uri
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self._reader = None
        self._writer = None

    def wait_until_ready(self) -> None:
        deadline = time.time() + self.timeout
        last_error = None
        while time.time() < deadline:
            try:
                self._connect()
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.2)

        raise RuntimeError(f"TTS server not ready at {self.uri}") from last_error

    def try_connect(self) -> bool:
        try:
            self._connect()
            return True
        except OSError:
            return False

    def synthesize(self, text: str, voice_name: Optional[str] = None) -> bytes:
        self._ensure_connected()
        voice = SynthesizeVoice(name=voice_name) if voice_name else None
        write_event(Synthesize(text=text, voice=voice).event(), self._writer)
        return self._read_wav_response()

    def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None

        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None

        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def _ensure_connected(self) -> None:
        if self._socket is None:
            self._connect()

    def _connect(self) -> None:
        if self._socket is not None:
            return

        parsed = urlparse(self.uri)
        if parsed.scheme == "tcp":
            host = parsed.hostname or "127.0.0.1"
            if parsed.port is None:
                raise ValueError("tcp:// uri requires a port")
            sock = socket.create_connection((host, parsed.port), timeout=self.timeout)
        elif parsed.scheme == "unix":
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect(parsed.path)
        else:
            raise ValueError("Only tcp:// or unix:// uris are supported for client use")

        self._socket = sock
        self._reader = sock.makefile("rb")
        self._writer = sock.makefile("wb")

    def _read_wav_response(self) -> bytes:
        wav_io = io.BytesIO()
        wav_file: Optional[wave.Wave_write] = None
        audio_started = False

        while True:
            event = read_event(self._reader)
            if event is None:
                break

            if AudioStart.is_type(event.type):
                start = AudioStart.from_event(event)
                wav_file = wave.open(wav_io, "wb")
                wav_file.setnchannels(start.channels)
                wav_file.setsampwidth(start.width)
                wav_file.setframerate(start.rate)
                audio_started = True
                continue

            if AudioChunk.is_type(event.type):
                chunk = AudioChunk.from_event(event)
                if wav_file is None:
                    wav_file = wave.open(wav_io, "wb")
                    wav_file.setnchannels(chunk.channels)
                    wav_file.setsampwidth(chunk.width)
                    wav_file.setframerate(chunk.rate)
                    audio_started = True
                wav_file.writeframes(chunk.audio)
                continue

            if AudioStop.is_type(event.type):
                break

        if wav_file is not None:
            wav_file.close()

        if not audio_started:
            raise RuntimeError("No audio returned from TTS server")

        return wav_io.getvalue()
