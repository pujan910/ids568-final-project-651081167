"""
Render A/B test result charts for the recommendation memo.

Produces visualizations/ab_test_results.png with three panels:
    1. Per-trial throughput (A vs B) — boxplot + raw points
    2. Per-trial p99 latency (A vs B) — boxplot + raw points
    3. Throughput difference 95% CI — visual decision plot
"""
import json
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CSV_PATH = "src/ab_test/results.csv"
JSON_PATH = "src/ab_test/results.json"
OUTPUT = "visualizations/ab_test_results.png"


def main():
    df = pd.read_csv(CSV_PATH)
    with open(JSON_PATH) as f:
        analysis = json.load(f)

    # Drop warm-up trials (matching simulation.py)
    df = df[df["trial"] >= analysis["settings"]["warmup_discarded"]].copy()
    a = df[df["variant"] == "A"]
    b = df[df["variant"] == "B"]

    plt.style.use("default")
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle(
        f"A/B Test: Variant A (size=4, timeout=20ms) vs Variant B (size=8, timeout=50ms)\n"
        f"Decision: {analysis['decision']}",
        fontsize=13,
        fontweight="bold",
    )

    color_a = "#4C72B0"
    color_b = "#DD8452"

    # Panel 1: throughput
    ax = axes[0]
    bp = ax.boxplot(
        [a["throughput_rps"], b["throughput_rps"]],
        labels=["A", "B"],
        patch_artist=True,
        widths=0.5,
    )
    for patch, c in zip(bp["boxes"], [color_a, color_b]):
        patch.set_facecolor(c)
        patch.set_alpha(0.6)
    ax.scatter(np.ones(len(a)), a["throughput_rps"], color=color_a, alpha=0.7, s=25, zorder=3)
    ax.scatter(2 * np.ones(len(b)), b["throughput_rps"], color=color_b, alpha=0.7, s=25, zorder=3)
    pt = analysis["primary_test_throughput"]
    ax.set_ylabel("Throughput (req/s)")
    ax.set_title(f"Throughput per trial\np = {pt['p_value']:.4f}, Δ = {pt['relative_change_pct']:+.1f}%")
    ax.grid(True, alpha=0.3)

    # Panel 2: p99 latency
    ax = axes[1]
    bp = ax.boxplot(
        [a["latency_p99_ms"], b["latency_p99_ms"]],
        labels=["A", "B"],
        patch_artist=True,
        widths=0.5,
    )
    for patch, c in zip(bp["boxes"], [color_a, color_b]):
        patch.set_facecolor(c)
        patch.set_alpha(0.6)
    ax.scatter(np.ones(len(a)), a["latency_p99_ms"], color=color_a, alpha=0.7, s=25, zorder=3)
    ax.scatter(2 * np.ones(len(b)), b["latency_p99_ms"], color=color_b, alpha=0.7, s=25, zorder=3)
    gt = analysis["guardrail_test_p99_latency"]
    ax.set_ylabel("p99 Latency (ms)")
    ax.set_title(f"p99 latency per trial (guardrail)\nΔ = {gt['relative_change_pct']:+.1f}% (limit: +25%)")
    ax.grid(True, alpha=0.3)

    # Panel 3: 95% CI on throughput difference
    ax = axes[2]
    ci_lo, ci_hi = pt["ci_95_difference_rps"]
    diff = pt["mean_difference_rps"]
    ax.errorbar(
        [diff],
        [1],
        xerr=[[diff - ci_lo], [ci_hi - diff]],
        fmt="o",
        color="black",
        capsize=10,
        linewidth=2,
        markersize=10,
    )
    ax.axvline(0, color="red", linestyle="--", alpha=0.6, label="No effect (Δ=0)")
    ax.set_yticks([])
    ax.set_ylim(0.5, 1.5)
    ax.set_xlabel("Throughput difference: B − A (req/s)")
    ax.set_title(f"95% CI on throughput difference\n[{ci_lo:.2f}, {ci_hi:.2f}] req/s")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    plt.savefig(OUTPUT, dpi=150, bbox_inches="tight")
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    main()
