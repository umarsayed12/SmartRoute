"""Empirical adversarial test harness for Challenger M3.

Aggressively probes the Dual-Scope routing architecture against:
1. Pronoun Follow-up Trap ('Why did you write it like that?' vs 'Why?' vs 'Thanks!' vs 'That looks super clean')
2. Short Technical Queries ('What about space complexity?', 'Fix line 3', 'Check edge case with null input')
3. 10-Turn Multi-Topic Thread Drift (code -> acknowledgment -> trivia drift -> technical follow-up -> closure)
4. False Negative / False Positive Checks ('Hi' -> small, complex single-turn requests -> large)
5. Latency & Scale Benchmark across 5,000 requests (mean & P99 < 1.0ms SLA)
"""

import gc
import random
import time
import pytest
from app.routing.features import extract_features, extract_dual_scope_features
from app.routing.heuristic import pick_tier


# =====================================================================
# Fixtures & Shared Conversational Scenarios
# =====================================================================

@pytest.fixture
def python_quicksort_history() -> list[dict[str, str]]:
    """Standard 2-turn history containing code."""
    return [
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
    ]


@pytest.fixture
def ten_turn_drift_dialogue() -> list[dict[str, str]]:
    """Full 10-turn dialogue cycling through coding, gratitude, trivia drift, and technical work."""
    return [
        # Turn 1 (user): Greeting
        {"role": "user", "content": "Hello there! Good morning."},
        # Turn 2 (assistant): Greeting response
        {"role": "assistant", "content": "Good morning! How can I assist you with your project today?"},
        # Turn 3 (user): Code request
        {"role": "user", "content": "Can you write a Python function to sort a list using quicksort?"},
        # Turn 4 (assistant): Code response
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
        # Turn 5 (user): Gratitude / polite acknowledgment
        {"role": "user", "content": "Thanks, got it! That looks super clean."},
        # Turn 6 (assistant): Polite acknowledgment response
        {"role": "assistant", "content": "You are very welcome! Let me know if you need any adjustments or another algorithm."},
        # Turn 7 (user): Topic drift / trivia question
        {"role": "user", "content": "By the way, what is the capital of Australia?"},
        # Turn 8 (assistant): Trivia response
        {"role": "assistant", "content": "The capital of Australia is Canberra."},
        # Turn 9 (user): Technical follow-up referencing prior code
        {"role": "user", "content": "Fix line 3"},
        # Turn 10 (assistant): Code fix response
        {"role": "assistant", "content": "Here is the corrected line 3:\n```python\n    if len(arr) <= 1: return arr\n```"},
        # Turn 11 (user): Conversational closure
        {"role": "user", "content": "Goodbye, thanks for everything!"},
        # Turn 12 (assistant): Closure response
        {"role": "assistant", "content": "Goodbye! Have a great day ahead!"},
    ]


# =====================================================================
# R3.1: Pronoun Follow-up Trap
# =====================================================================

class TestPronounFollowUpTrap:
    """Stress-test pronoun traps, praising acknowledgments, and anaphoric follow-ups."""

    @pytest.mark.parametrize(
        "polite_phrase",
        [
            "Thanks!",
            "Thank you!",
            "That looks super clean",
            "That looks great!",
            "Thanks! Got it.",
            "Got it. Thanks!",
            "Thank you! Got it.",
            "Thanks, that works!",
            "That works perfectly!",
            "It looks good",
            "Looks good to me",
            "Cool, all good",
            "Sounds good, thanks",
        ],
    )
    def test_gratitude_and_praise_route_to_small_despite_code_history(
        self, python_quicksort_history: list[dict[str, str]], polite_phrase: str
    ) -> None:
        """Praise and acknowledgments containing pronouns must short-circuit to small tier."""
        messages = python_quicksort_history + [{"role": "user", "content": polite_phrase}]
        features = extract_features(messages)
        tier, reason = pick_tier(features)

        assert tier == "small", (
            f"Expected 'small' tier for polite acknowledgment '{polite_phrase}', "
            f"but got '{tier}' (reason: {reason})"
        )

    @pytest.mark.parametrize(
        "anaphoric_prompt,expected_min_tier",
        [
            ("Why did you write it like that?", "medium"),
            ("Why?", "medium"),
            ("How does it work?", "medium"),
            ("Can you optimize it for memory?", "medium"),
            ("Explain that recursive step", "medium"),
            ("Rewrite it using an in-place partition", "medium"),
            ("What if arr is already sorted?", "medium"),
        ],
    )
    def test_anaphoric_followups_route_to_medium_or_higher(
        self,
        python_quicksort_history: list[dict[str, str]],
        anaphoric_prompt: str,
        expected_min_tier: str,
    ) -> None:
        """Questions referencing prior code must escalate to medium or large."""
        messages = python_quicksort_history + [{"role": "user", "content": anaphoric_prompt}]
        features = extract_features(messages)
        tier, reason = pick_tier(features)

        assert tier in ("medium", "large"), (
            f"Expected medium/large tier for anaphoric follow-up '{anaphoric_prompt}', "
            f"but got '{tier}' (reason: {reason})"
        )


