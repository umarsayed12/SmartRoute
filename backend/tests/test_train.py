"""Verify feedback labels, training safeguards, metrics, and saved model compatibility."""

import json
from datetime import datetime
from typing import Any
from unittest.mock import Mock

import joblib
import pytest
from sklearn.pipeline import Pipeline

from app import train as training
from app.routing import learned
from app.routing.features import FEATURE_ORDER, extract_features


def _rows() -> list[dict[str, Any]]:
    """Generate labelled feature rows without adding synthetic history to the user's database."""
    rows = []
    for tier, prompt in [
        ("small", "Hello"),
        ("medium", "Explain this Python code"),
        ("large", "Write a comprehensive essay"),
    ]:
        for index in range(10):
            features = extract_features([{
                "role": "user", "content": prompt + " context" * index,
            }])
            rows.append({
                "tier_final": tier, "feedback": 1,
                "features_json": json.dumps(dict(reversed(list(features.items())))),
            })
    return rows


@pytest.mark.parametrize(("tier", "feedback", "expected"), [
    ("small", 1, "small"), ("small", -1, "medium"),
    ("medium", 1, "medium"), ("medium", -1, "large"),
    ("large", 1, "large"), ("large", -1, "large"),
])
def test_feedback_labels(tier: str, feedback: int, expected: str) -> None:
    """Negative labels move one tier upward even when large currently falls back to medium."""
    assert training._feedback_label(tier, feedback) == expected


@pytest.mark.parametrize("count", [0, 29])
def test_insufficient_feedback_preserves_model(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    """Too few labelled rows leave existing artifacts untouched."""
    monkeypatch.setattr(training.db, "rows_for_training", Mock(return_value=_rows()[:count]))
    path = training.settings.MODEL_PATH
    path.write_bytes(b"existing artifact")
    metadata_path = path.with_name("router_model_meta.json")
    metadata_path.write_text('{"trained_at":"previous"}', encoding="utf-8")

    result = training.train()

    assert result["trained"] is False
    assert result["n_rows"] == count
    assert "30" in result["message"]
    assert path.read_bytes() == b"existing artifact"
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["trained_at"] == "previous"


def test_single_class_skips_training(monkeypatch: pytest.MonkeyPatch) -> None:
    """Logistic regression cannot train on a single target class."""
    rows = _rows()
    for row in rows:
        row["tier_final"] = "medium"
    monkeypatch.setattr(training.db, "rows_for_training", Mock(return_value=rows))

    result = training.train()

    assert result["trained"] is False
    assert "two tier labels" in result["message"]
    assert not training.settings.MODEL_PATH.exists()


@pytest.mark.parametrize("negative_small", [False, True])
def test_training_saves_usable_pipeline(
    monkeypatch: pytest.MonkeyPatch, negative_small: bool
) -> None:
    """Evaluate on held-out rows, refit on all rows, and save matching metadata."""
    rows = _rows()
    if negative_small:
        for row in rows[:10]:
            row["feedback"] = -1
    monkeypatch.setattr(training.db, "rows_for_training", Mock(return_value=rows))

    result = training.train()

    assert result["trained"] is True
    assert result["n_rows"] == 30
    assert result["evaluation"] == "holdout"
    assert 0 <= result["accuracy"] <= 1
    assert sum(sum(row) for row in result["confusion_matrix"]) == 6
    expected_classes = ["large", "medium"] if negative_small else ["large", "medium", "small"]
    assert result["classes"] == expected_classes
    assert datetime.fromisoformat(result["trained_at"]).utcoffset().total_seconds() == 0
    model_path = training.settings.MODEL_PATH
    metadata = json.loads(model_path.with_name("router_model_meta.json").read_text(encoding="utf-8"))
    assert metadata == result
    pipeline = joblib.load(model_path)
    assert isinstance(pipeline, Pipeline)
    assert pipeline.named_steps["classifier"].max_iter == 1000
    assert pipeline.named_steps["scaler"].n_samples_seen_ == 30
    assert pipeline.n_features_in_ == len(FEATURE_ORDER)
    prediction = learned.pick_tier(json.loads(rows[0]["features_json"]))
    assert prediction is not None
    assert prediction[0] == ("medium" if negative_small else "small")


def test_rare_class_marks_training_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """A singleton class permits fitting but must not claim a held-out evaluation."""
    rows = _rows()
    for row in rows:
        row["tier_final"] = "small"
    rows[-1]["tier_final"] = "large"
    monkeypatch.setattr(training.db, "rows_for_training", Mock(return_value=rows))

    result = training.train()

    assert result["trained"] is True
    assert result["evaluation"] == "training"
    assert sum(sum(row) for row in result["confusion_matrix"]) == 30


@pytest.mark.parametrize("bad_features", ['{"prompt_words":1}', 'not json', '{"prompt_words":"bad"}'])
def test_invalid_features_preserve_existing_model(
    monkeypatch: pytest.MonkeyPatch, bad_features: str
) -> None:
    """Incompatible saved features cannot overwrite a previously trained artifact."""
    rows = _rows()
    rows[0]["features_json"] = bad_features
    monkeypatch.setattr(training.db, "rows_for_training", Mock(return_value=rows))
    training.settings.MODEL_PATH.write_bytes(b"existing artifact")

    result = training.train()

    assert result["trained"] is False
    assert "invalid" in result["message"]
    assert training.settings.MODEL_PATH.read_bytes() == b"existing artifact"


def test_training_cli_without_feedback(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI handles a fresh database normally and prints its next-step message."""
    training.main()

    result = json.loads(capsys.readouterr().out)
    assert result["trained"] is False
    assert result["n_rows"] == 0
    assert "30 labelled requests" in result["message"]