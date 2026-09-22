<!-- Active hosted migration plan followed by the historical local-prototype build specification. -->
# SmartRoute — Build Specification for GitHub Copilot

> **Repo:** `https://github.com/umarsayed12/SmartRoute`
> **Owner:** `Umar Khursheed` · **Author handle for package metadata:** `umarsayed12`

> **Architecture amendment, 2026-09-22:** The owner approved a hosted,
> bring-your-own-model service using Neon Postgres and Neon managed authentication.
> This amendment supersedes the local/shared-storage assumptions below. Original
> Phases 1-11 are complete historical checkpoints; original Phases 12-13 are paused.

## Active Hosted Migration

The detailed architecture, security boundaries, setup, and acceptance criteria are
in [docs/HOSTED_ARCHITECTURE.md](docs/HOSTED_ARCHITECTURE.md). Follow these checkpoints
in order, test and push each one, and stop for the owner's "next" after pushing.

| Checkpoint | Scope | Completion gate |
| --- | --- | --- |
| M1 | Neon configuration, versioned workspace schema, secret primitives, migration docs | Connections verified; migration applied; schema/security tests pass; legacy data unchanged |
| M2 | Managed-auth login, verified backend identity, private workspace provisioning, SDK key creation/revocation, tenant-scoped repositories | Two-user isolation tests for every data operation; no unauthenticated workspace access |
| M3 | Encrypted OpenAI/Anthropic model configuration and tenant-aware routing | At least one owned model required; no hosted Ollama fallback; all billable attempts tracked |
| M4 | Web onboarding, model management, Integration page, SDK and CLI | A new user can configure models, obtain a gateway key, call the SDK, and see only their logs |
| M5 | Public-deployment security gates, quotas/limits, migration guide, publishing and deployment | Authentication, authorization, credential redaction, isolation, and abuse controls verified end to end |

### Approved Decisions

- One private workspace per user initially; team invitations are deferred.
- Neon managed email/password authentication; passwords remain with the auth service.
- Neon Postgres stores workspace data, not just user profiles. Do not enable the
  browser Data API for application data as part of this migration.
- Saved provider keys are encrypted at rest with a server-only key and never
  returned by API reads. Gateway API keys are high-entropy, hashed, and shown once.
- OpenAI and native Anthropic cloud APIs first. No public arbitrary endpoint URLs,
  local-network targets, or shared owner-funded model fallback in hosted mode.
- At least one user-configured model is mandatory. One model supports tracking;
  multiple configured tiers permit selection/escalation.
- SmartRoute has a free plan initially; model-provider charges belong to users.
  Reserve plan/usage data, but do not add payment processing yet.
- Keep the existing SQLite database and local prototype intact until explicit
  cutover. Never silently import local shared history into a new user's workspace.
- The current HTTP app remains local-only. `APP_MODE=hosted` is intentionally
  blocked during foundation work. Do not remove that guard until the required
  hosted routes, model ownership, and public-deployment gates are complete.

### Updated Coding Rules

- Retain Python 3.11+, FastAPI, async httpx, Pydantic v2, scikit-learn, and joblib.
- Hosted persistence uses SQLAlchemy Core 2, psycopg 3, and Alembic migrations;
  `sqlite3` remains only in the historical local implementation during cutover.
- Retain React 18, Vite, TypeScript, CSS Modules, Recharts, and the existing visual
  language. Use Neon's programmatic auth SDK with custom screens, not a UI framework.
- The eventual Python SDK remains httpx-based. Publishing waits for the hosted
  authentication and model-configuration contract to stabilize.
- Treat credentials as secrets throughout tools, tests, logs, configuration, and
  error output. Request readiness flags, never secret values in chat.
- Auth provider settings and connection credentials are deployment configuration;
  routing settings, saved models, usage, feedback, and training artifacts are per workspace.

---

## How Copilot must use this file

You are GitHub Copilot (agent mode) working inside this repository on **Windows with PowerShell**.

1. Follow the **Active Hosted Migration** above. The original phases below are historical reference until explicitly resumed.
2. At the start of each phase, briefly state the goal in one line, then create/modify the files.
3. When the phase's files are done, **run the phase's PowerShell block** in the integrated terminal (install, test, run, then `git add / commit / push`).
4. After pushing, **stop and wait** for me to say "next" before starting the next phase. Do not continue on your own.
5. Follow the **Coding Rules** below for every file. If a rule and a phase conflict, the phase wins.
6. When something fails (a test, a server, a build), fix it and re-run before committing. Never commit a broken state.
7. Commit messages: use the ones written in each phase, or rewrite them in the same style. Keep them short and lowercase.