# =====================================================================
# R3.2: Short Technical Queries
# =====================================================================

class TestShortTechnicalQueries:
    """Stress-test short technical queries standalone and multi-turn."""

    @pytest.mark.parametrize(
        "query",
        [
            "What about space complexity?",
            "Fix line 3",
            "Check edge case with null input",
            "What about time complexity?",
            "Fix the bug on line 12",
            "Add unit tests",
            "Watch out for off by one error",
            "Fix null pointer exception",
        ],
    )
    def test_standalone_short_technical_queries_route_to_medium(self, query: str) -> None:
        """Standalone short technical queries on Turn 1 must route to medium tier."""
        messages = [{"role": "user", "content": query}]
        features = extract_features(messages)
        tier, reason = pick_tier(features)

        assert tier == "medium", (
            f"Expected 'medium' tier for standalone short technical query '{query}', "
            f"but got '{tier}' (reason: {reason})"
        )

    @pytest.mark.parametrize(
        "query",
        [
            "What about space complexity?",
            "Fix line 3",
            "Check edge case with null input",
            "What about time complexity?",
            "Fix the bug on line 12",
            "Add unit tests",
        ],
    )
    def test_multiturn_short_technical_queries_route_to_medium(
        self, python_quicksort_history: list[dict[str, str]], query: str
    ) -> None:
        """Multi-turn short technical queries following code must route to medium tier."""
        messages = python_quicksort_history + [{"role": "user", "content": query}]
        features = extract_features(messages)
        tier, reason = pick_tier(features)

        assert tier == "medium", (
            f"Expected 'medium' tier for multi-turn short technical query '{query}', "
            f"but got '{tier}' (reason: {reason})"
        )


# =====================================================================
# R3.3: 10-Turn Multi-Topic Thread Drift
# =====================================================================

