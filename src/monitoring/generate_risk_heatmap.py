"""
Generate a risk heatmap PNG from the risks defined in docs/risk-matrix.md.
Visualizes likelihood × severity with risk IDs placed in their cells.
Output: visualizations/risk_heatmap.png
"""
import os
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict

OUT = "visualizations/risk_heatmap.png"

# (id, likelihood, severity, label_short)
RISKS = [
    ("S-01", 5, 4, "Open ingress"),
    ("S-02", 5, 4, "Hallucination"),
    ("S-03", 3, 5, "License"),
    ("S-04", 4, 4, "Memory OOM"),
    ("S-05", 4, 4, "Toxic output"),
    ("S-06", 3, 4, "Plain HTTP"),
    ("S-07", 3, 4, "PII memorization"),
    ("S-08", 4, 3, "Workload drift"),
    ("S-09", 4, 3, "Long-prompt abuse"),
    ("S-10", 2, 3, "Premature tuning"),
    ("S-11", 3, 2, "Stale cache"),
    ("S-12", 2, 3, "Batcher races"),
    ("S-13", 2, 3, "DEBUG logs"),
    ("S-14", 3, 2, "Non-English input"),
    ("S-15", 5, 1, "Cold start"),
    ("S-16", 3, 3, "Single replica"),
]


def main():
    # Build a 5x5 grid of background colors based on score = L*S
    grid = np.zeros((5, 5))  # rows = severity (5 at top), cols = likelihood (1..5)
    for L in range(1, 6):
        for S in range(1, 6):
            grid[5 - S, L - 1] = L * S

    fig, ax = plt.subplots(figsize=(11, 7.5))

    # Heatmap background
    im = ax.imshow(grid, cmap="RdYlGn_r", vmin=1, vmax=25, aspect="auto", alpha=0.55)

    # Cell labels (the score)
    for L in range(1, 6):
        for S in range(1, 6):
            ax.text(L - 1, 5 - S, f"{L * S}", ha="center", va="center",
                    color="#444", fontsize=8, alpha=0.6)

    # Place risk IDs in their cells, stacking when multiple share a cell
    cell_contents = defaultdict(list)
    for rid, L, S, label in RISKS:
        cell_contents[(L, S)].append(f"{rid} {label}")

    for (L, S), items in cell_contents.items():
        text = "\n".join(items)
        ax.text(L - 1, 5 - S, text, ha="center", va="center",
                fontsize=8.5, fontweight="bold", color="black",
                bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                          edgecolor="black", alpha=0.85))

    ax.set_xticks(range(5))
    ax.set_xticklabels([f"L={i}" for i in range(1, 6)])
    ax.set_yticks(range(5))
    ax.set_yticklabels([f"S={i}" for i in range(5, 0, -1)])
    ax.set_xlabel("Likelihood →", fontweight="bold")
    ax.set_ylabel("Severity ↑", fontweight="bold")
    ax.set_title("System Risk Heatmap — OPT-125m Inference Service\n"
                 "(green = low risk, red = high risk; cell shading = L × S)",
                 fontweight="bold")

    cbar = plt.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cbar.set_label("Risk score (Likelihood × Severity)")

    plt.tight_layout()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    plt.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
