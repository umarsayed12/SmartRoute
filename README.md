<!-- Project overview and planned layout for the SmartRoute LLM gateway. -->
# SmartRoute

SmartRoute is an OpenAI-compatible LLM gateway that sends each chat request to the cheapest model tier that can handle it. A small local model (via Ollama) answers first; a quick confidence check decides whether to escalate to a bigger tier. Every request is logged with actual cost vs. a "premium reference" cost, users can rate answers, and a small scikit-learn model retrains on that feedback to improve routing. A React frontend provides a Playground, a Dashboard ("$ saved vs quality retained"), a Requests Explorer, a Test Lab for running prompt suites, and a Settings page. A tiny Python client library (`smartroute-client`) is planned for PyPI so anyone can install it with pip and use the gateway in three lines.

Status: 🚧 in progress

## Planned Structure

```text
backend/   FastAPI gateway, routing, request logs, and training
frontend/  React playground, dashboard, and management pages
sdk/       Python client library and CLI
```

## License

MIT License. Copyright (c) 2026 Umar Khursheed. See [LICENSE](LICENSE).