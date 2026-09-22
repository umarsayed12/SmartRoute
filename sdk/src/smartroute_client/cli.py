"""Offer explicit gateway commands without accepting secrets in command-line arguments."""

import argparse
import json
import sys
import webbrowser

from smartroute_client.client import SmartRoute, SmartRouteError, _base_url


def main(argv: list[str] | None = None) -> int:
    """Run a workspace operation with environment-based gateway authentication."""
    parser = argparse.ArgumentParser(prog="smartroute")
    parser.add_argument("--base-url", help="Gateway root (or SMARTROUTE_BASE_URL)")
    parser.add_argument("--timeout", type=float, default=300, help="Request timeout in seconds; calls are not retried")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health", help="Check gateway readiness without inference")
    commands.add_parser("models", help="List workspace model mappings")
    commands.add_parser("workspace", help="Check the workspace identified by your gateway key")
    chat = commands.add_parser("chat", help="Generate a billable answer with saved models")
    chat.add_argument("prompt")
    chat.add_argument("--model", default="smartroute/auto")
    chat.add_argument("--max-tokens", type=int, default=1024)
    bench = commands.add_parser("bench", help="Run a billable Test Lab suite prefix")
    bench.add_argument("--mode", choices=["auto", "small", "medium", "large"], default="auto")
    bench.add_argument("--limit", type=int, default=5)
    stats = commands.add_parser("stats", help="Read completed-request estimates")
    stats.add_argument("--days", type=int, default=7)
    history = commands.add_parser("requests", help="List private request history")
    history.add_argument("--limit", type=int, default=20)
    detail = commands.add_parser("request", help="Inspect one request and its attempts")
    detail.add_argument("request_id")
    feedback = commands.add_parser("feedback", help="Rate a completed owned request")
    feedback.add_argument("request_id")
    rating = feedback.add_mutually_exclusive_group(required=True)
    rating.add_argument("--good", action="store_true")
    rating.add_argument("--bad", action="store_true")
    feedback.add_argument("--note")
    setup = commands.add_parser("setup", help="Open owner-authorized setup in your browser")
    setup.add_argument("--web-url", required=True, help="Web workspace origin, without credentials")
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            if not webbrowser.open(str(_base_url(args.web_url).join("models"))):
                raise SmartRouteError("Browser could not be opened; open Models in your web workspace.")
            return 0
        with SmartRoute(base_url=args.base_url, timeout=args.timeout) as client:
            if args.command == "chat":
                result = client.chat(args.prompt, model=args.model, max_tokens=args.max_tokens)
                print(result.content)
                print(f"\n{result.tier} | confidence={result.confidence:.2f} | estimated_cost=${result.cost_usd:.8f} | request={result.request_id}")
            elif args.command == "bench":
                result = client.bench(args.mode, args.limit)
                summary = result["summary"]
                print(f"prompts={result['prompt_count']} | tier_match={summary['routing_accuracy']:.1%} | estimated_cost=${summary['total_actual_usd']:.8f} | saved={summary['saved_pct']:.1f}%")
            else:
                operations = {"health": client.health, "models": client.models, "workspace": client.workspace,
                              "stats": lambda: client.stats(args.days), "requests": lambda: client.requests(limit=args.limit),
                              "request": lambda: client.request(args.request_id),
                              "feedback": lambda: client.feedback(args.request_id, args.good, args.note)}
                print(json.dumps(operations[args.command](), indent=2, ensure_ascii=False))
        return 0
    except (KeyError, IndexError, TypeError):
        print("Gateway returned an invalid command response.", file=sys.stderr)
        return 1
    except (SmartRouteError, ValueError) as error:
        print(str(error), file=sys.stderr)
        if isinstance(error, SmartRouteError) and error.request_id:
            print(f"Request: {error.request_id}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped waiting; check history before retrying.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())