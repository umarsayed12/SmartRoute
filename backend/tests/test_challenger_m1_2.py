"""Empirical test suite for Challenger M1.2.

Probing:
1. 10-turn dialogue drift: casual greeting -> coding task -> code output -> casual acknowledgment -> unrelated query -> technical follow-up.
2. Short technical queries: 'Fix line 3', 'What about space complexity?', 'Check edge case with null input'.
3. Malformed/atypical messages: empty messages, missing roles, uppercase roles, system messages.
"""

import pytest
from app.routing.features import extract_features
from app.routing.heuristic import pick_tier


# =====================================================================
# Area 1: 10-Turn Dialogue Drift & Context Retention
# =====================================================================

def build_10_turn_drift_conversation(follow_up_prompt: str) -> list[dict[str, str]]:
    """Build a standard 10-turn dialogue drift conversation ending in follow_up_prompt."""
    return [
        {"role": "user", "content": "Hello there! Good morning."},
        {"role": "assistant", "content": "Good morning! How can I help you today?"},
        {"role": "user", "content": "Can you write a Python function to sort a list using quicksort?"},
        {
            "role": "assistant",
            "content": (
                "```python\n"
                "def quicksort(arr):\n"
                "    if len(arr) <= 1:\n"
                "        return arr\n"
                "    pivot = arr[len(arr) // 2]\n"
                "    left = [x for x in arr if x < pivot]\n"
                "    middle = [x for x in arr if x == pivot]\n"
                "    right = [x for x in arr if x > pivot]\n"
                "    return quicksort(left) + middle + quicksort(right)\n"
                "```"
            ),
        },
        {"role": "user", "content": "Thanks, got it! That looks super clean."},
        {"role": "assistant", "content": "You're very welcome! Let me know if you need any adjustments or another algorithm."},
        {"role": "user", "content": "By the way, what is the capital of Australia?"},
        {"role": "assistant", "content": "The capital of Australia is Canberra."},
        {"role": "user", "content": follow_up_prompt},
    ]


class TestDialogueDrift:
    """Empirically test tier selection throughout the 10-turn dialogue drift lifecycle."""

    def test_turn1_greetings(self):
        """Test single-turn greetings with and without punctuation."""
        # Simple greeting 'Hello'
        f1 = extract_features([{"role": "user", "content": "Hello"}])
        assert pick_tier(f1)[0] == "small"
        assert f1.current_turn.is_pure_conversational is True

        # 'Hello there' is now recognized as pure conversational
        f_ht = extract_features([{"role": "user", "content": "Hello there"}])
        assert pick_tier(f_ht)[0] == "small"
        assert f_ht.current_turn.is_pure_conversational is True
        assert f_ht.current_turn.conversational_marker == "greeting"

        # Punctuated multi-phrase greeting cleanly parsed across inter-phrase '!'
        f2 = extract_features([{"role": "user", "content": "Hello there! Good morning."}])
        assert pick_tier(f2)[0] == "small"
        assert f2.current_turn.is_pure_conversational is True
        assert f2.current_turn.conversational_marker == "greeting"

    def test_turn3_coding_task(self):
        messages = [
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Good morning! How can I help you today?"},
            {"role": "user", "content": "Can you write a Python function to sort a list using quicksort?"},
        ]
        features = extract_features(messages)
        tier, reason = pick_tier(features)
        assert tier in ("medium", "large")
        assert features.current_turn.has_code is True

    def test_turn5_casual_acknowledgment_context_bleed(self):
        """Test whether casual acknowledgments with pronouns or punctuation bleed context."""
        code_history = [
            {"role": "user", "content": "Can you write a Python function to sort a list using quicksort?"},
            {
                "role": "assistant",
                "content": "```python\ndef quicksort(arr): return arr\n```",
            },
        ]

        # Case 1: Plain 'Thanks, got it.' -> routes to small via short circuit
        f_plain = extract_features(code_history + [{"role": "user", "content": "Thanks, got it."}])
        assert pick_tier(f_plain)[0] == "small"

        # Case 2: 'Thanks! Got it.' (with intermediate exclamation mark) short-circuits to small
        f_punc = extract_features(code_history + [{"role": "user", "content": "Thanks! Got it."}])
        tier_punc, reason_punc = pick_tier(f_punc)
        assert tier_punc == "small"
        assert "short-circuits to small tier" in reason_punc
        assert f_punc.current_turn.is_pure_conversational is True
        assert f_punc.current_turn.is_anaphoric is False

        # Case 3: 'Thanks, got it! That looks super clean.' conversational praise short-circuits to small
        f_praise = extract_features(code_history + [{"role": "user", "content": "Thanks, got it! That looks super clean."}])
        tier_praise, reason_praise = pick_tier(f_praise)
        assert tier_praise == "small"
        assert "short-circuits to small tier" in reason_praise
        assert f_praise.current_turn.is_pure_conversational is True
        assert f_praise.current_turn.is_anaphoric is False

    def test_turn7_unrelated_query(self):
        """Turn 7 must route to small and not bleed Turn 4 code."""
        messages = [
            {"role": "user", "content": "write code in python"},
            {"role": "assistant", "content": "```python\ndef f(): pass\n```"},
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "welcome"},
            {"role": "user", "content": "By the way, what is the capital of Australia?"},
        ]
        features = extract_features(messages)
        tier, reason = pick_tier(features)
        assert tier == "small"
        assert features.current_turn.has_code is False
        assert features.history.history_has_code is True
        assert features.history.prior_turn_has_code is False

    @pytest.mark.parametrize("follow_up", [
        "Fix line 3",
        "What about space complexity?",
        "Check edge case with null input",
        "Can you optimize that quicksort function?",
        "Optimize that",
    ])
    def test_turn9_technical_followup_after_drift_retains_context(self, follow_up: str):
        """Turn 9 technical follow-up correctly inherits medium tier from history_has_code."""
        messages = build_10_turn_drift_conversation(follow_up)
        features = extract_features(messages)
        tier, reason = pick_tier(features)

        assert tier == "medium"
        assert features.history.prior_turn_has_code is False
        assert features.history.history_has_code is True
        assert "Contextual follow-up referencing prior code" in reason


