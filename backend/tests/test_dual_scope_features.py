"""Tier 1: Comprehensive unit tests for Dual-Scope feature extraction.

Verifies:
1. CurrentTurnScope pure conversational markers (greetings, acknowledgments, closures).
2. Praise expressions with demonstrative pronouns and anaphora disarming.
3. CurrentTurnScope technical cues (code, math, reasoning, long output, question count).
4. Anaphora and elliptical cue detection ("Why did you write it like that?", "Why?", "Optimize that").
5. Short technical directives ("Fix line 3", "What about space complexity?").
6. HistoryScope role weighting (user 1.0, assistant 0.2, system 0.0) and recency decay (lambda=0.6).
7. Immediate prior turn (T-1) indicators vs cumulative history flags.
8. FeatureDict backward compatibility invariants (FEATURE_ORDER, dict inheritance, json.dumps).
9. Edge cases: empty messages, missing roles, whitespace, assistant-only conversations.
"""

import json
import pytest

from app.routing.features import (
    FEATURE_ORDER,
    RECENCY_DECAY_LAMBDA,
    ROLE_WEIGHTS,
    CurrentTurnScope,
    FeatureDict,
    HistoryScope,
    extract_dual_scope_features,
    extract_features,
)


# =====================================================================
# 1. CurrentTurnScope: Pure Conversational Markers
# =====================================================================


@pytest.mark.parametrize(
    "greeting",
    [
        "hi",
        "hello",
        "hey",
        "howdy",
        "greetings",
        "good morning",
        "good afternoon",
        "good evening",
        "hi there",
        "hey there",
        "hello there",
        "hiya",
        "yo",
        "Hello!",
        "Hey there...",
        "Good morning.",
    ],
)
def test_pure_conversational_greetings(greeting: str) -> None:
    """Unambiguous greetings are classified as pure conversational with marker 'greeting'."""
    features = extract_features([{"role": "user", "content": greeting}])
    curr = features.current_turn

    assert curr.is_pure_conversational is True
    assert curr.conversational_marker == "greeting"
    assert curr.is_anaphoric is False
    assert curr.has_code is False
    assert curr.has_math is False


@pytest.mark.parametrize(
    "ack",
    [
        "thanks",
        "thank you",
        "thx",
        "ok",
        "okay",
        "k",
        "got it",
        "understood",
        "cool",
        "great",
        "awesome",
        "perfect",
        "nice",
        "sure",
        "right",
        "all good",
        "much appreciated",
        "no problem",
        "thanks a lot",
        "thank you so much",
        "thank you very much",
    ],
)
def test_pure_conversational_acknowledgments(ack: str) -> None:
    """Unambiguous acknowledgments are classified as pure conversational with marker 'acknowledgment'."""
    features = extract_features([{"role": "user", "content": ack}])
    curr = features.current_turn

    assert curr.is_pure_conversational is True
    assert curr.conversational_marker == "acknowledgment"
    assert curr.is_anaphoric is False
    assert curr.has_code is False
    assert curr.has_math is False


@pytest.mark.parametrize(
    "closure",
    [
        "bye",
        "goodbye",
        "cya",
        "see you later",
        "farewell",
        "have a good one",
        "exit",
        "quit",
        "Bye!",
        "Goodbye.",
    ],
)
def test_pure_conversational_closures(closure: str) -> None:
    """Conversational closures are classified as pure conversational with marker 'closure'."""
    features = extract_features([{"role": "user", "content": closure}])
    curr = features.current_turn

    assert curr.is_pure_conversational is True
    assert curr.conversational_marker == "closure"
    assert curr.is_anaphoric is False


@pytest.mark.parametrize(
    "praise",
    [
        "That looks super clean",
        "It looks great",
        "This is awesome",
        "That's wonderful",
        "Looks clean",
        "That works for me",
        "That works great",
        "Works perfectly",
        "It helped a lot",
        "That solved it",
        "That's really slick",
        "That's super cool",
        "sounds good",
    ],
)
def test_praise_expressions_disarm_anaphora(praise: str) -> None:
    """Conversational praise containing demonstrative pronouns ('that', 'it') disarms anaphora."""
    features = extract_features([{"role": "user", "content": praise}])
    curr = features.current_turn

    assert curr.is_pure_conversational is True
    assert curr.conversational_marker == "praise"
    # Demonstrative pronouns in praise must NOT trigger anaphora
    assert curr.is_anaphoric is False


