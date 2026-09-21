"""Verify tier choices, rule precedence, and exact word-count boundaries."""

import pytest

from app.routing.features import extract_features
from app.routing.heuristic import pick_tier


@pytest.mark.parametrize(("prompt", "expected"), [
    ("Hello!", "small"),
    ("What is the capital of France?", "small"),
    ("Please return the next value in this Python list", "medium"),
    ("Why is the sky blue?", "medium"),
    ("Explain this code", "medium"),
    ("Give me a comprehensive overview", "large"),
    ("Write a detailed explanation of this Python code", "large"),
    ("Generate a report", "large"),
])
def test_prompt_tiers(prompt: str, expected: str) -> None:
    """Representative prompts cover all tiers and short high-complexity requests."""
    tier, reason = pick_tier(extract_features([{"role": "user", "content": prompt}]))

    assert tier == expected
    assert reason


@pytest.mark.parametrize(("words", "expected"), [
    (11, "small"), (12, "small"), (120, "small"), (121, "medium"),
])
def test_plain_prompt_boundaries(words: int, expected: str) -> None:
    """Length alone promotes a prompt only after 120 words."""
    prompt = " ".join(["context"] * words)
    tier, reason = pick_tier(extract_features([{"role": "user", "content": prompt}]))

    assert tier == expected
    assert reason


@pytest.mark.parametrize(("words", "expected"), [(200, "medium"), (201, "large")])
def test_code_reasoning_boundary(words: int, expected: str) -> None:
    """Code plus reasoning promotes to large only after 200 words."""
    prompt = "Explain code " + " ".join(["context"] * (words - 2))
    tier, reason = pick_tier(extract_features([{"role": "user", "content": prompt}]))

    assert tier == expected
    assert reason


@pytest.mark.parametrize("prefix", ["code", "explain"])
def test_large_complexity_requires_both_cues(prefix: str) -> None:
    """Length plus only code or only reasoning is not the large-tier combination."""
    prompt = prefix + " " + " ".join(["context"] * 200)
    tier, _reason = pick_tier(extract_features([{"role": "user", "content": prompt}]))

    assert tier == "medium"