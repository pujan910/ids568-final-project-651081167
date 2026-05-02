"""
Render a Grafana-style dashboard PNG from a Prometheus /metrics snapshot.

Reads dashboards/metrics_snapshot.txt (Prometheus text exposition format),
parses the histograms / counters / gauges, and renders 6 panels:
    1. Latency percentiles (p50, p95, p99) — split cached vs cold
    2. Request throughput + error rate
    3. Cache hit rate over total requests
    4. Batch size distribution
    5. Prompt length distribution (drift signal)
    6. System resources (CPU, memory)

Usage:
    python src/monitoring/render_dashboard.py
"""
import os
import re
from collections import defaultdict

import matplotlib.pyplot as plt
import numpy as np

SNAPSHOT_PATH = "dashboards/metrics_snapshot.txt"
OUTPUT_PATH = "screenshots/dashboard.png"

# ---------------------------------------------------------------------------
# Parser for Prometheus text format
# ---------------------------------------------------------------------------
def parse_metrics(path: str) -> dict:
    """
    Returns:
        {
            "<metric_name>": [(labels_dict, value), ...],
            ...
        }
    """
    metrics = defaultdict(list)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # parse `metric_name{label="x",...} value`
            m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)(\{[^}]*\})?\s+([\-0-9.eE+]+)", line)
            if not m:
                continue
            name, labels_str, value = m.groups()
            labels = {}
            if labels_str:
                # strip { }
                pairs = labels_str[1:-1].split(",")
                for p in pairs:
                    if "=" not in p:
                        continue
                    k, v = p.split("=", 1)
                    labels[k.strip()] = v.strip().strip('"')
            metrics[name].append((labels, float(value)))
    return metrics


def get_value(metrics, name, label_filter=None):
    """Return the first value matching the label filter (or any value)."""
    for labels, val in metrics.get(name, []):
        if label_filter is None or all(labels.get(k) == v for k, v in label_filter.items()):
            return val
    return 0.0


def get_histogram_buckets(metrics, name, label_filter=None):
    """Return sorted [(le, cumulative_count)] for a histogram."""
    buckets = []
    for labels, val in metrics.get(f"{name}_bucket", []):
        if label_filter and not all(labels.get(k) == v for k, v in label_filter.items()):
            continue
        le = labels.get("le")
        if le is None:
            continue
        buckets.append((float("inf") if le == "+Inf" else float(le), val))
    return sorted(buckets, key=lambda x: x[0])


def percentile_from_histogram(buckets, p):
    """Estimate p-th percentile from cumulative histogram buckets via linear interpolation
    within the bucket (matches Prometheus histogram_quantile() semantics)."""
    if not buckets:
        return 0.0
    total = buckets[-1][1]
    if total == 0:
        return 0.0
    target = total * p / 100.0
    prev_le, prev_count = 0.0, 0.0
    for le, count in buckets:
        if count >= target:
            if le == float("inf"):
                return prev_le
            if count == prev_count:
                return le
            # linear interpolation between prev_le and le
            return prev_le + (le - prev_le) * (target - prev_count) / (count - prev_count)
        prev_le, prev_count = le, count
    return buckets[-1][0]


def histogram_to_pdf(buckets):
    """Convert cumulative buckets to (bucket_label, count_in_bucket) for plotting."""
    if not buckets:
        return [], []
    labels, counts = [], []
    prev_count = 0
    prev_le = 0
    for le, count in buckets:
        diff = count - prev_count
        label = f"≤{le}" if le != float("inf") else f">{prev_le}"
        labels.append(label)
        counts.append(diff)
        prev_count = count
        prev_le = le
    return labels, counts


