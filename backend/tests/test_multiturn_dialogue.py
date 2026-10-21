"""Tier 3: Multi-turn Dialogue Drift & Edge-Case Traps.

Verifies:
1. Complete 10-turn dialogue drift lifecycle across alternating conversational and technical states.
2. Pronoun follow-up traps vs conversational praise in identical multi-turn context.
3. Intervening polite exchanges between code generation and line-level fixes.
4. System prompt isolation (system instructions do not bleed into pure greetings).
5. Multi-topic transitions (code -> chat -> math -> chat -> bug fix -> closure).
6. Elliptical questions ("Why?", "How?") across code, math, and explanation histories.
"""

import pytest

from app.routing.features import extract_features
from app.routing.heuristic import pick_tier


def test_10_turn_dialogue_drift_complete_lifecycle() -> None:
    """Verify tier selection and feature extraction across every turn of a 10-turn dialogue."""
    dialogue: list[dict[str, str]] = []

    # Turn 1: User greeting
    dialogue.append({"role": "user", "content": "Hello there! Good morning."})
    f1 = extract_features(dialogue)
    tier1, reason1 = pick_tier(f1)
    assert tier1 == "small"
    assert f1.current_turn.is_pure_conversational is True
    assert "Conversational greeting, acknowledgment, or closure" in reason1

    # Turn 2: Assistant responds
    dialogue.append({
        "role": "assistant",
        "content": "Good morning! How can I assist you with your programming tasks today?",
    })

    # Turn 3: User requests coding task
    dialogue.append({
        "role": "user",
        "content": "Help me implement a Python function to sort a list using merge sort",
    })
    f3 = extract_features(dialogue)
    tier3, reason3 = pick_tier(f3)
    assert tier3 == "medium"
    assert f3.current_turn.has_code is True
    assert "Current turn contains code or programming cues." in reason3

    # Turn 4: Assistant provides code
    dialogue.append({
        "role": "assistant",
        "content": (
            "```python\n"
            "def merge_sort(arr):\n"
            "    if len(arr) <= 1:\n"
            "        return arr\n"
            "    mid = len(arr) // 2\n"
            "    left = merge_sort(arr[:mid])\n"
            "    right = merge_sort(arr[mid:])\n"
            "    return merge(left, right)\n"
            "```"
        ),
    })

    # Turn 5: User acknowledges with praise (Pronoun Trap check)
    dialogue.append({"role": "user", "content": "Thanks, got it! That looks super clean."})
    f5 = extract_features(dialogue)
    tier5, reason5 = pick_tier(f5)
    # Must route to small tier with zero context bleed from Turn 4's code
    assert tier5 == "small"
    assert f5.current_turn.is_pure_conversational is True
    assert f5.current_turn.is_anaphoric is False
    assert "Conversational greeting, acknowledgment, or closure" in reason5

    # Turn 6: Assistant responds politely
    dialogue.append({
        "role": "assistant",
        "content": "You're very welcome! Let me know if you need any adjustments or another algorithm.",
    })

    # Turn 7: User asks unrelated casual knowledge question
    dialogue.append({"role": "user", "content": "By the way, what is the capital of Australia?"})
    f7 = extract_features(dialogue)
    tier7, reason7 = pick_tier(f7)
    # Must route to small tier without inheriting Turn 4's code
    assert tier7 == "small"
    assert "Current turn has fewer than 12 words" in reason7 or "at most 120 words" in reason7

    # Turn 8: Assistant answers
    dialogue.append({"role": "assistant", "content": "The capital of Australia is Canberra."})

    # Turn 9: User returns to code with technical query referencing Turn 4
    dialogue.append({"role": "user", "content": "Now back to that sorting algorithm: what about space complexity?"})
    f9 = extract_features(dialogue)
    tier9, reason9 = pick_tier(f9)
    # Inherits medium tier from history's code
    assert tier9 == "medium"
    assert f9.current_turn.is_short_technical is True or f9.current_turn.is_anaphoric is True
    assert "Contextual follow-up referencing prior code." in reason9

    # Turn 10: Assistant explains space complexity
    dialogue.append({
        "role": "assistant",
        "content": "Merge sort requires O(n) auxiliary space for temporary merging arrays.",
    })

    # Turn 11: User gives closure
    dialogue.append({"role": "user", "content": "Understood, thank you so much! Goodbye."})
    f11 = extract_features(dialogue)
    tier11, reason11 = pick_tier(f11)
    assert tier11 == "small"
    assert f11.current_turn.is_pure_conversational is True
    assert "Conversational greeting, acknowledgment, or closure" in reason11


