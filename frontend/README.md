<!-- Setup and behavior notes for the SmartRoute frontend workspace. -->
# SmartRoute Frontend

**Hosted migration:** the existing screens remain the local prototype. Managed
login, private workspace onboarding, saved provider-model configuration, and an
Integration page are upcoming checkpoints in the
[hosted architecture plan](../docs/HOSTED_ARCHITECTURE.md). The current UI is not
an authenticated multi-user deployment.

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

## Playground

- Auto, forced small/medium/large, and Compare all modes use the real gateway.
- Enter sends; Shift+Enter inserts a newline. Empty prompts are not submitted.
- Each response shows its actual model/tier, escalation or fallback, confidence,
  total routing latency, token counts, actual/reference costs, and routing reason.
- Compare all sends the same conversation to each forced tier sequentially.
  Choose one successful answer before sending a follow-up; other answers are
  not silently merged into the conversation. If large is disabled, the actual
  medium fallback is shown instead of claiming a large-model result.
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
`lint: frontend`. The build runs TypeScript and produces `dist/`; lint uses the
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

Production serving must route SPA URLs to `index.html` and proxy API traffic to
the backend. Production hosting and Docker configuration belong to Phase 13.
