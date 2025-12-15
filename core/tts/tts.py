from __future__ import annotations

import io
import re
import wave
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import sherpa_onnx as so

_PAUSE_PATTERN = re.compile(r"(\.\.\.|[.!?]|,)")
_DEFAULT_PAUSE_MAP: Dict[str, float] = {".": 1.0, "!": 1.0, "?": 1.0, "...": 1.5, ",": 0.35}
_DEFAULT_PAUSE_DUR: float = 0.1


class TTS:
    """
    sherpa-onnx TTS helper for Piper-format VITS voices.

    Expects a model directory containing:
    - a single *.onnx model
    - tokens.txt
    - espeak-ng-data/ (phonemizer data)
    """

    def __init__(
        self,
        model_info: dict,
        voice_info: dict,
        pause_map: Dict[str, float] | None = None,
    ) -> None:
        self.engine = model_info['engine']
        self.sid = voice_info['sid']
        self.tts = so.OfflineTts(
            self._build_model_config(model_info['config'], voice_info['config'])
        )
        self.sample_rate = int(self.tts.sample_rate)
        self.pause_map = pause_map or dict(_DEFAULT_PAUSE_MAP)

    # ------------------------------------------------------------------ public
    def synthesize(
        self,
        text: str,
        *,
        pause_seconds: float | None = None,
        pause_map: Dict[str, float] | None = None,
    ) -> bytes:
        """
        Convert text to WAV bytes.

        Args:
            text: Input text.
            speaker: Speaker id (0 for single-speaker voices).
            pause_seconds: If provided, split on punctuation and insert silence of
                           pause_map[punct] * pause_seconds after each segment.
            pause_map: Optional override for pause multipliers.
        """
        pause_map = pause_map or self.pause_map
        pause_seconds = pause_seconds or _DEFAULT_PAUSE_DUR if self.engine == 'vits' else pause_seconds

        if not pause_seconds:
            audio, sample_rate = self._generate_audio(text, self.sid)
        else:
            segments = self._split_with_pause_map(text, pause_map)
            chunks: List[np.ndarray] = []
            sample_rate = self.sample_rate

            for seg_text, pause_factor in segments:
                seg = seg_text.strip()
                if seg:
                    audio_arr, sample_rate = self._generate_audio(seg, self.sid)
                    chunks.append(audio_arr)
                if pause_factor and pause_seconds:
                    silence_len = int(pause_seconds * pause_factor * sample_rate)
                    if silence_len > 0:
                        chunks.append(np.zeros(silence_len, dtype=np.float32))

            audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)

        return self._to_wav_bytes(audio, sample_rate)

    # ------------------------------------------------------------------ internals
    def _generate_audio(self, text: str, speaker: int) -> Tuple[np.ndarray, int]:
        """Run sherpa-onnx once and return (audio_float32, sample_rate)."""
        generated = self.tts.generate(text, sid=speaker)
        audio = np.asarray(generated.samples, dtype=np.float32)
        return audio, int(generated.sample_rate)

    def _to_wav_bytes(self, audio: np.ndarray, sample_rate: int) -> bytes:
        """Convert float32 audio to 16-bit PCM WAV bytes."""
        pcm = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())
        return buffer.getvalue()

    def _split_with_pause_map(
        self, text: str, pause_map: Dict[str, float]
    ) -> List[Tuple[str, float | None]]:
        """
        Split text into segments and include a pause multiplier after each segment
        when punctuation matches pause_map.
        """
        segments: List[Tuple[str, float | None]] = []
        last = 0
        for match in _PAUSE_PATTERN.finditer(text):
            _start, end = match.span()
            prefix = text[last:end]
            punct = match.group(1)
            segments.append((prefix, pause_map.get(punct, 1.0)))
            last = end
        if last < len(text):
            segments.append((text[last:], None))
        return segments

    def _build_model_config(self, model_config:dict, voice_config:dict) -> so.OfflineTtsConfig:
        match self.engine:
            case 'vits':
                cfg = so.OfflineTtsModelConfig(
                    vits=so.OfflineTtsVitsModelConfig(**model_config, **voice_config),
                    num_threads=4
                )
            case 'kokoro':
                cfg = so.OfflineTtsModelConfig(
                    kokoro=so.OfflineTtsKokoroModelConfig(**model_config, **voice_config),
                    num_threads=4
                )
        
        return so.OfflineTtsConfig(cfg)