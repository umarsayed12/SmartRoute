<!-- Record the approved hosted architecture, migration boundaries, and Neon setup procedure. -->
# SmartRoute Hosted Architecture

Approved on 2026-09-22. This document supersedes the original single-workspace
deployment assumptions. The original Phases 1-11 remain a working local prototype.

## Product Contract

SmartRoute supplies routing, tracking, and a management UI. Users supply model
access and pay their own inference provider. Each authenticated user initially
owns one private workspace. At least one enabled model must be configured before
chat or Test Lab runs are accepted. There are no shared hosted Ollama defaults.

The website provides login, model configuration, request inspection, feedback,
statistics, training controls, and an Integration page. The Integration page will
show the installation command and a one-time gateway API key only after the SDK
is actually published. Do not advertise a package as installable before publication.

The SDK calls the backend, not the browser app. Its API key identifies a workspace.
Provider configuration can be managed through the website or explicit SDK setup
methods; routine chat calls reference saved models rather than repeatedly changing
configuration as an initialization side effect.

## Target Flow

```mermaid
flowchart LR
    User[Developer] --> Web[React workspace]
    Web --> Auth[Neon managed auth]
    Auth --> Identity[Verified identity]
    Identity --> API[FastAPI authorization]
    Client[Developer application and SDK] -->|SmartRoute API key| API
    API --> Tenant[Private workspace context]
    Tenant --> Router[Heuristic or workspace-trained router]
    Router --> Providers[User-owned OpenAI or Anthropic models]
    Providers --> Check[Provider-aware confidence and escalation]
    Check --> Usage[All answer and self-check attempts]
    Usage --> DB[Neon Postgres]
    Tenant --> DB
    DB --> Web
```

## Security Boundaries

- Website sessions are managed by Neon. Backend identity must be verified with
  the configured branch's trusted signing keys/claims, never a browser-supplied
  user ID. Confirm issuer, audience, token expiry, and key-rotation behavior with
  the configured service before implementing token verification.
- API keys are random high-entropy values. Store only their SHA-256 hash, prefix,
  workspace, creation/expiry/last-use timestamps, and revocation state. Show the
  plaintext once. A gateway key is different from an OpenAI/Anthropic key.
- Provider keys are encrypted with authenticated encryption using a server-only
  secret kept outside Neon. The encrypted payload includes workspace and provider
  identity, so moving ciphertext between tenants/providers fails validation.
  Never return plaintext or ciphertext from list/read APIs.
- Workspace context comes from verified identity or a valid gateway key. All
  request, feedback, settings, model, key, training, and run operations require
  that context. Do not expose unscoped repository functions on hosted routes.
- Browser auth and SDK keys have separate permissions. Browser-authenticated
  owners manage keys and provider configuration; ordinary gateway keys do not
  automatically grant every administrative action.
- SQL tenant filters, cross-workspace foreign-key checks, and dedicated runtime
  role/RLS verification are required before public deployment. Schema ownership
  alone is not tenant isolation, and Neon owner roles may bypass RLS.
- Application tables live in `smartroute`; managed identity tables stay in
  `neon_auth`. Do not modify Neon's managed schema or expose application tables
  through the Data API during this migration.
- OpenAI and Anthropic use fixed server-controlled API roots initially. Arbitrary
  URLs, redirects to internal networks, user-supplied proxies, and laptop localhost
  access are out of scope. This avoids introducing a public SSRF proxy.
- Full prompts and answers are sensitive workspace data. Define retention and
  deletion, redact credentials from logs, and disclose backend/provider processing.

## Data Model

| Table | Purpose |
| --- | --- |
| `users` | Verified identity reference and application profile; no passwords |
| `workspaces` | One private workspace per owner; default free plan |
| `api_keys` | Hashed gateway keys and revocation/usage metadata |
| `provider_credentials` | Workspace-bound encrypted OpenAI/Anthropic keys |
| `models` | Owned credential reference, logical tier, model ID, prices, enabled flag |
| `workspace_settings` | Per-workspace confidence, escalation, reference pricing, and routing policy |
| `requests` | Workspace-scoped conversation, final response, routing and cost summary |
| `request_attempts` | Every answer and self-check's provider, model, usage, cost, and timing |
| `testlab_runs` | Workspace-scoped run summaries and result references |
| `router_models` | Per-workspace trusted classifier artifact, feature order, and metadata |

The provider-credential and request-attempt relationships include `workspace_id`
in their foreign keys. All runtime reads and writes still need authorization;
these constraints prevent incorrect references but do not replace tenant filters.
The `premium` plan value is reserved for future use; there is no payment system or
automatic charge for SmartRoute in this version.

## Model And Routing Changes

Users configure one to three logical tiers. A tier is a routing role, not a
claim about a vendor model's size or price. One model permits tracking but no
meaningful cross-model selection. Missing tiers never use the owner's credentials
or the historical local Qwen installation.

Forced routing must identify a configured, enabled tier or return a setup error.
Auto routing resolves its predicted tier among the workspace's enabled models
and explains any resolution in metadata. Native Anthropic request/response parsing
is required; Anthropic is not assumed to implement OpenAI's chat API.

