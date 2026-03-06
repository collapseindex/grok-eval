"""Auto-generated markdown report from evaluation data.

Reads JSON result files and produces a formatted markdown report
suitable for sharing (e.g., xAI Discord, GitHub issues).

Usage:
    python -m grok_eval report data/runs/20260306_044152_eval.json
    python -m grok_eval report data/runs/ --all
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .agents import AGENTS
from .api import print_header


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("report", help="Generate markdown report from results")
    p.add_argument("input", nargs="?", default="data/runs", help="JSON file or runs directory")
    p.add_argument("--all", action="store_true", help="Generate reports for all runs in directory")
    p.add_argument("--output-dir", default="data/reports", help="Output directory")
    p.set_defaults(func=execute)


def _safe_path(p: Path, label: str) -> Path:
    """Resolve and verify path stays within working directory."""
    resolved = p.resolve()
    cwd = Path.cwd().resolve()
    if not str(resolved).startswith(str(cwd)):
        print(f"Error: {label} must be within project directory")
        raise SystemExit(1)
    return resolved


def execute(args) -> None:
    input_path = _safe_path(Path(args.input), "input")
    out_dir = _safe_path(Path(args.output_dir), "output-dir")
    out_dir.mkdir(parents=True, exist_ok=True)

    if input_path.is_dir():
        if args.all:
            json_files = sorted(input_path.glob("*.json"))
        else:
            # Pick the latest
            json_files = sorted(input_path.glob("*.json"))
            json_files = json_files[-1:] if json_files else []
    elif input_path.is_file():
        json_files = [input_path]
    else:
        print(f"Not found: {input_path}")
        return

    if not json_files:
        print(f"No JSON files found in {input_path}")
        return

    for jf in json_files:
        with open(jf) as f:
            data = json.load(f)
        report = generate_report(data, jf.name)
        report_name = jf.stem + "_report.md"
        report_path = out_dir / report_name
        with open(report_path, "w") as f:
            f.write(report)
        print(f"  Generated: {report_path}")

    print_header("Reports Generated")
    print(f"  Files:  {len(json_files)}")
    print(f"  Output: {out_dir}/")
    print()


def generate_report(data: dict, source_filename: str) -> str:
    """Generate a complete markdown report from evaluation data."""
    meta = data.get("meta", {})
    records = data.get("records", [])
    consistency = data.get("consistency", [])
    scenarios = data.get("scenarios", [])

    run_id = meta.get("run_id", "unknown")
    model = meta.get("grok_model", meta.get("model", "unknown"))
    temp = meta.get("temperature", "?")
    dc = meta.get("decision_counts", {})
    agent_summary = meta.get("agent_summary", {})
    command = meta.get("command", "eval")

    now = datetime.now(timezone.utc).strftime("%B %d, %Y %H:%M UTC")

    lines: list[str] = []
    w = lines.append  # shorthand

    # Header
    w(f"# Grok 4.20 Evaluation Report")
    w("")
    w(f"**Run ID:** {run_id}")
    w(f"**Source:** {source_filename}")
    w(f"**Model:** {model}")
    w(f"**Temperature:** {temp}")
    w(f"**Command:** {command}")
    w(f"**Generated:** {now}")
    w("")

    # Summary table
    w("## Summary")
    w("")
    w("| Metric | Value |")
    w("|--------|-------|")
    w(f"| Total checks | {meta.get('total_checks', len(records))} |")
    if dc:
        w(f"| Allow | {dc.get('allow', 0)} |")
        w(f"| Warn | {dc.get('warn', 0)} |")
        w(f"| Gate | {dc.get('gate', 0)} |")
        w(f"| Block | {dc.get('block', 0)} |")
    w(f"| Ghost events | {meta.get('ghost_events', 0)} confirmed, {meta.get('ghost_suspects', 0)} suspects |")
    if consistency:
        w(f"| Consistency runs | {len(consistency)} |")
    w("")


    # Per-agent breakdown
    if agent_summary:
        w("## Per-Agent Results")
        w("")
        w("| Agent | Final CI | Final AL | Avg Grok Latency | Tokens (in/out) |")
        w("|-------|----------|----------|------------------|-----------------|")
        for aid, s in agent_summary.items():
            name = AGENTS.get(aid, {}).get("name", aid)
            ci_f = s.get("ci_final")
            ci_str = f"{ci_f:.4f}" if ci_f is not None else "n/a"
            al_f = s.get("al_final")
            al_str = f"AL{al_f}" if al_f is not None else "n/a"
            g_lat = s.get("grok_latency_avg_ms")
            lat_str = f"{g_lat:.0f}ms" if g_lat else "n/a"
            ti = s.get("grok_tokens_in_total", 0)
            to = s.get("grok_tokens_out_total", 0)
            tok_str = f"{ti:,}/{to:,}"
            w(f"| {name} | {ci_str} | {al_str} | {lat_str} | {tok_str} |")
        w("")

    # Ghost hunting results
    if scenarios:
        w("## Ghost Hunting Results")
        w("")
        w("| Scenario | Correct Answer | Correct | Wrong | Ghost Signals |")
        w("|----------|---------------|---------|-------|---------------|")
        for s in scenarios:
            task = s.get("task", "?")[:40]
            correct_ans = s.get("correct_answer", "?")[:30]
            cc = s.get("correct_count", 0)
            wc = s.get("wrong_count", 0)
            gc = s.get("ghost_count", 0)
            ghost_mark = f"**{gc}**" if gc > 0 else str(gc)
            w(f"| {task} | {correct_ans} | {cc} | {wc} | {ghost_mark} |")
        w("")

        total_ghosts = sum(s.get("ghost_count", 0) for s in scenarios)
        if total_ghosts > 0:
            w(f"> **{total_ghosts} ghost signal(s) detected.** "
              "These are responses that were consistently wrong across repeated runs.")
            w("")

    # Consistency
    if consistency:
        w("## Consistency Test")
        w("")
        texts = [c["content"] for c in consistency if c.get("content")]
        if texts:
            # Compute pairwise Jaccard
            sims: list[float] = []
            for i in range(len(texts)):
                for j in range(i + 1, len(texts)):
                    wa = set(texts[i].lower().split())
                    wb = set(texts[j].lower().split())
                    if wa or wb:
                        sims.append(len(wa & wb) / len(wa | wb))
            if sims:
                avg_sim = sum(sims) / len(sims)
                w(f"**Average pairwise Jaccard similarity:** {avg_sim:.3f}")
                w("")
            for i, c in enumerate(consistency):
                w(f"**Run {i + 1}:** {c.get('content', 'n/a')}")
                w("")

    # Decision timeline
    if records and len(records) <= 60:  # Don't dump huge tables
        w("## Decision Timeline")
        w("")
        w("| Round | Agent | Action | Decision | CI | AL |")
        w("|-------|-------|--------|----------|----|----|")
        for r in records:
            name = AGENTS.get(r.get("agent", ""), {}).get("name", r.get("agent", "?"))
            ci = r.get("ci")
            ci_str = f"{ci:.3f}" if ci is not None else "-"
            al = r.get("al")
            al_str = str(al) if al is not None else "-"
            dec = r.get("umbra_decision", r.get("decision", "?"))
            w(f"| {r.get('round', r.get('scenario', '?'))} | {name} | {r.get('action', '?')} | {dec} | {ci_str} | {al_str} |")
        w("")

    # Plots reference
    w("## Plots")
    w("")
    w("Plots are saved alongside this report in `data/plots/`. Key charts:")
    w("")
    w(f"- `{run_id}_ci_drift.png` - CI drift curves per agent")
    w(f"- `{run_id}_al_heatmap.png` - Authority Level heatmap")
    w(f"- `{run_id}_decisions.png` - Decision distribution")
    w(f"- `{run_id}_latency.png` - Grok response latency")
    w(f"- `{run_id}_tokens.png` - Token usage")
    w(f"- `{run_id}_umbra_overhead.png` - Umbra check overhead")
    w("")

    # Footer
    w("---")
    w("")
    w(f"*Generated by [grok-eval](https://github.com/collapseindex/grok-eval) v0.1.0*")
    w(f"*Powered by [Umbra](https://github.com/collapseindex/umbra) + [CI-1T API](https://ci-1t-api.onrender.com)*")
    w("")

    return "\n".join(lines)
