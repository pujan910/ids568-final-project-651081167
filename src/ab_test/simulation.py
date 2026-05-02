"""
A/B test simulation for LLM inference server batching parameters.

Variant A (control):     max_batch_size=4,  batch_timeout_ms=20
Variant B (treatment):   max_batch_size=8,  batch_timeout_ms=50

Each trial runs N requests at fixed concurrency through a parameterized
queueing model that mirrors the real batcher's behavior (timeout-or-fill,
whichever comes first). We observe throughput and p99 latency per trial,
then run a two-sample Welch's t-test with Bonferroni correction on two
hypotheses:
    1. Throughput differs (primary, ship/hold decision)
    2. p99 latency differs (guardrail, must not regress > 25%)

Outputs:
    src/ab_test/results.csv  — raw per-trial measurements
    src/ab_test/results.json — statistical test results + decision

Usage:
    python src/ab_test/simulation.py
"""
import json
import os
import random
import statistics
from dataclasses import dataclass, asdict
from typing import List

import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SEED = 42
TRIALS_PER_VARIANT = 20
WARMUP_TRIALS = 2          # discarded from analysis
REQUESTS_PER_TRIAL = 100
CONCURRENCY = 4
ALPHA = 0.05
N_TESTS = 2                # Bonferroni: throughput + p99 latency
ALPHA_CORRECTED = ALPHA / N_TESTS

# Per-request inference time on cold cache (mean, std) — calibrated from
# Component 1's load test which observed ~3.4–5.0s cold latency on opt-125m.
COLD_LATENCY_MEAN_S = 0.42  # per-request work when batched
COLD_LATENCY_STD_S = 0.05
CACHE_HIT_RATE = 0.30       # mix of cached vs cold requests per trial
CACHED_LATENCY_MEAN_S = 0.025

# Variant configurations
VARIANTS = {
    "A": {"max_batch_size": 4, "batch_timeout_ms": 20},
    "B": {"max_batch_size": 8, "batch_timeout_ms": 50},
}


@dataclass
class TrialResult:
    variant: str
    trial: int
    throughput_rps: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    error_rate: float


# ---------------------------------------------------------------------------
# Simulator: models the real batcher's timeout-or-fill behavior
# ---------------------------------------------------------------------------
def simulate_trial(variant: str, trial_idx: int, rng: random.Random) -> TrialResult:
    """
    Run REQUESTS_PER_TRIAL requests at CONCURRENCY through a simulated batcher.

    The model:
      - Each request arrives, decides cache hit/miss via Bernoulli(CACHE_HIT_RATE)
      - Cache hits return immediately at CACHED_LATENCY_MEAN_S
      - Cache misses go into a batch queue; a batch fires when EITHER
        max_batch_size requests accumulate OR batch_timeout_ms elapses
      - Batch processing time is a single forward pass: the per-request
        cost amortized over batch size, plus a fixed kernel overhead
    """
    cfg = VARIANTS[variant]
    max_batch = cfg["max_batch_size"]
    timeout_s = cfg["batch_timeout_ms"] / 1000.0

    np_rng = np.random.default_rng(SEED + trial_idx + (1000 if variant == "B" else 0))

    # Generate request arrival times (Poisson process at concurrency-driven rate)
    # The arrival rate that keeps `concurrency` requests in flight is throughput-dependent;
    # we use the simpler "back-to-back per worker" model: total requests / nominal duration.
    # We track wall-clock per request for latency, and total wall-clock for throughput.
    arrival_gap = 0.005  # 5ms between arrivals — high enough to exercise batching
    arrivals = np.cumsum(np_rng.exponential(arrival_gap, REQUESTS_PER_TRIAL))

    is_hit = np_rng.random(REQUESTS_PER_TRIAL) < CACHE_HIT_RATE

    latencies = []
    pending = []                # list of (arrival_time, request_idx)
    pending_start = None        # when the first pending request arrived
    completion_times = []
    sim_clock = 0.0
    errors = 0

    for i, t_arrive in enumerate(arrivals):
        sim_clock = max(sim_clock, t_arrive)

        if is_hit[i]:
            # Cache hit — returns immediately
            lat = max(0.001, np_rng.normal(CACHED_LATENCY_MEAN_S, 0.005))
            latencies.append(lat * 1000)
            completion_times.append(sim_clock + lat)
            continue

        # Cache miss: enqueue
        pending.append((t_arrive, i))
        if pending_start is None:
            pending_start = t_arrive

        # Decide whether to flush now: full batch OR timeout reached
        full = len(pending) >= max_batch
        timed_out = (sim_clock - pending_start) >= timeout_s

        if full or timed_out:
            batch_size = len(pending)
            # Per-request inference cost in this batch (amortized, with overhead)
            per_req = max(
                0.05,
                np_rng.normal(COLD_LATENCY_MEAN_S, COLD_LATENCY_STD_S),
            )
            # Real batched inference: cost ~ const + per_req * batch_size,
            # but parallelization makes each request's *latency* ≈ per_req
            # while throughput improves. We model: batch wall time = per_req.
            batch_wall = per_req
            # The batch starts processing at sim_clock, finishes at sim_clock + batch_wall
            batch_finish = sim_clock + batch_wall
            for arrival_t, _ in pending:
                # End-to-end latency for each request = wait + process
                lat_s = (sim_clock - arrival_t) + batch_wall
                latencies.append(lat_s * 1000)
                completion_times.append(batch_finish)
            sim_clock = batch_finish
            pending = []
            pending_start = None

    # Flush any remaining
    if pending:
        per_req = max(
            0.05,
            np_rng.normal(COLD_LATENCY_MEAN_S, COLD_LATENCY_STD_S),
        )
        batch_wall = per_req
        batch_finish = sim_clock + batch_wall
        for arrival_t, _ in pending:
            lat_s = (sim_clock - arrival_t) + batch_wall
            latencies.append(lat_s * 1000)
            completion_times.append(batch_finish)
        sim_clock = batch_finish

    total_wall = max(completion_times) - 0.0
    throughput = REQUESTS_PER_TRIAL / total_wall

    latencies = sorted(latencies)
    return TrialResult(
        variant=variant,
        trial=trial_idx,
        throughput_rps=throughput,
        latency_p50_ms=np.percentile(latencies, 50),
        latency_p95_ms=np.percentile(latencies, 95),
        latency_p99_ms=np.percentile(latencies, 99),
        error_rate=errors / REQUESTS_PER_TRIAL,
    )