@pytest.mark.parametrize(
    "combo",
    [
        "Thanks, got it!",
        "Hey there! Thank you so much.",
        "Understood, goodbye!",
        "Cool, sounds good. Thanks!",
    ],
)
def test_multi_phrase_conversational_combinations(combo: str) -> None:
    """Compound conversational phrases remain pure conversational."""
    features = extract_features([{"role": "user", "content": combo}])
    curr = features.current_turn

    assert curr.is_pure_conversational is True
    assert curr.is_anaphoric is False


@pytest.mark.parametrize(
    ("prompt", "detected_cue"),
    [
        ("Hello, please write a python script to parse json", "has_code"),
        ("Hi! What is 2 + 2?", "has_math"),
        ("Got it, explain why this approach works", "asks_reasoning"),
        ("Hey, write a detailed essay about space exploration", "asks_long_output"),
    ],
)
def test_conversational_greeting_with_technical_cue_is_not_pure(
    prompt: str, detected_cue: str
) -> None:
    """Prompts mixing greetings with technical instructions are not pure conversational."""
    features = extract_features([{"role": "user", "content": prompt}])
    curr = features.current_turn

    assert curr.is_pure_conversational is False
    assert getattr(curr, detected_cue) is True


# =====================================================================
# 2. CurrentTurnScope: Technical Cues & Extraction
# =====================================================================


def test_code_generation_cues_in_current_turn() -> None:
    """Detect various code generation cues exclusively in current turn."""
    prompts = [
        "def bubble_sort(arr):",
        "const count = 0",
        "```typescript\ninterface User { id: string; }\n```",
        "Help me debug this SQL query: SELECT * FROM users",
    ]
    for prompt in prompts:
        features = extract_features([{"role": "user", "content": prompt}])
        assert features.current_turn.has_code is True
        assert features.current_turn.is_pure_conversational is False


def test_mathematical_cues_in_current_turn() -> None:
    """Detect math formulas and calculation keywords in current turn."""
    prompts = [
        "Calculate the derivative of f(x) = 3x^2 + 5x",
        "Solve the linear equation 2x + 7 = 19",
        "What is 15 * 3?",
        "Compute \u221a16 + \u222b x dx",
    ]
    for prompt in prompts:
        features = extract_features([{"role": "user", "content": prompt}])
        assert features.current_turn.has_math is True
        assert features.current_turn.is_pure_conversational is False


def test_reasoning_and_long_output_cues_in_current_turn() -> None:
    """Detect reasoning keywords and long-output requests in current turn."""
    reasoning_features = extract_features([
        {"role": "user", "content": "Explain why quicksort has O(n log n) average complexity"}
    ])
    assert reasoning_features.current_turn.asks_reasoning is True

    long_output_features = extract_features([
        {"role": "user", "content": "Write a comprehensive essay comparing SQL and NoSQL"}
    ])
    assert long_output_features.current_turn.asks_long_output is True


def test_question_count_and_metrics_in_current_turn() -> None:
    """Current turn metrics accurately measure words, chars, and question count."""
    text = "Why did this fail? Can we optimize it? What if we change the algorithm?"
    features = extract_features([{"role": "user", "content": text}])
    curr = features.current_turn

    assert curr.text == text
    assert curr.word_count == float(len(text.split()))
    assert curr.char_count == float(len(text))
    assert curr.question_count == 3.0


# =====================================================================
# 3. CurrentTurnScope: Anaphora & Coreference Detection
# =====================================================================


@pytest.mark.parametrize(
    "anaphoric_prompt",
    [
        "Why did you write it like that?",
        "How does it work?",
        "Could you optimize that?",
        "Refactor this function",
        "Can you simplify it for me?",
        "What about the previous approach?",
        "Speed up the earlier version",
        "Why is that needed?",
        "Explain the former method",
    ],
)
def test_explicit_anaphoric_pronoun_detection(anaphoric_prompt: str) -> None:
    """Detect explicit anaphoric references pointing to previous conversation entities."""
    features = extract_features([{"role": "user", "content": anaphoric_prompt}])
    assert features.current_turn.is_anaphoric is True


@pytest.mark.parametrize(
    "elliptical_prompt",
    [
        "Why?",
        "How?",
        "What for?",
        "How come?",
        "Why?!",
        "How...",
    ],
)
def test_elliptical_question_detection(elliptical_prompt: str) -> None:
    """Detect isolated elliptical follow-up questions as anaphoric cues."""
    features = extract_features([{"role": "user", "content": elliptical_prompt}])
    assert features.current_turn.is_anaphoric is True


def test_contrast_anaphora_vs_praise() -> None:
    """Verify that identical pronouns trigger anaphora in queries but not in praise."""
    # Anaphoric query with 'that'
    f_query = extract_features([{"role": "user", "content": "Why did you write that?"}])
    assert f_query.current_turn.is_anaphoric is True
    assert f_query.current_turn.is_pure_conversational is False

    # Praise with 'that'
    f_praise = extract_features([{"role": "user", "content": "That looks super clean"}])
    assert f_praise.current_turn.is_anaphoric is False
    assert f_praise.current_turn.is_pure_conversational is True