Confidence checks must use the selected provider adapter, rather than always
calling Ollama. Cost and quota accounting include auxiliary self-checks and every
escalation attempt. Store reported token categories and distinguish estimates from
provider invoices, including cached-token pricing where applicable. Reference cost
is hypothetical; neither routing confidence nor tier-match accuracy guarantees
answer correctness.

Feedback trains only that workspace's routing classifier, not a base language
model. Do not load another tenant's local joblib file or use a shared training set.
Server-generated classifier artifacts remain trusted internal data, not uploads.

## Neon Setup

Use a development branch of the selected Neon project. Enable managed Auth in an
AWS region and configure email/password. Add `http://127.0.0.1:5173` and
`http://localhost:5173` as local trusted origins. Production domains, email
verification, session behavior, and recovery URLs are deployment checks, not
assumptions inherited from localhost.

Append the fields from [backend/.env.hosted.example](../backend/.env.hosted.example)
to the existing ignored backend environment file without replacing existing values:

- `DATABASE_URL`: pooled application connection, with TLS required.
- `DATABASE_DIRECT_URL`: direct migration connection for the same branch/database.
- `NEON_AUTH_BASE_URL`: public Auth Base URL from that branch's Auth configuration.
- `PROVIDER_ENCRYPTION_KEY`: server-only encryption key, generated locally below.
- `APP_MODE=local`: retain the prototype while hosted cutover is incomplete.

Never paste connection strings, passwords, bearer tokens, or encryption keys into
assistant chat. Never put database credentials or the encryption key in `VITE_*`
variables. The frontend will receive only the public auth URL and API root.

From `backend/`, with dependencies installed:

```powershell
.\.venv\Scripts\python.exe -m app.hosted.setup derive-direct-url
.\.venv\Scripts\python.exe -m app.hosted.setup check
.\.venv\Scripts\python.exe -m app.hosted.setup generate-key
.\.venv\Scripts\python.exe -m app.hosted.migrate upgrade
.\.venv\Scripts\python.exe -m app.hosted.migrate check
.\.venv\Scripts\python.exe -m app.hosted.migrate current
```

`derive-direct-url` is optional and fills a missing direct URL only for a standard
Neon pooler hostname. `check` uses read-only queries and reports booleans, including
the presence of `neon_auth`; it does not prove a real login or JWT verification.
`generate-key` writes directly to the ignored environment file and does not rotate
an existing key. Back up that key in trusted deployment secret storage: losing it
means saved provider credentials cannot be decrypted.

Migrations target only `smartroute`, use the direct connection, and never run as an
automatic web-server startup side effect. Review each generated revision before
applying it. Keep immutable migration files in Git, but not credentials or database
dumps. The small application pool uses pooled connections and transaction-scoped
work; no request depends on PgBouncer retaining session settings.

## Migration Checkpoints

### M1: Foundation

Neon setup and direct/pooled verification, versioned schema, secret-handling
primitives, isolated tests, and updated documentation. The initial migration is
`0001_neon_foundation`. No HTTP route is moved to the new tables yet. Existing
SQLite data, file settings, and local model artifacts remain untouched.

`APP_MODE=hosted` deliberately fails startup at this checkpoint. The old HTTP app
is still unauthenticated and local-only. Do not describe it as safe to deploy just
because Neon tables and encryption helpers exist.

### M2: Identity And Isolation

Add custom login/signup/recovery screens using the managed auth SDK; verify backend
identity; provision one private workspace; create/list/revoke scoped SDK keys;
introduce workspace-required repositories and migrate history, feedback, settings,
stats, run history, and training access. Prove cross-user denial, expired/revoked
credential denial, and safe authorization on every route before any hosted access.

### M3: Bring Your Own Models

Add workspace model/credential APIs, OpenAI and native Anthropic providers,
provider-aware confidence, owned model resolution, and attempt-level metering.
Reject unconfigured routing and never fall back to a shared owner-funded model.
Test provider errors, redaction, key replacement, and credential ownership.

### M4: Onboarding And SDK

Complete website model setup, key management, Integration instructions, and the
httpx-based Python client/CLI. Use gateway keys for identity and explicit setup
methods for saved provider configurations. Test a new account through model setup,
SDK chat, private history, feedback, and key revocation. Do not publish misleading
installation instructions before the package is available.

### M5: Public Deployment Gate

Verify least-privilege database access/RLS behavior, account/workspace isolation,
auth origins and recovery flows, rate limits, concurrency limits, prompt/token
limits, request timeouts, retention, secret rotation, and cost attribution. Define
single-process versus distributed limit enforcement explicitly. Add deployment
configuration, final architecture docs, and SDK publishing. Lift the hosted-mode
guard only after these gates pass.

No automatic import of shared local logs is planned. If wanted later, an explicit
owner-confirmed migration must assign every imported row to one workspace and
must never assign data based on unverified email addresses.

## Current Reference Documentation

- [Neon managed authentication](https://neon.com/docs/auth/overview)
- [React authentication API quick start](https://neon.com/docs/auth/quick-start/react)
- [Authentication flow](https://neon.com/docs/auth/authentication-flow)
- [Pooled and direct connections](https://neon.com/docs/connect/connection-pooling)

Service availability and free-plan allowances can change. Verify current provider
terms at deployment; a free SmartRoute plan does not make model inference or
hosting infrastructure free.