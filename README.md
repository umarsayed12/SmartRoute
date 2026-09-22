<!-- Project overview and migration status for the SmartRoute bring-your-own-model gateway. -->
# SmartRoute

SmartRoute is an LLM routing and tracking gateway. Its hosted architecture lets
developers sign in, create a private workspace, configure their own OpenAI or
Anthropic models, and connect applications using a SmartRoute API key. The gateway
selects an appropriate configured tier, evaluates whether to escalate, and records
usage, estimated cost, feedback, and routing decisions for that workspace.

**Status: hosted migration in progress.** The completed local prototype includes
the Playground, Dashboard, Requests, Test Lab, and Settings. An authenticated
loopback preview now supports Neon login, private workspaces, gateway-key management,
encrypted OpenAI/Anthropic credentials, owned model routing, and private attempt-level
history. M4 adds the source Python SDK/CLI, setup gating, and Integration page.
SDK 0.1.0 is uploaded to TestPyPI; clean registry installation is unverified on the
managed development laptop. M5 public deployment and production PyPI publishing
remain pending. Provider protocol tests use mocked HTTP, not live paid inference.

The default local HTTP app is still unauthenticated and must remain local-only.
Use the documented authenticated preview to test the app and SDK. Public hosted startup
is deliberately blocked until the migration's security gates are met. SmartRoute
will initially be free; users remain responsible for their provider's model charges.

## Architecture And Setup

- [Hosted architecture and migration checkpoints](docs/HOSTED_ARCHITECTURE.md)
- [Active build specification](SMARTROUTE_BUILD_SPEC.md)
- [Backend development instructions](backend/README.md)
- [Frontend development instructions](frontend/README.md)

Neon managed authentication owns passwords and sessions. Neon Postgres holds
workspace profiles, hashed gateway keys, encrypted provider credentials, model
configurations, request history, and training artifacts. The browser and SDK call
the same authenticated backend; neither receives the database connection string.

No automatic migration of existing local request history is performed. Provider
credentials are encrypted in Neon; the encryption key and database connection
strings stay in ignored local environment files or deployment secret storage,
never in Git or browser configuration. Provider keys entered in the Models form
are cleared after saving and cannot be read back through the API.

## Owned Model Preview

After signing in and verifying your email, open **Models**, save an official
OpenAI or Anthropic credential, and configure at least one enabled tier with
explicit USD input/output prices per 1,000 tokens. No shared models or private
custom endpoints are used. Ordinary gateway keys can use configured models but
cannot change provider credentials or model configuration.

Every answer and confidence call contributes to estimated cost. Reported cache
and reasoning usage is retained, but cache-specific prices are not applied yet.
Failed calls with unreported usage have unknown cost, not zero; dashboard savings
cover completed requests only and are not a provider invoice. See the
[routing and accounting details](docs/HOSTED_ARCHITECTURE.md#m3-bring-your-own-models).

## Python Client

The Python client is available from this checkout and as a
[0.1.0 TestPyPI preview](https://test.pypi.org/project/smartroute-client/0.1.0/),
**not yet from production PyPI**:

```powershell
python -m pip install ./sdk
```

Use a workspace gateway key, not a provider key. The web **Integration** page
provides the current gateway URL and secret-safe examples. See the
[SDK guide](sdk/README.md) for Python, CLI, owner setup, and local build instructions.

Maintainers can follow the [manual production publishing procedure](docs/HOSTED_ARCHITECTURE.md#manual-sdk-publishing)
on an approved machine/network. For end users of the future deployed service, the
SDK needs the canonical HTTPS gateway URL and their own workspace gateway key,
not local backend setup or a PyPI token. See the
[deployment acceptance checklist](sdk/README.md#deployment-acceptance); package
publication alone does not verify a publicly deployed service.

## Repository Layout

```text
backend/   FastAPI gateway, routing, request logs, and training
frontend/  React playground, dashboard, and management pages
sdk/       Python client library and CLI
```

## License

MIT License. Copyright (c) 2026 Umar Khursheed. See [LICENSE](LICENSE).