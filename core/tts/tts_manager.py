import json
from .tts import TTS
from pathlib import Path
from typing import Optional

# Base directory of this file (the module where TTSManager lives)
BASE_DIR = Path(__file__).resolve().parent
MODELS_CONFIG_PATH = BASE_DIR / "configs" / "models.json"
VOICES_CONFIG_PATH = BASE_DIR / "configs" / "voices.json"
MODELS_DIR = BASE_DIR / "models"


class TTSManager:
    def __init__(self):

        self.models = self._load_models_config()
        with VOICES_CONFIG_PATH.open("r", encoding="utf-8") as f:
            self.voices = json.load(f)

    def initialize_tts(self, voice_id: str) -> "TTS":
        voice = self.voices[voice_id]
        model = self.models[voice["model_id"]]

        return TTS(
            model_info=model,
            voice_info=voice,
        )
    
    def _load_models_config(self):
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

        return models