---

## What we are building (one paragraph)

**SmartRoute** is an OpenAI-compatible LLM gateway that sends each chat request to the *cheapest model tier that can handle it*. A small local model (via Ollama) answers first; a quick confidence check decides whether to escalate to a bigger tier. Every request is logged with actual cost vs. a "premium reference" cost, users can rate answers, and a small scikit-learn model retrains on that feedback to improve routing. A React frontend provides a Playground, a Dashboard ("$ saved vs quality retained"), a Requests Explorer, a Test Lab for running prompt suites, and a Settings page. A tiny Python client library (`smartroute-client`) is published to PyPI so anyone can `pip install` it and use the gateway in three lines.

---

## Coding Rules (apply to every phase)

- **Simple over clever.** Plain functions, small files, obvious names. No abstract base classes unless a phase asks for one.
- **Backend:** Python 3.11+, FastAPI, httpx (async), Pydantic v2, `pydantic-settings`, standard `sqlite3`, scikit-learn, joblib. Type hints and 1–2 line docstrings on every public function.
- **Frontend:** React 18 + Vite + TypeScript, Recharts for charts, CSS Modules only (no UI framework). Small components, one component per file.
- **SDK:** pure Python, `httpx` only dependency, `pyproject.toml` with `hatchling` build backend.
- **Free resources only.** Local Ollama models: `qwen2.5:1.5b` (small) and `qwen2.5:7b` (medium). The "large" tier is optional and comes from env vars (any OpenAI-compatible endpoint, e.g. a free-tier provider); when unset, large falls back to medium.
- **Folders are separate:** `backend/`, `frontend/`, `sdk/`. Each has its own README with run instructions.
- **Every file you create gets a 1–2 line header comment** explaining its purpose (so the owner can explain it in an interview).
- **Never hardcode secrets.** Use `.env` + `.env.example`.
- **Tests:** pytest for backend routing logic; Vitest is optional for the frontend (skip unless trivial).

---

## Target repository structure

```
smartroute/
├── README.md                      # Pitch, architecture (Mermaid), quick start, benchmark, screenshots
├── .gitignore
├── docker-compose.yml             # Phase 13 (optional)
│
├── backend/
│   ├── README.md
│   ├── requirements.txt
│   ├── .env.example
│   ├── data/                      # smartroute.db, router_model.joblib (gitignored)
│   ├── app/
│   │   ├── main.py                # FastAPI app, CORS, router registration, startup (db init)
│   │   ├── config.py              # Tiers, prices, thresholds (from .env)
│   │   ├── schemas.py             # OpenAI-style request/response models + smartroute extras
│   │   ├── db.py                  # SQLite schema + helper functions
│   │   ├── providers/
│   │   │   ├── base.py            # ProviderResult dataclass
│   │   │   ├── ollama.py          # Async client for Ollama /api/chat
│   │   │   └── openai_compatible.py  # Async client for any /v1/chat/completions endpoint
│   │   ├── routing/
│   │   │   ├── features.py        # Prompt -> numeric features
│   │   │   ├── heuristic.py       # Rule-based tier picker (v1)
│   │   │   ├── learned.py         # scikit-learn tier picker (v2, falls back to heuristic)
│   │   │   ├── confidence.py      # Self-check + escalation decision
│   │   │   └── router.py          # Orchestrates: features -> pick tier -> call -> confidence -> escalate
│   │   ├── api/
│   │   │   ├── chat.py            # POST /v1/chat/completions
│   │   │   ├── feedback.py        # POST /v1/feedback
│   │   │   ├── stats.py           # GET /v1/stats, GET /v1/requests, GET /v1/requests/{id}
│   │   │   ├── testlab.py         # POST /v1/testlab/run, GET /v1/testlab/suites
│   │   │   └── admin.py           # GET /v1/tiers, GET/PUT /v1/settings, POST /v1/train
│   │   └── train.py               # Retrain learned router from feedback rows
│   ├── scripts/
│   │   ├── try_openai_sdk.py      # Proves OpenAI SDK compatibility
│   │   ├── prompts.jsonl          # Benchmark prompt suite (with expected_tier)
│   │   └── benchmark.py           # CLI benchmark -> benchmark_results.md
│   └── tests/
│       ├── test_features.py
│       ├── test_heuristic.py
│       └── test_confidence.py
│
├── frontend/
│   ├── README.md
│   ├── package.json
│   ├── vite.config.ts             # proxy /v1 -> http://localhost:8000
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                # Sidebar nav: Playground | Dashboard | Requests | Test Lab | Settings
│       ├── api.ts                 # Typed fetch helpers
│       ├── types.ts               # Shared TS types mirroring backend schemas
│       ├── pages/
│       │   ├── Playground.tsx     # Chat UI with tier badge, confidence, feedback, compare mode
│       │   ├── Dashboard.tsx      # KPIs + charts
│       │   ├── Requests.tsx       # Searchable/filterable table + detail drawer
│       │   ├── TestLab.tsx        # Run a prompt suite, see routing accuracy & cost
│       │   └── Settings.tsx       # Tiers, thresholds, retrain button, model status
│       └── components/
│           ├── TierBadge.tsx
│           ├── KpiCard.tsx
│           ├── DataTable.tsx
│           └── charts/
│               ├── TierPie.tsx
│               ├── QualityBar.tsx
│               └── SavingsLine.tsx
│
└── sdk/
    ├── README.md
    ├── pyproject.toml
    ├── LICENSE                    # MIT
    ├── src/smartroute_client/
    │   ├── __init__.py
    │   ├── client.py              # SmartRoute class: chat(), feedback(), stats()
    │   └── cli.py                 # `smartroute` CLI: health, chat, bench
    └── tests/
        └── test_client.py
```

