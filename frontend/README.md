<!-- Setup and behavior notes for the SmartRoute frontend workspace. -->
# SmartRoute Frontend

**Hosted migration:** the UI detects the backend mode through `/v1/client-config`.
The default backend retains the local prototype. An authenticated preview adds
managed login/signup/recovery, a private workspace, sign-out, and API-key creation
and revocation, encrypted provider credentials, and owned model configuration/routing.
M4 adds setup gating and an Integration page for the source SDK/CLI. Public deployment
and registry publication remain M5 work in the
[hosted architecture plan](../docs/HOSTED_ARCHITECTURE.md). Neither development
mode is a public-production deployment.

React 18, TypeScript, Vite, and CSS Modules. Phase 11 provides the Playground,
Dashboard, Requests explorer, Test Lab, and Settings using real gateway APIs.
Views load on demand and display explicit loading, empty, and error states.

## Run (Windows PowerShell)

Use Node 22.12+ or a current Node 24 release. Start the backend at
`http://127.0.0.1:8000` using the [backend instructions](../backend/README.md),
with Ollama and both local models available.

From the repository root:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open the URL printed by Vite, normally <http://127.0.0.1:5173>.
Vite proxies `/v1` and `/health` to the local backend. No browser API key is
needed. Never place provider secrets in frontend environment variables or code.
Commands use `npm.cmd` to avoid PowerShell execution-policy restrictions.

For the authenticated preview, run the backend on port 8001 using the architecture
guide, then set `$env:SMARTROUTE_BACKEND_URL="http://127.0.0.1:8001"` before starting
Vite on port 5174. Open `http://localhost:5174`, which matches Neon's pre-approved
localhost origin behavior. Provider secrets and database URLs never enter frontend
configuration. The pinned `@neondatabase/auth` headless adapter is used without
importing its optional UI framework. Upstream UI dependencies currently have
conflicting peer requirements, so the project-local `.npmrc` uses
`legacy-peer-deps=true` for consistent install/CI behavior. Do not remove that flag
without regenerating and validating the lockfile. The headless runtime, application
build, and lint are independently checked; revisit the workaround when the SDK
dependency graph is corrected upstream.

API key plaintext is shown once in a masked field and discarded on dismissal or
navigation. It is not written to application localStorage. Session tokens are
managed by Neon's SDK and forwarded in authorization headers. Never put actual
credentials into screenshots or bug reports. Browser auth tests use synthetic
credentials; real verification requires entering credentials directly in the browser.

For code-based email verification, open **API Keys**, enter the emailed value in
**Verification code**, and choose **Verify code**. **Send new code** requests a
replacement through Neon's email-OTP API. The backend profile is refreshed after
successful verification; key creation remains disabled until that profile confirms
the email is verified. Codes stay in component memory and are cleared on success.
Do not paste verification codes into assistant chat or issue reports.

## Workspace Models

In authenticated preview, verified owners use **Models** to save an official
OpenAI or Anthropic credential, then assign a model to small, medium, or large.
Input/output prices are required in USD per 1,000 tokens, including an explicit
zero when appropriate. These are estimates, not live provider price discovery.
Disable **Send temperature** for models that reject it; Anthropic values above
1 are capped at 1. The self-check budget defaults to 256 tokens and is configurable
from 32 to 1024. Higher budgets can incur additional provider charges.

Keys stay masked while being entered, clear after saving, and are never fetched
back. Lists show only metadata and suffixes. Rotation preserves tier references;
confirmed credential deletion also removes its tiers. Tiers can be edited,
disabled, or removed independently. Historical requests are preserved.

Hosted forced routing to a missing/disabled tier returns a setup error, never
a medium or shared-model fallback. Auto resolves only among enabled owned tiers.
Availability refreshes every 30 seconds or with the sidebar refresh control.
Gateway keys can call those models but cannot manage their credentials/configuration.

## Onboarding And Integration

In preview, Playground and Test Lab first show email verification or owned-model
setup when required. Model reads are distinct from availability probes; saving,
disabling, or removing a tier refreshes readiness immediately. Transient polling
errors do not erase an already-ready chat. The backend still independently enforces
verification, ownership, model configuration, and capacity.

**Integration** shows email/model readiness, active unexpired/unrevoked gateway-key
count, and SDK request activity, with links to the owning pages. Copy controls provide
the same-origin gateway URL and source-install/client examples for Python or CLI,
with PowerShell/Bash commands. No actual gateway/provider key or session token is
embedded in snippets. Keys are still created and displayed once only in API Keys.
The page explicitly marks the SDK as unpublished and never suggests a registry install.

## Playground

- Auto, forced small/medium/large, and Compare all modes use the real gateway.
- Enter sends; Shift+Enter inserts a newline. Empty prompts are not submitted.
- Each response shows its actual model/tier, escalation or fallback, confidence,
  total routing latency, token counts, actual/reference costs, and routing reason.
