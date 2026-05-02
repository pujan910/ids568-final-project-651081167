"""
Render drift visualizations for the diagnostic report.

Produces three figures:

    visualizations/drift_distributions.png
        4-panel grid: side-by-side reference vs production distributions
        for prompt_length, response_length, latency, and cache_hit.

    visualizations/drift_psi_summary.png
        Bar chart of PSI per feature with threshold lines (0.10, 0.25).

    visualizations/drift_time_windows.png
        Drift over time windows: PSI computed in 4 production sub-windows
        against the reference, showing whether drift is increasing or stable.
"""
import json
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REF_PATH = "src/drift/data/reference.csv"
PROD_PATH = "src/drift/data/production.csv"
RESULTS_PATH = "src/drift/results.json"
OUT_DIR = "visualizations"


# Re-implement PSI here (small, copy from drift_detection.py logic) so this
# script is independently runnable for time-window analysis.
def psi(reference, production, n_bins=10):
    eps = 1e-6
    quantiles = np.linspace(0, 1, n_bins + 1)
    edges = np.unique(np.quantile(reference, quantiles))
    if len(edges) < 2:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    rc, _ = np.histogram(reference, bins=edges)
    pc, _ = np.histogram(production, bins=edges)
    rp = rc / max(rc.sum(), 1)
    pp = pc / max(pc.sum(), 1)
    rp = np.where(rp == 0, eps, rp)
    pp = np.where(pp == 0, eps, pp)
    return float(np.sum((pp - rp) * np.log(pp / rp)))


def binary_psi(ref_rate, prod_rate):
    eps = 1e-6
    rp = max(ref_rate, eps); rn = max(1 - ref_rate, eps)
    pp = max(prod_rate, eps); pn = max(1 - prod_rate, eps)
    return (pp - rp) * np.log(pp / rp) + (pn - rn) * np.log(pn / rn)


