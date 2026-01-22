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
    
    def categorize(self, text: str):
        cleaned_text = self._preprocess(text)

        category: str
        if cleaned_text in ROUTINES:
            category = "Routine"
        else:
            category = self._simple_categorize(cleaned_text)

            if not category:
                category = self._ml_categorize(cleaned_text)
        
        return category, cleaned_text


    def _preprocess(self, text):
        """Mirror the training-time cleaning: remove trigger word, punctuation, stem, and strip."""
        cleaned = (text or "").lower()
        cleaned = cleaned.replace(self.trigger, "").strip()
        cleaned = re.sub(r"[^\w\s]", "", cleaned)
        
        return cleaned

    def _simple_categorize(self, query: str):
        if "what time is it" in query:
            return "Clock"
        elif "" in query:
            return ""
        else:
            return None

    def _ml_categorize(self, text):
        """Predict a category for a single string or a list of strings."""

        preds = self.model.predict([text])
        return preds[0]

__all__ = ["Categorizer"]