- Compare all sends the same conversation to each forced tier sequentially.
  Choose one successful answer before sending a follow-up; other answers are
  not silently merged into the conversation. In local mode, disabled large uses
  the actual medium fallback. In preview, unconfigured forced tiers return errors.
- Positive feedback is submitted immediately. Negative feedback offers an
  optional note; both rating controls lock after successful submission.
  Failed feedback stays retryable and shows the backend error.
- Copy uses the browser clipboard API. Markdown is rendered without executing
  raw HTML or loading model-supplied images; code blocks scroll independently.
- Clear chat removes only the in-memory browser conversation, not backend logs.
  Stop waiting aborts the browser request and ignores late responses, but cannot
  guarantee that already-started backend inference is cancelled.
- Errors are shown per answer, and an entirely failed turn can be retried.
  Switching navigation views preserves the session; reloading the page clears it.

Every API helper sends `X-SmartRoute-Source: playground`. All existing backend
endpoints have typed helpers in [src/api.ts](src/api.ts) and matching contracts
in [src/types.ts](src/types.ts). Model and gateway availability refresh every
30 seconds or through the sidebar refresh control.

Confidence is a routing signal, not a calibrated correctness probability.
The highest available backend tier reports 1.0 by convention. Reference costs
are hypothetical configured premium costs; local Ollama usage is free.

## Dashboard, Requests, Test Lab, And Settings

- Dashboard offers 7/14/30-day KPIs, tier distribution, feedback by tier, a
  dual-axis savings/feedback timeline, and latency percentiles. Unrated quality
  and missing latency remain N/A rather than being presented as zero quality.
- Requests filters by final tier, escalation, rating, source, and submitted
  search text. Page size and previous/next controls use server pagination.
  Open a prompt to inspect its full conversation, answer, feature JSON, routing
  reason, token counts, and costs. The native modal drawer closes with Escape
  or its close control and supports replacing historical feedback with a note.
  Preview records also show completed/failed status and each provider attempt,
  including self-checks, safe error codes, raw reported usage, and estimated cost.
  Missing usage/cost is shown as Unknown; failed requests have no savings or
  feedback controls. Dashboard aggregates cover completed requests only, not
  total provider invoice spend. Standard-rate estimates do not apply cache discounts.
- Test Lab selects a suite, mode, and prefix limit. Runs show a spinner rather
  than fabricated per-prompt progress. Auto-vs-Large comparisons run sequentially,
  retain completed results if the other mode fails, and show separate summaries
  and result tabs. Each result opens its logged request. Run history is paginated.
  In-progress run state survives sidebar navigation; reloading the browser can
  lose the local result view, so inspect history before retrying an uncertain run.
- Settings shows model availability/prices, a confidence slider, escalation
  budget, reference prices, policy preference, and health including actual model
  file presence. Save persists validated changes; reset discards only unsaved
  edits. Retraining displays the real outcome, class-ordered confusion matrix,
  evaluation type, and last-trained time. Insufficient data stays an explicit
  result, not a successful training claim.

Source filtering and `model_file_present` in `/health` require the Phase 11
backend. Settings and feedback actions change backend data; the browser itself
does not store provider credentials. The health/model-list endpoint does not
perform inference. A present model file is not the same as a validated training
report or a guarantee of prediction quality.

## Validation

```powershell
npm.cmd run build
npm.cmd run lint
```

The same commands are available as the VS Code tasks `build: frontend` and
`lint: frontend`. The build runs TypeScript and produces `../backend/static/`; lint uses the
scaffold's Oxlint configuration. The React Compiler is not enabled. Fonts (Manrope
and JetBrains Mono) are served locally through Fontsource packages. Icons use
Lucide, and Recharts is installed for the next phase's dashboard.

Browser verification covers desktop/mobile layout, live chat, sequential compare
payloads, answer selection, feedback, errors, cancellation, clear, and keyboard
input. Phase 11 checks also cover charts and empty periods, query filters,
pagination, drawer inspection, historical feedback, settings validation and save
retry, training results, sequential Test Lab comparison, and responsive tables.
Mocked browser responses are used for deterministic writes and failure cases so
test ratings and settings do not alter real backend data.

The backend now serves the compiled SPA and its assets from the same origin as
the API. Known page URLs work on direct navigation and refresh; missing assets and
API routes stay 404. Public mode hides the development API-reference link and
shows configured request retention in Settings. No frontend environment secrets
or separate Render static-site rewrites are needed. Follow the
[Render deployment guide](../docs/RENDER_DEPLOYMENT.md) before enabling public mode. M3
browser checks use synthetic auth/provider responses, including credential
rotation/deletion, explicit model prices, verification gating, mobile layout,
and failed-attempt details. No live paid OpenAI/Anthropic call was used for this checkpoint.