# =====================================================================
# Area 2: Short Technical Queries (Contextual vs. Standalone)
# =====================================================================

class TestShortTechnicalQueries:
    """Empirically test behavior of short technical queries in different contexts."""

    def test_immediate_followup_after_code(self):
        """When immediate prior turn has code, short technical queries route to medium."""
        queries = ["Fix line 3", "What about space complexity?", "Check edge case with null input"]
        for query in queries:
            messages = [
                {"role": "user", "content": "Write quicksort in python"},
                {"role": "assistant", "content": "```python\ndef quicksort(arr): return arr\n```"},
                {"role": "user", "content": query},
            ]
            features = extract_features(messages)
            tier, reason = pick_tier(features)
            assert tier == "medium"
            assert "Contextual follow-up referencing prior code" in reason

    def test_after_polite_acknowledgment_retains_context(self):
        """When user says 'Thanks' and assistant says 'You are welcome', technical queries retain medium tier."""
        queries = ["Fix line 3", "What about space complexity?", "Check edge case with null input", "Optimize that"]
        for query in queries:
            messages = [
                {"role": "user", "content": "Write quicksort in python"},
                {"role": "assistant", "content": "```python\ndef quicksort(arr): return arr\n```"},
                {"role": "user", "content": "Thanks!"},
                {"role": "assistant", "content": "You are welcome!"},
                {"role": "user", "content": query},
            ]
            features = extract_features(messages)
            tier, reason = pick_tier(features)
            assert tier == "medium"
            assert features.history.prior_turn_has_code is False
            assert features.history.history_has_code is True
            assert "Contextual follow-up referencing prior code" in reason

    def test_standalone_short_technical_queries_route_to_medium(self):
        """Standalone short technical queries (< 12 words) route to medium via Step 2."""
        queries = ["Fix line 3", "What about space complexity?", "Check edge case with null input"]
        for query in queries:
            messages = [{"role": "user", "content": query}]
            features = extract_features(messages)
            tier, reason = pick_tier(features)
            assert tier == "medium"
            assert features.current_turn.is_short_technical is True
            assert "Prompt contains concise technical query or instruction." in reason


# =====================================================================
# Area 3: Malformed & Atypical Messages
# =====================================================================