---

## Phase 1 — Repository skeleton

**Goal:** organised empty repo pushed to GitHub.

Create:
- Root `README.md`: project name, one-paragraph pitch (from above), "Status: 🚧 in progress", planned structure (three folders), MIT licence line.
- Root `.gitignore`: Python (`.venv/`, `__pycache__/`, `*.db`, `*.joblib`, `.env`, `dist/`, `*.egg-info/`), Node (`node_modules/`, `dist/`, `.env.local`), OS files.
- Root `LICENSE` (MIT, owner name from header).
- `backend/README.md`, `frontend/README.md`, `sdk/README.md` — one-line placeholders.

```powershell
git init
git add .
git commit -m "chore: repo skeleton, readme, license, gitignore"
git branch -M main
git remote add origin <PASTE YOUR GITHUB REPO LINK HERE>
git push -u origin main
```

---

## Phase 2 — FastAPI foundation, config and providers

**Goal:** `GET /health` runs; providers can call Ollama and return text + token counts.

Create in `backend/`:
- `requirements.txt`: `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic`, `pydantic-settings`, `python-dotenv`, `scikit-learn`, `numpy`, `joblib`, `pytest`, `pytest-asyncio`.
- `app/config.py` (pydantic-settings `Settings`):
  - `TIERS`: ordered list of 3 tier objects `{name, provider, model, base_url, api_key, input_price_per_1k, output_price_per_1k}`. Defaults: `small` = ollama `qwen2.5:1.5b` price 0; `medium` = ollama `qwen2.5:7b` price 0; `large` = provider `openai_compatible`, values from `LARGE_MODEL`, `LARGE_BASE_URL`, `LARGE_API_KEY`, `LARGE_INPUT_PRICE`, `LARGE_OUTPUT_PRICE`. If `LARGE_MODEL` is empty, `large` is disabled and resolves to `medium`.
  - `OLLAMA_BASE_URL` default `http://localhost:11434`.
  - `REFERENCE_INPUT_PRICE_PER_1K` default `0.0025`, `REFERENCE_OUTPUT_PRICE_PER_1K` default `0.010` ("what a premium model would have cost").
  - `CONFIDENCE_THRESHOLD` default `0.6`, `MAX_ESCALATIONS` default `1`.
  - `DB_PATH` default `data/smartroute.db`, `MODEL_PATH` default `data/router_model.joblib`.
