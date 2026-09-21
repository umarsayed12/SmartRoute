"""Check prompt feature counts, cue detection, Unicode, and empty input."""

import pytest

from app.routing.features import FEATURE_ORDER, extract_features


def test_empty_features_and_order() -> None:
    """An empty conversation yields a stable, all-zero numeric vector."""
    features = extract_features([])

    assert list(features) == FEATURE_ORDER == [
        "prompt_chars", "prompt_words", "num_turns", "has_code", "has_math",
        "question_count", "asks_reasoning", "asks_long_output",
        "non_ascii_ratio", "avg_word_len",
    ]
    assert all(isinstance(value, float) and value == 0 for value in features.values())


def test_conversation_counts() -> None:
    """Count every message content while excluding role names from the prompt."""
    features = extract_features([
        {"role": "user", "content": "Hi!"},
        {"role": "assistant", "content": "Why now?"},
    ])

    assert features["prompt_chars"] == 12
    assert features["prompt_words"] == 3
    assert features["num_turns"] == 2
    assert features["question_count"] == 1
    assert features["avg_word_len"] == pytest.approx(10 / 3)
    assert features["asks_reasoning"] == 1


def test_unicode_ratio() -> None:
    """Count non-ASCII characters, not encoded bytes, against total characters."""
    features = extract_features([{"role": "user", "content": "caf\u00e9 \u4f60\u597d"}])

    assert features["prompt_chars"] == 7
    assert features["prompt_words"] == 2
    assert features["non_ascii_ratio"] == pytest.approx(3 / 7)
    assert features["avg_word_len"] == 3


def test_whitespace_only_content() -> None:
    """Whitespace does not create words or cause division by zero."""
    features = extract_features([{"role": "user", "content": " \t\n"}])

    assert features["prompt_chars"] == 3
    assert features["num_turns"] == 1
    assert features["prompt_words"] == features["avg_word_len"] == 0


@pytest.mark.parametrize(("prompt", "feature", "expected"), [
    ("```\nprint(1)\n```", "has_code", 1),
    ("Return `value`", "has_code", 1),
    ("def add(left, right):", "has_code", 1),
    ("const answer = 42", "has_code", 1),
    ("Help debug this SQL query", "has_code", 1),
    ("Decode this greeting", "has_code", 0),
    ("What is 2 + 2?", "has_math", 1),
    ("Calculate an integral", "has_math", 1),
    ("What is \u221a9?", "has_math", 1),
    ("A consumer product", "has_math", 0),
    ("EXPLAIN gravity", "asks_reasoning", 1),
    ("Why is this true?", "asks_reasoning", 1),
    ("Compare these options", "asks_reasoning", 1),
    ("Analyze the result", "asks_reasoning", 1),
    ("Work step by step", "asks_reasoning", 1),
    ("Work step-by-step", "asks_reasoning", 1),
    ("Prove the claim", "asks_reasoning", 1),
    ("An unexplained event", "asks_reasoning", 0),
    ("An essay about space", "asks_long_output", 1),
    ("A DETAILED summary", "asks_long_output", 1),
    ("A comprehensive overview", "asks_long_output", 1),
    ("Write a story", "asks_long_output", 1),
    ("Generate a report", "asks_long_output", 1),
    ("A writer and a generator", "asks_long_output", 0),
])
def test_feature_cues(prompt: str, feature: str, expected: int) -> None:
    """Detect whole-word cues and syntax without matching unrelated substrings."""
    features = extract_features([{"role": "user", "content": prompt}])

    assert features[feature] == expected