class TestMalformedAndAtypicalMessages:
    """Empirically test edge cases: empty messages, missing/atypical roles, case sensitivity."""

    def test_empty_messages_list(self):
        features = extract_features([])
        tier, reason = pick_tier(features)
        assert tier == "small"
        assert features.current_turn.word_count == 0.0
        assert features.history.turn_count == 0

    def test_empty_content_string(self):
        messages = [{"role": "user", "content": ""}]
        features = extract_features(messages)
        tier, reason = pick_tier(features)
        assert tier == "small"
        assert features.current_turn.word_count == 0.0

    def test_none_content(self):
        messages = [{"role": "user", "content": None}]
        features = extract_features(messages)
        tier, reason = pick_tier(features)
        assert tier == "small"
        assert features.current_turn.word_count == 0.0

    def test_whitespace_only_content(self):
        messages = [{"role": "user", "content": "   \n\t  "}]
        features = extract_features(messages)
        tier, reason = pick_tier(features)
        assert tier == "small"
        assert features.current_turn.word_count == 0.0

    def test_missing_role_key(self):
        messages = [{"content": "Can you write a python script for quicksort?"}]
        features = extract_features(messages)
        tier, reason = pick_tier(features)
        assert tier in ("medium", "large")
        assert features.current_turn.has_code is True

    def test_none_role(self):
        messages = [{"role": None, "content": "Can you write a python script for quicksort?"}]
        features = extract_features(messages)
        tier, reason = pick_tier(features)
        assert tier in ("medium", "large")
        assert features.current_turn.has_code is True

    def test_uppercase_and_mixedcase_roles(self):
        messages = [
            {"role": "SYSTEM", "content": "You are a helpful assistant."},
            {"role": "USER", "content": "Hello!"},
            {"role": "ASSISTANT", "content": "Hi there!"},
            {"role": "uSeR", "content": "Can you write a python script for quicksort?"},
        ]
        features = extract_features(messages)
        tier, reason = pick_tier(features)
        assert tier in ("medium", "large")
        assert features.current_turn.text == "Can you write a python script for quicksort?"
        assert features.history.turn_count == 3

    def test_role_with_whitespace_normalized(self):
        """Role ' user ' is stripped and correctly identified as the latest user turn."""
        messages = [
            {"role": " user ", "content": "Can you write a python script for quicksort?"},
            {"role": "assistant", "content": "Sure, here it is."},
        ]
        features = extract_features(messages)
        assert features.current_turn.text == "Can you write a python script for quicksort?"
        assert features.current_turn.has_code is True
        assert pick_tier(features)[0] in ("medium", "large")

    def test_system_message_only(self):
        messages = [{"role": "system", "content": "You are a helpful assistant."}]
        features = extract_features(messages)
        tier, reason = pick_tier(features)
        assert tier == "small"

    def test_system_message_with_code_as_prior_turn(self):
        """System prompt with code followed by user greeting."""
        messages = [
            {"role": "system", "content": "Always output code like: ```python\ndef hello(): pass\n```"},
            {"role": "user", "content": "Hello!"},
        ]
        features = extract_features(messages)
        tier, reason = pick_tier(features)
        assert tier == "small"
        assert features.current_turn.is_pure_conversational is True

    def test_pronoun_trap_why_vs_thanks(self):
        """Test 'Why did you write it like that?' vs 'Why?' vs 'Thanks!' after code."""
        code_history = [
            {"role": "user", "content": "Write quicksort in python"},
            {"role": "assistant", "content": "```python\ndef qs(a): return a\n```"},
        ]

        # Case 1: 'Thanks!' -> must be small
        m_thanks = code_history + [{"role": "user", "content": "Thanks!"}]
        f_thanks = extract_features(m_thanks)
        t_thanks, _ = pick_tier(f_thanks)
        assert t_thanks == "small"

        # Case 2: 'Why?' -> must be medium
        m_why = code_history + [{"role": "user", "content": "Why?"}]
        f_why = extract_features(m_why)
        t_why, _ = pick_tier(f_why)
        assert t_why == "medium"

        # Case 3: 'Why did you write it like that?' -> must be medium
        m_why_like_that = code_history + [{"role": "user", "content": "Why did you write it like that?"}]
        f_why_like_that = extract_features(m_why_like_that)
        t_why_like_that, _ = pick_tier(f_why_like_that)
        assert t_why_like_that == "medium"
