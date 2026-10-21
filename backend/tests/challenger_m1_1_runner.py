"""Challenger M1.1: Empirical Verification & Stress Test Harness.

Probes multi-turn edge cases:
1. Pronoun traps ('Why did you write it like that?', 'Why?', 'Optimize that', 'Explain how that hash map works').
2. Pure conversational anti-bleed ('Hi', 'Hello', 'Thanks', 'Understood', 'Okay, got it, thank you!', 'Bye', etc.).
3. Single-turn baseline and boundary queries ('Hi' -> small, 'Write a 300-line kernel' -> large).
4. 5,000-iteration sub-millisecond latency microbenchmark.
"""

import os
import sys
import time
import statistics

# Ensure backend root is on sys.path
backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.routing.features import FEATURE_ORDER, extract_dual_scope_features, extract_features
from app.routing.heuristic import pick_tier


def main() -> int:
    backtick3 = chr(96) * 3
    results = {"passed": 0, "failed": 0, "details": []}

    def record(name: str, passed: bool, msg: str = "") -> None:
        if passed:
            results["passed"] += 1
            results["details"].append((name, "PASS", msg))
            print(f"  [PASS] {name} -> {msg}")
        else:
            results["failed"] += 1
            results["details"].append((name, "FAIL", msg))
            print(f"  [FAIL] {name} -> {msg}")

    print("=" * 70)
    print("CHALLENGER M1.1 EMPIRICAL VERIFICATION HARNESS")
    print("=" * 70)

    # ---------------------------------------------------------
    # SUITE 1: PRONOUN TRAPS WITH CODE HISTORY
    # ---------------------------------------------------------
    print("\n[Suite 1] Probing Pronoun Traps (with Prior Code Turn)...")
    code_history = [
        {"role": "user", "content": "Write a quicksort in Python."},
        {
            "role": "assistant",
            "content": (
                backtick3
                + "python\ndef quicksort(arr):\n    if len(arr) <= 1: return arr\n"
                + "    pivot = arr[0]\n"
                + "    return quicksort([x for x in arr[1:] if x < pivot]) + [pivot] + quicksort([x for x in arr[1:] if x >= pivot])\n"
                + backtick3
            ),
        },
    ]

    pronoun_cases = [
        ("Why did you write it like that?", ("medium", "large")),
        ("Why?", ("medium", "large")),
        ("Optimize that", ("medium", "large")),
        ("Explain how that hash map works", ("medium", "large")),
        ("How does it work?", ("medium", "large")),
        ("Can you refactor that?", ("medium", "large")),
        ("Speed this up", ("medium", "large")),
        ("Simplify it", ("medium", "large")),
        ("What if we change that?", ("medium", "large")),
        ("Can you rewrite it in C++?", ("medium", "large")),
    ]

    for q, expected_tiers in pronoun_cases:
        msgs = code_history + [{"role": "user", "content": q}]
        f = extract_dual_scope_features(msgs)
        tier, reason = pick_tier(f)
        ok = tier in expected_tiers
        record(f"Pronoun Trap: {q!r}", ok, f"tier={tier}, is_anaphoric={f.current_turn.is_anaphoric}, reason={reason}")

    # ---------------------------------------------------------
    # SUITE 2: NEGATIVE CONTROLS FOR PRONOUNS
    # ---------------------------------------------------------
    print("\n[Suite 2] Probing Negative Controls (Pronouns without Technical Context)...")
    casual_history = [
        {"role": "user", "content": "Good morning! The weather is sunny."},
        {"role": "assistant", "content": "Good morning! Yes, it is a bright sunny day today."},
    ]
    # 'Optimize that' with no code in history should NOT inherit medium tier
    msgs = casual_history + [{"role": "user", "content": "Optimize that"}]
    f = extract_dual_scope_features(msgs)
    tier, reason = pick_tier(f)
    record(
        "Negative Control: 'Optimize that' without code history",
        tier == "small",
        f"tier={tier}, reason={reason}",
    )

    # ---------------------------------------------------------
    # SUITE 3: PURE CONVERSATIONAL ANTI-BLEED WITH HEAVY CODE
    # ---------------------------------------------------------
    print("\n[Suite 3] Probing Pure Conversational Anti-Bleed (Heavy Code in History)...")
    heavy_code_history = [
        {"role": "user", "content": "Write a 1000-line CUDA raytracer kernel."},
        {
            "role": "assistant",
            "content": (
                backtick3
                + "cuda\n__global__ void raytrace() { int i = threadIdx.x; }\n"
                + backtick3
                + "\n"
                + ("code " * 500)
            ),
        },
    ]

    pure_conv_cases = [
        "Hi",
        "Hello",
        "Thanks",
        "Understood",
        "Okay, got it, thank you!",
        "Bye",
        "Hey",
        "Howdy",
        "Greetings",
        "Good morning",
        "Good afternoon",
        "Good evening",
        "Hi there",
        "Hey there",
        "Hiya",
        "Yo",
        "Thanks a lot",
        "Thank you so much",
        "Thank you very much!",
        "Thx",
        "Ok",
        "Okay",
        "K",
        "Got it",
        "Cool",
        "Great",
        "Awesome",
        "Perfect",
        "Nice",
        "Sure",
        "Right",
        "All good",
        "Sounds good",
        "Much appreciated",
        "No problem",
        "Goodbye",
        "Cya",
        "See you",
        "See you later",
        "Farewell",
        "Have a good day",
        "Have a good one",
        "Exit",
        "Quit",
        # Extra casing and whitespace variants
        "  HELLO  ",
        "HI!",
        "Thanks!!",
        "Understood...",
        "Bye!",
    ]

    for q in pure_conv_cases:
        msgs = heavy_code_history + [{"role": "user", "content": q}]
        f = extract_dual_scope_features(msgs)
        tier, reason = pick_tier(f)
        ok = tier == "small"
        record(f"Pure Conv Anti-Bleed: {q!r}", ok, f"tier={tier}, is_pure_conv={f.current_turn.is_pure_conversational}")

    # ---------------------------------------------------------
    # SUITE 4: SINGLE TURN PROMPTS & BOUNDARIES
    # ---------------------------------------------------------
    print("\n[Suite 4] Probing Single Turn Baselines & Boundaries...")
    single_turn_cases = [
        ("Hi", "small"),
        ("Write a 300-line kernel", "large"),
        ("Hello", "small"),
        ("What is the weather in Tokyo?", "small"),
        ("def calculate_sum(a, b): return a + b", "medium"),
        ("What is 45 * 192?", "medium"),
        ("Explain how backpropagation works", "medium"),
        ("Write a comprehensive documentation for this API", "large"),
        ("Generate a detailed report", "large"),
        ("A short query with few words", "small"),
    ]

    for q, expected in single_turn_cases:
        msgs = [{"role": "user", "content": q}]
        f = extract_dual_scope_features(msgs)
        tier, reason = pick_tier(f)
        ok = tier == expected
        record(f"Single Turn: {q!r}", ok, f"tier={tier}, expected={expected}, reason={reason}")

    # Boundary tests
    for count, exp_tier in [(11, "small"), (12, "small"), (120, "small"), (121, "medium")]:
        prompt = " ".join(["context"] * count)
        f = extract_dual_scope_features([{"role": "user", "content": prompt}])
        tier, _ = pick_tier(f)
        record(f"Word Count Boundary ({count} words)", tier == exp_tier, f"tier={tier}, expected={exp_tier}")

    for count, exp_tier in [(200, "medium"), (201, "large")]:
        prompt = "Explain code " + " ".join(["context"] * (count - 2))
        f = extract_dual_scope_features([{"role": "user", "content": prompt}])
        tier, _ = pick_tier(f)
        record(f"Code+Reasoning Boundary ({count} words)", tier == exp_tier, f"tier={tier}, expected={exp_tier}")

    # ---------------------------------------------------------
    # SUITE 5: BACKWARD COMPATIBILITY
    # ---------------------------------------------------------
    print("\n[Suite 5] Probing Backward Compatibility...")
    plain_f = extract_features([{"role": "user", "content": "Explain this code"}])
    record("FeatureDict keys match FEATURE_ORDER", list(plain_f) == FEATURE_ORDER, f"keys={list(plain_f)}")
    record("FeatureDict hasattr current_turn", hasattr(plain_f, "current_turn"), "current_turn attached")
    record("FeatureDict hasattr history", hasattr(plain_f, "history"), "history attached")
    legacy_tier, _ = pick_tier(dict(plain_f))
    record("Legacy dict input fallback", legacy_tier == "medium", f"tier={legacy_tier}")

    # ---------------------------------------------------------
    # SUITE 6: LATENCY BENCHMARK (5,000 ITERATIONS)
    # ---------------------------------------------------------
    print("\n[Suite 6] Executing 5,000-Iteration Latency Benchmark...")
    benchmark_prompts = [
        heavy_code_history + [{"role": "user", "content": "Why did you write it like that?"}],
        heavy_code_history + [{"role": "user", "content": "Why?"}],
        heavy_code_history + [{"role": "user", "content": "Optimize that"}],
        heavy_code_history + [{"role": "user", "content": "Explain how that hash map works"}],
        heavy_code_history + [{"role": "user", "content": "Okay, got it, thank you!"}],
        [{"role": "user", "content": "Hi"}],
        [{"role": "user", "content": "Write a 300-line kernel"}],
    ]

    # Warm-up (100 iterations)
    for i in range(100):
        pick_tier(extract_dual_scope_features(benchmark_prompts[i % len(benchmark_prompts)]))

    latencies_ms = []
    iterations = 5000
    t_start = time.perf_counter()
    for i in range(iterations):
        msgs = benchmark_prompts[i % len(benchmark_prompts)]
        t0 = time.perf_counter()
        f = extract_dual_scope_features(msgs)
        tier, _ = pick_tier(f)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)
    total_benchmark_time = time.perf_counter() - t_start

    lat_avg = statistics.mean(latencies_ms)
    lat_median = statistics.median(latencies_ms)
    lat_p90 = statistics.quantiles(latencies_ms, n=10)[8]
    lat_p95 = statistics.quantiles(latencies_ms, n=20)[18]
    lat_p99 = statistics.quantiles(latencies_ms, n=100)[98]
    lat_min = min(latencies_ms)
    lat_max = max(latencies_ms)

    sla_passed = lat_avg < 1.0 and lat_p99 < 1.0
    record(
        f"Latency SLA (<1.0ms across {iterations} iterations)",
        sla_passed,
        f"avg={lat_avg:.4f}ms, p50={lat_median:.4f}ms, p95={lat_p95:.4f}ms, p99={lat_p99:.4f}ms, max={lat_max:.4f}ms",
    )

    print("\n" + "=" * 70)
    print("EMPIRICAL BENCHMARK METRICS SUMMARY")
    print("=" * 70)
    print(f"Total Iterations:        {iterations:,}")
    print(f"Total Execution Time:    {total_benchmark_time:.4f} s")
    print(f"Average Latency:         {lat_avg:.4f} ms")
    print(f"Median Latency (P50):    {lat_median:.4f} ms")
    print(f"90th Percentile (P90):   {lat_p90:.4f} ms")
    print(f"95th Percentile (P95):   {lat_p95:.4f} ms")
    print(f"99th Percentile (P99):   {lat_p99:.4f} ms")
    print(f"Minimum Latency:         {lat_min:.4f} ms")
    print(f"Maximum Latency:         {lat_max:.4f} ms")
    print(f"SLA Target:              < 1.0000 ms")
    print(f"SLA Headroom:            {(1.0 - lat_avg) / 1.0 * 100:.1f}%")
    print("-" * 70)
    print(f"Total Functional Tests:  {results['passed'] + results['failed']}")
    print(f"Passed:                  {results['passed']}")
    print(f"Failed:                  {results['failed']}")
    print("=" * 70)

    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