# ---------------------------------------------------------------------------
# Dashboard rendering
# ---------------------------------------------------------------------------
def render(metrics):
    plt.style.use("dark_background")
    fig, axes = plt.subplots(2, 3, figsize=(18, 10), facecolor="#0d1117")
    fig.suptitle(
        "LLM Inference Server — Production Monitoring Dashboard",
        fontsize=16,
        color="white",
        fontweight="bold",
    )
    grafana_orange = "#ff9900"
    grafana_green = "#33b86c"
    grafana_blue = "#5794f2"
    grafana_red = "#f2495c"

    # -----------------------------------------------------------------------
    # Panel 1: Latency percentiles (cached vs cold)
    # -----------------------------------------------------------------------
    ax = axes[0, 0]
    cold_buckets = get_histogram_buckets(
        metrics, "llm_request_latency_seconds", {"cached": "false"}
    )
    cached_buckets = get_histogram_buckets(
        metrics, "llm_request_latency_seconds", {"cached": "true"}
    )
    pcts = [50, 95, 99]
    cold_p = [percentile_from_histogram(cold_buckets, p) * 1000 for p in pcts]
    cached_p = [percentile_from_histogram(cached_buckets, p) * 1000 for p in pcts]
    x = np.arange(len(pcts))
    w = 0.35
    ax.bar(x - w / 2, cold_p, w, label="Cold (cache miss)", color=grafana_orange)
    ax.bar(x + w / 2, cached_p, w, label="Warm (cache hit)", color=grafana_green)
    ax.set_xticks(x)
    ax.set_xticklabels([f"p{p}" for p in pcts])
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Request Latency — Cached vs Cold", color="white")
    ax.legend()
    ax.grid(True, alpha=0.2)

    # -----------------------------------------------------------------------
    # Panel 2: Total requests & error rate
    # -----------------------------------------------------------------------
    ax = axes[0, 1]
    total_success = get_value(metrics, "llm_requests_total", {"status": "success"})
    total_error = get_value(metrics, "llm_requests_total", {"status": "error"})
    total = total_success + total_error
    error_rate = (total_error / total * 100) if total else 0
    ax.bar(["Success", "Error"], [total_success, total_error], color=[grafana_green, grafana_red])
    ax.set_ylabel("Request Count")
    ax.set_title(f"Throughput — {int(total)} total · {error_rate:.2f}% error rate", color="white")
    for i, v in enumerate([total_success, total_error]):
        ax.text(i, v + 0.5, f"{int(v)}", ha="center", color="white", fontweight="bold")
    ax.grid(True, alpha=0.2)

    # -----------------------------------------------------------------------
    # Panel 3: Cache hit rate
    # -----------------------------------------------------------------------
    ax = axes[0, 2]
    hits = get_value(metrics, "llm_cache_hits_total")
    misses = get_value(metrics, "llm_cache_misses_total")
    total_cache = hits + misses
    hit_rate = (hits / total_cache * 100) if total_cache else 0
    ax.pie(
        [hits, misses],
        labels=[f"Hits\n({int(hits)})", f"Misses\n({int(misses)})"],
        colors=[grafana_green, grafana_orange],
        autopct="%1.1f%%",
        startangle=90,
        textprops={"color": "white", "fontweight": "bold"},
    )
    ax.set_title(f"Cache Hit Rate — {hit_rate:.1f}%", color="white")

    # -----------------------------------------------------------------------
    # Panel 4: Batch size distribution
    # -----------------------------------------------------------------------
    ax = axes[1, 0]
    batch_buckets = get_histogram_buckets(metrics, "llm_batch_size")
    labels, counts = histogram_to_pdf(batch_buckets)
    if labels:
        ax.bar(labels, counts, color=grafana_blue)
    ax.set_ylabel("Batches")
    ax.set_xlabel("Batch size (≤ bucket)")
    ax.set_title("Batch Size Distribution", color="white")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(True, alpha=0.2)

    # -----------------------------------------------------------------------
    # Panel 5: Prompt length distribution (drift signal)
    # -----------------------------------------------------------------------
    ax = axes[1, 1]
    prompt_buckets = get_histogram_buckets(metrics, "llm_prompt_length_chars")
    labels, counts = histogram_to_pdf(prompt_buckets)
    if labels:
        ax.bar(labels, counts, color=grafana_orange)
    ax.set_ylabel("Requests")
    ax.set_xlabel("Prompt length (chars)")
    ax.set_title("Prompt Length Distribution — Drift Signal", color="white")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(True, alpha=0.2)

    # -----------------------------------------------------------------------
    # Panel 6: System resources
    # -----------------------------------------------------------------------
    ax = axes[1, 2]
    cpu = get_value(metrics, "llm_cpu_percent")
    mem = get_value(metrics, "llm_memory_percent")
    active = get_value(metrics, "llm_active_requests")
    bars = ax.bar(["CPU %", "Memory %", "Active Reqs"], [cpu, mem, active],
                  color=[grafana_orange, grafana_blue, grafana_green])
    ax.set_ylabel("Value")
    ax.set_title("System Resources", color="white")
    ax.set_ylim(0, max(100, cpu, mem, active) * 1.2)
    for bar, v in zip(bars, [cpu, mem, active]):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 1, f"{v:.1f}",
                ha="center", color="white", fontweight="bold")
    ax.grid(True, alpha=0.2)

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    plt.savefig(OUTPUT_PATH, dpi=150, facecolor="#0d1117", bbox_inches="tight")
    print(f"Dashboard saved to {OUTPUT_PATH}")

    # Also dump the headline numbers to console for the README/interpretation
    print()
    print("=" * 50)
    print("Headline Metrics")
    print("=" * 50)
    print(f"  Total requests:    {int(total)}")
    print(f"  Error rate:        {error_rate:.2f}%")
    print(f"  Cache hit rate:    {hit_rate:.1f}%")
    print(f"  Cold p50:          {cold_p[0]:.1f} ms")
    print(f"  Cold p95:          {cold_p[1]:.1f} ms")
    print(f"  Cold p99:          {cold_p[2]:.1f} ms")
    print(f"  Cached p50:        {cached_p[0]:.1f} ms")
    print(f"  Cached p99:        {cached_p[2]:.1f} ms")
    print(f"  CPU %:             {cpu:.1f}")
    print(f"  Memory %:          {mem:.1f}")


if __name__ == "__main__":
    metrics = parse_metrics(SNAPSHOT_PATH)
    render(metrics)
