"""Run explicit schema migrations without exposing database credentials on failure."""

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config


def main(argv: list[str] | None = None) -> None:
    """Expose safe upgrade/current/check commands and explicit revision generation."""
    parser = argparse.ArgumentParser(description="Manage the hosted SmartRoute schema.")
    parser.add_argument("action", choices=["upgrade", "current", "check", "revision"])
    parser.add_argument("--revision-id", default=None)
    parser.add_argument("--message", default=None)
    args = parser.parse_args(argv)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    try:
        if args.action == "upgrade":
            command.upgrade(config, "head")
            print("Hosted schema upgraded successfully.")
        elif args.action == "current":
            command.current(config)
        elif args.action == "check":
            command.check(config)
        else:
            if not args.revision_id or not args.message:
                parser.error("revision requires --revision-id and --message")
            command.revision(config, message=args.message, rev_id=args.revision_id, autogenerate=True)
    except Exception as error:
        raise SystemExit(
            f"Migration failed ({type(error).__name__}). Check database access and migration configuration; secret values were not displayed."
        ) from None


if __name__ == "__main__":
    main()