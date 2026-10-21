"""Tier 2: Boundary, Decision, and Context-Aware Heuristic Tests.

Verifies:
1. Cascade Step 1: Conversational short-circuit (greetings, acknowledgments, praise, closures)
   routing to 'small' regardless of prior code/reasoning in history.
2. Cascade Step 2: Standalone current turn evaluation (long output, code+reasoning > 200 words,
   code, math, reasoning, short technical without history).
3. Cascade Step 3: Conditional history inheritance (anaphoric and short technical cues
   referencing prior code, math, or reasoning, and large-tier inheritance).
4. Non-inheritance / Context Isolation: Unrelated queries do NOT inherit prior complexity.
5. Cascade Step 4: Word count boundaries on current turn (11, 12, 120, 121).
6. Legacy plain dict duck-typing fallback for backward compatibility.
"""

import pytest

from app.routing.features import extract_features
from app.routing.heuristic import _pick_tier_legacy, pick_tier


HEAVY_CODE_HISTORY = [
    {"role": "user", "content": "Write a complete distributed raft consensus module in Python."},
    {
        "role": "assistant",
        "content": (
            "```python\n"
            "class RaftNode:\n"
            "    def __init__(self, node_id, peers):\n"
            "        self.node_id = node_id\n"
            "        self.peers = peers\n"
            "        self.current_term = 0\n"
            "        self.voted_for = None\n"
            "        self.log = []\n"
            "        self.commit_index = 0\n"
            "        self.state = 'follower'\n"
            "\n"
            "    def handle_append_entries(self, term, leader_id, prev_log_idx, prev_log_term, entries):\n"
            "        if term < self.current_term:\n"
            "            return False\n"
            "        self.current_term = term\n"
            "        return True\n"
            "```\n" + " ".join(["log_entry"] * 400)
        ),
    },
]

HEAVY_MATH_HISTORY = [
    {"role": "user", "content": "Derive the Kalman filter state update equations."},
    {
        "role": "assistant",
        "content": (
            "We solve the equation: x_hat = A * x + B * u.\n"
            "The covariance update is P = A * P * A^T + Q.\n"
            "Calculate Kalman gain K = P * H^T * (H * P * H^T + R)^-1.\n"
            + " ".join(["derivation_step"] * 200)
        ),
    },
]

HEAVY_REASONING_HISTORY = [
    {"role": "user", "content": "Compare synchronous vs asynchronous consensus models."},
    {
        "role": "assistant",
        "content": (
            "Let us analyze step by step the theoretical bounds of the FLP impossibility theorem.\n"
            "Explain why no deterministic asynchronous consensus can guarantee liveness with crashes.\n"
            + " ".join(["theoretical_analysis"] * 250)
        ),
    },
]


# =====================================================================
# 1. Cascade Step 1: Conversational Short-Circuit to Small
# =====================================================================


