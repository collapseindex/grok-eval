"""Shared evaluation loop used by all commands.

Each command (run, sweep, ghost, showdown) configures an EvalConfig
and calls run_eval_loop() which handles the agent x round iteration,
Umbra checks, Grok calls, data collection, and terminal output.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .agents import AGENTS, AGENT_IDS
from .api import (
    DEFAULT_UMBRA_URL,
    DIM,
    GREEN,
    GROK_REASONING,
    CYAN,
    MAGENTA,
    BOLD,
    RED,
    RESET,
    WHITE,
    YELLOW,
    AGENT_TERM_COLORS,
    colorize_decision,
    get_xai_key,
    grok_chat,
    print_header,
    print_section,
    umbra_check,
)
from .collector import EvalCollector
from .prompts import CONSISTENCY_PROMPT


@dataclass
class EvalConfig:
    """Configuration for a single evaluation run."""
    model: str = GROK_REASONING
    temperature: float = 0.7
    max_tokens: int = 200
    rounds: int = 30
    consistency_runs: int = 3
    skip_grok: bool = False
    skip_plots: bool = False
    umbra_url: str = DEFAULT_UMBRA_URL
    output_dir: Path = field(default_factory=lambda: Path("data/runs"))
    prompts: list[dict] | None = None  # override prompt set
    label: str = ""  # extra label for output filename


_VERDICT_COLORS = {
    "STABLE": GREEN,
    "DRIFTING": YELLOW,
    "ERRATIC": RED,
    "GATED": MAGENTA,
}


def _print_stability_summary(data: dict) -> None:
    """Print a formatted behavioral stability table to the terminal."""
    summary = data.get("meta", {}).get("agent_summary")
    if not summary:
        return

    print_header("Behavioral Stability Profile")

    # Table header
    hdr = (
        f"  {'Agent':<14s} {'Drift':<14s} {'Volatility':<12s}"
        f"{'Recovery':<11s}{'Gate/Block':<13s}{'Verdict'}"
    )
    sep = "  " + "-" * 78
    print(sep)
    print(hdr)
    print(sep)

    reliabilities = []

    for aid, s in summary.items():
        bp = s.get("behavioral_profile", {})
        drift_sig = bp.get("drift_significance", {})
        slope = drift_sig.get("slope", 0)
        p_val = drift_sig.get("p_value", 1.0)

        # Significance stars
        stars = ""
        if drift_sig.get("significant_01"):
            stars = " **"
        elif drift_sig.get("significant_05"):
            stars = " *"
        drift_str = f"{slope:+.4f}{stars}"

        vol = bp.get("volatility", 0)
        rec = bp.get("recovery_rate", 0)
        gbr = bp.get("gate_block_rate", 0)
        verdict = bp.get("verdict", "?")
        verdict_color = _VERDICT_COLORS.get(verdict, WHITE)

        rel = bp.get("split_half_reliability", 0)
        reliabilities.append(rel)

        # CI mean interval
        ci_ci = bp.get("ci_mean_95ci", [])
        ci_mean_val = bp.get("ci_mean", 0)

        print(
            f"  {aid:<14s} {drift_str:<14s} {vol:<12.4f}"
            f"{rec:<11.1%}{gbr:<13.1%}"
            f"{verdict_color}{BOLD}{verdict}{RESET}"
        )

        # Detail line: CI mean with 95% CI
        if ci_ci:
            print(
                f"  {'':<14s} {DIM}CI mean={ci_mean_val:.4f} "
                f"[{ci_ci[0]:.4f}, {ci_ci[1]:.4f}]{RESET}"
            )

    print(sep)

    # Significance key
    print(f"  {DIM}** p < 0.01   * p < 0.05   (H0: zero drift){RESET}")

    # Split-half reliability (average across agents)
    if reliabilities:
        avg_rel = sum(reliabilities) / len(reliabilities)
        if avg_rel >= 0.9:
            rel_label = f"{GREEN}EXCELLENT{RESET}"
        elif avg_rel >= 0.7:
            rel_label = f"{GREEN}GOOD{RESET}"
        elif avg_rel >= 0.5:
            rel_label = f"{YELLOW}MODERATE{RESET}"
        else:
            rel_label = f"{RED}LOW{RESET}"
        print(f"\n  Split-half reliability (avg): r = {avg_rel:.4f} -- {rel_label}")
        print(f"  {DIM}(odd/even round consistency with Spearman-Brown correction){RESET}")

    # Behavioral drivers
    drivers = data.get("meta", {}).get("behavioral_drivers", {})
    if drivers:
        print(f"\n  {BOLD}Behavioral Drivers{RESET} (mean CI by action type):")
        for action, info in sorted(drivers.items(), key=lambda x: x[1]["mean_ci"], reverse=True):
            bar_len = int(info["mean_ci"] * 40)  # scale to ~40 chars
            bar = CYAN + "|" * bar_len + RESET
            print(
                f"    {action:<8s} CI={info['mean_ci']:.4f}  "
                f"(n={info['count']})  {bar}"
            )

    print()


def run_eval_loop(cfg: EvalConfig) -> dict:
    """Execute a full evaluation run. Returns the finalized data dict."""
    api_key = "" if cfg.skip_grok else get_xai_key()
    with httpx.Client(timeout=30.0) as umbra, httpx.Client(timeout=60.0) as xai:
        return _eval_loop_inner(cfg, api_key, umbra, xai)


def _eval_loop_inner(cfg: EvalConfig, api_key: str, umbra: httpx.Client, xai: httpx.Client) -> dict:
    """Inner evaluation loop with pre-opened HTTP clients."""
    collector = EvalCollector(cfg.model, cfg.umbra_url, cfg.temperature)

    label = f" ({cfg.label})" if cfg.label else ""
    print_header(f"Grok 4.20 Evaluation{label}")
    print(f"  Model:    {cfg.model}")
    print(f"  Temp:     {cfg.temperature}")
    print(f"  Rounds:   {cfg.rounds}")
    print(f"  Agents:   {', '.join(AGENT_IDS)}")
    print(f"  Run ID:   {collector.run_id}")

    # ── Health check ───────────────────────────────────────────
    step = 1
    print_section(step, "Umbra health check")
    try:
        h = umbra.get(f"{cfg.umbra_url}/health").json()
        print(f"    status={h['status']}  version={h['version']}  policy={h['policy']}")
        collector.meta["umbra_version"] = h["version"]
        collector.meta["umbra_policy"] = h["policy"]
    except Exception:
        print(f"    {RED}Umbra not reachable at {cfg.umbra_url}{RESET}")
        print("    Start with: umbra serve")
        sys.exit(1)

    # ── Evaluation rounds ──────────────────────────────────────
    # At high round counts, prompts cycle. Repeated prompts at different
    # rounds measure behavioral consistency -- the core stability question.
    from .prompts import EVAL_PROMPTS
    base_prompts = cfg.prompts or EVAL_PROMPTS
    prompts = [base_prompts[i % len(base_prompts)] for i in range(cfg.rounds)]
    step += 1

    for round_idx, eval_round in enumerate(prompts):
        print_section(
            step + round_idx,
            f"Round {round_idx + 1}/{len(prompts)}: {eval_round['task']}",
        )

        for agent_id in AGENT_IDS:
            agent_cfg = AGENTS[agent_id]
            color = AGENT_TERM_COLORS[agent_id]
            cycle = agent_cfg["action_cycle"]
            action_type, escalation = cycle[round_idx % len(cycle)]

            # 1. Umbra check
            umbra_resp, umbra_lat = umbra_check(
                umbra, cfg.umbra_url, agent_id, action_type, escalation
            )
            decision = umbra_resp["decision"]
            ci = umbra_resp.get("ci")
            al = umbra_resp.get("al")
            ghost_suspect = umbra_resp.get("ghost_suspect", False)
            ghost_confirmed = umbra_resp.get("ghost_confirmed", False)
            buffered = umbra_resp.get("buffered", False)

            # Print
            dec_str = colorize_decision(decision)
            ci_str = f"CI={ci:.3f}" if ci is not None else ""
            al_str = f"AL={al}" if al is not None else ""
            buf_str = f" {DIM}(buffered){RESET}" if buffered else ""
            ghost_str = ""
            if ghost_confirmed:
                ghost_str = f" {MAGENTA}{BOLD}GHOST{RESET}"
            elif ghost_suspect:
                ghost_str = f" {MAGENTA}ghost?{RESET}"
            esc_str = " [ESC]" if escalation else ""

            print(
                f"    {color}{agent_cfg['name']:<12s}{RESET} "
                f"{action_type:<18s} -> {dec_str}  "
                f"{ci_str} {al_str}{ghost_str}{buf_str}{esc_str}  "
                f"{DIM}({umbra_lat:.0f}ms){RESET}"
            )

            # 2. Grok call (if allowed)
            grok_result = None
            if decision not in ("block", "gate") and not cfg.skip_grok:
                prompt = eval_round["prompts"].get(agent_id, "")
                grok_result = grok_chat(
                    xai, api_key, agent_cfg["system"], prompt,
                    model=cfg.model,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens,
                )
                if grok_result["error"]:
                    print(f"      {RED}Grok error: {grok_result['error']}{RESET}")
                else:
                    snippet = grok_result["content"][:100]
                    if len(grok_result["content"]) > 100:
                        snippet += "..."
                    toks = grok_result["tokens_in"] + grok_result["tokens_out"]
                    print(
                        f"      {WHITE}{snippet}{RESET}\n"
                        f"      {DIM}({grok_result['latency_ms']:.0f}ms, "
                        f"{toks} tokens){RESET}"
                    )
            elif decision in ("block", "gate"):
                print(f"      {RED}{decision.upper()} -- skipped Grok call{RESET}")

            # 3. Record
            record: dict[str, Any] = {
                "round": round_idx + 1,
                "task": eval_round["task"],
                "agent": agent_id,
                "agent_name": agent_cfg["name"],
                "action": action_type,
                "escalation": escalation,
                "umbra_decision": decision,
                "ci": ci,
                "al": al,
                "buffered": buffered,
                "ghost_suspect": ghost_suspect,
                "ghost_confirmed": ghost_confirmed,
                "umbra_latency_ms": round(umbra_lat, 2),
                "grok_latency_ms": grok_result["latency_ms"] if grok_result else None,
                "grok_tokens_in": grok_result["tokens_in"] if grok_result else None,
                "grok_tokens_out": grok_result["tokens_out"] if grok_result else None,
                "grok_response_len": (
                    len(grok_result["content"])
                    if grok_result and grok_result["content"]
                    else None
                ),
                "grok_response": (
                    grok_result["content"]
                    if grok_result and grok_result["content"]
                    else None
                ),
                "grok_error": grok_result["error"] if grok_result else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            collector.add_record(record)

    # ── Consistency test ───────────────────────────────────────
    if not cfg.skip_grok and cfg.consistency_runs > 0:
        step_c = step + len(prompts)
        print_section(step_c, f"Consistency test ({cfg.consistency_runs} runs)")

        for run_idx in range(cfg.consistency_runs):
            result = grok_chat(
                xai, api_key,
                CONSISTENCY_PROMPT["system"],
                CONSISTENCY_PROMPT["user"],
                model=cfg.model,
                temperature=cfg.temperature,
            )
            if result["error"]:
                print(f"    Run {run_idx + 1}: {RED}{result['error']}{RESET}")
            else:
                snippet = result["content"][:80]
                if len(result["content"]) > 80:
                    snippet += "..."
                print(f"    Run {run_idx + 1}: {WHITE}{snippet}{RESET}")

            collector.add_consistency({
                "run": run_idx + 1,
                "content": result["content"],
                "latency_ms": result["latency_ms"],
                "tokens_in": result["tokens_in"],
                "tokens_out": result["tokens_out"],
                "error": result["error"],
            })

    # ── Per-agent final status ─────────────────────────────────
    step_s = step + len(prompts) + (1 if not cfg.skip_grok and cfg.consistency_runs > 0 else 0)
    print_section(step_s, "Per-agent final status")
    try:
        resp = umbra.get(f"{cfg.umbra_url}/status").json()
        for a in resp.get("agents", []):
            aid = a["agent"]
            if aid not in AGENTS:
                continue
            color = AGENT_TERM_COLORS.get(aid, WHITE)
            ci_val = a.get("ci", 0)
            al_val = a.get("al", "?")
            rds = a.get("round_count", 0)
            ghost = ""
            if a.get("ghost_confirmed"):
                ghost = f" {MAGENTA}{BOLD}GHOST{RESET}"
            print(f"    {color}{aid:<22s}{RESET} AL={al_val}  CI={ci_val:.4f}  rounds={rds}{ghost}")
    except Exception:
        print(f"    {DIM}(status endpoint not available){RESET}")

    # ── Save ───────────────────────────────────────────────────
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    data = collector.finalize()
    suffix = f"_{cfg.label}" if cfg.label else ""
    json_path = cfg.output_dir / f"{collector.run_id}{suffix}_eval.json"

    import json
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print_section(step_s + 1, "Results saved")
    print(f"    {json_path}")


    # ── Behavioral stability summary ─────────────────────────
    _print_stability_summary(data)

    # ── Summary ────────────────────────────────────────────────
    dc = data["meta"]["decision_counts"]
    print_header("Evaluation Complete")
    print(f"  Rounds:    {len(prompts)}")
    print(f"  Checks:    {data['meta']['total_checks']}")
    print(f"  Decisions: allow={dc['allow']} warn={dc['warn']} gate={dc['gate']} block={dc['block']}")
    print(f"  Ghosts:    {data['meta']['ghost_events']} confirmed, {data['meta']['ghost_suspects']} suspects")
    if data["meta"].get("agent_summary"):
        print(f"\n  Per-agent:")
        for aid, s in data["meta"]["agent_summary"].items():
            ci_f = s.get("ci_final")
            ci_s = f"CI={ci_f:.4f}" if ci_f is not None else "CI=n/a"
            al_f = s.get("al_final")
            al_s = f"AL={al_f}" if al_f is not None else "AL=n/a"
            u_lat = s.get("umbra_latency_avg_ms")
            u_s = f"umbra={u_lat:.0f}ms" if u_lat else ""
            g_lat = s.get("grok_latency_avg_ms")
            g_s = f"grok={g_lat:.0f}ms" if g_lat else ""
            print(f"    {aid:<22s} {ci_s}  {al_s}  {u_s}  {g_s}")
    print()

    return data
