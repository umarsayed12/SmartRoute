"""Start the single-worker public service on Render's assigned port without trusting proxy headers."""

import os

import uvicorn


def main() -> None:
    """Reject accidental local/preview deployment and keep process-local limits single-worker."""
    if os.environ.get("APP_MODE") != "hosted":
        raise RuntimeError("The deployment entry point requires APP_MODE=hosted.")
    port = int(os.environ.get("PORT", "10000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be a valid TCP port.")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, workers=1, proxy_headers=False, access_log=False,
                limit_concurrency=64, timeout_keep_alive=5, timeout_graceful_shutdown=30)


if __name__ == "__main__":
    main()