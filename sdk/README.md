<!-- Track the SDK scope while hosted authentication and model configuration are being introduced. -->
# SmartRoute Python SDK

The SDK is not published yet. Its implementation follows hosted migration
checkpoint M4 in the [architecture plan](../docs/HOSTED_ARCHITECTURE.md), replacing
the original unauthenticated local-only client plan.

The client will authenticate with a workspace's SmartRoute API key, call the
gateway for chat/feedback/stats, and provide explicit model-configuration methods.
Provider credentials are separate from the gateway key and must come from the
developer's environment or secret storage. There are no shared hosted model defaults.

Publishing and the website's real installation instructions wait until the auth,
tenant isolation, model ownership, and SDK contracts pass the deployment gates.