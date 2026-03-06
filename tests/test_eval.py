"""Tests for the grok-eval suite.

Tests cover module imports, data structures,
report generation, and CLI argument parsing. All tests run
offline (no API calls).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure package is importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Module imports ────────────────────────────────────────────────

class TestImports:
    def test_package_version(self):
        from grok_eval import __version__
        assert __version__ == "0.3.0"

    def test_agents_structure(self):
        from grok_eval.agents import AGENTS, AGENT_IDS, AGENT_COLORS_HEX
        assert len(AGENTS) == 4
        assert len(AGENT_IDS) == 4
        assert set(AGENT_IDS) == {"grok-captain", "grok-harper", "grok-benjamin", "grok-lucas"}
        for aid in AGENT_IDS:
            agent = AGENTS[aid]
            assert "name" in agent
            assert "role" in agent
            assert "system" in agent
            assert "action_cycle" in agent
            assert len(agent["action_cycle"]) == 5
            assert aid in AGENT_COLORS_HEX

    def test_prompts_structure(self):
        from grok_eval.prompts import EVAL_PROMPTS, GHOST_PROMPTS, CONSISTENCY_PROMPT
        assert len(EVAL_PROMPTS) == 30
        assert len(GHOST_PROMPTS) == 10
        for ep in EVAL_PROMPTS:
            assert "task" in ep
            assert "prompts" in ep
            assert len(ep["prompts"]) == 4
        for gp in GHOST_PROMPTS:
            assert "task" in gp
            assert "correct" in gp
            assert "prompts" in gp
            assert "concepts" in gp
            assert isinstance(gp["concepts"], list)
            assert "anti_concepts" in gp
        assert "system" in CONSISTENCY_PROMPT
        assert "user" in CONSISTENCY_PROMPT

    def test_api_constants(self):
        from grok_eval.api import (
            XAI_BASE, GROK_REASONING, GROK_NON_REASONING,
            DEFAULT_UMBRA_URL,
        )
        assert "api.x.ai" in XAI_BASE
        assert "reasoning" in GROK_REASONING
        assert "non-reasoning" in GROK_NON_REASONING
        assert "127.0.0.1" in DEFAULT_UMBRA_URL


# ── Collector ─────────────────────────────────────────────────────

class TestCollector:
    def test_collector_init(self):
        from grok_eval.collector import EvalCollector
        c = EvalCollector("test-model", "http://localhost:8400", 0.7)
        assert c.meta["grok_model"] == "test-model"
        assert c.meta["temperature"] == 0.7
        assert len(c.records) == 0
        assert len(c.consistency) == 0

    def test_collector_add_record(self):
        from grok_eval.collector import EvalCollector
        c = EvalCollector("test-model", "http://localhost:8400")
        c.add_record({"agent": "grok-captain", "umbra_decision": "allow", "ci": 0.1, "al": 1})
        assert len(c.records) == 1

    def test_collector_finalize(self):
        from grok_eval.collector import EvalCollector
        c = EvalCollector("test-model", "http://localhost:8400")
        c.add_record({
            "agent": "grok-captain",
            "umbra_decision": "allow",
            "ci": 0.1,
            "al": 1,
            "umbra_latency_ms": 5.0,
            "grok_latency_ms": 1000.0,
            "grok_tokens_in": 100,
            "grok_tokens_out": 200,
            "ghost_suspected": False,
            "ghost_confirmed": False,
        })
        c.add_record({
            "agent": "grok-benjamin",
            "umbra_decision": "block",
            "ci": 0.8,
            "al": 4,
            "umbra_latency_ms": 3.0,
            "grok_latency_ms": None,
            "grok_tokens_in": None,
            "grok_tokens_out": None,
            "ghost_suspected": False,
            "ghost_confirmed": False,
        })
        data = c.finalize()
        assert data["meta"]["total_checks"] == 2
        assert data["meta"]["decision_counts"]["allow"] == 1
        assert data["meta"]["decision_counts"]["block"] == 1


# ── Report generation ─────────────────────────────────────────────

class TestReport:
    def _sample_data(self) -> dict:
        return {
            "meta": {
                "run_id": "20260306_test",
                "grok_model": "test-model",
                "temperature": 0.7,
                "total_checks": 4,
                "decision_counts": {"allow": 2, "warn": 1, "gate": 1, "block": 0},
                "ghost_events": 0,
                "ghost_suspects": 0,
                "agent_summary": {
                    "grok-captain": {
                        "ci_final": 0.05,
                        "al_final": 1,
                        "grok_latency_avg_ms": 5000.0,
                        "grok_tokens_in_total": 100,
                        "grok_tokens_out_total": 200,
                    },
                },
            },
            "records": [
                {"round": 1, "agent": "grok-captain", "action": "api_call",
                 "umbra_decision": "allow", "ci": 0.05, "al": 1},
            ],
            "consistency": [
                {"run": 1, "content": "CI measures prediction stability.", "latency_ms": 100,
                 "tokens_in": 50, "tokens_out": 20, "error": None},
                {"run": 2, "content": "CI measures prediction stability across variants.", "latency_ms": 110,
                 "tokens_in": 50, "tokens_out": 25, "error": None},
            ],
        }

    def test_report_generation(self):
        from grok_eval.report import generate_report
        data = self._sample_data()
        report = generate_report(data, "test.json")
        assert "# Grok 4.20 Evaluation Report" in report
        assert "test-model" in report
        assert "Captain" in report
        assert "Consistency Test" in report

    def test_report_ghost_section(self):
        from grok_eval.report import generate_report
        data = self._sample_data()
        data["scenarios"] = [
            {
                "task": "Bat and ball",
                "correct_answer": "$0.05",
                "correct_count": 3,
                "wrong_count": 1,
                "ghost_count": 1,
            },
        ]
        report = generate_report(data, "ghost.json")
        assert "Ghost Hunting Results" in report
        assert "Bat and ball" in report
        assert "**1**" in report  # ghost count bolded


# ── CLI argument parsing ──────────────────────────────────────────

class TestCLI:
    def test_run_parser(self):
        import argparse
        from grok_eval.commands.run import add_parser
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        add_parser(sub)
        args = parser.parse_args(["run", "--rounds", "5", "--skip-grok"])
        assert args.rounds == 5
        assert args.skip_grok is True

    def test_sweep_parser(self):
        import argparse
        from grok_eval.commands.sweep import add_parser
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        add_parser(sub)
        args = parser.parse_args(["sweep", "--temps", "0.0,1.0", "--rounds", "3"])
        assert args.temps == "0.0,1.0"
        assert args.rounds == 3

    def test_ghost_parser(self):
        import argparse
        from grok_eval.commands.ghost import add_parser
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        add_parser(sub)
        args = parser.parse_args(["ghost", "--repeats", "5", "--skip-grok"])
        assert args.repeats == 5
        assert args.skip_grok is True

    def test_showdown_parser(self):
        import argparse
        from grok_eval.commands.showdown import add_parser
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        add_parser(sub)
        args = parser.parse_args(["showdown", "--rounds", "3", "--skip-grok"])
        assert args.rounds == 3
        assert args.skip_grok is True


# ── Ghost helpers ─────────────────────────────────────────────────

class TestGhostHelpers:
    def test_concept_check_positive(self):
        from grok_eval.commands.ghost import _concept_check
        scenario = {
            "correct": "The ball costs $0.05",
            "concepts": ["0.05", "five cent", "5 cent"],
            "anti_concepts": ["$0.10"],
        }
        assert _concept_check(scenario, "The ball costs $0.05 after doing the algebra")

    def test_concept_check_synonym(self):
        from grok_eval.commands.ghost import _concept_check
        scenario = {
            "correct": "The ball costs $0.05",
            "concepts": ["0.05", "five cent", "5 cent"],
            "anti_concepts": ["$0.10"],
        }
        assert _concept_check(scenario, "The answer is five cents")

    def test_concept_check_negative(self):
        from grok_eval.commands.ghost import _concept_check
        scenario = {
            "correct": "The ball costs $0.05",
            "concepts": ["0.05", "five cent", "5 cent"],
            "anti_concepts": ["$0.10"],
        }
        assert not _concept_check(scenario, "The answer is ten cents obviously $0.10")

    def test_concept_check_anti_concept_only(self):
        from grok_eval.commands.ghost import _concept_check
        scenario = {
            "correct": "Approximately 1%",
            "concepts": ["~1%", "approximately 1%", "about 1%"],
            "anti_concepts": ["99%", "very likely"],
        }
        assert not _concept_check(scenario, "The probability is 99% that you have the disease")

    def test_keyword_fallback(self):
        from grok_eval.commands.ghost import _keyword_fallback
        assert _keyword_fallback("the ball costs five cents", "the ball costs five cents exactly")
        assert not _keyword_fallback("the ball costs five cents", "the answer is ten dollars")

    def test_avg_jaccard_identical(self):
        from grok_eval.commands.ghost import _avg_jaccard
        texts = ["hello world foo bar", "hello world foo bar"]
        assert _avg_jaccard(texts) == pytest.approx(1.0)

    def test_avg_jaccard_different(self):
        from grok_eval.commands.ghost import _avg_jaccard
        texts = ["apple banana cherry", "dog elephant frog"]
        assert _avg_jaccard(texts) == pytest.approx(0.0)

    def test_avg_jaccard_single(self):
        from grok_eval.commands.ghost import _avg_jaccard
        assert _avg_jaccard(["hello"]) == 0.0


# ── Security ──────────────────────────────────────────────────────

class TestSecurity:
    def test_umbra_url_localhost_allowed(self):
        from grok_eval.api import validate_umbra_url
        assert validate_umbra_url("http://127.0.0.1:8400") == "http://127.0.0.1:8400"
        assert validate_umbra_url("http://localhost:8400") == "http://localhost:8400"

    def test_umbra_url_remote_blocked(self):
        from grok_eval.api import validate_umbra_url
        with pytest.raises(SystemExit):
            validate_umbra_url("http://evil.com:8400")

    def test_umbra_url_internal_ip_blocked(self):
        from grok_eval.api import validate_umbra_url
        with pytest.raises(SystemExit):
            validate_umbra_url("http://192.168.1.1:8400")

    def test_umbra_url_bad_scheme_blocked(self):
        from grok_eval.api import validate_umbra_url
        with pytest.raises(SystemExit):
            validate_umbra_url("ftp://127.0.0.1:8400")

    def test_error_message_no_leakage(self):
        """Verify grok_chat catch-all returns generic error, not str(exception)."""
        from grok_eval.api import grok_chat
        import httpx
        # Use a client pointed at a port that won't connect
        client = httpx.Client(timeout=1.0)
        result = grok_chat(client, "fake-key", "sys", "prompt")
        assert result["error"] is not None
        # Should not contain stack traces or internal paths
        assert "\\" not in (result["error"] or "")
        assert "/" not in (result["error"] or "").replace("request_failed", "")
        client.close()

    def test_report_path_traversal_blocked(self):
        """Verify report command rejects paths outside project directory."""
        from grok_eval.report import _safe_path
        with pytest.raises(SystemExit):
            _safe_path(Path("C:/Windows/System32"), "test")


# ── EvalConfig ────────────────────────────────────────────────────

class TestEvalConfig:
    def test_defaults(self):
        from grok_eval.core import EvalConfig
        cfg = EvalConfig()
        assert cfg.rounds == 30
        assert cfg.temperature == 0.7
        assert cfg.consistency_runs == 3
        assert cfg.skip_grok is False
        assert "reasoning" in cfg.model

    def test_custom(self):
        from grok_eval.core import EvalConfig
        cfg = EvalConfig(rounds=5, temperature=0.0, label="test")
        assert cfg.rounds == 5
        assert cfg.temperature == 0.0
        assert cfg.label == "test"


# ── Behavioral stats ─────────────────────────────────────────────

class TestStats:
    def test_ci_drift_rate_flat(self):
        from grok_eval.stats import ci_drift_rate
        # Constant CI values -> zero slope
        assert ci_drift_rate([0.1, 0.1, 0.1, 0.1]) == pytest.approx(0.0)

    def test_ci_drift_rate_increasing(self):
        from grok_eval.stats import ci_drift_rate
        # Monotonically increasing -> positive slope
        assert ci_drift_rate([0.0, 0.1, 0.2, 0.3]) > 0

    def test_ci_drift_rate_decreasing(self):
        from grok_eval.stats import ci_drift_rate
        # Monotonically decreasing -> negative slope
        assert ci_drift_rate([0.3, 0.2, 0.1, 0.0]) < 0

    def test_ci_drift_rate_single(self):
        from grok_eval.stats import ci_drift_rate
        assert ci_drift_rate([0.5]) == 0.0

    def test_ci_volatility_constant(self):
        from grok_eval.stats import ci_volatility
        assert ci_volatility([0.5, 0.5, 0.5]) == pytest.approx(0.0)

    def test_ci_volatility_variable(self):
        from grok_eval.stats import ci_volatility
        assert ci_volatility([0.0, 1.0, 0.0, 1.0]) > 0

    def test_ci_mean(self):
        from grok_eval.stats import ci_mean
        assert ci_mean([0.1, 0.2, 0.3]) == pytest.approx(0.2)
        assert ci_mean([]) == 0.0

    def test_ci_max(self):
        from grok_eval.stats import ci_max
        assert ci_max([0.1, 0.5, 0.3]) == 0.5
        assert ci_max([]) == 0.0

    def test_rounds_to_escalation_found(self):
        from grok_eval.stats import rounds_to_escalation
        assert rounds_to_escalation([1, 2, 3, 4], threshold=3) == 3

    def test_rounds_to_escalation_not_found(self):
        from grok_eval.stats import rounds_to_escalation
        assert rounds_to_escalation([1, 1, 2, 2], threshold=3) is None

    def test_recovery_rate_full(self):
        from grok_eval.stats import recovery_rate
        # Spike at index 1 (0.1 -> 0.5 -> 0.2) = recovery
        assert recovery_rate([0.1, 0.5, 0.2]) == pytest.approx(1.0)

    def test_recovery_rate_no_recovery(self):
        from grok_eval.stats import recovery_rate
        # Monotonic increase -> no spikes -> perfect stability
        assert recovery_rate([0.1, 0.2, 0.3, 0.4]) == pytest.approx(1.0)

    def test_recovery_rate_short(self):
        from grok_eval.stats import recovery_rate
        assert recovery_rate([0.1, 0.2]) == 0.0

    def test_gate_block_rate(self):
        from grok_eval.stats import gate_block_rate
        assert gate_block_rate(["allow", "gate", "block", "allow"]) == pytest.approx(0.5)
        assert gate_block_rate(["allow", "allow"]) == pytest.approx(0.0)
        assert gate_block_rate([]) == 0.0

    def test_behavioral_profile(self):
        from grok_eval.stats import behavioral_profile
        profile = behavioral_profile(
            ci_values=[0.1, 0.2, 0.3, 0.4, 0.5],
            al_values=[1, 2, 3, 3, 4],
            decisions=["allow", "allow", "warn", "gate", "block"],
        )
        assert "drift_rate" in profile
        assert "volatility" in profile
        assert "ci_mean" in profile
        assert "ci_max" in profile
        assert "rounds_to_al3" in profile
        assert "recovery_rate" in profile
        assert "gate_block_rate" in profile
        assert profile["drift_rate"] > 0  # increasing CI
        assert profile["ci_max"] == 0.5
        assert profile["rounds_to_al3"] == 3
        assert profile["gate_block_rate"] == pytest.approx(0.4)

    def test_behavioral_profile_in_collector(self):
        from grok_eval.collector import EvalCollector
        c = EvalCollector("test-model", "http://localhost:8400")
        for i in range(5):
            c.add_record({
                "agent": "grok-captain",
                "umbra_decision": "allow",
                "ci": 0.1 * (i + 1),
                "al": i,
                "umbra_latency_ms": 5.0,
                "grok_latency_ms": 1000.0,
                "grok_tokens_in": 100,
                "grok_tokens_out": 200,
            })
        data = c.finalize()
        summary = data["meta"]["agent_summary"]["grok-captain"]
        assert "behavioral_profile" in summary
        assert summary["behavioral_profile"]["ci_mean"] > 0


# ── Statistical significance and CIs ─────────────────────────────

class TestStatisticalRigor:
    """Tests for p-values, confidence intervals, reliability, and verdicts."""

    def test_drift_significance_flat(self):
        from grok_eval.stats import ci_drift_significance
        # Constant values -> slope ~0, p ~1, not significant
        result = ci_drift_significance([0.1] * 20)
        assert result["slope"] == pytest.approx(0.0, abs=1e-6)
        assert result["p_value"] >= 0.5
        assert not result["significant_05"]

    def test_drift_significance_strong_trend(self):
        from grok_eval.stats import ci_drift_significance
        # Perfect linear increase -> very significant
        result = ci_drift_significance([0.01 * i for i in range(30)])
        assert result["slope"] > 0
        assert result["p_value"] < 0.001
        assert result["significant_05"]
        assert result["significant_01"]

    def test_drift_significance_too_short(self):
        from grok_eval.stats import ci_drift_significance
        result = ci_drift_significance([0.1, 0.2])
        assert result["p_value"] == 1.0
        assert not result["significant_05"]

    def test_drift_significance_noisy(self):
        from grok_eval.stats import ci_drift_significance
        # Moderately noisy data with mild trend
        import random
        rng = random.Random(42)
        vals = [0.1 + 0.001 * i + rng.gauss(0, 0.05) for i in range(30)]
        result = ci_drift_significance(vals)
        # Should have non-trivial p-value (may or may not be significant)
        assert 0 < result["p_value"] <= 1.0
        assert result["t_stat"] != 0

    def test_mean_confidence_interval(self):
        from grok_eval.stats import mean_confidence_interval
        lo, hi = mean_confidence_interval([0.1, 0.2, 0.3, 0.4, 0.5])
        mean = 0.3
        assert lo < mean < hi
        assert lo > 0
        assert hi < 0.6

    def test_mean_ci_single_value(self):
        from grok_eval.stats import mean_confidence_interval
        lo, hi = mean_confidence_interval([0.42])
        assert lo == hi == 0.42

    def test_proportion_confidence_interval(self):
        from grok_eval.stats import proportion_confidence_interval
        lo, hi = proportion_confidence_interval(5, 20)  # 25%
        assert 0 < lo < 0.25
        assert 0.25 < hi < 1.0

    def test_proportion_ci_edge_zero(self):
        from grok_eval.stats import proportion_confidence_interval
        lo, hi = proportion_confidence_interval(0, 10)
        assert lo == 0.0
        assert hi > 0  # Wilson interval gives nonzero upper even for 0/n

    def test_proportion_ci_edge_all(self):
        from grok_eval.stats import proportion_confidence_interval
        lo, hi = proportion_confidence_interval(10, 10)
        assert lo > 0.5
        assert hi == 1.0

    def test_proportion_ci_empty(self):
        from grok_eval.stats import proportion_confidence_interval
        lo, hi = proportion_confidence_interval(0, 0)
        assert lo == 0.0
        assert hi == 0.0

    def test_split_half_reliability_consistent(self):
        from grok_eval.stats import split_half_reliability
        # Linearly increasing -> odd/even halves strongly correlated
        vals = [0.01 * i for i in range(30)]
        r = split_half_reliability(vals)
        assert r > 0.9  # Should be very high for monotonic data

    def test_split_half_reliability_random(self):
        from grok_eval.stats import split_half_reliability
        import random
        rng = random.Random(99)
        vals = [rng.random() for _ in range(30)]
        r = split_half_reliability(vals)
        # Random data -> low reliability
        assert -1.0 <= r <= 1.0

    def test_split_half_reliability_short(self):
        from grok_eval.stats import split_half_reliability
        assert split_half_reliability([0.1, 0.2, 0.3]) == 0.0

    def test_split_half_constant(self):
        from grok_eval.stats import split_half_reliability
        # Zero variance in both halves -> returns 1.0
        r = split_half_reliability([0.5] * 10)
        assert r == 1.0

    def test_bootstrap_ci_mean(self):
        from grok_eval.stats import bootstrap_ci
        vals = [0.1, 0.2, 0.3, 0.4, 0.5]
        est, lo, hi = bootstrap_ci(vals, lambda v: sum(v) / len(v))
        assert lo <= est <= hi
        assert lo > 0
        assert hi < 0.6

    def test_bootstrap_ci_empty(self):
        from grok_eval.stats import bootstrap_ci
        est, lo, hi = bootstrap_ci([], lambda v: 0.0)
        assert est == 0.0

    def test_classify_stable(self):
        from grok_eval.stats import classify_behavior
        profile = {
            "gate_block_rate": 0.0,
            "drift_significance": {"significant_05": False},
            "volatility": 0.05,
        }
        assert classify_behavior(profile) == "STABLE"

    def test_classify_drifting(self):
        from grok_eval.stats import classify_behavior
        profile = {
            "gate_block_rate": 0.1,
            "drift_significance": {"significant_05": True},
            "volatility": 0.05,
        }
        assert classify_behavior(profile) == "DRIFTING"

    def test_classify_erratic(self):
        from grok_eval.stats import classify_behavior
        profile = {
            "gate_block_rate": 0.1,
            "drift_significance": {"significant_05": False},
            "volatility": 0.20,
        }
        assert classify_behavior(profile) == "ERRATIC"

    def test_classify_gated(self):
        from grok_eval.stats import classify_behavior
        profile = {
            "gate_block_rate": 0.5,
            "drift_significance": {"significant_05": True},
            "volatility": 0.30,
        }
        # GATED takes priority over everything
        assert classify_behavior(profile) == "GATED"

    def test_behavioral_profile_includes_new_fields(self):
        from grok_eval.stats import behavioral_profile
        profile = behavioral_profile(
            ci_values=[0.1, 0.2, 0.15, 0.25, 0.3, 0.2, 0.35, 0.4, 0.3, 0.5],
            al_values=[1, 1, 2, 2, 3, 3, 3, 4, 4, 4],
            decisions=["allow", "allow", "warn", "allow", "gate",
                       "allow", "warn", "block", "gate", "block"],
        )
        # P-value and significance
        assert "drift_significance" in profile
        assert "p_value" in profile["drift_significance"]
        assert "significant_05" in profile["drift_significance"]
        # Confidence intervals
        assert "ci_mean_95ci" in profile
        lo, hi = profile["ci_mean_95ci"]
        assert lo <= profile["ci_mean"] <= hi
        # Gate/block CI
        assert "gate_block_rate_95ci" in profile
        # Split-half
        assert "split_half_reliability" in profile
        assert -1 <= profile["split_half_reliability"] <= 1
        # Verdict
        assert "verdict" in profile
        assert profile["verdict"] in ("STABLE", "DRIFTING", "ERRATIC", "GATED")


class TestBehavioralDrivers:
    """Tests for the behavioral drivers (CI by action type) in collector."""

    def test_drivers_present_in_finalize(self):
        from grok_eval.collector import EvalCollector
        c = EvalCollector("test-model", "http://localhost:8400")
        decisions = ["allow", "allow", "warn", "gate", "allow"]
        for i, dec in enumerate(decisions):
            c.add_record({
                "agent": "grok-captain",
                "umbra_decision": dec,
                "ci": 0.1 * (i + 1),
                "al": i,
                "umbra_latency_ms": 5.0,
                "grok_latency_ms": 1000.0,
                "grok_tokens_in": 100,
                "grok_tokens_out": 200,
            })
        data = c.finalize()
        drivers = data["meta"]["behavioral_drivers"]
        assert "allow" in drivers
        assert "warn" in drivers
        assert "gate" in drivers
        assert drivers["allow"]["count"] == 3
        assert drivers["warn"]["count"] == 1
        assert drivers["gate"]["count"] == 1

    def test_drivers_mean_ci(self):
        from grok_eval.collector import EvalCollector
        c = EvalCollector("test-model", "http://localhost:8400")
        # allow records: CI=0.1, 0.2 -> mean=0.15
        # gate records: CI=0.5, 0.6 -> mean=0.55
        for ci, dec in [(0.1, "allow"), (0.2, "allow"), (0.5, "gate"), (0.6, "gate")]:
            c.add_record({
                "agent": "grok-captain",
                "umbra_decision": dec,
                "ci": ci,
                "al": 1,
                "umbra_latency_ms": 5.0,
                "grok_latency_ms": 1000.0,
                "grok_tokens_in": 100,
                "grok_tokens_out": 200,
            })
        data = c.finalize()
        drivers = data["meta"]["behavioral_drivers"]
        assert drivers["allow"]["mean_ci"] == pytest.approx(0.15)
        assert drivers["gate"]["mean_ci"] == pytest.approx(0.55)
