import json
from .tts import TTS
from pathlib import Path
from huggingface_hub import snapshot_download


# Base directory of this file (the module where TTSManager lives)
BASE_DIR = Path(__file__).resolve().parent
MODELS_CONFIG_PATH = BASE_DIR / "configs" / "models.json"
VOICES_CONFIG_PATH = BASE_DIR / "configs" / "voices.json"
MODELS_DIR = BASE_DIR / "models"
SHARED_ESPEAK_DIR = MODELS_DIR / "espeak-ng-data"
HUGGING_FACE_BASE : str = "abastian/"


class TTSManager:
    def __init__(self):

        self.models = self._load_models_config()
        with VOICES_CONFIG_PATH.open("r", encoding="utf-8") as f:
            self.voices = json.load(f)

    def initialize_tts(self, voice_id: str) -> "TTS":
        voice = self.voices[voice_id]
        model_id = voice["model_id"]
        if not model_id in self.models:
            self._download_model(model_id)
        model = self.models[model_id]

        return TTS(
            model_info=model,
            voice_info=voice,
        )
    
    def _download_model(self, model_id:str):
        repo_id = HUGGING_FACE_BASE + model_id

        snapshot_download(
            repo_id=repo_id,
            revision="main",
            local_dir=MODELS_DIR / model_id
        )

        self._create_model_config(model_id)
        self.models = self._load_models_config()

    
    def _create_model_config(self, model_id: str) -> dict:
        model_dir = MODELS_DIR / model_id

        if not model_dir.exists():
            raise FileNotFoundError(f"Model directory not found: {model_dir}")

        def require(name: str) -> Path:
            path = model_dir / name
            if not path.exists():
                raise FileNotFoundError(f"Required file missing: {path}")
            return path

        def optional(name: str) -> Path | None:
            path = model_dir / name
            return path if path.exists() else None

        # Required for all Piper/Kokoro-style models
        model_file = self._find_onnx_model(model_dir)
        tokens_file = require("tokens.txt")
        # Optional (kokoro-specific)
        voices_file = optional("voices.bin")

        config = {
            "engine": "kokoro" if voices_file else "vits",
            "config": {
                "model": str(model_file.relative_to(MODELS_DIR)),
                "tokens": str(tokens_file.relative_to(MODELS_DIR)),
                "data_dir": str(SHARED_ESPEAK_DIR),
            }
        }

        if voices_file:
            config["config"]["voices"] = str(
                voices_file.relative_to(MODELS_DIR)
            )

        with open(MODELS_CONFIG_PATH, "r") as f:
            jf = json.load(f)
            jf[model_id] = config
        with open(MODELS_CONFIG_PATH, "w") as f:
            json.dump(jf, f, indent=2)

    def _find_onnx_model(self, model_dir: Path) -> Path:
        onnx_files = sorted(
            p for p in model_dir.iterdir()
            if p.is_file() and p.suffix == ".onnx"
        )

        if not onnx_files:
            raise FileNotFoundError(f"No .onnx file found in {model_dir}")

        if len(onnx_files) > 1:
            raise RuntimeError(
                f"Multiple .onnx files found in {model_dir}: "
                f"{[p.name for p in onnx_files]}"
            )

        return onnx_files[0]
    

    def _load_models_config(self):
        if MODELS_CONFIG_PATH.exists():
            with MODELS_CONFIG_PATH.open("r", encoding="utf-8") as f:
                models = json.load(f)

            for model_id, model_info in models.items():
                config_paths = model_info.get("config", {})
                for key, value in list(config_paths.items()):
                    # Only normalize string paths
                    if isinstance(value, str):
                        p = Path(value)
                        # If it's relative, make it relative to MODELS_DIR
                        if not p.is_absolute():
                            config_paths[key] = str((MODELS_DIR / p).resolve())
                        else:
                            config_paths[key] = str(p)

                # Write back the normalized config
                model_info["config"] = config_paths
        else:
            models = {}
            with MODELS_CONFIG_PATH.open('w') as f:
                json.dump(models, f)

        return models

