<!-- Project overview and migration status for the SmartRoute bring-your-own-model gateway. -->
# SmartRoute

SmartRoute is an LLM routing and tracking gateway. Its hosted architecture lets
developers sign in, create a private workspace, configure their own OpenAI or
Anthropic models, and connect applications using a SmartRoute API key. The gateway
selects an appropriate configured tier, evaluates whether to escalate, and records
usage, estimated cost, feedback, and routing decisions for that workspace.

**Status: hosted migration in progress.** The completed local prototype includes
the Playground, Dashboard, Requests, Test Lab, and Settings. The Neon foundation
is being added in tested checkpoints. Login, tenant-scoped HTTP routes, hosted
model onboarding, and the published SDK are not complete yet.

The current HTTP app is unauthenticated and must remain local-only. Hosted startup
is deliberately blocked until the migration's security gates are met. SmartRoute
will initially be free; users remain responsible for their provider's model charges.

## Architecture And Setup

- [Hosted architecture and migration checkpoints](docs/HOSTED_ARCHITECTURE.md)
- [Active build specification](SMARTROUTE_BUILD_SPEC.md)
- [Backend development instructions](backend/README.md)
- [Frontend development instructions](frontend/README.md)

Neon managed authentication owns passwords and sessions. Neon Postgres will hold
workspace profiles, hashed gateway keys, encrypted provider credentials, model
configurations, request history, and training artifacts. The browser and SDK call
the same authenticated backend; neither receives the database connection string.

No automatic migration of existing local request history is performed. Provider
credentials and Neon connection strings stay in ignored local environment files
or deployment secret storage, never in Git or browser configuration.

## Planned Structure

```text
backend/   FastAPI gateway, routing, request logs, and training
frontend/  React playground, dashboard, and management pages
sdk/       Python client library and CLI
```

## License

MIT License. Copyright (c) 2026 Umar Khursheed. See [LICENSE](LICENSE).