# =====================================================================
# 4. CurrentTurnScope: Short Technical Directives
# =====================================================================


@pytest.mark.parametrize(
    "tech_directive",
    [
        "Fix line 3",
        "What about space complexity?",
        "Check time complexity",
        "What is the Big O notation?",
        "Please add unit tests",
        "Watch out for memory leak",
        "Handle the null pointer exception",
        "Catch the runtime error",
        "Fix the bug in this function",
        "Debug the issue",
    ],
)
def test_short_technical_directives(tech_directive: str) -> None:
    """Short technical instructions and complexity queries trigger is_short_technical."""
    features = extract_features([{"role": "user", "content": tech_directive}])
    assert features.current_turn.is_short_technical is True


def test_non_technical_plain_query_is_not_short_technical() -> None:
    """Generic non-technical short queries do not trigger is_short_technical."""
    prompts = [
        "What is the capital of France?",
        "How old is the earth?",
        "Tell me a short joke",
    ]
    for prompt in prompts:
        features = extract_features([{"role": "user", "content": prompt}])
        assert features.current_turn.is_short_technical is False


# =====================================================================
# 5. HistoryScope: Role Weighting & Recency Decay
# =====================================================================


def test_history_role_weights() -> None:
    """Assistant turns are weighted at 0.2, user at 1.0, and system at 0.0."""
    assert ROLE_WEIGHTS["assistant"] == 0.2
    assert ROLE_WEIGHTS["user"] == 1.0
    assert ROLE_WEIGHTS["system"] == 0.0
    assert RECENCY_DECAY_LAMBDA == 0.6

    # Test single assistant history message
    hist_assistant = [
        {"role": "assistant", "content": "one two three four five six seven eight nine ten"},
        {"role": "user", "content": "Hi"},
    ]
    f_asst = extract_features(hist_assistant)
    # 10 words * 0.2 weight * (0.6 ** 0) = 2.0
    assert f_asst.history.turn_count == 1
    assert f_asst.history.weighted_word_count == 2.0

    # Test single user history message
    hist_user = [
        {"role": "user", "content": "one two three four five six seven eight nine ten"},
        {"role": "assistant", "content": "acknowledged"},
        {"role": "user", "content": "Hi"},
    ]
    # Here hist_msgs = [user(10 words), assistant(1 word)]
    # i=0 (user): d = 2 - 1 - 0 = 1 -> 10 * 1.0 * 0.6 = 6.0
    # i=1 (asst): d = 2 - 1 - 1 = 0 -> 1 * 0.2 * 1.0 = 0.2
    # total = 6.2
    f_user = extract_features(hist_user)
    assert f_user.history.turn_count == 2
    assert f_user.history.weighted_word_count == 6.2

    # Test system message weighting (0.0)
    hist_system = [
        {"role": "system", "content": " ".join(["system_prompt"] * 100)},
        {"role": "user", "content": "Hello"},
    ]
    f_sys = extract_features(hist_system)
    assert f_sys.history.turn_count == 1
    assert f_sys.history.weighted_word_count == 0.0


def test_history_recency_decay_calculation() -> None:
    """Exponential decay (lambda=0.6) discounts older history turns."""
    # 3 assistant turns prior to user turn:
    # Turn 0: 10 words, d=2 -> 10 * 0.2 * 0.36 = 0.72
    # Turn 1: 10 words, d=1 -> 10 * 0.2 * 0.6 = 1.20
    # Turn 2: 10 words, d=0 -> 10 * 0.2 * 1.0 = 2.00
    # Total = 3.92
    words_10 = "word " * 10
    messages = [
        {"role": "assistant", "content": words_10},
        {"role": "assistant", "content": words_10},
        {"role": "assistant", "content": words_10},
        {"role": "user", "content": "Current turn"},
    ]
    features = extract_features(messages)
    assert features.history.turn_count == 3
    assert features.history.weighted_word_count == pytest.approx(3.92, rel=1e-3)


# =====================================================================
# 6. HistoryScope: Immediate Prior Turn (T-1) vs Cumulative Indicators
# =====================================================================