class TestMultiTopicThreadDrift:
    """Stress-test a complete 10-turn dialogue alternating between coding, casual chat, and drift."""

    def test_drift_dialogue_lifecycle(
        self, ten_turn_drift_dialogue: list[dict[str, str]]
    ) -> None:
        """Verify routing decisions at each user turn across the 10-turn thread drift lifecycle."""
        # Turn 1: Greeting
        t1_msgs = ten_turn_drift_dialogue[:1]
        t1_tier, _ = pick_tier(extract_features(t1_msgs))
        assert t1_tier == "small", f"Turn 1 greeting routed to {t1_tier}, expected small"

        # Turn 3: Code generation request
        t3_msgs = ten_turn_drift_dialogue[:3]
        t3_tier, _ = pick_tier(extract_features(t3_msgs))
        assert t3_tier in ("medium", "large"), f"Turn 3 code generation routed to {t3_tier}, expected medium/large"

        # Turn 5: Gratitude / praise acknowledgment ("Thanks, got it! That looks super clean.")
        t5_msgs = ten_turn_drift_dialogue[:5]
        t5_tier, t5_reason = pick_tier(extract_features(t5_msgs))
        assert t5_tier == "small", f"Turn 5 acknowledgment routed to {t5_tier} ({t5_reason}), expected small"

        # Turn 7: Unrelated geography/trivia drift ("By the way, what is the capital of Australia?")
        t7_msgs = ten_turn_drift_dialogue[:7]
        t7_tier, t7_reason = pick_tier(extract_features(t7_msgs))
        assert t7_tier == "small", f"Turn 7 trivia drift routed to {t7_tier} ({t7_reason}), expected small"

        # Turn 9: Technical follow-up after drift ("Fix line 3")
        t9_msgs = ten_turn_drift_dialogue[:9]
        t9_tier, t9_reason = pick_tier(extract_features(t9_msgs))
        assert t9_tier == "medium", f"Turn 9 technical follow-up routed to {t9_tier} ({t9_reason}), expected medium"

        # Turn 11: Conversational closure ("Goodbye, thanks for everything!")
        t11_msgs = ten_turn_drift_dialogue[:11]
        t11_tier, t11_reason = pick_tier(extract_features(t11_msgs))
        assert t11_tier == "small", f"Turn 11 closure routed to {t11_tier} ({t11_reason}), expected small"

    @pytest.mark.parametrize(
        "drift_query",
        [
            "What about space complexity?",
            "Check edge case with null input",
            "Optimize that",
            "Can you refactor that quicksort?",
        ],
    )
    def test_technical_resumption_after_trivia_drift(
        self, ten_turn_drift_dialogue: list[dict[str, str]], drift_query: str
    ) -> None:
        """Technical queries returning after trivia drift must route to medium."""
        # Replace Turn 9 with the drift_query
        msgs = ten_turn_drift_dialogue[:8] + [{"role": "user", "content": drift_query}]
        tier, reason = pick_tier(extract_features(msgs))
        assert tier == "medium", (
            f"Resumed technical query '{drift_query}' routed to {tier} ({reason}), expected medium"
        )


# =====================================================================
# R3.4: False Positive / Negative Checks
# =====================================================================

class TestFalsePositiveNegativeChecks:
    """Ensure clean separation: simple greetings -> small, heavy requests -> large."""

    @pytest.mark.parametrize(
        "simple_greeting",
        [
            "Hi",
            "Hello",
            "Hey",
            "Good morning",
            "Howdy",
            "Greetings",
            "Yo",
        ],
    )
    def test_single_turn_pure_greetings_route_to_small(self, simple_greeting: str) -> None:
        """Single-turn greetings must route to small tier."""
        messages = [{"role": "user", "content": simple_greeting}]
        tier, reason = pick_tier(extract_features(messages))
        assert tier == "small", f"Single-turn greeting '{simple_greeting}' routed to {tier}"

    def test_single_turn_complex_kernel_routes_to_large(self) -> None:
        """A single-turn request for a 300-line kernel in C++ with templates and lock-free queues must route to large."""
        prompt = "Write a 300-line kernel in C++ with templates and lock-free queues"
        messages = [{"role": "user", "content": prompt}]
        tier, reason = pick_tier(extract_features(messages))
        assert tier == "large", (
            f"Complex kernel request routed to {tier} ({reason}), expected large tier"
        )

    def test_code_and_reasoning_over_200_words_routes_to_large(self) -> None:
        """A prompt combining code and reasoning over 200 words routes to large."""
        long_prompt = (
            "Please analyze the performance of this Python implementation in detail. "
            "Explain step by step why this algorithm exhibits quadratic worst-case behavior. "
            "Compare it with introsort and merge sort under adversarial input distributions. "
            "Here is the code to inspect: \n```python\n"
            "def partition(arr, low, high):\n"
            "    pivot = arr[high]\n"
            "    i = low - 1\n"
            "    for j in range(low, high):\n"
            "        if arr[j] <= pivot:\n"
            "            i = i + 1\n"
            "            arr[i], arr[j] = arr[j], arr[i]\n"
            "    arr[i + 1], arr[high] = arr[high], arr[i + 1]\n"
            "    return i + 1\n"
            "```\n"
            + ("Explain the cache locality implications and branch prediction failure modes. " * 16)
        )
        assert len(long_prompt.split()) > 200
        messages = [{"role": "user", "content": long_prompt}]
        tier, reason = pick_tier(extract_features(messages))
        assert tier == "large", f"Code + reasoning > 200 words routed to {tier}, expected large"