- `app/providers/base.py`: `@dataclass ProviderResult(content, prompt_tokens, completion_tokens, latency_ms, model)`.
- `app/providers/ollama.py`: `async def chat(model, messages, temperature=0.2, max_tokens=None) -> ProviderResult` using `/api/chat`, `stream=false`; read `prompt_eval_count` / `eval_count` for tokens.
- `app/providers/openai_compatible.py`: same signature against `{base_url}/v1/chat/completions` with bearer key.
- `app/main.py`: app, CORS for `http://localhost:5173`, `GET /health` -> `{"status":"ok","tiers":[...names], "ollama": true/false}` (ping Ollama `/api/tags` with 1s timeout).
- `.env.example` listing every variable with a comment.
- `backend/README.md`: setup + run instructions.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Start-Process powershell -ArgumentList "-NoExit","-Command","cd $PWD; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload"
Start-Sleep -Seconds 4
Invoke-RestMethod http://127.0.0.1:8000/health
cd ..
git add .
git commit -m "feat(backend): fastapi app, tier config, ollama and openai-compatible providers"
git push
```

---

## Phase 3 — OpenAI-compatible chat endpoint (single tier)

**Goal:** any OpenAI SDK pointed at `http://localhost:8000/v1` gets an answer from the small tier.

- `app/schemas.py`: `ChatMessage`, `ChatCompletionRequest` (`model`, `messages`, `temperature=0.2`, `max_tokens=None`, `stream=False` — reject `stream=True` with 400 for now), `Usage`, `Choice`, `ChatCompletionResponse` (OpenAI shape: `id`, `object="chat.completion"`, `created`, `model`, `choices`, `usage`) plus extra field `smartroute: RoutingInfo` = `{request_id, tier_chosen, tier_final, escalated, confidence, reason, routing_mode, latency_ms, actual_cost_usd, reference_cost_usd}`.
- `app/api/chat.py`: `POST /v1/chat/completions` — always `small` for now, build response.
- Register router in `main.py`.
- `scripts/try_openai_sdk.py`: uses `openai` package with `base_url="http://localhost:8000/v1"`, `api_key="not-needed"`, prints reply and `response.model_extra["smartroute"]` (or the raw JSON).

```powershell
pip install openai
python backend/scripts/try_openai_sdk.py
git add .
git commit -m "feat(api): openai-compatible chat completions endpoint"
git push
```

---

## Phase 4 — Feature extraction and heuristic router (v1)

**Goal:** explainable rules pick `small` / `medium` / `large`.

- `app/routing/features.py`: `extract_features(messages) -> dict[str, float]` with keys: `prompt_chars`, `prompt_words`, `num_turns`, `has_code`, `has_math`, `question_count`, `asks_reasoning` ("explain", "why", "compare", "analyze", "step by step", "prove"), `asks_long_output` ("essay", "detailed", "comprehensive", "write a", "generate a"), `non_ascii_ratio`, `avg_word_len`. Also `FEATURE_ORDER` list for consistent vectorisation.
- `app/routing/heuristic.py`: `pick_tier(features) -> tuple[str, str]` (tier, reason). Readable rule set, e.g.: greeting/very short (< 12 words, no code, no reasoning) → small; code OR reasoning OR > 120 words → medium; (code AND reasoning AND > 200 words) OR long-output request → large.
- `app/routing/router.py`: `async def route_and_answer(request) -> (ProviderResult, RoutingInfo)` — for now: features → heuristic → call tier. `chat.py` uses it.
- Tests: `tests/test_features.py`, `tests/test_heuristic.py` (6+ cases covering all tiers).

```powershell
cd backend; pytest -q; cd ..
git add .
git commit -m "feat(routing): prompt features and heuristic tier picker"
git push
```

---

## Phase 5 — Confidence check and escalation (the cascade)

**Goal:** small answers first; low confidence escalates once.

- `app/routing/confidence.py`:
  - `heuristic_confidence(question, answer) -> float`: penalise empty/very short answers, hedges ("I'm not sure", "I don't know", "as an AI"), answers that just repeat the question.
  - `async def self_check(model, question, answer) -> float`: ask the same model "Rate from 0 to 10 how confident you are that this answer is correct and complete. Reply with only the number." `max_tokens=4`, parse int, /10, default 0.5 on parse failure.
  - `async def score(question, answer, tier) -> float` = `0.5*heuristic + 0.5*self_check` (skip self_check on the top tier and return 1.0).
- `router.py`: after first answer, if `confidence < CONFIDENCE_THRESHOLD` and escalations < `MAX_ESCALATIONS`, call next tier; set `escalated=True`, `tier_final`.
- Forced routing: `model` = `smartroute/small|medium|large` skips routing (`routing_mode="forced"`); `smartroute/auto` or anything else = auto.
- Cost: `actual_cost = tokens/1000 * tier prices` (sum across all tiers tried); `reference_cost = final tokens/1000 * reference prices`.
- `tests/test_confidence.py` for the heuristic part.