def test_immediate_prior_turn_indicators() -> None:
    """Distinguish immediate prior turn (T-1) code/math/reasoning from older turns."""
    # Case A: T-1 has code
    messages_a = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Here is code:\n```python\nprint(1)\n```"},
        {"role": "user", "content": "What about space complexity?"},
    ]
    f_a = extract_features(messages_a)
    assert f_a.history.prior_turn_has_code is True
    assert f_a.history.history_has_code is True

    # Case B: T-2 has code, but T-1 is casual acknowledgment
    messages_b = [
        {"role": "assistant", "content": "```python\ndef foo(): pass\n```"},
        {"role": "assistant", "content": "Hope this explanation helps you!"},
        {"role": "user", "content": "What about space complexity?"},
    ]
    f_b = extract_features(messages_b)
    # T-1 does not have code
    assert f_b.history.prior_turn_has_code is False
    # Cumulative history does have code
    assert f_b.history.history_has_code is True


def test_prior_turn_math_and_reasoning_indicators() -> None:
    """Prior turn math and reasoning indicators are accurately extracted."""
    # Prior turn has math
    messages_math = [
        {"role": "assistant", "content": "We solve the equation: 2x + 5 = 15 so x = 5"},
        {"role": "user", "content": "Why?"},
    ]
    f_math = extract_features(messages_math)
    assert f_math.history.prior_turn_has_math is True
    assert f_math.history.prior_turn_has_code is False

    # Prior turn has reasoning
    messages_reasoning = [
        {"role": "assistant", "content": "Let me explain step by step why this design pattern is chosen."},
        {"role": "user", "content": "Can you elaborate on that?"},
    ]
    f_reasoning = extract_features(messages_reasoning)
    assert f_reasoning.history.prior_turn_asks_reasoning is True
    assert f_reasoning.history.history_asks_reasoning is True


# =====================================================================
# 7. FeatureDict: Backward Compatibility & Invariants
# =====================================================================


def test_feature_dict_invariants() -> None:
    """FeatureDict satisfies dict inheritance, exact FEATURE_ORDER keys, and JSON serialization."""
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "Please write quicksort in Python"},
    ]
    features = extract_features(messages)

    # 1. Inherits from dict
    assert isinstance(features, dict)
    assert isinstance(features, FeatureDict)

    # 2. Preserves exact 10 legacy keys in FEATURE_ORDER
    assert list(features.keys()) == FEATURE_ORDER
    assert len(features) == 10

    # 3. All values are float
    assert all(isinstance(val, float) for val in features.values())

    # 4. Scopes attached
    assert isinstance(features.current_turn, CurrentTurnScope)
    assert isinstance(features.history, HistoryScope)

    # 5. Copy preserves scopes
    copied = features.copy()
    assert isinstance(copied, FeatureDict)
    assert copied.current_turn.text == features.current_turn.text
    assert copied.history.turn_count == features.history.turn_count

    # 6. JSON serialization dumps only legacy numeric keys (crucial for DB storage & learned router)
    serialized = json.dumps(features)
    deserialized = json.loads(serialized)
    assert list(deserialized.keys()) == FEATURE_ORDER
    assert deserialized["has_code"] == 1.0


def test_extract_dual_scope_features_alias() -> None:
    """extract_dual_scope_features is identical to extract_features."""
    messages = [{"role": "user", "content": "Hello"}]
    f1 = extract_features(messages)
    f2 = extract_dual_scope_features(messages)

    assert f1 == f2
    assert f1.current_turn.text == f2.current_turn.text
    assert f1.history.turn_count == f2.history.turn_count


# =====================================================================
# 8. Boundary & Malformed Inputs Edge Cases
# =====================================================================


def test_empty_messages_conversation() -> None:
    """Empty conversation returns zeroed legacy vector and clean zeroed scopes."""
    features = extract_features([])

    assert list(features) == FEATURE_ORDER
    assert all(v == 0.0 for v in features.values())
    assert features.current_turn.text == ""
    assert features.current_turn.word_count == 0.0
    assert features.current_turn.is_pure_conversational is False
    assert features.history.turn_count == 0
    assert features.history.weighted_word_count == 0.0


def test_assistant_only_messages() -> None:
    """When no user role exists, fallback to latest message for current turn."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "assistant", "content": "Hello, how can I assist you today?"},
    ]
    features = extract_features(messages)

    assert features.current_turn.text == "Hello, how can I assist you today?"
    assert features.history.turn_count == 1
    # System role has weight 0.0
    assert features.history.weighted_word_count == 0.0


def test_whitespace_and_empty_content_messages() -> None:
    """Whitespace-only and empty content messages do not crash or produce NaN."""
    messages = [
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "   \n\t  "},
        {"role": "user", "content": "   "},
    ]
    features = extract_features(messages)

    assert features.current_turn.word_count == 0.0
    assert features.current_turn.char_count == 3.0
    assert features.current_turn.is_pure_conversational is False
    assert features.history.turn_count == 2