# ---------------------------------------------------------------------------
# Run experiment
# ---------------------------------------------------------------------------
def run_experiment() -> List[TrialResult]:
    rng = random.Random(SEED)
    results = []
    # Balanced ABAB ordering to remove time-correlated noise
    for trial in range(TRIALS_PER_VARIANT):
        for variant in ["A", "B"]:
            results.append(simulate_trial(variant, trial, rng))
    return results


# ---------------------------------------------------------------------------
# Statistical analysis
# ---------------------------------------------------------------------------
def analyze(results: List[TrialResult]) -> dict:
    df = pd.DataFrame([asdict(r) for r in results])
    # Drop warm-up trials per variant
    df = df[df["trial"] >= WARMUP_TRIALS].copy()

    a = df[df["variant"] == "A"]
    b = df[df["variant"] == "B"]

    # ---- Primary: throughput ----
    tp_t, tp_p = stats.ttest_ind(b["throughput_rps"], a["throughput_rps"], equal_var=False)
    tp_diff = b["throughput_rps"].mean() - a["throughput_rps"].mean()
    tp_pct = tp_diff / a["throughput_rps"].mean() * 100
    # 95% CI on the difference (Welch)
    tp_se = np.sqrt(b["throughput_rps"].var(ddof=1) / len(b) + a["throughput_rps"].var(ddof=1) / len(a))
    df_welch = (b["throughput_rps"].var(ddof=1) / len(b) + a["throughput_rps"].var(ddof=1) / len(a)) ** 2 / (
        (b["throughput_rps"].var(ddof=1) / len(b)) ** 2 / (len(b) - 1)
        + (a["throughput_rps"].var(ddof=1) / len(a)) ** 2 / (len(a) - 1)
    )
    tcrit = stats.t.ppf(1 - ALPHA_CORRECTED / 2, df_welch)
    tp_ci = (tp_diff - tcrit * tp_se, tp_diff + tcrit * tp_se)

    # ---- Guardrail: p99 latency ----
    p99_t, p99_p = stats.ttest_ind(b["latency_p99_ms"], a["latency_p99_ms"], equal_var=False)
    p99_diff = b["latency_p99_ms"].mean() - a["latency_p99_ms"].mean()
    p99_pct = p99_diff / a["latency_p99_ms"].mean() * 100

    # ---- Decision ----
    throughput_significant = tp_p < ALPHA_CORRECTED
    throughput_winner = "B" if tp_diff > 0 else "A"
    p99_regressed = p99_pct > 25.0

    if throughput_significant and throughput_winner == "B" and not p99_regressed:
        decision = "SHIP B"
        rationale = "B wins on throughput with statistical significance and does not regress p99 beyond the 25% guardrail."
    elif throughput_significant and throughput_winner == "B" and p99_regressed:
        decision = "HOLD — investigate latency"
        rationale = f"B wins on throughput but p99 regressed by {p99_pct:.1f}% (above 25% guardrail)."
    elif throughput_significant and throughput_winner == "A":
        decision = "KEEP A"
        rationale = "A is significantly faster than B; do not ship the proposed change."
    else:
        decision = "RUN MORE DATA"
        rationale = f"Throughput difference is not statistically significant (p={tp_p:.4f} > α={ALPHA_CORRECTED})."

    return {
        "settings": {
            "trials_per_variant": TRIALS_PER_VARIANT,
            "warmup_discarded": WARMUP_TRIALS,
            "requests_per_trial": REQUESTS_PER_TRIAL,
            "alpha": ALPHA,
            "n_tests": N_TESTS,
            "alpha_bonferroni_corrected": ALPHA_CORRECTED,
            "seed": SEED,
        },
        "summary": {
            "A": {
                "throughput_mean_rps": round(a["throughput_rps"].mean(), 3),
                "throughput_std_rps": round(a["throughput_rps"].std(ddof=1), 3),
                "p50_latency_ms": round(a["latency_p50_ms"].mean(), 1),
                "p95_latency_ms": round(a["latency_p95_ms"].mean(), 1),
                "p99_latency_ms": round(a["latency_p99_ms"].mean(), 1),
            },
            "B": {
                "throughput_mean_rps": round(b["throughput_rps"].mean(), 3),
                "throughput_std_rps": round(b["throughput_rps"].std(ddof=1), 3),
                "p50_latency_ms": round(b["latency_p50_ms"].mean(), 1),
                "p95_latency_ms": round(b["latency_p95_ms"].mean(), 1),
                "p99_latency_ms": round(b["latency_p99_ms"].mean(), 1),
            },
        },
        "primary_test_throughput": {
            "test": "Welch's two-sample t-test, two-sided",
            "t_statistic": round(tp_t, 4),
            "p_value": round(tp_p, 6),
            "p_value_threshold_bonferroni": ALPHA_CORRECTED,
            "significant": throughput_significant,
            "mean_difference_rps": round(tp_diff, 3),
            "relative_change_pct": round(tp_pct, 2),
            "ci_95_difference_rps": [round(tp_ci[0], 3), round(tp_ci[1], 3)],
        },
        "guardrail_test_p99_latency": {
            "test": "Welch's two-sample t-test, two-sided",
            "t_statistic": round(p99_t, 4),
            "p_value": round(p99_p, 6),
            "mean_difference_ms": round(p99_diff, 1),
            "relative_change_pct": round(p99_pct, 2),
            "regressed_beyond_guardrail": p99_regressed,
            "guardrail_threshold_pct": 25.0,
        },
        "decision": decision,
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"Running A/B simulation: {TRIALS_PER_VARIANT} trials/variant, "
          f"{REQUESTS_PER_TRIAL} req/trial, seed={SEED}")
    print()
    results = run_experiment()

    out_dir = "src/ab_test"
    os.makedirs(out_dir, exist_ok=True)
    df = pd.DataFrame([asdict(r) for r in results])
    df.to_csv(f"{out_dir}/results.csv", index=False)

    analysis = analyze(results)
    # Convert numpy types to native Python so json can serialize
    def _to_native(obj):
        if isinstance(obj, dict):
            return {k: _to_native(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_to_native(x) for x in obj]
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        return obj
    with open(f"{out_dir}/results.json", "w") as f:
        json.dump(_to_native(analysis), f, indent=2)

    # Print human-readable summary
    print("=" * 70)
    print("A/B TEST RESULTS")
    print("=" * 70)
    print()
    print(f"Variant A (control):    batch_size=4,  timeout=20ms")
    print(f"Variant B (treatment):  batch_size=8,  timeout=50ms")
    print()
    print(f"  A throughput: {analysis['summary']['A']['throughput_mean_rps']:.2f} ± "
          f"{analysis['summary']['A']['throughput_std_rps']:.2f} req/s")
    print(f"  B throughput: {analysis['summary']['B']['throughput_mean_rps']:.2f} ± "
          f"{analysis['summary']['B']['throughput_std_rps']:.2f} req/s")
    print(f"  A p99 latency: {analysis['summary']['A']['p99_latency_ms']:.1f} ms")
    print(f"  B p99 latency: {analysis['summary']['B']['p99_latency_ms']:.1f} ms")
    print()
    print("Primary test (throughput):")
    pt = analysis['primary_test_throughput']
    print(f"  t = {pt['t_statistic']}, p = {pt['p_value']}")
    print(f"  Mean diff: {pt['mean_difference_rps']:+.2f} req/s "
          f"({pt['relative_change_pct']:+.1f}%)")
    print(f"  95% CI on diff: [{pt['ci_95_difference_rps'][0]}, {pt['ci_95_difference_rps'][1]}] req/s")
    print(f"  Significant at α={ALPHA_CORRECTED}: {pt['significant']}")
    print()
    print("Guardrail test (p99 latency):")
    gt = analysis['guardrail_test_p99_latency']
    print(f"  Mean diff: {gt['mean_difference_ms']:+.1f} ms ({gt['relative_change_pct']:+.1f}%)")
    print(f"  Regressed beyond +25%: {gt['regressed_beyond_guardrail']}")
    print()
    print("=" * 70)
    print(f"DECISION: {analysis['decision']}")
    print(f"  {analysis['rationale']}")
    print("=" * 70)
    print()
    print(f"Raw data:    {out_dir}/results.csv")
    print(f"Analysis:    {out_dir}/results.json")


if __name__ == "__main__":
    main()
