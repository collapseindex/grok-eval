"""CLI entry point for grok-eval.

Usage:
    python -m grok_eval run --rounds 10
    python -m grok_eval sweep --temps 0.0,0.3,0.7,1.0
    python -m grok_eval ghost --rounds 8 --repeats 3
    python -m grok_eval showdown
    python -m grok_eval report data/runs/XXXXX.json
"""

from __future__ import annotations

import argparse
import sys

from . import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="grok-eval",
        description="Grok 4.20 evaluation suite with Umbra behavioral gating",
    )
    parser.add_argument(
        "--version", action="version", version=f"grok-eval {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Register command modules
    from .commands import run, sweep, ghost, showdown, full
    from . import report

    run.add_parser(subparsers)
    sweep.add_parser(subparsers)
    ghost.add_parser(subparsers)
    showdown.add_parser(subparsers)
    full.add_parser(subparsers)
    report.add_parser(subparsers)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
