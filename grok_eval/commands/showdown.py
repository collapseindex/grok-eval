"""Cross-model showdown: reasoning vs non-reasoning comparison.

Usage:
    python -m grok_eval showdown
    python -m grok_eval showdown --rounds 5 --skip-grok
"""

from __future__ import annotations

import json
from pathlib import Path

from ..api import (
    DEFAULT_UMBRA_URL,
    GROK_NON_REASONING,
    GROK_REASONING,
    print_header,
    print_section,
    validate_umbra_url,
)
from ..core import EvalConfig, run_eval_loop
from ..plots import generate_base_plots, generate_stability_plots, plot_model_comparison


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("showdown", help="Cross-model comparison")
    p.add_argument(
        "--models",
        default=f"{GROK_REASONING},{GROK_NON_REASONING}",
        help="Comma-sep model slugs to compare",
    )
    p.add_argument("--rounds", type=int, default=30, help="Rounds per model (1-100)")
    p.add_argument("--consistency-runs", type=int, default=3, help="Consistency runs")
    p.add_argument("--temperature", type=float, default=0.7, help="Temperature")
    p.add_argument("--umbra-url", default=DEFAULT_UMBRA_URL, help="Umbra URL")
    p.add_argument("--skip-grok", action="store_true", help="Skip Grok API calls")
    p.add_argument("--skip-plots", action="store_true", help="Skip plots")
    p.set_defaults(func=execute)


def execute(args) -> None:
    validate_umbra_url(args.umbra_url)
    models = [m.strip() for m in args.models.split(",")]
    out = Path("data/runs")
    plot_dir = Path("data/plots")
    plot_dir.mkdir(parents=True, exist_ok=True)
    all_runs: list[dict] = []

    for model in models:
        # Short label for output filenames
        if "non-reasoning" in model:
            label = "non_reasoning"
        elif "reasoning" in model:
            label = "reasoning"
        else:
            label = model.split("-")[-1][:20]

        cfg = EvalConfig(
            model=model,
            temperature=args.temperature,
            rounds=max(1, min(100, args.rounds)),
            consistency_runs=args.consistency_runs,
            skip_grok=args.skip_grok,
            skip_plots=True,  # combined plots at end
            umbra_url=args.umbra_url,
            output_dir=out,
            label=label,
        )
        data = run_eval_loop(cfg)
        all_runs.append(data)

        # Per-model base plots
        if not args.skip_plots:
            prefix = f"{data['meta']['run_id']}_{label}"
            generate_base_plots(data, plot_dir, prefix)
            generate_stability_plots(data, plot_dir, prefix)

    # Combined comparison plot
    if not args.skip_plots and len(all_runs) > 1:
        print_section(99, "Generating model comparison")
        prefix = all_runs[0]["meta"]["run_id"] + "_showdown"
        fname = plot_model_comparison(all_runs, plot_dir, prefix)
        print(f"    {fname}")

    # Save combined data
    showdown_path = out / f"{all_runs[0]['meta']['run_id']}_showdown_combined.json"
    with open(showdown_path, "w") as f:
        json.dump(
            {"models": models, "runs": [r["meta"] for r in all_runs]},
            f, indent=2, default=str,
        )

    print_header("Showdown Complete")
    for run_data in all_runs:
        m = run_data["meta"]
        dc = m.get("decision_counts", {})
        ghosts = m.get("ghost_events", 0)
        print(f"  {m['grok_model']}")
        print(f"    Decisions: allow={dc.get('allow', 0)} warn={dc.get('warn', 0)} "
              f"gate={dc.get('gate', 0)} block={dc.get('block', 0)}")
        print(f"    Ghosts: {ghosts}")

    print()
