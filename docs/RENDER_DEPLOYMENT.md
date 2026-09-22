<!-- Deploy the compiled frontend and authenticated API as one gated Render Docker service. -->
# Render Deployment

Deploy the web app first; production PyPI publishing comes afterward. The repository
now contains the single-service deployment code, but **the service has not been
deployed or certified against live Neon/provider accounts**. Previously exposed
credentials have not yet been rotated. Keep release approval disabled until the
preparation steps below are complete.

## What Runs

The root Dockerfile builds React with Node 24 and copies its output into
`backend/static`. One non-root Python 3.11 process serves both the compiled site
and the authenticated API on Render's `PORT`. No second frontend service, Vite
development server, Ollama installation, or Jinja template engine is needed.

The server returns the SPA shell for `/`, `/dashboard`, `/requests`, `/testlab`,
`/settings`, `/models`, `/account`, `/integration`, and `/reset-password`, including direct navigation
and browser refresh. Unknown API routes and missing assets stay 404; they never
receive the SPA HTML. Hashed assets are cacheable, HTML is revalidated, and API
responses are not cached. Add future client page routes to `app.web.PAGE_ROUTES`.

The Integration page and SDK use the same public HTTPS origin as the browser.
The browser never receives database credentials or the provider-encryption key.
Neon stores profiles, encrypted provider credentials, history, keys, and classifiers.
Nothing persistent depends on Render's local filesystem.

## Before Deploying

1. **Rotate the exposed database password and provider credentials.** Update every
   legitimate consumer privately, remove stale copies, and verify old credentials
   no longer work. Do not reuse the values previously shared in chat/attachments.
2. **Coordinate provider-encryption key rotation.** Simply replacing the Fernet key
   makes existing ciphertext unreadable. For an early workspace, each owner can
   explicitly delete their saved credentials in Models, which also deletes linked
   tier mappings, then re-add rotated provider keys after a new encryption key is
   installed. Historical request rows are preserved. With multiple existing users,
   use a reviewed re-encryption maintenance process instead; no automatic rotation
   is performed by this deploy. Never silently delete other users' configuration.
3. Back up the intended database and record the encryption key securely. Choose the
   production Neon branch deliberately; database URLs, Auth Base URL, issuer, and
   audience must all refer to that environment. Do not enable the browser Data API.
4. Require the repository's **Validate deployment** CI workflow to pass, including
   the real PostgreSQL policy test and Docker image build. Local checks alone do
   not prove those two gates on this managed laptop.
5. Review the retention and usage limits below, the managed-auth JWT lifetime,
   verification delivery, and recovery flow. Browser logout does not necessarily
   invalidate an already-issued JWT immediately. Gateway keys have their own
   expiry/revocation lifecycle and must be revoked separately when deprovisioning
   an account. Do not advertise immediate global session revocation.

Use an organization-approved machine/network for any installation or database
maintenance. Do not disable TLS checks or bypass managed-device restrictions.

## Prepare Neon

### Apply The Migration

