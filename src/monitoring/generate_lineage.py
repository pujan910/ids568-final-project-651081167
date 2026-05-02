"""
Generate the lineage diagram PNG: data → training → eval → deployment → monitoring.
Output: docs/lineage-diagram.png
"""
import os
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUTPUT = "docs/lineage-diagram.png"


def draw_box(ax, x, y, w, h, label, sublabel, color):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02",
        linewidth=2, edgecolor="black", facecolor=color, alpha=0.85,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h * 0.62, label, ha="center", va="center",
            fontsize=11, fontweight="bold", color="black")
    ax.text(x + w / 2, y + h * 0.30, sublabel, ha="center", va="center",
            fontsize=8, color="#222")


def draw_arrow(ax, x1, y1, x2, y2):
    arrow = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle="->,head_width=0.30,head_length=0.45",
        linewidth=2, color="#444", mutation_scale=15,
    )
    ax.add_patch(arrow)


def main():
    fig, ax = plt.subplots(figsize=(15, 7))
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 7)
    ax.axis("off")

    fig.suptitle(
        "OPT-125m Inference Service — Data & Model Lineage",
        fontsize=14, fontweight="bold",
    )

    # Top row — upstream provenance (training pipeline run by Meta, NOT by us)
    ax.text(1.5, 6.4, "UPSTREAM (Meta AI, 2022) — frozen, inherited",
            fontsize=9, style="italic", color="#666")

    draw_box(ax, 0.3, 5.0, 2.2, 1.0, "Pretraining\nCorpus",
             "BookCorpus, Pile,\nCC-Stories, Reddit", "#fde0a8")
    draw_box(ax, 3.0, 5.0, 2.2, 1.0, "OPT Training",
             "Causal LM\n125M params", "#fde0a8")
    draw_box(ax, 5.7, 5.0, 2.2, 1.0, "OPT-125m\nCheckpoint",
             "HF: facebook/opt-125m", "#fde0a8")

    draw_arrow(ax, 2.5, 5.5, 3.0, 5.5)
    draw_arrow(ax, 5.2, 5.5, 5.7, 5.5)

    # Bridge: HF Hub
    draw_arrow(ax, 6.8, 5.0, 6.8, 4.2)
    ax.text(6.95, 4.6, "transformers.pipeline()", fontsize=8, style="italic")

    # Middle row — our serving & evaluation
    ax.text(0.3, 3.7, "OUR SYSTEM (this repository)",
            fontsize=9, style="italic", color="#666")

    draw_box(ax, 0.3, 2.5, 2.3, 1.2, "Inference\nServer",
             "FastAPI + batcher\n+ in-proc cache", "#a8d8ea")
    draw_box(ax, 3.1, 2.5, 2.3, 1.2, "Evaluation",
             "Load gen + A/B sim\n(Welch t-test)", "#a8d8ea")
    draw_box(ax, 5.9, 2.5, 2.3, 1.2, "Deployment",
             "uvicorn :8000\nlocal / dev only", "#a8d8ea")
    draw_box(ax, 8.7, 2.5, 2.3, 1.2, "Monitoring",
             "Prometheus /metrics\n+ alert rules", "#a8d8ea")
    draw_box(ax, 11.5, 2.5, 2.3, 1.2, "Drift Detection",
             "PSI + KS on\nprompts/responses", "#a8d8ea")

    draw_arrow(ax, 2.6, 3.1, 3.1, 3.1)
    draw_arrow(ax, 5.4, 3.1, 5.9, 3.1)
    draw_arrow(ax, 8.2, 3.1, 8.7, 3.1)
    draw_arrow(ax, 11.0, 3.1, 11.5, 3.1)

    # Feedback loop: monitoring + drift back into evaluation
    draw_arrow(ax, 12.6, 2.5, 12.6, 1.7)
    draw_arrow(ax, 12.6, 1.7, 4.2, 1.7)
    draw_arrow(ax, 4.2, 1.7, 4.2, 2.5)
    ax.text(8.0, 1.4, "Drift / alert signal triggers re-evaluation",
            fontsize=9, style="italic", color="#444", ha="center")

    # Governance overlay
    draw_box(ax, 0.3, 0.1, 14.5, 0.7, "Governance Layer",
             "Model Card · Risk Register · Audit Trail · CTO Risk Memo", "#d4c5e2")

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    plt.savefig(OUTPUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    main()
