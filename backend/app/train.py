"""Train a feedback-labelled routing pipeline and persist its evaluation metadata."""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app import db
from app.config import settings
from app.routing.features import FEATURE_ORDER


def _feedback_label(tier_final: str, feedback: int) -> str:
    """Keep a positively rated tier or promote a negative rating by one tier."""
    if feedback not in (-1, 1):
        raise ValueError("Training feedback must be -1 or 1.")
    tiers = [tier.name for tier in settings.TIERS]
    index = tiers.index(tier_final)
    return tiers[min(index + int(feedback == -1), len(tiers) - 1)]


def train() -> dict[str, Any]:
    """Train from saved feedback, returning metrics or a non-destructive skip reason."""
    db.init_db()
    rows = db.rows_for_training()
    row_count = len(rows)
    if row_count < 30:
        return {
            "trained": False, "n_rows": row_count,
            "message": f"Need at least 30 labelled requests to train; found {row_count}.",
        }

    try:
        features = [json.loads(row["features_json"]) for row in rows]
        vectors = np.asarray(
            [[feature[name] for name in FEATURE_ORDER] for feature in features], dtype=float
        )
        labels = [_feedback_label(row["tier_final"], row["feedback"]) for row in rows]
        if not np.isfinite(vectors).all():
            raise ValueError("Training features must be finite.")
    except (ValueError, KeyError, TypeError):
        return {
            "trained": False, "n_rows": row_count,
            "message": "Saved features or feedback are invalid; the existing model was not changed.",
        }

    counts = Counter(labels)
    if len(counts) < 2:
        return {
            "trained": False, "n_rows": row_count,
            "message": "Need feedback covering at least two tier labels to train a classifier.",
        }

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(max_iter=1000)),
    ])
    if min(counts.values()) >= 2:
        training_vectors, evaluation_vectors, training_labels, evaluation_labels = train_test_split(
            vectors, labels, test_size=0.2, random_state=42, stratify=labels
        )
        evaluation = "holdout"
    else:
        training_vectors = evaluation_vectors = vectors
        training_labels = evaluation_labels = labels
        evaluation = "training"
    pipeline.fit(training_vectors, training_labels)
    predictions = pipeline.predict(evaluation_vectors)
    classes = pipeline.classes_.tolist()
    metadata = {
        "trained": True,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": row_count,
        "accuracy": float(accuracy_score(evaluation_labels, predictions)),
        "classes": classes,
        "confusion_matrix": confusion_matrix(evaluation_labels, predictions, labels=classes).tolist(),
        "evaluation": evaluation,
    }
    pipeline.fit(vectors, labels)

    model_path = settings.MODEL_PATH
    model_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = model_path.with_name("router_model_meta.json")
    with TemporaryDirectory(dir=model_path.parent) as directory:
        staged_model = Path(directory) / "model.joblib"
        staged_metadata = Path(directory) / "metadata.json"
        joblib.dump(pipeline, staged_model)
        staged_metadata.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        staged_model.replace(model_path)
        staged_metadata.replace(metadata_path)
    return metadata


def main() -> None:
    """Print training accuracy, confusion matrix, or a friendly skip message as JSON."""
    print(json.dumps(train(), indent=2))


if __name__ == "__main__":
    main()