Use the reviewed checkout on an approved machine. Configure the **rotated direct
migration-owner URL** privately for that process, not in Render. After installing
backend requirements into its development environment, run from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m app.hosted.migrate upgrade
if ($LASTEXITCODE -ne 0) { throw 'Migration failed.' }
.\.venv\Scripts\python.exe -m app.hosted.migrate current
.\.venv\Scripts\python.exe -m app.hosted.migrate check
```

The expected new head is `0003_tenant_policies`. This migration is provided in the
repository but **has not been applied to the live Neon database by the agent**.
It enables workspace row policies for provider credentials, models, settings,
requests, attempts, Test Lab runs, and classifiers. Existing columns/data are retained.

### Create The Runtime Role

As the migration owner in Neon's SQL Editor, review and run
[runtime_role.sql](../backend/scripts/runtime_role.sql). It creates
`smartroute_runtime` with no owner/superuser/bypass role attributes and grants
application DML plus only the managed-auth profile columns needed for verification.
It does not alter or delete managed auth tables. Set/reset this role's password
privately through Neon. Do not grant it `neon_superuser` or migration-owner membership.

If a role with that name already exists, inspect its attributes and memberships;
the script does not silently take ownership of or replace an existing role. Fix
unsafe privileges instead of disabling the startup check.

Copy the **pooled TLS connection string for `smartroute_runtime`** into Render's
`DATABASE_URL`. Do not deploy the migration-owner connection string. User/workspace
bootstrap metadata and hashed gateway-key lookup necessarily happen before tenant
resolution; those three bootstrap tables retain explicit application tenant filters.
Private data tables additionally use transaction-local RLS context, cleared on pool
reuse. This is defense against missing tenant predicates, not against theft of the
backend's database credentials or arbitrary SQL execution in the server.

Optionally verify the runtime URL from an approved machine before Render startup.
This command reads only process environment, not the backend environment file:

```powershell
$secureDatabase = Read-Host 'Rotated runtime pooled DATABASE_URL' -AsSecureString
$env:DATABASE_URL = [System.Net.NetworkCredential]::new('', $secureDatabase).Password
try {
    .\.venv\Scripts\python.exe -m app.hosted.access
    if ($LASTEXITCODE -ne 0) { throw 'Runtime database checks failed.' }
} finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Variable secureDatabase -ErrorAction SilentlyContinue
}
```

Do not use the migration role for this check. Public startup repeats it and refuses
owner/bypass roles, missing tenant policies, or unscoped reads of private data.

## Render Service

Either import the root [render.yaml](../render.yaml) as a Render Blueprint, or create
**New > Web Service** from the connected GitHub repository with these settings:

| Setting | Value |
| --- | --- |
| Branch | `main`, after Validate deployment passes |
| Language/runtime | **Docker** |
| Root Directory | Leave empty: repository root |
| Dockerfile Path | `./Dockerfile` |
| Docker Build Context | `.` |
| Docker Command | Leave empty: use the image's command |
| Health Check Path | `/health` |
| Region | Singapore is the supplied default; choose near the selected Neon region |
| Instances/workers | Exactly one instance and one worker |
| Auto Deploy | Off during setup; optionally checks-pass afterward |
| Build/Start Commands | No separate commands for a Docker service |

Do not set Root Directory to `backend`; Docker needs both frontend and backend
sources. Do not add a Render static-site `/* -> /index.html` rewrite. FastAPI already
handles the page routes and preserves API status codes.

The Blueprint intentionally sets `HOSTED_RELEASE_APPROVED=false`. Initial startup
will fail closed until preparation is complete; this is not a missing-port bug.
Once the assigned Render URL is known, add that exact HTTPS origin to **Neon Auth
Configuration > Domains**. Test signup, verification, and password recovery against
that environment during the controlled launch. Only then open access to users.

After rotation, CI, migration, role checks, and auth-origin configuration are ready,
set `HOSTED_RELEASE_APPROVED=true` in the Render environment and manually deploy.
Approval is an operator acknowledgement, not proof that an external provider has
been tested. A Blueprint resync can restore its deliberately disabled default;
review the flag on resync. Never switch to `local` or `preview` to bypass a failure.

## Render Environment

Enter secret values only in Render's environment settings, without surrounding
quotes. The Docker build never consumes secret build arguments.

| Variable | Required value |
| --- | --- |
| `APP_MODE` | `hosted` |
| `HOSTED_RELEASE_APPROVED` | `false` during preparation; `true` only after the launch checklist |
| `DATABASE_URL` | Rotated **pooled** Neon URL for `smartroute_runtime`, requiring TLS |
| `NEON_AUTH_BASE_URL` | Public HTTPS Auth Base URL for the same Neon environment |
| `NEON_AUTH_ISSUER` | Exact verified JWT issuer; the existing managed-auth setup uses its HTTPS origin, not the Render origin |
| `NEON_AUTH_AUDIENCE` | Exact verified JWT audience, not a guessed value |
| `NEON_AUTH_ALGORITHM` | `EdDSA` for the currently verified service configuration |
| `PROVIDER_ENCRYPTION_KEY` | Valid Fernet key matching saved ciphertext, after coordinated rotation |
| `PUBLIC_BASE_URL` | Optional override for the canonical HTTPS origin, especially a custom domain; no path/query |

Without `PUBLIC_BASE_URL`, the app uses Render's automatic `RENDER_EXTERNAL_URL`.
Render also supplies `PORT`; the process binds `0.0.0.0:$PORT` automatically. Do
not set port 8000 manually. For custom domains, configure the same canonical
origin in Render, `PUBLIC_BASE_URL`, and Neon Auth; SDKs should use that origin.
Other Host/Origin values are rejected instead of trusting forwarded headers.

Do **not** set `DATABASE_DIRECT_URL` on the web service; public startup explicitly
rejects it. Also omit `DATABASE_URL_POOLED`, `OLLAMA_BASE_URL`, `LARGE_API_KEY`,
shared OpenAI/Anthropic keys, `VITE_*` secrets, `SMARTROUTE_API_KEY`, and PyPI tokens.
Provider keys belong to each user's Models configuration, not Render's shared env.

Optional operating limits (the supplied defaults are conservative demo settings):

| Variable | Default |
| --- | --- |
| `REQUEST_MAX_BYTES` | `524288` |
| `REQUEST_TIMEOUT_SECONDS` | `180` |
| `WORKSPACE_REQUESTS_PER_MINUTE` | `120` |
| `GLOBAL_REQUESTS_PER_MINUTE` | `600` |
| `WORKSPACE_INFERENCES_PER_DAY` | `100` recorded requests in a rolling 24-hour window |
| `WORKSPACE_HISTORY_LIMIT` | `1000` retained requests; generation pauses at the cap |
| `REQUEST_RETENTION_DAYS` | `30` |

Rate counters and active-operation locks are per-process and reset on restart;
they are not distributed or financial spending guarantees. Deploy overlaps may
temporarily run two versions. Do not scale out without shared rate limits and
transactional quota reservations. Daily/history checks use persisted request rows.
Failures with unknown provider charges are not treated as free.

Retention deletes old request rows, cascaded attempts, and Test Lab summaries at
startup and hourly while running. On a sleeping free instance it resumes on wake,
so expiry is not an exact wall-clock deletion SLA. Review the policy before enabling
it on existing data. Provider settings, API-key metadata, and trained classifier
artifacts are not deleted by history retention. Operator-managed backups have their
own retention. Account erasure and exceptional data deletion require an authenticated
owner request and coordinated operator cleanup, including key revocation.

## Launch Verification

1. Require a successful Render Docker build and public database readiness check.
   No owner URL, environment file, or private experiment belongs in the image.
2. Open the HTTPS service URL; test login/signup, email verification, recovery, and
   logout. Check the browser console for blocked auth/CSP requests. Do not disable
   origin or token validation to make login pass.
3. Navigate to and refresh every page, especially `/requests`, `/models`, and
   `/integration`. Verify assets load and a request to `/v1/missing` returns JSON
   404 rather than SPA HTML. Public `/docs` and `/openapi.json` are intentionally off.
4. Configure an official provider and enabled model in the web workspace. Issue a
   gateway key, use the source SDK against the same HTTPS origin, and make one
   small generation only after approving its provider charges.
5. Match the SDK request ID to the web Requests row, attempts, costs, and feedback.
   Verify another workspace cannot access it and revocation makes the next SDK
   call return 401. See [SDK acceptance](../sdk/README.md#deployment-acceptance).
6. Exercise invalid/expired credentials, provider errors, limits, and timeouts.
   Inspect recorded attempts before retrying uncertain inference. Test Lab can be
   interrupted by the total deadline and retain partial request history.
7. Confirm a restart preserves Neon-backed configuration/history and disclose the
   retention policy and backend/provider handling of prompts to users.

The current local checks exercise mocked providers. Docker/real PostgreSQL CI,
live Neon grants, public-domain auth/recovery, and real provider generation are
distinct gates; do not mark them passed based on a local build or this document.

## Free Tier Caveats

Render currently documents 0.1 CPU/512 MB for Free, sleep after 15 idle minutes,
roughly a minute to wake, 750 shared free-instance hours/month, ephemeral disk,
and no free shell/one-off jobs. High external database/API traffic can cause
suspension. Limits can change; review the linked provider docs before launch.

Use Free for a demo, not an always-on production promise. Cold starts can return
a platform loading/error response before the app is ready; SDK users should first
check non-billable health/workspace access. Do not add automatic generation retries
or keep-alive traffic to disguise the limitation. Use paid compute for dependable
availability after approving its cost. This blueprint provisions no paid resources.

References: [Render Docker](https://render.com/docs/docker),
[web services](https://render.com/docs/web-services),
[free limits](https://render.com/docs/free),
[Blueprint fields](https://render.com/docs/blueprint-spec).