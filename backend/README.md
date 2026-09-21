<!-- Setup, configuration, and verification for the SmartRoute backend. -->
# SmartRoute Backend

FastAPI foundation with environment-driven model tiers and async Ollama and
OpenAI-compatible providers. Phase 3 exposes `/health` and
`POST /v1/chat/completions`, currently using only the small tier.

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
Confidence defaults to 0.6 with one escalation. These and the database/model
paths are configuration for subsequent phases; routing and persistence are not
implemented yet. Relative data paths assume the backend working directory.

## OpenAI-Compatible Chat

With Ollama, the small model, and the backend running, use the official OpenAI
SDK example from `backend/`:

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
costs. Token counts come from Ollama. Local model usage costs $0; reference cost
uses the configured premium prices.

All requested model names currently select small, including names such as
`smartroute/large`. Tier selection and forced routing arrive in later phases.
The routing mode is `single_tier`, and confidence is `null` until confidence
scoring is implemented. Requests must include a model and at least one text
message. Streaming (`stream=true`) returns HTTP 400 without calling Ollama.
Provider connection failures return 503, timeouts return 504, and provider HTTP
errors return 502; pull the small model if Ollama reports that it is missing.

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
compatibility. VS Code also has `install: backend` and `test: backend` tasks,
using the same virtual environment.