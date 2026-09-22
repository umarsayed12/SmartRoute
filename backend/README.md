<!-- Setup, configuration, and verification for the SmartRoute backend. -->
# SmartRoute Backend

**Hosted migration:** [the active architecture](../docs/HOSTED_ARCHITECTURE.md)
now targets Neon Postgres, managed authentication, private workspaces, and user-owned
OpenAI/Anthropic models. The M1 schema and setup tooling are present, but the HTTP
routes documented below still use the local SQLite implementation. `APP_MODE=hosted`
is intentionally blocked until the migration is complete. Do not deploy the current
unauthenticated API publicly. Existing local data is not automatically imported.

FastAPI foundation with environment-driven model tiers and async Ollama and
OpenAI-compatible providers. Phase 9 adds a repeatable Test Lab and benchmark
runner to feedback-driven routing, dashboard statistics, runtime settings,
training administration, and searchable request history.

## Setup (Windows PowerShell)

Requires Python 3.11 or newer. From the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Commands use the virtual environment's Python directly, so activation and
PowerShell execution-policy changes are not required. `.env` is gitignored.

## Local Models

Install [Ollama](https://ollama.com/download), start it, then download the free models:

```powershell
ollama pull qwen2.5:1.5b
ollama pull qwen2.5:7b
```

If Ollama is not already running through its desktop app, run `ollama serve` in
a separate terminal. The default address is `http://localhost:11434`.

## Run

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app
```

Watching only the application directory avoids reloads caused by virtual
environment activity.

In another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

API documentation: <http://127.0.0.1:8000/docs>.

```json
{"status":"ok","tiers":["small","medium"],"ollama":true,"model_file_present":false}
```

`ollama: false` means the server did not respond successfully to `/api/tags`
within the configured one-second HTTP timeouts. The backend remains healthy;
this flag checks reachability, not whether the two models have been downloaded.
`model_file_present` checks the configured learned-model path without loading it.
It does not assert that the artifact or its training report is valid.

## Configuration

Every environment variable is documented in [.env.example](.env.example).
Environment variables override `backend/.env`; restart the backend after changes.
The `TIERS` list is derived from these settings, not a separate environment variable.
On startup, saved runtime settings override their environment defaults. Provider
URLs, models, and credentials remain environment-only configuration.

| Tier | Provider | Default model | Default cost |
| --- | --- | --- | --- |
| small | Ollama | `qwen2.5:1.5b` | Free |
| medium | Ollama | `qwen2.5:7b` | Free |
| large | OpenAI-compatible | Disabled | Configurable |

Leaving `LARGE_MODEL` empty disables large; `settings.get_tier("large")` then
returns medium. To enable large, configure `LARGE_MODEL`, `LARGE_BASE_URL`, and
any required `LARGE_API_KEY` in `.env`. Use a free-tier provider to keep the setup
free. API roots with or without a trailing `/v1` are accepted. Set the input and
output prices to the provider's actual USD price per 1,000 tokens.

Reference prices default to $0.0025 input and $0.010 output per 1,000 tokens.
The confidence threshold defaults to 0.6 and `MAX_ESCALATIONS` defaults to 1;
setting it to 0 disables escalation. `DB_PATH` defaults to `data/smartroute.db`,
which is initialized automatically on startup. The learned-model path is
`MODEL_PATH` (default `data/router_model.joblib`). Relative paths assume the
backend working directory.

## OpenAI-Compatible Chat

With Ollama, both local models, and the backend running, use the official OpenAI
SDK example from `backend/`. Before training, its explanation prompt selects medium:

```powershell
.\.venv\Scripts\python.exe scripts/try_openai_sdk.py
```

The `openai` package is included in the backend requirements. The example points
at `http://localhost:8000/v1`, uses `api_key="not-needed"`, and prints both the
answer and `response.model_extra["smartroute"]` metadata.

For a direct HTTP request in PowerShell:

```powershell
$body = @{
	model = "smartroute/auto"
	messages = @(@{ role = "user"; content = "Hello!" })
	temperature = 0.2
	max_tokens = 64
} | ConvertTo-Json -Depth 5
Invoke-RestMethod http://127.0.0.1:8000/v1/chat/completions -Method Post -ContentType "application/json" -Body $body -TimeoutSec 180
```

Responses contain OpenAI's `id`, `object`, `created`, `model`, `choices`, and
`usage`, plus a `smartroute` object with the request ID, chosen/final tier,
escalation flag, confidence, reason, routing mode, latency, and actual/reference
costs. OpenAI `usage` reports the final answer's provider token counts. Actual
cost sums all answer attempts; reference cost uses only the final answer's
tokens with the configured premium prices. Local answers and self-checks are
free. Routing latency includes every answer attempt and confidence check.

With the default routing preference, `smartroute/auto` and unrecognized model
names use the trained classifier when available (`routing_mode="learned"`),
otherwise the heuristic (`routing_mode="heuristic"`). Both paths use the confidence cascade. Use
`smartroute/small`, `smartroute/medium`, or `smartroute/large` to bypass both
selectors and stay on a fixed tier (`routing_mode="forced"`). Forced requests
are scored but never escalate. Disabled large still resolves to medium.

Requests must include a model and at least one text message. Streaming
(`stream=true`) returns HTTP 400 without a provider call. Provider connection
failures return 503, timeouts return 504, and provider HTTP errors return 502;
pull the selected model if Ollama reports it is missing.

## Heuristic Routing

Feature extraction joins all message contents with newlines, excluding role
names. It measures characters, whitespace-separated words, message count,
code/math cues, question marks, reasoning/long-output cues, non-ASCII character
ratio, and average word length. `FEATURE_ORDER` defines the same stable vector
order for training and learned predictions.

Rules are evaluated in this order; the first matching rule supplies the reason:

| Signal | Selected tier |
| --- | --- |
| Long-output cues: essay, detailed, comprehensive, write a, generate a | large |
| Code and reasoning cues together, with more than 200 words | large |
| Code cues, reasoning cues, or more than 120 words | medium |
| Fewer than 12 words without higher-tier cues | small |
| Any remaining prompt | small |

Reasoning cues include explain, why, compare, analyze, step by step, and prove.
These are deliberately simple rules, not a guarantee of answer quality. Math
and the other measured features remain available for later learned routing.

If large is disabled, metadata records `tier_chosen="large"` and
`tier_final="medium"`, and the reason explains the fallback. This is one call to
medium, not an escalation: `escalated=false`. An enabled large tier uses the
configured OpenAI-compatible provider and its token prices.

## Confidence Cascade

Auto mode starts at the learned- or heuristic-selected tier. Confidence is the average of
two signals: a text heuristic penalizing empty, short, hedged, or repeated-question
answers, and a same-model self-check requesting an integer from 0 to 10 with
`max_tokens=4`. Scoring uses the latest user question. Invalid or unavailable
self-checks contribute a neutral 0.5 rather than discarding a generated answer.

When confidence is strictly below `CONFIDENCE_THRESHOLD`, the router tries the
next enabled tier, preserving the conversation and generation options. It stops
at the escalation budget, a satisfactory score, or the highest enabled tier.
The default budget allows one step; increasing it permits up to small -> medium
-> large when all tiers are enabled. The reason records each transition, while
`tier_chosen` retains the original selection and `tier_final` identifies the
returned answer's tier.

The highest enabled tier skips the self-check and returns confidence 1.0. That
is medium when large is disabled, otherwise large. This is a routing convention,
not a calibrated probability or a guarantee that the answer is correct. Lower
tiers are local Ollama models, so their auxiliary self-checks do not incur fees.

## Request History

Every successful chat completion queues one SQLite row with its full conversation,
final answer, features, routing decisions, final token counts, total routing latency,
and actual/reference costs. The row's `id` matches the completion ID and
`smartroute.request_id`. Rejected requests and provider failures are not stored as
completed answers. Logging runs through `BackgroundTasks` after the HTTP response,
so history can briefly lag the reply; pending writes are not a durable queue.

Set the optional `X-SmartRoute-Source` header to `api`, `playground`, `testlab`, or
`sdk`. It defaults to `api`; unknown values return HTTP 422 before calling a model.
The database uses WAL mode and a separate, closed connection for each operation.
Full conversations and answers are stored unencrypted locally; runtime database
files are gitignored.

`GET /v1/requests` returns `{items, total, limit, offset}`, newest first. `total`
counts all matching rows before pagination. Supported query parameters:

| Parameter | Behavior |
| --- | --- |
| `limit` | Page size, 1-100; default 50 |
| `offset` | Number of matching rows to skip; default 0 |
| `tier` | Final tier: small, medium, or large |
| `escalated` | `true` or `false` |
| `feedback` | `1` positive, `-1` negative, `0` unrated; omit for all |
| `source` | `api`, `playground`, `testlab`, or `sdk`; omit for all |
| `search` | Literal substring in stored prompt or answer; SQLite ASCII case folding |

List items contain previews and metadata, not full prompts, answers, or feature
vectors. `GET /v1/requests/{id}` returns the complete record or HTTP 404. In the
detail record, `prompt_full` is JSON text preserving message roles and content,
`features_json` is JSON text containing the numeric feature dictionary, and
`answer_full` is the final answer text. Previews use the latest user message,
normalize whitespace, and are limited to 200 characters. Timestamps are UTC.

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/v1/requests?limit=10&escalated=false&feedback=0'
```

## Feedback And Training

`POST /v1/feedback` accepts `{request_id, score, note?}`. `score` must be the JSON
integer `1` or `-1`; strings, booleans, and zero are rejected with HTTP 422.
Success returns the saved fields. Unknown request IDs return HTTP 404, including
a request whose background log has not appeared yet. Posting again replaces the
rating; omitting `note` clears a previous note.

```powershell
$feedback = @{ request_id = "<request ID from a completion>"; score = 1; note = "Helpful answer" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/v1/feedback -Method Post -ContentType "application/json" -Body $feedback
```

After rating at least 30 requests, train from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m app.train
```

A positive rating labels `tier_final` as sufficient. A negative rating labels
the next tier above it, capped at large. This uses all three tier labels even
when large currently falls back to medium. The trainer vectorizes features in
`FEATURE_ORDER` and fits `StandardScaler` followed by
`LogisticRegression(max_iter=1000)`.

Fewer than 30 labelled rows, only one target class, or invalid saved features
produce a friendly skip message and leave any existing model untouched. The CLI
exits normally for these cases. Feedback does not trigger training automatically;
call `train()` from Python or run the command again after adding ratings.

The command prints accuracy, class order, and a confusion matrix. With at least
two examples per class, evaluation uses a reproducible stratified 20% holdout;
the saved pipeline is then refitted on all labelled rows. A singleton class uses
explicitly marked `evaluation="training"` metrics instead. Those in-sample
metrics are optimistic, and neither metric estimates answer correctness.

Training writes `MODEL_PATH` and a sibling `router_model_meta.json` containing
the UTC training time, row count, accuracy, classes, confusion matrix, and
evaluation type. Each file is staged before replacement. Default artifacts are
under gitignored `data/`. Only load trusted, locally trained joblib files: the
format can execute Python during deserialization.

The gateway loads the model lazily and refreshes it when the artifact changes,
without a restart. In the default `auto` preference, missing, unreadable, or
incompatible artifacts fall back to the heuristic. The learned class probability appears in the routing reason;
`smartroute.confidence` still describes the generated answer's confidence check,
not the classifier's probability. The normal escalation and disabled-large
fallback rules still apply.

## Dashboard Statistics

`GET /v1/stats?days=7` accepts 1-365 UTC calendar days, including today through
the current time. Its response contains `totals`, `cost`, `quality`,
`tier_distribution`, `latency`, `timeline`, and `routing_modes`.

Request and escalation counts cover all matching completed requests. Quality
rates use only rated answers; `quality.by_tier.count` is the number of ratings
for that final tier. Escalation and positive-feedback rates are fractions from
0 to 1, while `cost.saved_pct` is a percentage. Unrated quality rates and empty
tier latency percentiles are `null`, not misleading zero-quality measurements.

Latency p50/p95 use linear interpolation over full routing time in milliseconds,
grouped by final tier. Savings are reference cost minus actual cost and may be
negative. Saved percentage is 0 when reference spend is zero. All days in the
requested range appear in the timeline, including days without requests.
Stored costs remain unchanged when runtime reference prices are edited.

## Runtime Administration

These endpoints are unauthenticated development controls. Keep the server bound
to loopback or a trusted environment; do not expose it publicly without access
controls.

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/tiers` | Ordered model tiers, prices, enabled flags, and live availability |
| `GET /v1/settings` | Current editable settings, without credentials |
| `PUT /v1/settings` | Validate, merge, persist, and apply supplied settings |
| `POST /v1/train` | Run the feedback trainer and return its result |
| `GET /v1/train/status` | Saved training metadata, or `{"trained":false}` |

Tier availability probes Ollama `/api/tags` or a remote provider's `/v1/models`
with a two-second HTTP timeout, requiring the configured model to be listed.
Disabled tiers are not probed. API keys are used only for remote authentication
and are excluded from responses. Probes generate no model output; a provider
without a compatible model-list endpoint can report unavailable even if its
chat endpoint works.

Editable fields are `confidence_threshold` (0-1), `max_escalations` (non-negative
integer), `reference_input_price_per_1k`, `reference_output_price_per_1k`
(non-negative finite USD values), and `routing_mode_preference`:

- `auto`: prefer a learned model, otherwise use the heuristic.
- `heuristic_only`: skip the learned model entirely.
- `learned_only`: require a usable learned model; return HTTP 503 if unavailable.

Explicit `smartroute/small|medium|large` requests bypass these policy preferences.
The confidence cascade remains enabled for non-forced requests.

`PUT` accepts partial updates. The validated result is written atomically to
`settings.json` beside `DB_PATH` (normally `data/settings.json`) before shared
in-memory values are updated. A failed write returns HTTP 500 without applying
the change. Saved values are reloaded on startup; invalid files are ignored with
a warning. Files contain only the editable, non-secret settings and are
gitignored at the default location.

```powershell
$settings = @{ confidence_threshold = 0.7; routing_mode_preference = "auto" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/v1/settings -Method Put -ContentType "application/json" -Body $settings
Invoke-RestMethod http://127.0.0.1:8000/v1/train -Method Post
Invoke-RestMethod http://127.0.0.1:8000/v1/train/status
```

Training runs off the event loop and follows the same 30-row/two-class guards
as the CLI. Insufficient data returns HTTP 200 with `trained=false`. Overlapping
admin training jobs in the same process return HTTP 409. Status returns metadata
only when the artifact exists and its report is valid; it does not unpickle the
artifact or claim that a prediction was performed.

## Test Lab And Benchmarks

The built-in `default` suite contains 40 JSONL prompts: 15 small (greetings,
facts, conversions), 15 medium (coding tasks and explanations), and 10 hard
(multi-step reasoning, design, and constrained code). Every line is valid JSON;
the first record's `_comment` field is file-purpose metadata, not another prompt.
Expected tiers are human-authored routing targets, not verified answer-quality labels.

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/testlab/suites` | Available suites, prompt counts, tier distribution, and output limit |
| `POST /v1/testlab/run` | Run `{suite:"default", mode, limit?}` sequentially |
| `GET /v1/testlab/runs` | Paginated completed-run summaries (`items`, `total`, `limit`, `offset`) |

Modes are `auto`, `small`, `medium`, and `large`; default is `auto`. `limit` runs
the first 1-40 prompts, so a short prefix is not representative of the full
tier mix. All prompts are independent one-message conversations, use the same
256-token output limit, and pass through the normal chat handler. Successful
answers are logged with `source="testlab"` before the next prompt starts.
An overlapping Test Lab run in the same process returns HTTP 409.

Run responses contain `run_id`, metadata, per-prompt `results`, and `summary`.
Each result includes its suite ID, gateway `request_id`, prompt, expected and
final tiers, escalation, confidence, latency, costs, and `match`. Summary routing
accuracy is the fraction where `tier_final == expected_tier`; escalation is a
fraction, saved cost is a percentage, and latency is average routing milliseconds.
Matching tiers is not a test of factual correctness. If large is disabled, its
fallback to medium still counts as a mismatch for prompts labelled large.

Only completed run summaries are saved in `testlab_runs`; full answers remain
in normal request history. Provider failure stops the run with an error naming
the failed prompt and the completed count. Already completed requests remain
logged, but no successful run summary is created. A client/network interruption
can leave a run outcome uncertain; check run history before retrying.

With the backend and both local models running, execute from `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark.py
```

This runs the same full suite in auto and large-only modes, prints a Markdown
comparison, and writes [scripts/benchmark_results.md](scripts/benchmark_results.md).
The report includes final-tier counts so large-to-medium fallback is visible.
It compares actual costs to the configured premium reference and does not claim
equivalent answer quality. The report is written only after both modes succeed.

For a short smoke check or a separate local gateway:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark.py --limit 2 --base-url http://localhost:8000 --output data/benchmark_smoke.md
```

The CLI allows the server time to finish a complete suite; individual provider
timeouts still apply. A full 80-answer comparison can take several minutes or
longer depending on hardware and model loading. `auto` follows current routing
preferences, so `learned_only` requires a usable trained model. Large-only is
forced and resolves to medium when no remote large model is configured.

## Provider Smoke Check

After pulling the small model, run from `backend/`:

```powershell
.\.venv\Scripts\python.exe -c "import asyncio; from app.providers.ollama import chat; print(asyncio.run(chat('qwen2.5:1.5b', [{'role': 'user', 'content': 'Hello!'}])))"
```

Both providers return `ProviderResult` with text, prompt/completion token counts,
latency in milliseconds, and the model name. Calls are non-streaming, with a
10-second connection timeout and a 120-second read timeout. Provider HTTP and
connection errors propagate to the caller.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use mocked HTTP responses and require neither Ollama nor remote credentials.
They cover tier configuration and fallback, request payloads, token accounting,
provider errors, health checks, CORS, chat validation, and official OpenAI SDK
compatibility, plus feature signals, rule boundaries, provider selection, and
large-tier fallback/costs. Confidence tests cover penalties, parsing failures,
top-tier behavior, forced modes, escalation limits, and cumulative costs/timing.
Request-log tests cover round trips, startup, source labels, safe filters,
pagination, concurrent inserts, and full-detail retrieval. Learned-router tests
cover feedback validation, training safeguards, saved-model loading, replacement,
fallback, and the complete feedback-to-routing flow. Admin tests cover aggregate
math, settings persistence and effects, secret redaction, model health, and training
status/failure handling. Test Lab tests cover suite integrity, sequencing, mode
selection, request logging, summary arithmetic, failed runs, and benchmark output.
Tests use temporary databases, settings, and model files,
never the user's request history or trained artifact. VS Code
also has `install: backend` and `test: backend` tasks, using the same virtual environment.