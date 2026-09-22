<!-- Measured results of the explicitly authorized, isolated MAQ compatibility smoke test. -->
# MAQ Routing Smoke Test

Date: 2026-09-22. Endpoint: `https://llm.maqsoftware.net/v1`.
Scope: four synthetic requests in a standalone process; no hosted workspace or
database records were created. Answer cap: 512 tokens. Six provider calls in the
successful run, including two self-checks. No automatic retries.

| Case | Selected / Final Tier | Final Model | Routing Latency | Input Tokens, All Calls | Completion Tokens, All Calls |
| --- | --- | --- | ---: | ---: | ---: |
| Forced baseline, brief greeting | small / small | qwen-3.8-27b | 4,028 ms | 154 | 34 |
| Forced next tier, brief greeting | medium / medium | muse-glimmer-30b | 3,884 ms | 63 | 198 |
| Auto, capital of France | small / small | qwen-3.8-27b | 3,278 ms | 159 | 24 |
| Auto, explain caching and latency | medium / medium | muse-glimmer-30b | 4,933 ms | 66 | 249 |

Both models returned final answers. The two auto cases selected the configured
tiers; neither escalated in this live run. Mocked tests separately exercise the
escalation path. These four prompts are not a quality or cost benchmark.

## Limitations

- A prior 64-token-cap attempt stopped when Muse used the budget without final
  answer text. The owner approved the 512-token cap for the successful run.
- Both four-token Qwen self-checks consumed four completion tokens but returned
  no final text. The existing confidence scorer therefore used its neutral 0.5
  self-check fallback. This is not evidence of calibrated model confidence.
- The highest test tier reports confidence 1.0 by routing convention, not an
  independent correctness assessment.
- Token counts are reported by the provider and may include processing not shown
  in the final answer. Earlier failed diagnostic attempts are not included in
  this successful-run table.
- Prices were not provided, so no dollar cost, savings claim, or ranking of these
  models by cost is reported. Parameter counts do not establish capability order.
- The authenticated web gateway still blocks inference until M3 model ownership,
  configuration, provider-aware confidence, and usage accounting are implemented.