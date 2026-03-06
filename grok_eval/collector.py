"""Data collection for evaluation runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .agents import AGENTS
from .stats import behavioral_profile


class EvalCollector:
    """Collects per-check records and consistency runs."""

    def __init__(self, model: str, umbra_url: str, temperature: float = 0.7) -> None:
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.records: list[dict] = []
        self.consistency: list[dict] = []
        self.meta: dict[str, Any] = {
            "run_id": self.run_id,
            "grok_model": model,
            "umbra_url": umbra_url,
            "temperature": temperature,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "agents": list(AGENTS.keys()),
        }

    def add_record(self, record: dict) -> None:
        self.records.append(record)

    def add_consistency(self, record: dict) -> None:
        self.consistency.append(record)

    def finalize(self) -> dict:
        self.meta["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.meta["total_checks"] = len(self.records)
        self.meta["total_consistency_runs"] = len(self.consistency)

        # Decision counts
        decisions = [r["umbra_decision"] for r in self.records]
        self.meta["decision_counts"] = {
            d: decisions.count(d) for d in ["allow", "warn", "gate", "block"]
        }
        self.meta["ghost_events"] = sum(
            1 for r in self.records if r.get("ghost_confirmed")
        )
        self.meta["ghost_suspects"] = sum(
            1 for r in self.records if r.get("ghost_suspect")
        )

        # Per-agent summary
        self.meta["agent_summary"] = self._agent_summary()

        # Behavioral drivers -- CI grouped by action type
        self.meta["behavioral_drivers"] = self._behavioral_drivers()

        return {
            "meta": self.meta,
            "records": self.records,
            "consistency": self.consistency,
        }

    # ── Per-agent summary ─────────────────────────────────────────

    def _agent_summary(self) -> dict:
        summary: dict[str, Any] = {}
        for agent_id in AGENTS:
            recs = [r for r in self.records if r["agent"] == agent_id]
            if not recs:
                continue

            cis = [r["ci"] for r in recs if r["ci"] is not None]
            als = [r["al"] for r in recs if r["al"] is not None]
            umbra_lats = [r["umbra_latency_ms"] for r in recs]
            grok_lats = [
                r["grok_latency_ms"] for r in recs
                if r.get("grok_latency_ms") is not None
            ]
            ti = [r.get("grok_tokens_in", 0) or 0 for r in recs]
            to = [r.get("grok_tokens_out", 0) or 0 for r in recs]
            agent_decs = [r["umbra_decision"] for r in recs]

            summary[agent_id] = {
                "rounds": len(recs),
                "ci_values": cis,
                "ci_final": cis[-1] if cis else None,
                "al_values": als,
                "al_final": als[-1] if als else None,
                "decision_counts": {
                    d: agent_decs.count(d)
                    for d in ["allow", "warn", "gate", "block"]
                },
                "umbra_latency_avg_ms": (
                    round(sum(umbra_lats) / len(umbra_lats), 2)
                    if umbra_lats else None
                ),
                "grok_latency_avg_ms": (
                    round(sum(grok_lats) / len(grok_lats), 2)
                    if grok_lats else None
                ),
                "grok_tokens_in_total": sum(ti),
                "grok_tokens_out_total": sum(to),
                "ghost_events": sum(
                    1 for r in recs if r.get("ghost_confirmed")
                ),
                "behavioral_profile": behavioral_profile(cis, als, agent_decs),
            }
        return summary

    # ── Behavioral drivers ────────────────────────────────────────

    def _behavioral_drivers(self) -> dict:
        """Group CI by Umbra decision type to identify instability drivers.

        Shows which action types (allow/warn/gate/block) correlate with
        higher or lower CI, helping explain WHAT triggers instability
        even though CI internals are opaque.
        """
        action_cis: dict[str, list[float]] = {}
        for r in self.records:
            action = r.get("umbra_decision", "unknown")
            ci = r.get("ci")
            if ci is not None:
                action_cis.setdefault(action, []).append(ci)

        drivers: dict[str, dict] = {}
        for action, cis in action_cis.items():
            n = len(cis)
            mean = sum(cis) / n
            drivers[action] = {
                "count": n,
                "mean_ci": round(mean, 4),
                "max_ci": round(max(cis), 4),
                "min_ci": round(min(cis), 4),
            }
        return drivers