@pytest.mark.parametrize(
    "greeting",
    [
        "Hi",
        "Hello",
        "Hey",
        "Good morning",
        "Hi there",
        "Hello there",
        "Howdy",
        "Greetings",
    ],
)
def test_short_circuit_greetings_despite_heavy_code_history(greeting: str) -> None:
    """Greetings immediately short-circuit to small tier regardless of prior code in history."""
    messages = list(HEAVY_CODE_HISTORY) + [{"role": "user", "content": greeting}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "small"
    assert "Conversational greeting, acknowledgment, or closure short-circuits to small tier." in reason


@pytest.mark.parametrize(
    "ack",
    [
        "Thanks",
        "Thank you",
        "Got it",
        "Understood",
        "Okay",
        "Cool",
        "All good",
        "Much appreciated",
        "No problem",
    ],
)
def test_short_circuit_acknowledgments_despite_heavy_code_history(ack: str) -> None:
    """Acknowledgments short-circuit to small tier regardless of prior code in history."""
    messages = list(HEAVY_CODE_HISTORY) + [{"role": "user", "content": ack}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "small"
    assert "Conversational greeting, acknowledgment, or closure short-circuits to small tier." in reason


@pytest.mark.parametrize(
    "praise",
    [
        "That looks super clean",
        "It looks great",
        "That works for me",
        "This is awesome",
        "That solved it",
        "It helped a lot",
        "Sounds good",
    ],
)
def test_short_circuit_praise_despite_heavy_code_history(praise: str) -> None:
    """Praise with pronouns short-circuits to small tier without triggering anaphoric inheritance."""
    messages = list(HEAVY_CODE_HISTORY) + [{"role": "user", "content": praise}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "small"
    assert "Conversational greeting, acknowledgment, or closure short-circuits to small tier." in reason


@pytest.mark.parametrize(
    "closure",
    [
        "Bye",
        "Goodbye",
        "See you later",
        "Farewell",
        "Have a good one",
        "Exit",
    ],
)
def test_short_circuit_closures_despite_heavy_code_history(closure: str) -> None:
    """Conversational closures short-circuit to small tier regardless of history."""
    messages = list(HEAVY_CODE_HISTORY) + [{"role": "user", "content": closure}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "small"
    assert "Conversational greeting, acknowledgment, or closure short-circuits to small tier." in reason


# =====================================================================
# 2. Cascade Step 2: Standalone Current Turn Evaluation
# =====================================================================


@pytest.mark.parametrize(
    "prompt",
    [
        "Write a comprehensive essay on distributed operating systems",
        "Generate a detailed report analyzing database indexing strategies",
        "Give me a detailed comparison between REST, gRPC, and GraphQL",
    ],
)
def test_standalone_long_output_routes_to_large(prompt: str) -> None:
    """Current turn asking for long or detailed output routes to large tier."""
    tier, reason = pick_tier(extract_features([{"role": "user", "content": prompt}]))

    assert tier == "large"
    assert reason == "Current turn asks for long or detailed output."


def test_standalone_code_and_reasoning_over_200_words_routes_to_large() -> None:
    """Current turn combining code and reasoning over 200 words routes to large tier."""
    prompt = (
        "Please explain why this code behaves unexpectedly.\n"
        "```python\n"
        "def fibonacci(n):\n"
        "    if n <= 1: return n\n"
        "    return fibonacci(n-1) + fibonacci(n-2)\n"
        "```\n"
        + " ".join(["context_word"] * 200)
    )
    tier, reason = pick_tier(extract_features([{"role": "user", "content": prompt}]))

    assert tier == "large"
    assert reason == "Current turn combines code and reasoning with over 200 words."


@pytest.mark.parametrize(
    "code_prompt",
    [
        "def quicksort(arr):\n    pass",
        "Please provide a Python script to parse an nginx access log",
        "Help me debug this SQL query: SELECT id FROM orders WHERE status = 'active'",
        "const express = require('express');",
    ],
)
def test_standalone_code_routes_to_medium(code_prompt: str) -> None:
    """Standalone current turn containing code or programming cues routes to medium."""
    tier, reason = pick_tier(extract_features([{"role": "user", "content": code_prompt}]))

    assert tier == "medium"
    assert reason == "Current turn contains code or programming cues."


@pytest.mark.parametrize(
    "math_prompt",
    [
        "Calculate 25 * 40",
        "Solve the equation 3x + 12 = 0",
        "What is the integral of x^2 dx?",
        "Find the sum of the first 50 prime numbers",
    ],
)
def test_standalone_math_routes_to_medium(math_prompt: str) -> None:
    """Standalone current turn containing mathematical cues routes to medium."""
    tier, reason = pick_tier(extract_features([{"role": "user", "content": math_prompt}]))

    assert tier == "medium"
    assert reason == "Current turn contains mathematical formulas or calculations."


@pytest.mark.parametrize(
    "reasoning_prompt",
    [
        "Explain why neural networks require activation functions",
        "Compare the architectural trade-offs of microservices vs monoliths",
        "Analyze why this query execution plan chooses a sequential scan",
        "Prove that the square root of 2 is irrational",
    ],
)
def test_standalone_reasoning_routes_to_medium(reasoning_prompt: str) -> None:
    """Standalone current turn asking for reasoning or explanation routes to medium."""
    tier, reason = pick_tier(extract_features([{"role": "user", "content": reasoning_prompt}]))

    assert tier == "medium"
    assert reason == "Current turn asks for explanation or reasoning."


@pytest.mark.parametrize(
    "short_tech",
    [
        "Fix line 3",
        "What about space complexity?",
        "Check time complexity",
        "Add unit tests for this",
    ],
)
def test_standalone_short_technical_routes_to_medium(short_tech: str) -> None:
    """Short technical query without history routes to medium as a concise technical query."""
    tier, reason = pick_tier(extract_features([{"role": "user", "content": short_tech}]))

    assert tier == "medium"
    assert reason == "Prompt contains concise technical query or instruction."


# =====================================================================
# 3. Cascade Step 3: Conditional History Inheritance
# =====================================================================


@pytest.mark.parametrize(
    "follow_up",
    [
        "How does it work?",
        "Optimize that",
        "Can you simplify it?",
        "Speed that up",
        "Refactor it for performance",
    ],
)
def test_anaphoric_follow_up_inherits_prior_code(follow_up: str) -> None:
    """Anaphoric queries referencing prior code inherit medium tier via prior code."""
    messages = list(HEAVY_CODE_HISTORY) + [{"role": "user", "content": follow_up}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "medium"
    assert reason == "Contextual follow-up referencing prior code."


@pytest.mark.parametrize(
    "follow_up",
    [
        "Why did you write it like that?",
        "Why?",
    ],
)
def test_anaphoric_reasoning_follow_up_routes_to_medium(follow_up: str) -> None:
    """Anaphoric queries containing reasoning cues ('why') route to medium via reasoning."""
    messages = list(HEAVY_CODE_HISTORY) + [{"role": "user", "content": follow_up}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "medium"
    assert reason == "Current turn asks for explanation or reasoning."


@pytest.mark.parametrize(
    "follow_up",
    [
        "Fix line 3",
        "What about space complexity?",
        "Check time complexity",
        "Handle edge cases with empty input",
    ],
)
def test_short_technical_follow_up_inherits_prior_code(follow_up: str) -> None:
    """Short technical queries referencing prior code inherit medium tier."""
    messages = list(HEAVY_CODE_HISTORY) + [{"role": "user", "content": follow_up}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "medium"
    assert reason == "Contextual follow-up referencing prior code."


@pytest.mark.parametrize(
    "follow_up",
    [
        "How does that step follow?",
        "What about the third step?",
        "Can you simplify that for me?",
    ],
)
def test_contextual_follow_up_inherits_prior_math(follow_up: str) -> None:
    """Contextual follow-ups referencing prior math inherit medium tier."""
    messages = list(HEAVY_MATH_HISTORY) + [{"role": "user", "content": follow_up}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "medium"
    assert reason == "Contextual follow-up referencing prior mathematical derivation."


@pytest.mark.parametrize(
    "follow_up",
    [
        "How does that work in practice?",
        "What about the alternative?",
        "Can you elaborate on that?",
    ],
)
def test_contextual_follow_up_inherits_prior_reasoning(follow_up: str) -> None:
    """Contextual follow-ups referencing prior reasoning inherit medium tier."""
    # Build history that has reasoning without code
    messages = list(HEAVY_REASONING_HISTORY) + [{"role": "user", "content": follow_up}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "medium"
    # When follow-up has no reasoning keyword, inherits prior reasoning; if elaborate/why, matches reasoning
    assert "referencing prior explanation or reasoning" in reason or "asks for explanation or reasoning" in reason


def test_contextual_follow_up_inheriting_large_tier() -> None:
    """Contextual follow-up combining code and reasoning exceeding 200 words routes to large."""
    # History has code and reasoning
    history_with_code_and_reasoning = [
        {"role": "user", "content": "Explain and write a distributed raft consensus module in Python."},
        {
            "role": "assistant",
            "content": (
                "```python\ndef raft(): pass\n```\n"
                "Explain step by step how leader election operates.\n"
                + " ".join(["word"] * 400)
            ),
        },
    ]
    # Current turn is anaphoric (> 200 words referencing prior code and reasoning)
    anaphoric_follow_up = "Optimize that implementation and refactor the state machine " + " ".join(["context"] * 205)
    messages = history_with_code_and_reasoning + [{"role": "user", "content": anaphoric_follow_up}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "large"
    assert reason == "Contextual follow-up combines code and reasoning exceeding 200 words."


# =====================================================================
# 4. Context Isolation (No Context Bleed on Unrelated Queries)
# =====================================================================


@pytest.mark.parametrize(
    "unrelated_short_query",
    [
        "What is the capital of France?",
        "How many continents are there?",
        "Tell me a short joke",
        "The sky is very blue today.",
    ],
)
def test_unrelated_queries_do_not_bleed_context_from_prior_code(
    unrelated_short_query: str,
) -> None:
    """Unrelated queries following code history do NOT inherit complexity."""
    messages = list(HEAVY_CODE_HISTORY) + [{"role": "user", "content": unrelated_short_query}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "small"
    assert "Current turn has fewer than 12 words" in reason or "at most 120 words" in reason


def test_moderate_length_unrelated_query_remains_small() -> None:
    """A 50-word generic query without technical cues remains small despite prior code."""
    prompt = " ".join(["sentence"] * 50)
    messages = list(HEAVY_CODE_HISTORY) + [{"role": "user", "content": prompt}]
    tier, reason = pick_tier(extract_features(messages))

    assert tier == "small"
    assert reason == "Current turn has at most 120 words and no higher-tier cues."


# =====================================================================
# 5. Cascade Step 4: Word Count Boundaries on Current Turn
# =====================================================================


@pytest.mark.parametrize(
    ("words", "expected_tier", "expected_reason"),
    [
        (11, "small", "Current turn has fewer than 12 words and no code or reasoning cues."),
        (12, "small", "Current turn has at most 120 words and no higher-tier cues."),
        (120, "small", "Current turn has at most 120 words and no higher-tier cues."),
        (121, "medium", "Current turn contains over 120 words."),
    ],
)
def test_current_turn_word_count_boundaries(
    words: int, expected_tier: str, expected_reason: str
) -> None:
    """Exact word count boundary transitions on current turn without cues."""
    prompt = " ".join(["plain"] * words)
    tier, reason = pick_tier(extract_features([{"role": "user", "content": prompt}]))

    assert tier == expected_tier
    assert reason == expected_reason


# =====================================================================
# 6. Legacy Plain Dict Fallback Duck-Typing
# =====================================================================


def test_legacy_plain_dict_long_output() -> None:
    """Plain dictionary input with asks_long_output routes to large via legacy rules."""
    legacy_features = {
        "prompt_words": 10.0,
        "has_code": 0.0,
        "asks_reasoning": 0.0,
        "asks_long_output": 1.0,
    }
    tier, reason = pick_tier(legacy_features)

    assert tier == "large"
    assert reason == "Prompt asks for long or detailed output."


def test_legacy_plain_dict_code_and_reasoning_over_200_words() -> None:
    """Plain dictionary input with code and reasoning over 200 words routes to large."""
    legacy_features = {
        "prompt_words": 201.0,
        "has_code": 1.0,
        "asks_reasoning": 1.0,
        "asks_long_output": 0.0,
    }
    tier, reason = pick_tier(legacy_features)

    assert tier == "large"
    assert reason == "Prompt combines code and reasoning with over 200 words."


@pytest.mark.parametrize(
    ("features", "expected_tier", "expected_reason"),
    [
        ({"has_code": 1.0, "prompt_words": 20.0}, "medium", "Prompt contains code or programming cues."),
        ({"asks_reasoning": 1.0, "prompt_words": 20.0}, "medium", "Prompt asks for explanation or reasoning."),
        ({"prompt_words": 121.0}, "medium", "Prompt contains over 120 words."),
        ({"prompt_words": 11.0}, "small", "Prompt has fewer than 12 words and no code or reasoning cues."),
        ({"prompt_words": 50.0}, "small", "Prompt has at most 120 words and no higher-tier cues."),
    ],
)
def test_legacy_plain_dict_rules(
    features: dict[str, float], expected_tier: str, expected_reason: str
) -> None:
    """Plain dictionary without current_turn/history correctly executes legacy rules."""
    tier, reason = pick_tier(features)

    assert tier == expected_tier
    assert reason == expected_reason


def test_pick_tier_legacy_direct_call() -> None:
    """Direct invocation of _pick_tier_legacy produces expected legacy routing."""
    tier, reason = _pick_tier_legacy({"prompt_words": 5.0, "has_code": 0.0})
    assert tier == "small"
    assert reason == "Prompt has fewer than 12 words and no code or reasoning cues."