# ---------------------------------------------------------------------------
# Figure 1: side-by-side distributions
# ---------------------------------------------------------------------------
def plot_distributions(ref, prod, results):
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("Reference vs Production Distributions", fontsize=14, fontweight="bold")
    color_ref = "#4C72B0"
    color_prod = "#DD8452"

    feats = [
        ("prompt_length_chars", "Prompt length (chars)", axes[0, 0]),
        ("response_length_chars", "Response length (chars)", axes[0, 1]),
        ("latency_ms", "Latency (ms)", axes[1, 0]),
    ]
    for col, label, ax in feats:
        bins = np.linspace(
            min(ref[col].min(), prod[col].min()),
            max(ref[col].quantile(0.99), prod[col].quantile(0.99)),
            40,
        )
        ax.hist(ref[col], bins=bins, alpha=0.6, label="Reference", color=color_ref, density=True)
        ax.hist(prod[col], bins=bins, alpha=0.6, label="Production", color=color_prod, density=True)
        # Find PSI from results
        psi_val = next((r["psi"] for r in results["features"] if r["feature"] == col), 0.0)
        ax.set_xlabel(label)
        ax.set_ylabel("Density")
        ax.set_title(f"{label} — PSI = {psi_val:.3f}")
        ax.legend()
        ax.grid(True, alpha=0.3)

    # Cache hit bar chart
    ax = axes[1, 1]
    ref_rate = ref["cache_hit"].mean()
    prod_rate = prod["cache_hit"].mean()
    cache_psi = next((r["psi"] for r in results["features"] if r["feature"] == "cache_hit"), 0.0)
    bars = ax.bar(["Reference", "Production"], [ref_rate, prod_rate],
                  color=[color_ref, color_prod], alpha=0.8)
    for bar, v in zip(bars, [ref_rate, prod_rate]):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.01, f"{v:.1%}",
                ha="center", fontweight="bold")
    ax.set_ylim(0, 1)
    ax.set_ylabel("Cache hit rate")
    ax.set_title(f"Cache hit rate — PSI = {cache_psi:.3f}")
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(OUT_DIR, "drift_distributions.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.close()


# ---------------------------------------------------------------------------
# Figure 2: PSI summary
# ---------------------------------------------------------------------------
def plot_psi_summary(results):
    fig, ax = plt.subplots(figsize=(11, 6))
    feats = [r["feature"] for r in results["features"]]
    psis = [r["psi"] for r in results["features"]]
    labels = [r["psi_label"] for r in results["features"]]

    color_map = {
        "stable": "#2ca02c",
        "moderate_drift": "#ff7f0e",
        "significant_drift": "#d62728",
    }
    colors = [color_map[l] for l in labels]

    bars = ax.bar(feats, psis, color=colors, alpha=0.85, edgecolor="black")
    ax.axhline(0.10, color="#888", linestyle="--", linewidth=1.5, label="Stable threshold (0.10)")
    ax.axhline(0.25, color="#444", linestyle="--", linewidth=1.5, label="Significant threshold (0.25)")

    for bar, v in zip(bars, psis):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.03,
                f"{v:.3f}", ha="center", fontweight="bold", fontsize=10)

    ax.set_ylabel("PSI")
    ax.set_title("Population Stability Index by Feature\n(Reference vs Production)",
                 fontweight="bold")
    ax.set_ylim(0, max(psis) * 1.15)
    ax.tick_params(axis="x", rotation=20)
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    out = os.path.join(OUT_DIR, "drift_psi_summary.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.close()


# ---------------------------------------------------------------------------
# Figure 3: drift over time windows
# ---------------------------------------------------------------------------
def plot_time_windows(ref, prod):
    """
    Split the production data into 4 equal time windows and compute PSI for each
    against the (full) reference. This shows whether drift is constant or growing.
    """
    n_windows = 4
    window_size = len(prod) // n_windows
    windows = [
        prod.iloc[i * window_size:(i + 1) * window_size] for i in range(n_windows)
    ]

    feats_to_track = ["prompt_length_chars", "response_length_chars", "latency_ms"]
    cache_track = []
    feat_track = {f: [] for f in feats_to_track}

    for w in windows:
        for f in feats_to_track:
            feat_track[f].append(psi(ref[f].values, w[f].values))
        cache_track.append(binary_psi(ref["cache_hit"].mean(), w["cache_hit"].mean()))

    fig, ax = plt.subplots(figsize=(11, 6))
    x = list(range(1, n_windows + 1))
    markers = ["o", "s", "^", "D"]

    for (feat, vals), m in zip(feat_track.items(), markers):
        ax.plot(x, vals, marker=m, linewidth=2, markersize=8, label=feat)
    ax.plot(x, cache_track, marker="D", linewidth=2, markersize=8, label="cache_hit")

    ax.axhline(0.10, color="#888", linestyle="--", linewidth=1, alpha=0.7)
    ax.axhline(0.25, color="#444", linestyle="--", linewidth=1, alpha=0.7)
    ax.text(n_windows + 0.05, 0.10, " stable (0.10)", va="center", fontsize=9, color="#666")
    ax.text(n_windows + 0.05, 0.25, " significant (0.25)", va="center", fontsize=9, color="#444")

    ax.set_xlabel("Production time window")
    ax.set_ylabel("PSI vs reference")
    ax.set_title("Drift Over Production Time Windows", fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([f"Window {i}\n({(i-1)*window_size}-{i*window_size})" for i in x])
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    out = os.path.join(OUT_DIR, "drift_time_windows.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.close()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    ref = pd.read_csv(REF_PATH)
    prod = pd.read_csv(PROD_PATH)
    with open(RESULTS_PATH) as f:
        results = json.load(f)

    plot_distributions(ref, prod, results)
    plot_psi_summary(results)
    plot_time_windows(ref, prod)


if __name__ == "__main__":
    main()
