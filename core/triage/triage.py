from pathlib import Path
from os import listdir

import re
import joblib

_TRIAGE_DIR = Path(__file__).resolve().parent
MODELS_DIR = _TRIAGE_DIR / "models"

ROUTINES = [
    'reset subwoofer',
    'goodnight'
]

class UtteranceCategorizer:
    def __init__(self, model_name="LinearSVC", trigger="alexa"):
        self.trigger = trigger
        self.model_name = model_name
        self.models_dir = MODELS_DIR
        AVAILABLE_MODELS = {m.split('.')[0]: m for m in listdir(self.models_dir)}

        if model_name not in AVAILABLE_MODELS:
            raise ValueError(f"Unknown model '{model_name}'. Choose from: {list(AVAILABLE_MODELS)}")

        model_path = self.models_dir / AVAILABLE_MODELS[model_name]
        if not model_path.exists():
            raise FileNotFoundError(
                f"Model artifact not found at {model_path}. Save your trained pipeline there or update AVAILABLE_MODELS."
            )
        # Keep the model hot in memory
        self.model = joblib.load(model_path)

    def _preprocess(self, text):
        """Mirror the training-time cleaning: remove trigger word, punctuation, stem, and strip."""
        cleaned = (text or "").lower()
        cleaned = cleaned.replace(self.trigger, "").strip()
        cleaned = re.sub(r"[^\w\s]", "", cleaned)
        
        return cleaned

    def categorize(self, text):
        """Predict a category for a single string or a list of strings."""
        text = self._preprocess(text)

        if text in ROUTINES:
            return "Routine"
        else:
            preds = self.model.predict(text)
            return preds[0]

__all__ = ["Categorizer"]
