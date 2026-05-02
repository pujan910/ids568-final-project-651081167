"""
Generate the system boundary diagram for Component 5.
Shows: client trust boundary → FastAPI ingress → batcher → cache → model → response,
plus the observability and governance overlays.

Output: docs/system-boundary-diagram.png
"""
import os
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

OUT = "docs/system-boundary-diagram.png"


def box(ax, x, y, w, h, label, sub, color):
    p = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02",
        linewidth=2, edgecolor="black", facecolor=color, alpha=0.85,
    )
    ax.add_patch(p)
    ax.text(x + w / 2, y + h * 0.62, label,
            ha="center", va="center", fontsize=10.5, fontweight="bold")
    ax.text(x + w / 2, y + h * 0.30, sub,
            ha="center", va="center", fontsize=8, color="#222")


def arrow(ax, x1, y1, x2, y2, label=None, dashed=False):
    style = "->,head_width=0.30,head_length=0.45"
    a = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle=style, linewidth=1.8, color="#333",
        linestyle="--" if dashed else "-",
        mutation_scale=15,
    )
    ax.add_patch(a)
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.12, label,
                ha="center", fontsize=8, style="italic", color="#555")


def trust_zone(ax, x, y, w, h, label, color):
    rect = Rectangle((x, y), w, h, linewidth=1.5, edgecolor=color,
                     facecolor=color, alpha=0.08, linestyle="--")
    ax.add_patch(rect)
    ax.text(x + 0.1, y + h - 0.18, label,
            fontsize=9, fontweight="bold", color=color, style="italic")


def main():
    fig, ax = plt.subplots(figsize=(15, 8.5))
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 8.5)
    ax.axis("off")
    fig.suptitle(
        "OPT-125m Inference Service — System Boundary Diagram",
        fontsize=14, fontweight="bold",
    )

    # --- Trust zones (background) ---
    trust_zone(ax, 0.2, 4.5, 2.2, 2.6, "Untrusted (client)", "#cc4444")
    trust_zone(ax, 2.6, 1.5, 9.7, 5.6, "Trusted service boundary", "#3b7ddd")
    trust_zone(ax, 12.6, 4.5, 2.2, 2.6, "Upstream (HF Hub)", "#888888")

    # --- Client side ---
    box(ax, 0.4, 5.4, 1.8, 1.0, "Client", "HTTP POST\n/generate", "#ffd6d6")

    # --- FastAPI ingress ---
    box(ax, 2.9, 5.4, 1.9, 1.0, "FastAPI ingress",
        "Request validation\n(/generate, /metrics, /health)", "#cfe7ff")

    # --- Cache lookup ---
    box(ax, 5.2, 5.4, 1.9, 1.0, "Cache lookup",
        "SHA-keyed in-proc\nLRU + TTL", "#cfe7ff")

    # --- Batcher ---
    box(ax, 7.5, 5.4, 1.9, 1.0, "Dynamic batcher",
        "size ≤ 8, timeout 50 ms\nasyncio.Lock", "#cfe7ff")

    # --- Model ---
    box(ax, 9.8, 5.4, 1.9, 1.0, "OPT-125m",
        "HF transformers\nGreedy decode", "#cfe7ff")

    # --- HF source ---
    box(ax, 12.8, 5.4, 1.9, 1.0, "HF Hub",
        "facebook/opt-125m", "#dddddd")

    # --- Cache write-back ---
    box(ax, 5.2, 3.4, 1.9, 1.0, "Cache write",
        "Store result\nfor TTL", "#cfe7ff")

    # --- Response ---
    box(ax, 0.4, 3.4, 1.8, 1.0, "Response", "JSON to client", "#ffd6d6")

    # --- Observability layer ---
    box(ax, 2.9, 1.7, 9.0, 1.2, "Observability + Drift Layer",
        "Prometheus /metrics · alert_rules.yml · PSI/KS drift detector · audit trail",
        "#fde0a8")

    # --- Arrows: forward path ---
    arrow(ax, 2.2, 5.9, 2.9, 5.9)
    arrow(ax, 4.8, 5.9, 5.2, 5.9)
    arrow(ax, 7.1, 5.9, 7.5, 5.9, "miss", dashed=True)
    arrow(ax, 9.4, 5.9, 9.8, 5.9)
    arrow(ax, 11.7, 5.9, 12.8, 5.9, "load (boot)", dashed=True)

    # Cache hit short-circuit
    arrow(ax, 6.15, 5.4, 6.15, 4.4, "hit", dashed=True)
    arrow(ax, 5.2, 3.9, 2.2, 3.9)

    # Model -> cache write (single L-shaped path, drawn with two segments)
    arrow(ax, 10.7, 5.4, 10.7, 3.9)
    arrow(ax, 10.7, 3.9, 7.1, 3.9)

    # Observability ingestion (dashed lines from each component down)
    for x_center in [3.85, 6.15, 8.45, 10.75]:
        arrow(ax, x_center, 5.4, x_center, 2.9, dashed=True)

    # --- Risk-class callouts on the side ---
    ax.text(0.3, 0.95, "Major risk surfaces", fontsize=10,
            fontweight="bold", color="#333")
    ax.text(0.3, 0.55,
            "1) Open ingress (no authn) · 2) Cache leakage · "
            "3) Hallucination · 4) Toxic / biased output · 5) License compliance",
            fontsize=9, color="#333")

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    plt.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
