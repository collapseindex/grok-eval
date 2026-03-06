"""Full evaluation suite: chains run -> ghost -> showdown -> report.

Usage:
    python -m grok_eval full
    python -m grok_eval full --rounds 30 --skip-plots
"""

from __future__ import annotations

import argparse
import sys
import time

from ..api import (
    DEFAULT_UMBRA_URL,
    GROK_NON_REASONING,
    GROK_REASONING,
    print_header,
    validate_umbra_url,
)


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("full", help="Run all evals: run + ghost + showdown + report")
    p.add_argument("--rounds", type=int, default=30, help="Rounds per eval (1-100)")
    p.add_argument("--consistency-runs", type=int, default=3, help="Consistency runs")
    p.add_argument("--ghost-repeats", type=int, default=3, help="Ghost stability repeats")
    p.add_argument("--temperature", type=float, default=0.7, help="Temperature")
    p.add_argument("--umbra-url", default=DEFAULT_UMBRA_URL, help="Umbra URL")
    p.add_argument("--skip-grok", action="store_true", help="Skip Grok API calls")
    p.add_argument("--skip-plots", action="store_true", help="Skip plot generation")
    p.add_argument(
        "--showdown-models",
        default=f"{GROK_REASONING},{GROK_NON_REASONING}",
        help="Comma-sep models for showdown",
    )
    p.set_defaults(func=execute)


def execute(args) -> None:
    validate_umbra_url(args.umbra_url)

    from . import run as run_cmd
    from . import ghost as ghost_cmd
    from . import showdown as showdown_cmd
    from .. import report as report_mod

    stages = [
        ("Standard Eval", "run"),
        ("Ghost Hunt", "ghost"),
        ("Showdown", "showdown"),
        ("Report", "report"),
    ]
    results_files: list[str] = []
    total_start = time.time()

    print_header("Full Evaluation Suite")
    print(f"  Rounds:      {args.rounds}")
    print(f"  Temperature: {args.temperature}")
    print(f"  Ghost reps:  {args.ghost_repeats}")
    print(f"  Skip Grok:   {args.skip_grok}")
    print(f"  Stages:      {' -> '.join(s[0] for s in stages)}")
    print()

    # --- Stage 1: Standard eval ---
    _stage_banner(1, "Standard Eval")
    run_args = argparse.Namespace(
        rounds=args.rounds,
        consistency_runs=args.consistency_runs,
        model=GROK_REASONING,
        temperature=args.temperature,
        umbra_url=args.umbra_url,
        skip_grok=args.skip_grok,
        skip_plots=args.skip_plots,
    )
    run_cmd.execute(run_args)

    # --- Stage 2: Ghost hunt ---
    _stage_banner(2, "Ghost Hunt")
    ghost_args = argparse.Namespace(
        rounds=args.rounds,
        repeats=args.ghost_repeats,
        model=GROK_REASONING,
        temperature=args.temperature,
        umbra_url=args.umbra_url,
        skip_grok=args.skip_grok,
        skip_plots=args.skip_plots,
    )
    ghost_cmd.execute(ghost_args)

    # --- Stage 3: Showdown ---
    _stage_banner(3, "Showdown")
    showdown_args = argparse.Namespace(
        models=args.showdown_models,
        rounds=args.rounds,
        consistency_runs=args.consistency_runs,
        temperature=args.temperature,
        umbra_url=args.umbra_url,
        skip_grok=args.skip_grok,
        skip_plots=args.skip_plots,
    )
    showdown_cmd.execute(showdown_args)

    # --- Stage 4: Generate reports for all runs ---
    _stage_banner(4, "Reports")
    report_args = argparse.Namespace(
        input="data/runs/",
        output_dir="data/reports",
        all=True,
    )
    try:
        report_mod.generate_report(report_args)
    except Exception as exc:
        print(f"  Report generation note: {type(exc).__name__}")

    elapsed = time.time() - total_start
    print_header("Full Suite Complete")
    print(f"  Total time: {elapsed:.1f}s")
    print(f"  Results in: data/runs/")
    print(f"  Plots in:   data/plots/")
    print(f"  Reports in: data/reports/")
    print()


def _stage_banner(num: int, name: str) -> None:
    print()
    print(f"  {'='*50}")
    print(f"  Stage {num}/4: {name}")
    print(f"  {'='*50}")
    print()