# =====================================================================
# 2. Pronoun Follow-up Trap vs Conversational Praise
# =====================================================================


SHARED_CODE_CONVERSATION = [
    {"role": "user", "content": "Write a python function to compute moving averages."},
    {
        "role": "assistant",
        "content": (
            "```python\n"
            "def moving_average(values, window):\n"
            "    weights = np.repeat(1.0, window) / window\n"
            "    return np.convolve(values, weights, 'valid')\n"
            "```"
        ),
    },
]


@pytest.mark.parametrize(
    ("praise_prompt", "expected_tier"),
    [
        ("That looks super clean", "small"),
        ("It looks great", "small"),
        ("That works for me", "small"),
        ("That solved it", "small"),
        ("It helped a lot", "small"),
        ("This is really awesome", "small"),
        ("That's pretty slick", "small"),
    ],
)
def test_pronoun_praise_routes_to_small(praise_prompt: str, expected_tier: str) -> None:
    """Conversational praise containing pronouns disarms anaphora and routes to small."""
    messages = list(SHARED_CODE_CONVERSATION) + [{"role": "user", "content": praise_prompt}]
    features = extract_features(messages)
    tier, reason = pick_tier(features)

    assert tier == expected_tier
    assert features.current_turn.is_pure_conversational is True
    assert features.current_turn.is_anaphoric is False
    assert "Conversational greeting, acknowledgment, or closure" in reason


@pytest.mark.parametrize(
    ("anaphoric_prompt", "expected_tier"),
    [
        ("How does it work?", "medium"),
        ("Optimize that", "medium"),
        ("Can you simplify it?", "medium"),
        ("Speed that up", "medium"),
        ("Refactor it for readability", "medium"),
        ("Why did you write it like that?", "medium"),
        ("Why?", "medium"),
    ],
)
def test_pronoun_queries_route_to_medium(anaphoric_prompt: str, expected_tier: str) -> None:
    """True anaphoric queries referencing prior code inherit medium tier."""
    messages = list(SHARED_CODE_CONVERSATION) + [{"role": "user", "content": anaphoric_prompt}]
    features = extract_features(messages)
    tier, _reason = pick_tier(features)

    assert tier == expected_tier
    assert features.current_turn.is_pure_conversational is False
    assert features.current_turn.is_anaphoric is True


# =====================================================================
# 3. Intervening Polite Exchanges
# =====================================================================


def test_intervening_polite_exchange_before_fix_line() -> None:
    """An intervening polite exchange does not wash away prior code context for short technical fixes."""
    messages = [
        {"role": "user", "content": "Write quicksort in Python"},
        {
            "role": "assistant",
            "content": "```python\ndef quicksort(arr): return arr\n```",
        },
        {"role": "user", "content": "Thanks!"},
        {"role": "assistant", "content": "You are welcome!"},
        {"role": "user", "content": "Fix line 3"},
    ]
    features = extract_features(messages)
    tier, reason = pick_tier(features)

    assert tier == "medium"
    assert features.current_turn.is_short_technical is True
    assert reason == "Contextual follow-up referencing prior code."


def test_intervening_polite_exchange_before_complexity_query() -> None:
    """An intervening polite exchange preserves history_has_code for complexity questions."""
    messages = [
        {"role": "user", "content": "Implement binary search tree insertion"},
        {
            "role": "assistant",
            "content": "```python\nclass Node:\n    def __init__(self, val): self.val = val\n```",
        },
        {"role": "user", "content": "Understood, cool."},
        {"role": "assistant", "content": "Glad to help! Any other questions?"},
        {"role": "user", "content": "What about space complexity?"},
    ]
    features = extract_features(messages)
    tier, reason = pick_tier(features)

    assert tier == "medium"
    assert features.current_turn.is_short_technical is True
    assert reason == "Contextual follow-up referencing prior code."