```powershell
cd backend; pytest -q; cd ..
git add .
git commit -m "feat(routing): confidence self-check with single-step escalation"
git push
```

---

## Phase 6 — SQLite request log

**Goal:** every request persisted with full routing detail.

- `app/db.py` (sqlite3, `check_same_thread=False`, WAL mode). Table `requests`: `id TEXT PK, created_at TEXT, prompt_preview TEXT, prompt_full TEXT, answer_full TEXT, features_json TEXT, tier_chosen TEXT, tier_final TEXT, escalated INTEGER, confidence REAL, reason TEXT, routing_mode TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, latency_ms INTEGER, actual_cost_usd REAL, reference_cost_usd REAL, feedback INTEGER NULL, feedback_note TEXT NULL, source TEXT` (`"api" | "playground" | "testlab" | "sdk"`; read from optional header `X-SmartRoute-Source`, default `api`).
  Helpers: `init_db()`, `insert_request(row)`, `set_feedback(id, score, note)`, `get_request(id)`, `list_requests(limit, offset, tier, escalated, feedback, search)`, `rows_for_training()`.
- Call `init_db()` on startup; insert via `BackgroundTasks` in `chat.py`.
- `app/api/stats.py`: `GET /v1/requests` (with the filters above, paginated) and `GET /v1/requests/{id}` (full prompt/answer).

```powershell
git add .
git commit -m "feat(db): sqlite request log with filters and detail endpoint"
git push
```

---

## Phase 7 — Feedback + learned router (v2)

**Goal:** thumbs up/down teaches the router.

- `app/api/feedback.py`: `POST /v1/feedback {request_id, score: 1|-1, note?}`.
- `app/train.py`:
  - Load rows with feedback. Label rule: `score=1` → label = `tier_final` (that tier was enough); `score=-1` → label = next tier above `tier_final` (or top tier if already there).
  - `X` = features in `FEATURE_ORDER`; Pipeline(`StandardScaler`, `LogisticRegression(max_iter=1000)`).
  - Require ≥ 30 labelled rows, else print a friendly message and exit code 0.
  - Print accuracy + confusion matrix, save to `MODEL_PATH`, also save `data/router_model_meta.json` `{trained_at, n_rows, accuracy, classes}`.
  - Expose `train() -> dict` so the admin endpoint can call it.
- `app/routing/learned.py`: load model lazily; `pick_tier(features) -> (tier, probability, reason)`; if model file missing → `None` so `router.py` falls back to heuristic. `routing_mode` = `"learned"` or `"heuristic"`.
- Add `python -m app.train` to `backend/README.md`.

```powershell
git add .
git commit -m "feat(routing): feedback endpoint and learned routing policy"
git push
```

---

## Phase 8 — Stats and admin endpoints

**Goal:** all numbers the frontend needs, plus settings control.

- `GET /v1/stats?days=7` → `{totals:{requests, escalations, escalation_rate}, cost:{actual_usd, reference_usd, saved_usd, saved_pct}, quality:{feedback_count, positive_rate, by_tier:{tier:{count, positive_rate}}}, tier_distribution:{tier:count}, latency:{tier:{p50, p95}}, timeline:[{date, requests, saved_usd, positive_rate}], routing_modes:{heuristic, learned, forced}}`.
- `app/api/admin.py`:
  - `GET /v1/tiers` → tiers with prices, enabled flag, and live reachability check.
  - `GET /v1/settings` / `PUT /v1/settings` → runtime-editable `confidence_threshold`, `max_escalations`, `reference prices`, `routing_mode_preference` (`auto|heuristic_only|learned_only`). Store in memory + `data/settings.json` so it survives restarts.
  - `POST /v1/train` → calls `train.train()` and returns its dict; `GET /v1/train/status` → meta json or `{trained: false}`.

```powershell
git add .
git commit -m "feat(api): stats, tiers, runtime settings and train endpoints"
git push
```

---

## Phase 9 — Test Lab backend

**Goal:** run a prompt suite through the gateway and score routing.

