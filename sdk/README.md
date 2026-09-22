<!-- Explain source installation, authenticated SDK/CLI usage, and owner-only model setup. -->
# SmartRoute Python SDK

SmartRoute provides a synchronous, text-only Python client and CLI for a separately
running SmartRoute gateway. Requires Python 3.11+; `httpx` is the only runtime
dependency. Streaming is not supported. Installing this package does not deploy
the gateway, supply provider credentials, or create a hosted account.

The 0.1.0 preview is on TestPyPI. Production registry availability and hosted-service
readiness are separate checks; neither is implied by a successful TestPyPI upload.
See the [release procedure](https://github.com/umarsayed12/SmartRoute/blob/main/docs/HOSTED_ARCHITECTURE.md#manual-sdk-publishing)
for production publishing and the required deployment acceptance checks.

## TestPyPI Preview

Preview release: <https://test.pypi.org/project/smartroute-client/0.1.0/>.
TestPyPI is a separate testing registry, not a production distribution channel;
its projects may be removed. Installing a public package requires no upload token.

From the repository root, create an isolated environment, install dependencies
from production PyPI, and install only this SDK from TestPyPI:

```powershell
.\backend\.venv\Scripts\python.exe -m venv sdk/.venv
.\sdk\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple "httpx>=0.27,<1"
.\sdk\.venv\Scripts\python.exe -m pip install --index-url https://test.pypi.org/simple/ --no-deps smartroute-client==0.1.0
.\sdk\.venv\Scripts\smartroute.exe --help
```

Do not add TestPyPI as an extra dependency index. `--no-deps` keeps dependencies
on production PyPI; it does not remove the need to install `httpx` first. These
commands do not call an inference provider or publish anything. The test environment
is ignored by Git. Clean TestPyPI installation has not been verified on the managed
development laptop because registry downloads are blocked. Use an organization-approved
machine/network or ask IT to enable the official package hosts. Do not bypass policy,
disable certificate verification, or use an unapproved mirror to work around the block.

Uploaded distribution files are immutable. Documentation edits in this repository
do not change the already-uploaded README or wheel; replacing an artifact on the
same registry requires a new version. TestPyPI and production PyPI have independent
namespaces, so a TestPyPI version does not itself prevent its first production upload.
Keep publishing tokens out of application environment files, source code,
chat attachments, and screenshots. Revoke exposed tokens before using them again.

## Production Installation

Run this only after the maintainer confirms that the version exists under the
correct owner at <https://pypi.org/project/smartroute-client/>. An absent project
page does not guarantee that PyPI will accept the name. The current release target
is 0.1.0; use the actual published version if it changes.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple smartroute-client==0.1.0
.\.venv\Scripts\smartroute.exe --help
```

Production installs resolve `httpx` automatically from PyPI. Do not use `--no-deps`
or TestPyPI for ordinary end-user installation. No PyPI upload token is needed to
install a public package. On macOS/Linux, create the environment with `python3`
and use `.venv/bin/python` and `.venv/bin/smartroute`.

## Install From Source

From a checkout of this repository, using Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ./sdk
.\.venv\Scripts\smartroute.exe --help
```

On macOS/Linux use `.venv/bin/python` and `.venv/bin/smartroute`. No shell
activation is required. This is a source install, not a claim that the package
name is available on production PyPI. Production name availability and publication
are M5 gates.

## Prepare A Workspace

1. Start the [authenticated preview](../docs/HOSTED_ARCHITECTURE.md#run-the-preview),
   sign in at `http://localhost:5174`, and verify your email in **API Keys**.
2. In **Models**, save an official OpenAI or Anthropic credential and configure at
   least one enabled tier with explicit USD input/output prices per 1,000 tokens.
3. In **API Keys**, create a SmartRoute gateway key and retain its one-time value
   in your application's secret storage. It is not your provider key.
4. Open **Integration** for the current gateway URL, source-install commands,
   Python/CLI examples, active-key count, and SDK request activity.

After public deployment passes its security gates, use the deployed web workspace
instead of localhost for these account/model/key steps. Each application needs its
own workspace's gateway key. End users do not need to run Ollama, clone this repository,
install backend dependencies, or configure Neon directly when using that deployed service.

The preview gateway can be reached directly at `http://localhost:8001`, or through
Vite at `http://localhost:5174`. Neither is a public deployment. Public URLs must
use HTTPS; the SDK permits HTTP only for localhost/loopback. URL user information,
query strings, and fragments are rejected. Roots with or without `/v1` work.

## Connect To Deployment

Set `SMARTROUTE_BASE_URL` to the canonical **HTTPS gateway root**, not the Neon Auth
URL, a model-provider URL, or a frontend URL that only serves HTML. The SDK appends
`/v1/chat/completions` and the other API paths itself. Do not use the full chat URL
as the root. The API must accept bearer gateway keys without interactive login redirects.

The current Integration page copies the web origin. For those examples to work
unchanged, that origin must proxy `/v1/*` and `/health` to the same authenticated
backend used by the browser. A split frontend/API deployment must instead supply
the API origin explicitly and update the Integration/bootstrap configuration before
launch. A SPA catch-all must not turn API errors into `index.html` responses.

For a manual check, enter the gateway URL and key directly in your terminal:

```powershell
$env:SMARTROUTE_BASE_URL = Read-Host 'Deployed HTTPS gateway root'
$secureKey = Read-Host 'SmartRoute gateway key' -AsSecureString
$env:SMARTROUTE_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password
try {
	 .\.venv\Scripts\smartroute.exe health
	 if ($LASTEXITCODE -ne 0) { throw 'Gateway health failed.' }
	 .\.venv\Scripts\smartroute.exe workspace
	 if ($LASTEXITCODE -ne 0) { throw 'Gateway key authentication failed.' }
	 .\.venv\Scripts\smartroute.exe models
	 if ($LASTEXITCODE -ne 0) { throw 'Workspace model lookup failed.' }
} finally {
	 Remove-Item Env:SMARTROUTE_API_KEY -ErrorAction SilentlyContinue
	 Remove-Variable secureKey -ErrorAction SilentlyContinue
}
```

These are metadata calls, not inference. Public health alone does not prove key
authentication or provider access. Confirm the workspace is yours and at least one
model is enabled. The backend, browser, and SDK must use the same database/auth
environment; development and production keys/workspaces are not interchangeable.

For a deployed application, inject both environment variables from its secret/config
system and use the following pattern. Explicit lookups prevent an unset production
URL from silently falling back to the SDK's localhost default. This chat call can
incur provider charges; run it only with permission to use that workspace's models.

```python
import os
from smartroute_client import SmartRoute

with SmartRoute(
	 base_url=os.environ["SMARTROUTE_BASE_URL"],
	 api_key=os.environ["SMARTROUTE_API_KEY"],
) as client:
	 result = client.chat("Reply with a short greeting.", max_tokens=64)
	 record = client.request(result.request_id)
	 assert record["id"] == result.request_id
	 assert record["source"] == "sdk"
	 assert record["status"] == "completed"
	 assert record["attempts"]
	 print(result.content)
	 print(result.request_id, result.tier, result.cost_usd)
```

The API key belongs in your application's backend/secret storage, not public
frontend JavaScript. Keep it separate from PyPI tokens, provider keys, database
credentials, and managed-auth session tokens. A revoked/expired key must be replaced
with a newly issued gateway key; reinstalling the SDK does not repair authorization.

### Deployment Acceptance

Before advertising the deployed SDK/web workflow as verified:

1. Install the published wheel into a clean Python 3.11+ environment on an approved
	network and verify CLI/imports independently of the source checkout.
2. Complete signup, email verification, model configuration, and one-time gateway-key
	creation on the deployed website. Verify HTTPS `health`, `workspace`, and `models`.
3. Make one authorized small chat call, then find the exact returned request ID in
	the same account's web Requests view with source `sdk`, matching attempts and costs.
4. After reviewing the answer, submit feedback and confirm it in the browser. Do
	not mark a smoke-test response as positive without review.
5. Confirm another workspace cannot inspect/rate that request, then revoke the
	test gateway key and require HTTP 401 from its next authenticated call.
6. Check proxy/hosting timeouts against the SDK's timeout, cold-start behavior,
	input limits, and redacted errors. Never retry uncertain billable calls blindly.

Local source/wheel installs and mocked SDK-to-backend tests have passed. A clean
TestPyPI download and a live deployed provider-to-dashboard flow remain unverified;
the backend's public hosted mode is still gated by M5. No deployment URL has been
certified by these instructions.

## Python

For a local preview example, run the following with your environment's Python.
Enter secrets only in the hidden terminal prompt, never in
chat, source code, URLs, screenshots, or issue reports. This call can incur charges.

```python
from getpass import getpass
from smartroute_client import SmartRoute

with SmartRoute(
	base_url="http://localhost:8001",
	api_key=getpass("SmartRoute gateway key: "),
) as client:
	result = client.chat("Hello", max_tokens=64)
	print(result.content)
	print(result.tier, result.cost_usd, result.request_id)
```

For application deployments, use `SMARTROUTE_BASE_URL` and `SMARTROUTE_API_KEY`
from trusted environment/secret configuration and construct `SmartRoute()`.
Explicit constructor values take precedence. The default root is
`http://localhost:8000` for the original local prototype; hosted preview needs the
explicit preview URL. An absent key is useful only for local mode/public readiness.
Construction never sends a request or changes model configuration.

`chat()` accepts a string or a list of `{role, content}` messages and forwards
generation options such as `temperature` and `max_tokens`. Routing aliases are
`smartroute/auto`, `smartroute/small`, `smartroute/medium`, and `smartroute/large`.
A forced tier must exist and be enabled; there is no shared hosted fallback.

`ChatResult` contains `content`, `tier`, `escalated`, `confidence`, `cost_usd`,
`saved_usd`, `request_id`, and the original `raw` response. Cost includes all
answer and self-check attempts at configured standard rates, not invoice-specific
cache prices. Savings can be negative; reference prices are hypothetical. Invalid
or missing costs/confidence are rejected instead of becoming zero. Confidence is
a routing signal, not a correctness guarantee.

Other operations, on an open client:

```python
client.workspace()
client.models()
client.requests(source="sdk", limit=20)
client.request(result.request_id)
client.stats(days=7)
client.health()
```

After reviewing an answer, explicitly call `client.feedback(result.request_id,
good=True)` or `good=False, note="..."`. Re-rating replaces previous feedback.
Failed requests cannot be rated. Failed-call costs may be `None` in request
details; statistics cover completed requests, not all possible provider charges.
`client.bench(mode="auto", limit=5)` explicitly runs a billable Test Lab prefix.

Use a context manager or call `close()` to release connections. The default
request timeout is 300 seconds; longer cascades or suites may need an explicit
`timeout=`. There are no automatic retries and redirects are not followed. A
timeout or browser/CLI cancellation does not prove that inference was unbilled.
Inspect history before manually retrying an uncertain request.

HTTP/transport/protocol failures raise `SmartRouteError`. Its `status_code` and
optional `request_id` are safe diagnostics; arbitrary error bodies are not echoed.
Revoked or expired gateway keys return 401 on the next request. Ordinary gateway
keys cannot create keys, administer models, change settings, or train the router.

## CLI

Load a key into the current PowerShell session without including it in history:

```powershell
$secureKey = Read-Host 'SmartRoute gateway key' -AsSecureString
$env:SMARTROUTE_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password
$env:SMARTROUTE_BASE_URL = 'http://localhost:8001'
.\.venv\Scripts\smartroute.exe workspace
.\.venv\Scripts\smartroute.exe models
.\.venv\Scripts\smartroute.exe chat 'Hello' --max-tokens 64
.\.venv\Scripts\smartroute.exe requests --limit 10
.\.venv\Scripts\smartroute.exe stats --days 7
Remove-Item Env:SMARTROUTE_API_KEY
Remove-Variable secureKey
```

Global options (`--base-url`, `--timeout`) precede the subcommand. `health` makes
no inference call. `bench --mode auto --limit 2` deliberately incurs provider work;
its limit is 1-40, default 5, and its tier-match metric is not answer accuracy.
`request REQUEST_ID` shows recorded attempts; `feedback REQUEST_ID --good` or
`--bad --note '...'` rates a reviewed completion. Commands return 0 on success,
1 for SDK errors, 2 for argument errors, and 130 when interrupted.

`smartroute setup --web-url http://localhost:5174` opens Models in your browser.
It does not take a password, acquire a session, or upgrade a gateway key's rights.
`python -m smartroute_client.cli` is equivalent to the installed console entry.

## Explicit Owner Setup

Most users should configure providers in the website. Automation with an existing
trusted managed-auth flow may use `OwnerSetup(base_url, session_token)` with a
short-lived owner JWT. The caller acquires that JWT through managed authentication;
the SDK never reads browser storage or handles account passwords. Email verification
and ownership are still enforced by the backend. A gateway/provider key is rejected
as an owner-session credential.

On an open `OwnerSetup` client, explicit methods are `credentials()`,
`create_credential(provider, label, api_key)`, `replace_credential(id, api_key)`,
`delete_credential(id)`, `delete_model(tier)`, and:

```python
owner.configure_model(
	"small",
	credential_id=owned_credential_id,
	model=provider_model_id,
	input_price_per_1k=input_rate,
	output_price_per_1k=output_rate,
	enabled=True,
	send_temperature=True,
	self_check_max_tokens=256,
)
```

Supply those values from your explicit setup workflow, not every chat call. Only
OpenAI and native Anthropic are supported. Metadata reads never return saved key
values. Credential deletion also removes its tier mappings, not request history.
Keep owner sessions separate from long-lived application gateway keys.

## Development And Validation

From the repository root, with the backend development environment available:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install build 'hatchling>=1.27,<2' -e './sdk[test]'
.\backend\.venv\Scripts\python.exe -m pytest -q -c sdk/pyproject.toml sdk/tests
.\backend\.venv\Scripts\python.exe -m build sdk --outdir sdk/dist --no-isolation
```

VS Code tasks: `install: sdk`, `test: sdk`, and `build: sdk`. Distribution artifacts
are ignored by Git. SDK tests use `httpx.MockTransport`; the backend suite also
exercises actual authenticated routes with the source SDK through owner setup,
chat, feedback, private history, cross-user denial, and gateway-key revocation.
No paid provider call or registry upload is part of M4 validation.