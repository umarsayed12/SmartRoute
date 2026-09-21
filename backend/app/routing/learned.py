"""Lazily load a trained tier classifier, falling back when it is unavailable."""

import logging
from functools import lru_cache

import joblib
from sklearn.pipeline import Pipeline

from app.config import settings
from app.routing.features import FEATURE_ORDER

_logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_model(path: str, _modified_ns: int, _size: int) -> Pipeline | None:
    """Cache one model version, including failed loads, until its file changes."""
    try:
        model = joblib.load(path)
        if not isinstance(model, Pipeline) or model.n_features_in_ != len(FEATURE_ORDER):
            raise ValueError("Model does not match the routing feature vector.")
        if not set(model.classes_).issubset({"small", "medium", "large"}):
            raise ValueError("Model contains unknown tier labels.")
        return model
    except Exception as error:
        _logger.warning("Learned router could not be loaded; using heuristic: %s", error)
        return None


def pick_tier(features: dict[str, float]) -> tuple[str, float, str] | None:
    """Predict a tier and probability, or return none for heuristic fallback."""
    path = settings.MODEL_PATH.resolve()
    try:
        version = path.stat()
    except OSError:
        return None
    model = _load_model(str(path), version.st_mtime_ns, version.st_size)
    if model is None:
        return None
    try:
        probabilities = model.predict_proba([[features[name] for name in FEATURE_ORDER]])[0]
        index = int(probabilities.argmax())
        tier = str(model.classes_[index])
        probability = float(probabilities[index])
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        _logger.warning("Learned prediction failed; using heuristic: %s", error)
        return None
    return tier, probability, f"Learned router selected {tier} (probability {probability:.2f})."