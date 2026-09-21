<!-- Setup, configuration, and verification for the SmartRoute backend. -->
# SmartRoute Backend

FastAPI foundation with environment-driven model tiers and async Ollama and
OpenAI-compatible providers. Phase 6 exposes `/health` and
`POST /v1/chat/completions` with heuristic routing, confidence-based escalation,
fixed-tier modes, and a searchable SQLite request history.

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
{"status":"ok","tiers":["small","medium"],"ollama":true}
```

`ollama: false` means the server did not respond successfully to `/api/tags`
within the configured one-second HTTP timeouts. The backend remains healthy;
this flag checks reachability, not whether the two models have been downloaded.

## Configuration

Every environment variable is documented in [.env.example](.env.example).
Environment variables override `backend/.env`; restart the backend after changes.
The `TIERS` list is derived from these settings, not a separate environment variable.

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
configuration for a subsequent phase. Relative paths assume the backend working
directory.

## OpenAI-Compatible Chat

With Ollama, both local models, and the backend running, use the official OpenAI
SDK example from `backend/`. Its explanation prompt now selects medium:

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

`smartroute/auto` and unrecognized model names use heuristic selection and the
confidence cascade (`routing_mode="heuristic"`). Use `smartroute/small`,
`smartroute/medium`, or `smartroute/large` to bypass heuristic selection and stay
on a fixed tier (`routing_mode="forced"`). Forced requests are scored but never
escalate, so comparisons use the requested tier. Disabled large still resolves
to medium.

Requests must include a model and at least one text message. Streaming
(`stream=true`) returns HTTP 400 without a provider call. Provider connection
failures return 503, timeouts return 504, and provider HTTP errors return 502;
pull the selected model if Ollama reports it is missing.

## Heuristic Routing

Feature extraction joins all message contents with newlines, excluding role
names. It measures characters, whitespace-separated words, message count,
code/math cues, question marks, reasoning/long-output cues, non-ASCII character
ratio, and average word length. `FEATURE_ORDER` defines the stable vector order
for the later learned router.

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

Auto mode starts at the heuristic-selected tier. Confidence is the average of
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

The database feedback and training-row helpers are ready; the public feedback
endpoint and learned router arrive in Phase 7.

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
pagination, concurrent inserts, and full-detail retrieval. Every test uses an
isolated temporary database rather than the local request history. VS Code also
has `install: backend` and `test: backend` tasks, using the same virtual environment.