# =====================================================================
# 4. System Prompt Isolation
# =====================================================================


def test_system_prompt_with_code_does_not_bleed_into_greeting() -> None:
    """System prompts containing code instructions do not cause greetings to route to medium."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert compiler engineer. Output all solutions using LLVM IR "
                "or Python code: ```python\ndef solve(): pass\n```"
            ),
        },
        {"role": "user", "content": "Hello!"},
    ]
    features = extract_features(messages)
    tier, reason = pick_tier(features)

    assert tier == "small"
    assert features.history.weighted_word_count == 0.0
    assert "Conversational greeting, acknowledgment, or closure" in reason


def test_system_prompt_with_reasoning_does_not_bleed_into_acknowledgment() -> None:
    """System prompts with reasoning instructions do not cause acknowledgments to route to medium."""
    messages = [
        {
            "role": "system",
            "content": "Analyze step by step and explain why every decision was made.",
        },
        {"role": "user", "content": "Thanks a lot"},
    ]
    features = extract_features(messages)
    tier, reason = pick_tier(features)

    assert tier == "small"
    assert features.history.weighted_word_count == 0.0
    assert "Conversational greeting, acknowledgment, or closure" in reason


# =====================================================================
# 5. Multi-Topic Thread Drift
# =====================================================================


def test_multi_topic_thread_drift_transitions() -> None:
    """A conversation alternating between coding, casual chat, math, and bug fixes routes appropriately at each stage."""
    dialogue: list[dict[str, str]] = []

    # 1. Coding request -> medium
    dialogue.append({"role": "user", "content": "Help me implement Python code to ping an API endpoint"})
    assert pick_tier(extract_features(dialogue))[0] == "medium"
    dialogue.append({"role": "assistant", "content": "```python\nimport httpx\nr = httpx.get('url')\n```"})

    # 2. Casual banter -> small
    dialogue.append({"role": "user", "content": "Are you having a good day?"})
    assert pick_tier(extract_features(dialogue))[0] == "small"
    dialogue.append({"role": "assistant", "content": "I am having a great day, thank you!"})

    # 3. Math calculation -> medium
    dialogue.append({"role": "user", "content": "Calculate 15 * 12 + 40"})
    assert pick_tier(extract_features(dialogue))[0] == "medium"
    dialogue.append({"role": "assistant", "content": "The result of 15 * 12 + 40 is 220."})

    # 4. Casual acknowledgment -> small
    dialogue.append({"role": "user", "content": "Awesome, thank you!"})
    assert pick_tier(extract_features(dialogue))[0] == "small"
    dialogue.append({"role": "assistant", "content": "You are welcome!"})

    # 5. Code debugging -> medium
    dialogue.append({"role": "user", "content": "Fix line 3"})
    assert pick_tier(extract_features(dialogue))[0] == "medium"
    dialogue.append({"role": "assistant", "content": "Line 3 has been updated."})

    # 6. Farewell -> small
    dialogue.append({"role": "user", "content": "Bye!"})
    assert pick_tier(extract_features(dialogue))[0] == "small"


# =====================================================================
# 6. Elliptical Questions Across Different Contexts
# =====================================================================


def test_elliptical_why_after_code_history() -> None:
    """An isolated 'Why?' after code routes to medium."""
    messages = [
        {"role": "assistant", "content": "```python\ndef hash(key): return len(key) % 10\n```"},
        {"role": "user", "content": "Why?"},
    ]
    tier, _ = pick_tier(extract_features(messages))
    assert tier == "medium"


def test_elliptical_why_after_math_history() -> None:
    """An isolated 'Why?' after mathematical derivation routes to medium."""
    messages = [
        {"role": "assistant", "content": "Solving the equation: 3x = 9, so x = 3."},
        {"role": "user", "content": "Why?"},
    ]
    tier, _ = pick_tier(extract_features(messages))
    assert tier == "medium"


def test_elliptical_why_after_explanation_history() -> None:
    """An isolated 'Why?' after conceptual reasoning routes to medium."""
    messages = [
        {"role": "assistant", "content": "Relational databases use B-Trees for primary keys."},
        {"role": "user", "content": "Why?"},
    ]
    tier, _ = pick_tier(extract_features(messages))
    assert tier == "medium"