- `backend/scripts/prompts.jsonl`: 40 prompts — 15 simple (greetings, one-line facts, unit conversions), 15 medium (small coding tasks, "explain X"), 10 hard (multi-step reasoning, design questions, long code with constraints). Fields: `{id, prompt, expected_tier, category}`.
- `app/api/testlab.py`:
  - `GET /v1/testlab/suites` → list available suites (`default` from prompts.jsonl).
  - `POST /v1/testlab/run {suite:"default", mode:"auto"|"small"|"medium"|"large", limit?:int}` → runs sequentially (Ollama is single-threaded anyway), tags rows `source="testlab"`, returns `{run_id, results:[{id, prompt, expected_tier, tier_final, escalated, confidence, latency_ms, actual_cost_usd, reference_cost_usd, match:boolean}], summary:{routing_accuracy, escalation_rate, avg_latency_ms, total_actual_usd, total_reference_usd, saved_pct}}`. Persist run summaries in table `testlab_runs`. `GET /v1/testlab/runs` lists them.
- `scripts/benchmark.py`: CLI wrapper that calls the same logic for `auto` and `large`, prints a markdown table, writes `scripts/benchmark_results.md`.

```powershell
git add .
git commit -m "feat(testlab): prompt suite runner, run history and benchmark script"
git push
```

---

## Phase 10 — Frontend scaffold + Playground

**Goal:** chat page that shows exactly how each request was routed.

- Scaffold: `npm create vite@latest frontend -- --template react-ts`; install `recharts`, `react-router-dom`. `vite.config.ts` proxy `/v1` → `http://localhost:8000`.
- `src/types.ts` mirrors backend schemas. `src/api.ts` typed helpers for every endpoint (send header `X-SmartRoute-Source: playground`).
- `src/App.tsx`: left sidebar nav with 5 routes; dark neutral theme via CSS variables.
- `src/pages/Playground.tsx`:
  - Message thread + input + Send (Enter to send, Shift+Enter newline).
  - Mode selector: Auto | Force small | Force medium | Force large | **Compare all** (sends to each tier and renders answers side by side with latency/cost — great for demos).
  - Each assistant message: `TierBadge` (colour per tier), "escalated ↑" tag, confidence %, latency, tokens, cost vs reference, routing reason (tooltip).
  - 👍 / 👎 buttons → `POST /v1/feedback`; disable after click; optional note on 👎.
  - "Clear chat" button.
- `src/components/TierBadge.tsx`.

```powershell
cd frontend
npm install
Start-Process powershell -ArgumentList "-NoExit","-Command","cd $PWD; npm run dev"
cd ..
git add .
git commit -m "feat(frontend): vite scaffold, nav shell and playground with compare mode"
git push
```

---

## Phase 11 — Dashboard, Requests explorer, Test Lab, Settings pages

**Goal:** the full frontend — this is what goes in README screenshots.

- `Dashboard.tsx`: KPI row (`KpiCard`): Requests · $ Saved (+ saved %) · Escalation rate · Positive feedback rate · Learned-router share. Charts: `TierPie` (distribution), `QualityBar` (positive rate per tier), `SavingsLine` (7/14/30-day saved_usd + positive_rate dual axis). Latency p50/p95 table. Days selector + refresh.
- `Requests.tsx`: `DataTable` with filters (tier, escalated, feedback, source, search text), pagination, and a right-side detail drawer showing full prompt, full answer, features JSON, reason, cost breakdown, and feedback buttons (so you can label historic rows to grow training data).
- `TestLab.tsx`: pick suite + mode + limit → Run → live progress (poll or simple spinner) → results table with green/red `match` column → summary cards (routing accuracy, escalation rate, avg latency, $ saved %). "Run history" list from `/v1/testlab/runs`. Button "Compare Auto vs Large-only" that runs both and shows a two-column summary.
- `Settings.tsx`: tiers table (model, prices, reachable ✅/❌), editable confidence threshold slider, max escalations, reference prices, routing preference radio; **Retrain router** button showing accuracy/confusion result and last-trained info; **Health** panel (backend, Ollama, model file present).

```powershell
git add .
git commit -m "feat(frontend): dashboard, requests explorer, test lab and settings pages"
git push
```

---

## Phase 12 — Python SDK on PyPI (free)

**Goal:** `pip install smartroute-client` works for anyone.

