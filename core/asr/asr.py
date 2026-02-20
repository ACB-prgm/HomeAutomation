import numpy as np
import soundfile as sf
from pathlib import Path
from sherpa_onnx import OfflineRecognizer

ASR_DIR = Path(__file__).resolve().parent / "models/asr"


class ASR:
    def __init__(
        self,
        r_model_path: str | Path = ASR_DIR / "model.int8.onnx",
        r_tokens_path: str | Path = ASR_DIR / "tokens.txt",
        num_threads: int = 4,
        provider: str = "cpu",
    ):
        self.recognizer = OfflineRecognizer.from_nemo_ctc(
            model=str(r_model_path),
            tokens=str(r_tokens_path),
            num_threads=num_threads,
            provider=provider,
        )

    def transcribe(self, wav_path: str) -> str:
        wav_path = Path(wav_path)
        if not wav_path.exists():
            raise FileNotFoundError(wav_path)

        audio, sample_rate = sf.read(wav_path, dtype="float32")
        return self.transcribe_samples(sample_rate=sample_rate, audio=audio)

    def transcribe_samples(self, sample_rate: int, audio: np.ndarray) -> str:
        x = np.asarray(audio, dtype=np.float32)
        if x.ndim == 2:
            x = np.mean(x, axis=1)
        x = x.reshape(-1)
        if x.size == 0:
            return ""

        return self._transcribe(sample_rate, x)

    def _transcribe(self, sample_rate: int, audio: np.ndarray) -> str:
        stream = self.recognizer.create_stream()
        stream.accept_waveform(int(sample_rate), np.asarray(audio, dtype=np.float32))
        self.recognizer.decode_stream(stream)
        return stream.result.text.strip()
