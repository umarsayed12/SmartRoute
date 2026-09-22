<!-- Explain source installation, authenticated SDK/CLI usage, and owner-only model setup. -->
# SmartRoute Python SDK

The M4 client and CLI are implemented, but **not published to PyPI**. Install from
this repository until M5 publishing. Requires Python 3.11+; `httpx` is the only
runtime dependency. The client is synchronous and text-only; it does not stream.

## Install From Source

From a checkout of this repository, using Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ./sdk
.\.venv\Scripts\smartroute.exe --help
```

On macOS/Linux use `.venv/bin/python` and `.venv/bin/smartroute`. No shell
activation is required. This is a source install, not a claim that the package
name is available from a registry. Name availability and publication are M5 gates.

## Prepare A Workspace

1. Start the [authenticated preview](../docs/HOSTED_ARCHITECTURE.md#run-the-preview),
   sign in at `http://localhost:5174`, and verify your email in **API Keys**.
2. In **Models**, save an official OpenAI or Anthropic credential and configure at
   least one enabled tier with explicit USD input/output prices per 1,000 tokens.
3. In **API Keys**, create a SmartRoute gateway key and retain its one-time value
   in your application's secret storage. It is not your provider key.
4. Open **Integration** for the current gateway URL, source-install commands,
   Python/CLI examples, active-key count, and SDK request activity.

The preview gateway can be reached directly at `http://localhost:8001`, or through
Vite at `http://localhost:5174`. Neither is a public deployment. Public URLs must
use HTTPS; the SDK permits HTTP only for localhost/loopback. URL user information,
query strings, and fragments are rejected. Roots with or without `/v1` work.

## Python

Save the following as your own application's example, then run it with the
environment's Python. Enter secrets only in the hidden terminal prompt, never in
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