- `sdk/pyproject.toml` (hatchling): name `smartroute-client` (if taken, use `smartroute-gateway-client`), version `0.1.0`, description, readme, MIT, author from header, `requires-python >=3.9`, dependency `httpx>=0.25`, `[project.scripts] smartroute = "smartroute_client.cli:main"`, project URLs → repo link.
- `src/smartroute_client/client.py`: `class SmartRoute(base_url="http://localhost:8000", api_key=None, source="sdk")` with `chat(messages | str, model="smartroute/auto", **kw) -> ChatResult` (dataclass: `content`, `tier`, `escalated`, `confidence`, `cost_usd`, `saved_usd`, `request_id`, `raw`), `feedback(request_id, good: bool, note=None)`, `stats(days=7)`, `health()`. Sync using `httpx.Client`; add `AsyncSmartRoute` mirror if it stays under ~60 lines.
- `src/smartroute_client/cli.py` (argparse): `smartroute health`, `smartroute chat "question" [--model]`, `smartroute bench [--mode auto|large] [--limit N]` (calls `/v1/testlab/run` and prints the summary table).
- `sdk/README.md`: install, 3-line usage, CLI examples, link to repo.
- `sdk/tests/test_client.py`: use `httpx.MockTransport` to test `chat()` parsing without a server.
- Root README: add "Install the client" section.

**Publishing (free):** create an account on https://pypi.org and https://test.pypi.org, generate an API token on each (scope: entire account for the first upload). Then:

```powershell
cd sdk
pip install build twine pytest
pytest -q
python -m build
# Test index first
python -m twine upload --repository testpypi dist/*    # username: __token__ , password: <TestPyPI token>
pip install --index-url https://test.pypi.org/simple/ --no-deps smartroute-client
# Real index
python -m twine upload dist/*                          # username: __token__ , password: <PyPI token>
cd ..
git add .
git commit -m "feat(sdk): smartroute-client python package and cli, published to pypi"
git tag v0.1.0
git push; git push --tags
```

> If the name is taken on PyPI, change `name` in `pyproject.toml` and the import path stays `smartroute_client`.

---

## Phase 13 — README polish, benchmark numbers, Docker (optional)

**Goal:** portfolio-ready repo.

- Run the benchmark and paste the table.
- Root `README.md` sections in order: banner line + badges (PyPI version, license, Python, Node) · **Why** (3 bullets: cost, latency, learns from feedback) · **Architecture** Mermaid diagram (`client/SDK → gateway → features → router(heuristic|learned) → tier small → confidence → escalate medium/large`; `feedback → trainer → learned router`; `log → stats → dashboard`) · **Quick start** (Ollama pull, backend, frontend, SDK) · **How routing works** (4 short paragraphs: features, heuristic, confidence cascade, learned policy) · **Benchmark** table · **Screenshots** (placeholders `docs/screenshots/*.png` — owner will add) · **API** table of endpoints · **Roadmap** (streaming SSE, semantic cache tier, A/B routing policies, more providers) · **License**.
- `docker-compose.yml`: `backend` (uvicorn) + `frontend` (vite build served by nginx); `OLLAMA_BASE_URL=http://host.docker.internal:11434`. Add `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf` proxying `/v1` to backend.
- Update `frontend/README.md` and `backend/README.md` to final state. Remove "in progress" badge.

```powershell
cd backend; .\.venv\Scripts\Activate.ps1; python scripts/benchmark.py; cd ..
git add .
git commit -m "docs: architecture, quick start, benchmark results and docker setup"
git push
```

---

## Stretch phases (only if the owner asks)

| # | Feature | Summary |
|---|---|---|
| S1 | Streaming | `stream=true` via SSE; routing decided before first token; SDK `chat(stream=True)` yields chunks. |
| S2 | Semantic cache tier | Tier 0 before `small`: `sentence-transformers` embedding + FAISS; return cached answer when cosine > 0.92; shows as tier `cache` everywhere. |
| S3 | Policy A/B | 50/50 heuristic vs learned, tagged per row; Dashboard compares positive rate per policy. |
| S4 | Auth | Optional `SMARTROUTE_API_KEY` env; bearer check on `/v1/*` except `/health`. |

---

## Definition of done (for the owner)

- [ ] `pip install smartroute-client` + 3 lines of code returns an answer with tier info.
- [ ] Playground shows tier, confidence, escalation, cost for every message; Compare-all works.
- [ ] Dashboard shows $ saved vs positive feedback rate with charts.
- [ ] Requests explorer lets me open any request and label it.
- [ ] Test Lab runs the 40-prompt suite and reports routing accuracy and $ saved %.
- [ ] Settings can change threshold and retrain the router from the UI.
- [ ] README has diagram, benchmark table, quick start, PyPI badge.