# =====================================================================
# R3.5: 5,000-Request Latency & Scale Microbenchmark
# =====================================================================

class TestLatencyAndScaleBenchmark:
    """Benchmark 5,000 requests across diverse real-world workloads."""

    def test_5000_requests_scale_benchmark(self) -> None:
        """Benchmark 5,000 requests across realistic workloads, asserting mean and P99 latency < 1.0 ms."""
        workloads = [
            # 1. Single turn greetings
            [{"role": "user", "content": "Hello"}],
            [{"role": "user", "content": "Good morning! How are you?"}],
            # 2. Single turn technical / code
            [{"role": "user", "content": "Write a Python script to parse JSON and insert records into Postgres."}],
            [{"role": "user", "content": "What is the time complexity of Dijkstra with a Fibonacci heap?"}],
            # 3. Two turn acknowledgments after code
            [
                {"role": "user", "content": "Write quicksort in Python."},
                {"role": "assistant", "content": "```python\ndef quicksort(arr): ...\n```"},
                {"role": "user", "content": "Thanks, that works perfectly!"},
            ],
            # 4. Short technical queries
            [{"role": "user", "content": "Fix line 3"}],
            [{"role": "user", "content": "What about space complexity?"}],
            # 5. Multi-turn technical follow-up
            [
                {"role": "user", "content": "Write quicksort in Python."},
                {"role": "assistant", "content": "```python\ndef quicksort(arr): ...\n```"},
                {"role": "user", "content": "Why did you write it like that?"},
            ],
            # 6. 10-turn drift conversation
            [
                {"role": "user", "content": "Hello there!"},
                {"role": "assistant", "content": "Hello! How can I help?"},
                {"role": "user", "content": "Write a binary search tree in C++."},
                {"role": "assistant", "content": "```cpp\nclass BST { ... };\n```"},
                {"role": "user", "content": "Thanks! Got it."},
                {"role": "assistant", "content": "You are welcome!"},
                {"role": "user", "content": "What is the capital of France?"},
                {"role": "assistant", "content": "Paris."},
                {"role": "user", "content": "What about space complexity?"},
            ],
        ]

        total_requests = 5000
        rng = random.Random(42)
        sampled_requests = [rng.choice(workloads) for _ in range(total_requests)]

        # Warmup
        for w in workloads:
            for _ in range(20):
                pick_tier(extract_features(w))

        latencies_ms: list[float] = []
        for req in sampled_requests:
            t0 = time.perf_counter()
            _tier, _reason = pick_tier(extract_features(req))
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1000.0)

        sorted_latencies = sorted(latencies_ms)
        mean_ms = sum(sorted_latencies) / total_requests
        p50_ms = sorted_latencies[int(0.50 * total_requests)]
        p90_ms = sorted_latencies[int(0.90 * total_requests)]
        p99_ms = sorted_latencies[int(0.99 * total_requests)]
        max_ms = sorted_latencies[-1]

        print(f"\n--- 5,000 Request Benchmark Results ---")
        print(f"Total Requests: {total_requests}")
        print(f"Mean Latency:   {mean_ms:.4f} ms (SLA < 1.0 ms)")
        print(f"P50 Latency:    {p50_ms:.4f} ms")
        print(f"P90 Latency:    {p90_ms:.4f} ms")
        print(f"P99 Latency:    {p99_ms:.4f} ms (SLA < 1.0 ms)")
        print(f"Max Latency:    {max_ms:.4f} ms")

        assert mean_ms < 1.0, f"Mean latency {mean_ms:.4f} ms exceeded 1.0 ms SLA"
        assert p99_ms < 1.0, f"P99 latency {p99_ms:.4f} ms exceeded 1.0 ms SLA"
