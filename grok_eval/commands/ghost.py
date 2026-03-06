"""Ghost hunting: adversarial prompts to detect stable-but-wrong outputs.

A ghost error is: stable + confident + wrong.
This command runs adversarial prompts multiple times and checks if
wrong answers remain consistent (stable), flagging ghost candidates.

Usage:
    python -m grok_eval ghost --rounds 8 --repeats 3
    python -m grok_eval ghost --skip-grok --rounds 5
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..agents import AGENTS, AGENT_IDS
from ..api import (
    DEFAULT_UMBRA_URL,
    DIM,
    GROK_REASONING,
    RED,
    RESET,
    WHITE,
    YELLOW,
    MAGENTA,
    BOLD,
    AGENT_TERM_COLORS,
    colorize_decision,
    get_xai_key,
    grok_chat,
    print_header,
    print_section,
    umbra_check,
)
from ..api import validate_umbra_url
from ..plots import plot_ghost_scorecard
from ..prompts import GHOST_PROMPTS


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("ghost", help="Ghost hunting with adversarial prompts")
    p.add_argument("--rounds", type=int, default=10, help="Scenarios to run (1-10, one per scenario)")
    p.add_argument("--repeats", type=int, default=3, help="Repeat Benjamin prompts N times for stability check")
    p.add_argument("--model", default=GROK_REASONING, help="Model slug")
    p.add_argument("--temperature", type=float, default=0.7, help="Temperature")
    p.add_argument("--umbra-url", default=DEFAULT_UMBRA_URL, help="Umbra URL")
    p.add_argument("--skip-grok", action="store_true", help="Skip Grok API calls")
    p.add_argument("--skip-plots", action="store_true", help="Skip plots")
    p.set_defaults(func=execute)


def execute(args) -> None:
    validate_umbra_url(args.umbra_url)
    api_key = "" if args.skip_grok else get_xai_key()

    with httpx.Client(timeout=30.0) as umbra, httpx.Client(timeout=60.0) as xai:
        _run_ghost(args, api_key, umbra, xai)


def _run_ghost(args, api_key: str, umbra: httpx.Client, xai: httpx.Client) -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    scenarios_used = GHOST_PROMPTS[: max(1, min(10, args.rounds))]

    print_header("Ghost Hunting")
    print(f"  Model:     {args.model}")
    print(f"  Scenarios: {len(scenarios_used)}")
    print(f"  Repeats:   {args.repeats} (for stability check)")
    print(f"  Run ID:    {run_id}")

    total_in = 0
    total_out = 0
    scenario_results: list[dict] = []
    all_records: list[dict] = []

    for s_idx, scenario in enumerate(scenarios_used):
        print_section(s_idx + 1, f"{scenario['task']}")
        print(f"    {DIM}Correct: {scenario['correct']}{RESET}")

        responses: dict[str, list[str]] = {aid: [] for aid in AGENT_IDS}
        scenario_records: list[dict] = []

        # Run each agent once through Umbra + Grok
        for agent_id in AGENT_IDS:
            agent_cfg = AGENTS[agent_id]
            color = AGENT_TERM_COLORS[agent_id]
            cycle = agent_cfg["action_cycle"]
            action_type, escalation = cycle[s_idx % len(cycle)]

            umbra_resp, umbra_lat = umbra_check(
                umbra, args.umbra_url, agent_id, action_type, escalation,
            )
            decision = umbra_resp["decision"]
            dec_str = colorize_decision(decision)
            print(f"    {color}{agent_cfg['name']:<12s}{RESET} -> {dec_str}  {DIM}({umbra_lat:.0f}ms){RESET}")

            grok_result = None
            if decision not in ("block", "gate") and not args.skip_grok:
                prompt = scenario["prompts"].get(agent_id, "")
                grok_result = grok_chat(
                    xai, api_key, agent_cfg["system"], prompt,
                    model=args.model, temperature=args.temperature,
                )
                if grok_result["error"]:
                    print(f"      {RED}Error: {grok_result['error']}{RESET}")
                else:
                    snippet = grok_result["content"][:120]
                    if len(grok_result["content"]) > 120:
                        snippet += "..."
                    print(f"      {WHITE}{snippet}{RESET}")
                    responses[agent_id].append(grok_result["content"])
                    total_in += grok_result["tokens_in"]
                    total_out += grok_result["tokens_out"]

            scenario_records.append({
                "scenario": s_idx + 1,
                "task": scenario["task"],
                "agent": agent_id,
                "action": action_type,
                "decision": decision,
                "response": grok_result["content"] if grok_result else None,
                "latency_ms": grok_result["latency_ms"] if grok_result else None,
            })

        # Stability check: repeat Benjamin's math prompt N times
        benjamin_prompt = scenario["prompts"].get("grok-benjamin", "")
        benjamin_system = AGENTS["grok-benjamin"]["system"]
        stability_responses: list[str] = []

        if not args.skip_grok and args.repeats > 0:
            print(f"\n    {YELLOW}Stability check (Benjamin x{args.repeats}):{RESET}")
            for rep in range(args.repeats):
                result = grok_chat(
                    xai, api_key, benjamin_system, benjamin_prompt,
                    model=args.model, temperature=args.temperature,
                )
                if result["content"]:
                    stability_responses.append(result["content"])
                    total_in += result["tokens_in"]
                    total_out += result["tokens_out"]
                    snippet = result["content"][:80]
                    if len(result["content"]) > 80:
                        snippet += "..."
                    print(f"      Rep {rep + 1}: {WHITE}{snippet}{RESET}")

        # Analyze stability
        correct_count = 0
        wrong_count = 0
        ghost_count = 0

        all_responses = []
        for aid, resps in responses.items():
            all_responses.extend(resps)
        all_responses.extend(stability_responses)

        for resp in all_responses:
            if _concept_check(scenario, resp):
                correct_count += 1
            else:
                wrong_count += 1

        # Ghost = wrong responses that are stable (high similarity)
        if stability_responses and wrong_count > 0:
            wrong_resps = [
                r for r in stability_responses
                if not _concept_check(scenario, r)
            ]
            if len(wrong_resps) >= 2:
                sim = _avg_jaccard(wrong_resps)
                if sim > 0.5:  # high stability among wrong answers
                    ghost_count = len(wrong_resps)
                    print(f"    {MAGENTA}{BOLD}GHOST CANDIDATE: {len(wrong_resps)} stable wrong answers (similarity={sim:.2f}){RESET}")

        scenario_results.append({
            "task": scenario["task"],
            "correct_answer": scenario["correct"],
            "correct_count": correct_count,
            "wrong_count": wrong_count,
            "ghost_count": ghost_count,
            "total_responses": len(all_responses),
            "stability_responses": stability_responses,
        })
        all_records.extend(scenario_records)

    # Save data
    out_dir = Path("data/runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    ghost_data = {
        "meta": {
            "run_id": run_id,
            "command": "ghost",
            "model": args.model,
            "temperature": args.temperature,
            "scenarios": len(scenarios_used),
            "repeats": args.repeats,
            "cost": {
                "tokens_in": total_in,
                "tokens_out": total_out,
            },
        },
        "scenarios": scenario_results,
        "records": all_records,
    }
    json_path = out_dir / f"{run_id}_ghost.json"
    with open(json_path, "w") as f:
        json.dump(ghost_data, f, indent=2, default=str)

    # Plot
    if not args.skip_plots:
        plot_dir = Path("data/plots")
        plot_dir.mkdir(parents=True, exist_ok=True)
        plot_ghost_scorecard(ghost_data, plot_dir, run_id)

    # Summary
    total_ghosts = sum(s["ghost_count"] for s in scenario_results)
    total_wrong = sum(s["wrong_count"] for s in scenario_results)
    total_correct = sum(s["correct_count"] for s in scenario_results)

    print_header("Ghost Hunt Complete")
    print(f"  Scenarios:     {len(scenarios_used)}")
    print(f"  Correct:       {total_correct}")
    print(f"  Wrong:         {total_wrong}")
    print(f"  Ghost signals: {total_ghosts}")
    print(f"  Data:          {json_path}")
    print()


def _concept_check(scenario: dict, response: str) -> bool:
    """Concept-based answer check using explicit concept lists.

    Checks if ANY concept from the scenario's 'concepts' list appears
    in the response. Also checks anti_concepts: if an anti-concept
    appears without any concept, it's wrong.

    Falls back to keyword matching on the 'correct' field if no
    concepts are defined.
    """
    resp_lower = response.lower()
    concepts = scenario.get("concepts", [])
    anti_concepts = scenario.get("anti_concepts", [])

    if concepts:
        has_concept = any(c.lower() in resp_lower for c in concepts)
        if has_concept:
            return True
        # Check anti-concepts: if ONLY anti-concepts present, it's wrong
        if anti_concepts and any(ac.lower() in resp_lower for ac in anti_concepts):
            return False
        # Fallback to keyword check on correct field
        return _keyword_fallback(scenario["correct"].lower(), resp_lower)

    # No concepts defined -- use keyword fallback
    return _keyword_fallback(scenario["correct"].lower(), resp_lower)


def _keyword_fallback(correct_keywords: str, response: str) -> bool:
    """Fallback keyword-based answer check."""
    keywords = [w for w in correct_keywords.split() if len(w) > 3]
    if not keywords:
        return True
    matches = sum(1 for kw in keywords if kw in response)
    return matches >= len(keywords) * 0.5


def _avg_jaccard(texts: list[str]) -> float:
    """Average pairwise Jaccard similarity."""
    if len(texts) < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            wa = set(texts[i].lower().split())
            wb = set(texts[j].lower().split())
            if wa or wb:
                total += len(wa & wb) / len(wa | wb)
            else:
                total += 1.0
            pairs += 1
    return total / pairs if pairs else 0.0
