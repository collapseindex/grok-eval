"""Temperature sweep: run eval at multiple temperature settings.

Usage:
    python -m grok_eval sweep --temps 0.0,0.3,0.7,1.0
    python -m grok_eval sweep --temps 0.0,1.0 --rounds 5
"""

from __future__ import annotations

import json
from pathlib import Path

from ..api import GROK_REASONING, DEFAULT_UMBRA_URL, print_header, print_section, validate_umbra_url
from ..core import EvalConfig, run_eval_loop
from ..plots import generate_base_plots, generate_stability_plots, plot_temp_comparison


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("sweep", help="Temperature sweep")
    p.add_argument("--temps", default="0.0,0.3,0.7,1.0", help="Comma-sep temperatures")
    p.add_argument("--rounds", type=int, default=30, help="Rounds per temp (1-100)")
    p.add_argument("--consistency-runs", type=int, default=5, help="Consistency per temp")
    p.add_argument("--model", default=GROK_REASONING, help="Model slug")
    p.add_argument("--umbra-url", default=DEFAULT_UMBRA_URL, help="Umbra URL")
    p.add_argument("--skip-grok", action="store_true", help="Skip Grok API calls")
    p.add_argument("--skip-plots", action="store_true", help="Skip plots")
    p.set_defaults(func=execute)


def execute(args) -> None:
    validate_umbra_url(args.umbra_url)
    temps = [float(t.strip()) for t in args.temps.split(",")]
    out = Path("data/runs")
    plot_dir = Path("data/plots")
    plot_dir.mkdir(parents=True, exist_ok=True)
    all_runs: list[dict] = []

    for temp in temps:
        cfg = EvalConfig(
            model=args.model,
            temperature=temp,
            rounds=max(1, min(100, args.rounds)),
            consistency_runs=args.consistency_runs,
            skip_grok=args.skip_grok,
            skip_plots=True,  # we generate combined plots at end
            umbra_url=args.umbra_url,
            output_dir=out,
            label=f"temp{temp}",
        )
        data = run_eval_loop(cfg)
        all_runs.append(data)

        if not args.skip_plots:
            prefix = f"{data['meta']['run_id']}_temp{temp}"
            generate_base_plots(data, plot_dir, prefix)
            generate_stability_plots(data, plot_dir, prefix)

    # Combined temperature comparison plot
    if not args.skip_plots and len(all_runs) > 1:
        print_section(99, "Generating temperature comparison")
        prefix = all_runs[0]["meta"]["run_id"] + "_sweep"
        fname = plot_temp_comparison(all_runs, plot_dir, prefix)
        print(f"    {fname}")

    # Save combined sweep data
    sweep_path = out / f"{all_runs[0]['meta']['run_id']}_sweep_combined.json"
    with open(sweep_path, "w") as f:
        json.dump(
            {"temps": temps, "runs": [r["meta"] for r in all_runs]},
            f, indent=2, default=str,
        )

    print_header("Sweep Complete")
    print(f"  Temperatures: {temps}")
    print(f"  Total runs:   {len(all_runs)}")
    print()
