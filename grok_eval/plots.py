"""Plot generation for all evaluation modes.

Base plots (6):
    1. CI drift curves per agent
    2. AL heatmap (agent x round)
    3. Decision distribution (grouped bar)
    4. Grok response latency (boxplot)
    5. Token usage per agent
    6. Umbra overhead histogram

Extended plots:
    7. Temperature comparison (CI at different temps)
    8. Model comparison (side-by-side bar)
    9. Ghost scorecard (correct/wrong per scenario)
   10. Consistency similarity matrix
"""

from __future__ import annotations

from pathlib import Path

from .agents import AGENTS, AGENT_IDS, AGENT_COLORS_HEX


def _agent_names() -> dict[str, str]:
    return {k: v["name"] for k, v in AGENTS.items()}


# ── Base plot suite ──────────────────────────────────────────────

def generate_base_plots(data: dict, out_dir: Path, prefix: str) -> list[str]:
    """Generate the 6 standard plots. Returns list of saved filenames."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    records = data["records"]
    names = _agent_names()
    saved: list[str] = []

    # 1. CI drift
    fig, ax = plt.subplots(figsize=(12, 6))
    for aid in AGENT_IDS:
        recs = [r for r in records if r["agent"] == aid and r["ci"] is not None]
        if not recs:
            continue
        ax.plot(
            [r["round"] for r in recs],
            [r["ci"] for r in recs],
            marker="o", linewidth=2, markersize=6,
            label=names[aid], color=AGENT_COLORS_HEX[aid],
        )
    ax.set_xlabel("Round", fontsize=12)
    ax.set_ylabel("Collapse Index (CI)", fontsize=12)
    ax.set_title("CI Drift Per Agent", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    fname = f"{prefix}_ci_drift.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    saved.append(fname)
    print(f"    [1/6] CI drift curves")

    # 2. AL heatmap
    max_round = max(r["round"] for r in records)
    al_matrix = np.full((len(AGENT_IDS), max_round), np.nan)
    for r in records:
        if r["al"] is not None and r["agent"] in AGENT_IDS:
            row = AGENT_IDS.index(r["agent"])
            al_matrix[row, r["round"] - 1] = r["al"]

    fig, ax = plt.subplots(figsize=(12, 4))
    im = ax.imshow(al_matrix, aspect="auto", cmap="RdYlGn_r", vmin=0, vmax=4, interpolation="nearest")
    ax.set_yticks(range(len(AGENT_IDS)))
    ax.set_yticklabels([names[a] for a in AGENT_IDS], fontsize=11)
    ax.set_xticks(range(max_round))
    ax.set_xticklabels([str(i + 1) for i in range(max_round)], fontsize=10)
    ax.set_xlabel("Round", fontsize=12)
    ax.set_title("Authority Level Heatmap", fontsize=14, fontweight="bold")
    cbar = fig.colorbar(im, ax=ax, ticks=[0, 1, 2, 3, 4])
    cbar.set_ticklabels(["AL0", "AL1", "AL2", "AL3", "AL4"])
    for i in range(len(AGENT_IDS)):
        for j in range(max_round):
            val = al_matrix[i, j]
            if not np.isnan(val):
                ax.text(j, i, f"{int(val)}", ha="center", va="center",
                        fontsize=10, fontweight="bold",
                        color="white" if val >= 3 else "black")
    fig.tight_layout()
    fname = f"{prefix}_al_heatmap.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    saved.append(fname)
    print(f"    [2/6] AL heatmap")

    # 3. Decision distribution
    dtypes = ["allow", "warn", "gate", "block"]
    dcolors = ["#2ecc71", "#f39c12", "#e74c3c", "#8b0000"]
    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(AGENT_IDS))
    width = 0.18
    for i, dt in enumerate(dtypes):
        counts = [
            sum(1 for r in records if r["agent"] == aid and r["umbra_decision"] == dt)
            for aid in AGENT_IDS
        ]
        ax.bar(x + i * width, counts, width, label=dt.upper(), color=dcolors[i])
    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels([names[a] for a in AGENT_IDS], fontsize=11)
    ax.set_ylabel("Count", fontsize=12)
    ax.set_title("Decision Distribution Per Agent", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fname = f"{prefix}_decisions.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    saved.append(fname)
    print(f"    [3/6] Decision distribution")

    # 4. Grok latency boxplot
    fig, ax = plt.subplots(figsize=(10, 6))
    lat_data, lat_labels = [], []
    for aid in AGENT_IDS:
        lats = [r["grok_latency_ms"] for r in records if r["agent"] == aid and r.get("grok_latency_ms")]
        if lats:
            lat_data.append(lats)
            lat_labels.append(names[aid])
    if lat_data:
        bp = ax.boxplot(lat_data, labels=lat_labels, patch_artist=True)
        for patch, aid in zip(bp["boxes"], AGENT_IDS[: len(lat_data)]):
            patch.set_facecolor(AGENT_COLORS_HEX.get(aid, "#999"))
            patch.set_alpha(0.7)
        ax.set_ylabel("Latency (ms)", fontsize=12)
        ax.grid(True, alpha=0.3, axis="y")
    else:
        ax.text(0.5, 0.5, "No Grok data (--skip-grok)", ha="center", va="center",
                transform=ax.transAxes, fontsize=14)
    ax.set_title("Grok Response Latency", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fname = f"{prefix}_latency.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    saved.append(fname)
    print(f"    [4/6] Grok latency")

    # 5. Token usage
    fig, ax = plt.subplots(figsize=(10, 6))
    ti_per = [sum((r.get("grok_tokens_in") or 0) for r in records if r["agent"] == a) for a in AGENT_IDS]
    to_per = [sum((r.get("grok_tokens_out") or 0) for r in records if r["agent"] == a) for a in AGENT_IDS]
    x = np.arange(len(AGENT_IDS))
    w = 0.35
    ax.bar(x - w / 2, ti_per, w, label="Input", color="#3498db")
    ax.bar(x + w / 2, to_per, w, label="Output", color="#e74c3c")
    ax.set_xticks(x)
    ax.set_xticklabels([names[a] for a in AGENT_IDS], fontsize=11)
    ax.set_ylabel("Tokens", fontsize=12)
    ax.set_title("Token Usage Per Agent", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fname = f"{prefix}_tokens.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    saved.append(fname)
    print(f"    [5/6] Token usage")

    # 6. Umbra overhead histogram
    fig, ax = plt.subplots(figsize=(10, 5))
    all_lats = [r["umbra_latency_ms"] for r in records]
    if all_lats:
        ax.hist(all_lats, bins=30, color="#00BFFF", edgecolor="black", alpha=0.7)
        avg = sum(all_lats) / len(all_lats)
        p95 = sorted(all_lats)[int(len(all_lats) * 0.95)]
        ax.axvline(avg, color="red", linestyle="--", linewidth=2, label=f"avg={avg:.1f}ms")
        ax.axvline(p95, color="orange", linestyle="--", linewidth=2, label=f"p95={p95:.1f}ms")
        ax.legend(fontsize=11)
    ax.set_xlabel("Latency (ms)", fontsize=12)
    ax.set_ylabel("Count", fontsize=12)
    ax.set_title("Umbra Check Overhead", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fname = f"{prefix}_umbra_overhead.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    saved.append(fname)
    print(f"    [6/6] Umbra overhead")

    return saved


# ── Temperature comparison plot ──────────────────────────────────

def plot_temp_comparison(runs: list[dict], out_dir: Path, prefix: str) -> str:
    """CI drift across temperature settings. Each run is a dict with meta.temperature."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = _agent_names()
    fig, axes = plt.subplots(1, len(AGENT_IDS), figsize=(5 * len(AGENT_IDS), 5), sharey=True)
    if len(AGENT_IDS) == 1:
        axes = [axes]

    temp_colors = {0.0: "#3498db", 0.3: "#2ecc71", 0.7: "#f39c12", 1.0: "#e74c3c"}

    for ax_idx, aid in enumerate(AGENT_IDS):
        ax = axes[ax_idx]
        for run in runs:
            temp = run["meta"]["temperature"]
            recs = [r for r in run["records"] if r["agent"] == aid and r["ci"] is not None]
            if not recs:
                continue
            color = temp_colors.get(temp, "#999")
            ax.plot(
                [r["round"] for r in recs],
                [r["ci"] for r in recs],
                marker="o", linewidth=2, markersize=5,
                label=f"T={temp}", color=color,
            )
        ax.set_title(names[aid], fontsize=12, fontweight="bold")
        ax.set_xlabel("Round")
        if ax_idx == 0:
            ax.set_ylabel("CI")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.set_ylim(bottom=0)

    fig.suptitle("CI Drift by Temperature", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fname = f"{prefix}_temp_comparison.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    return fname


# ── Model comparison plot ────────────────────────────────────────

def plot_model_comparison(runs: list[dict], out_dir: Path, prefix: str) -> str:
    """Side-by-side comparison of models."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    names = _agent_names()
    models = [r["meta"]["grok_model"] for r in runs]
    model_labels = [m.split("-")[-2] if "-" in m else m for m in models]  # short label

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Panel 1: Final CI per agent per model
    ax = axes[0]
    x = np.arange(len(AGENT_IDS))
    w = 0.8 / max(len(runs), 1)
    for i, run in enumerate(runs):
        summary = run["meta"].get("agent_summary", {})
        cis = [summary.get(a, {}).get("ci_final") or 0 for a in AGENT_IDS]
        ax.bar(x + i * w, cis, w, label=model_labels[i])
    ax.set_xticks(x + w * (len(runs) - 1) / 2)
    ax.set_xticklabels([names[a] for a in AGENT_IDS], fontsize=10)
    ax.set_ylabel("Final CI")
    ax.set_title("Final CI by Model", fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    # Panel 2: Avg Grok latency per agent per model
    ax = axes[1]
    for i, run in enumerate(runs):
        summary = run["meta"].get("agent_summary", {})
        lats = [summary.get(a, {}).get("grok_latency_avg_ms") or 0 for a in AGENT_IDS]
        ax.bar(x + i * w, lats, w, label=model_labels[i])
    ax.set_xticks(x + w * (len(runs) - 1) / 2)
    ax.set_xticklabels([names[a] for a in AGENT_IDS], fontsize=10)
    ax.set_ylabel("Avg Latency (ms)")
    ax.set_title("Grok Latency by Model", fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    fig.suptitle("Cross-Model Comparison", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fname = f"{prefix}_model_comparison.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    return fname


# ── Ghost scorecard ──────────────────────────────────────────────

def plot_ghost_scorecard(ghost_data: dict, out_dir: Path, prefix: str) -> str:
    """Scorecard showing correct/wrong/ghost per scenario."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    scenarios = ghost_data.get("scenarios", [])
    if not scenarios:
        return ""

    labels = [s["task"][:40] for s in scenarios]
    correct_counts = [s.get("correct_count", 0) for s in scenarios]
    wrong_counts = [s.get("wrong_count", 0) for s in scenarios]
    ghost_counts = [s.get("ghost_count", 0) for s in scenarios]

    fig, ax = plt.subplots(figsize=(12, max(6, len(labels) * 0.6)))
    y = np.arange(len(labels))
    h = 0.25
    ax.barh(y - h, correct_counts, h, label="Correct", color="#2ecc71")
    ax.barh(y, wrong_counts, h, label="Wrong", color="#f39c12")
    ax.barh(y + h, ghost_counts, h, label="Ghost (stable+wrong)", color="#e74c3c")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Count")
    ax.set_title("Ghost Hunting Scorecard", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3, axis="x")
    fig.tight_layout()
    fname = f"{prefix}_ghost_scorecard.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    return fname


# ── Consistency similarity matrix ────────────────────────────────

def plot_consistency_matrix(consistency: list[dict], out_dir: Path, prefix: str) -> str:
    """Pairwise Jaccard similarity heatmap for consistency runs."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    texts = [c["content"] for c in consistency if c.get("content")]
    if len(texts) < 2:
        return ""

    n = len(texts)
    sim_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            sim_matrix[i, j] = _jaccard(texts[i], texts[j])

    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(sim_matrix, cmap="YlGn", vmin=0, vmax=1)
    for i in range(n):
        for j in range(n):
            ax.text(j, i, f"{sim_matrix[i, j]:.2f}", ha="center", va="center",
                    fontsize=10, color="black" if sim_matrix[i, j] > 0.5 else "white")
    ax.set_xticks(range(n))
    ax.set_xticklabels([f"Run {i + 1}" for i in range(n)], fontsize=10)
    ax.set_yticks(range(n))
    ax.set_yticklabels([f"Run {i + 1}" for i in range(n)], fontsize=10)
    ax.set_title("Consistency: Pairwise Jaccard Similarity", fontsize=14, fontweight="bold")
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fname = f"{prefix}_consistency_matrix.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    return fname


def _jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa and not wb:
        return 1.0
    return len(wa & wb) / len(wa | wb)


# ── Stability analysis plots ────────────────────────────────────

def generate_stability_plots(data: dict, out_dir: Path, prefix: str) -> list[str]:
    """Generate 4 behavioral stability plots. Returns saved filenames.

    Requires agent_summary to contain behavioral_profile stats.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from .stats import ci_drift_rate

    records = data["records"]
    names = _agent_names()
    summary = data.get("meta", {}).get("agent_summary", {})
    saved: list[str] = []

    # 11. CI drift with regression lines
    fig, ax = plt.subplots(figsize=(12, 6))
    for aid in AGENT_IDS:
        recs = [r for r in records if r["agent"] == aid and r["ci"] is not None]
        if not recs:
            continue
        rounds = [r["round"] for r in recs]
        cis = [r["ci"] for r in recs]
        color = AGENT_COLORS_HEX[aid]
        ax.scatter(rounds, cis, color=color, alpha=0.4, s=20)

        # OLS regression line
        if len(cis) >= 2:
            slope = ci_drift_rate(cis)
            y_mean = sum(cis) / len(cis)
            x_mean = (len(cis) - 1) / 2.0
            x_line = np.array([0, len(cis) - 1])
            y_line = y_mean + slope * (x_line - x_mean)
            ax.plot(
                [rounds[0], rounds[-1]], y_line,
                linewidth=2, linestyle="--", color=color,
                label=f"{names[aid]} (slope={slope:+.4f})",
            )
    ax.set_xlabel("Round", fontsize=12)
    ax.set_ylabel("Collapse Index (CI)", fontsize=12)
    ax.set_title("CI Drift with Regression Lines", fontsize=14, fontweight="bold")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    fname = f"{prefix}_drift_regression.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    saved.append(fname)
    print(f"    [S1/4] Drift regression")

    # 12. Volatility bands (mean +/- 1 std dev)
    fig, ax = plt.subplots(figsize=(12, 6))
    for aid in AGENT_IDS:
        recs = [r for r in records if r["agent"] == aid and r["ci"] is not None]
        if not recs:
            continue
        rounds = [r["round"] for r in recs]
        cis = [r["ci"] for r in recs]
        color = AGENT_COLORS_HEX[aid]
        mean_ci = sum(cis) / len(cis)
        if len(cis) >= 2:
            std_ci = (sum((v - mean_ci) ** 2 for v in cis) / (len(cis) - 1)) ** 0.5
        else:
            std_ci = 0.0

        ax.plot(rounds, cis, linewidth=1.5, color=color, label=names[aid])
        ax.fill_between(
            rounds,
            [mean_ci - std_ci] * len(rounds),
            [mean_ci + std_ci] * len(rounds),
            alpha=0.15, color=color,
        )
        ax.axhline(mean_ci, color=color, linestyle=":", alpha=0.5)
    ax.set_xlabel("Round", fontsize=12)
    ax.set_ylabel("Collapse Index (CI)", fontsize=12)
    ax.set_title("CI Volatility Bands (mean +/- 1 std)", fontsize=14, fontweight="bold")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    fname = f"{prefix}_volatility_bands.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    saved.append(fname)
    print(f"    [S2/4] Volatility bands")

    # 13. Escalation timeline (AL over rounds with threshold)
    fig, ax = plt.subplots(figsize=(12, 5))
    al_threshold = 3
    for aid in AGENT_IDS:
        recs = [r for r in records if r["agent"] == aid and r["al"] is not None]
        if not recs:
            continue
        rounds = [r["round"] for r in recs]
        als = [r["al"] for r in recs]
        color = AGENT_COLORS_HEX[aid]
        ax.step(rounds, als, where="mid", linewidth=2, color=color, label=names[aid])
    ax.axhline(al_threshold, color="red", linestyle="--", linewidth=2, alpha=0.7,
               label=f"Escalation threshold (AL{al_threshold})")
    ax.set_xlabel("Round", fontsize=12)
    ax.set_ylabel("Authority Level (AL)", fontsize=12)
    ax.set_title("Escalation Timeline", fontsize=14, fontweight="bold")
    ax.set_yticks([0, 1, 2, 3, 4])
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fname = f"{prefix}_escalation_timeline.png"
    fig.savefig(out_dir / fname, dpi=150)
    plt.close(fig)
    saved.append(fname)
    print(f"    [S3/4] Escalation timeline")

    # 14. Behavioral profile radar chart
    profile_keys = ["drift_rate", "volatility", "ci_mean", "recovery_rate", "gate_block_rate"]
    profile_labels = ["Drift Rate", "Volatility", "CI Mean", "Recovery Rate", "Gate/Block Rate"]
    agents_with_profiles = [
        aid for aid in AGENT_IDS
        if summary.get(aid, {}).get("behavioral_profile")
    ]
    if agents_with_profiles:
        # Normalize each metric to [0, 1] across agents for radar chart
        raw_vals = {
            aid: [summary[aid]["behavioral_profile"].get(k, 0) or 0 for k in profile_keys]
            for aid in agents_with_profiles
        }
        # Find max for each metric to normalize
        n_metrics = len(profile_keys)
        maxes = [
            max(abs(raw_vals[a][i]) for a in agents_with_profiles) or 1.0
            for i in range(n_metrics)
        ]
        norm_vals = {
            aid: [abs(raw_vals[aid][i]) / maxes[i] for i in range(n_metrics)]
            for aid in agents_with_profiles
        }

        angles = np.linspace(0, 2 * np.pi, n_metrics, endpoint=False).tolist()
        angles += angles[:1]  # Close the polygon

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        for aid in agents_with_profiles:
            values = norm_vals[aid] + norm_vals[aid][:1]  # Close
            ax.plot(angles, values, linewidth=2, color=AGENT_COLORS_HEX[aid],
                    label=names[aid])
            ax.fill(angles, values, alpha=0.1, color=AGENT_COLORS_HEX[aid])

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(profile_labels, fontsize=10)
        ax.set_title("Behavioral Profile Radar", fontsize=14, fontweight="bold", pad=20)
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=10)
        fig.tight_layout()
        fname = f"{prefix}_behavioral_radar.png"
        fig.savefig(out_dir / fname, dpi=150, bbox_inches="tight")
        plt.close(fig)
        saved.append(fname)
        print(f"    [S4/4] Behavioral profile radar")
    else:
        print(f"    [S4/4] Behavioral radar -- skipped (no profile data)")

    return saved
