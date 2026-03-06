"""Standard evaluation run.

Usage:
    python -m grok_eval run --rounds 10
    python -m grok_eval run --skip-grok --rounds 5
"""

from __future__ import annotations

from pathlib import Path

from ..api import GROK_REASONING, DEFAULT_UMBRA_URL, print_section, validate_umbra_url
from ..core import EvalConfig, run_eval_loop
from ..plots import generate_base_plots, generate_stability_plots, plot_consistency_matrix


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("run", help="Standard evaluation run")
    p.add_argument("--rounds", type=int, default=30, help="Rounds (1-100)")
    p.add_argument("--consistency-runs", type=int, default=3, help="Consistency runs")
    p.add_argument("--model", default=GROK_REASONING, help="Model slug")
    p.add_argument("--temperature", type=float, default=0.7, help="Temperature")
    p.add_argument("--umbra-url", default=DEFAULT_UMBRA_URL, help="Umbra URL")
    p.add_argument("--skip-grok", action="store_true", help="Skip Grok API calls")
    p.add_argument("--skip-plots", action="store_true", help="Skip plot generation")
    p.set_defaults(func=execute)


def execute(args) -> None:
    validate_umbra_url(args.umbra_url)
    out = Path("data/runs")
    cfg = EvalConfig(
        model=args.model,
        temperature=args.temperature,
        rounds=max(1, min(100, args.rounds)),
        consistency_runs=args.consistency_runs,
        skip_grok=args.skip_grok,
        skip_plots=args.skip_plots,
        umbra_url=args.umbra_url,
        output_dir=out,
    )
    data = run_eval_loop(cfg)

    if not args.skip_plots:
        plot_dir = Path("data/plots")
        plot_dir.mkdir(parents=True, exist_ok=True)
        prefix = data["meta"]["run_id"]
        print_section(99, "Generating plots")
        generate_base_plots(data, plot_dir, prefix)
        generate_stability_plots(data, plot_dir, prefix)
        if data.get("consistency"):
            plot_consistency_matrix(data["consistency"], plot_dir, prefix)
        print(f"    Plots saved to {plot_dir}/")
