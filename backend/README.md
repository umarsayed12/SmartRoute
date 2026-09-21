<!-- Setup, configuration, and verification for the SmartRoute backend. -->
# SmartRoute Backend

FastAPI foundation with environment-driven model tiers and async Ollama and
OpenAI-compatible providers. Phase 2 exposes `/health`; the chat endpoint is
planned for Phase 3.

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
provider errors, health checks, and CORS. VS Code also has `install: backend` and
`test: backend` tasks, using the same virtual environment.