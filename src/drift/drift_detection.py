"""
Drift & integrity detection for the LLM inference service.

Compares a reference window against a production window across three feature
types — prompt length, response length, cache hit rate, latency — using:

    1. PSI (Population Stability Index)
       <0.10  : stable
       0.10–0.25 : moderate drift, monitor
       >0.25  : significant drift, investigate

    2. Kolmogorov–Smirnov two-sample test
       Reports p-value for the null hypothesis "same distribution"

    3. Outlier integrity check
       z-score > 3 against the reference distribution

Output:
    src/drift/results.json   — structured drift scores per feature
    Also prints a human-readable summary.

Usage:
    python src/drift/drift_detection.py
"""
import json
import os
from typing import Dict

import numpy as np
import pandas as pd
from scipy import stats

REF_PATH = "src/drift/data/reference.csv"
PROD_PATH = "src/drift/data/production.csv"
OUTPUT = "src/drift/results.json"

# Features to evaluate, with the type of drift we expect to see
NUMERIC_FEATURES = [
    "prompt_length_chars",
    "prompt_token_count",
    "response_length_chars",
    "latency_ms",
]
BINARY_FEATURES = ["cache_hit"]

PSI_THRESHOLDS = {
    "stable": 0.10,
    "moderate": 0.25,
}


# ---------------------------------------------------------------------------
# PSI
# ---------------------------------------------------------------------------
def population_stability_index(reference: np.ndarray, production: np.ndarray, n_bins: int = 10) -> float:
    """
    Standard PSI calculation:
        PSI = sum( (prod_pct - ref_pct) * ln(prod_pct / ref_pct) )
    Bins are fixed by reference quantiles, applied to both samples.
    Empty bins are smoothed with epsilon to avoid log(0).
    """
    eps = 1e-6
    # Build bin edges from reference quantiles
    quantiles = np.linspace(0, 1, n_bins + 1)
    bin_edges = np.unique(np.quantile(reference, quantiles))
    if len(bin_edges) < 2:
        return 0.0
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf

    ref_counts, _ = np.histogram(reference, bins=bin_edges)
    prod_counts, _ = np.histogram(production, bins=bin_edges)

    ref_pct = ref_counts / max(ref_counts.sum(), 1)
    prod_pct = prod_counts / max(prod_counts.sum(), 1)

    ref_pct = np.where(ref_pct == 0, eps, ref_pct)
    prod_pct = np.where(prod_pct == 0, eps, prod_pct)

    psi = np.sum((prod_pct - ref_pct) * np.log(prod_pct / ref_pct))
    return float(psi)


def psi_label(psi: float) -> str:
    if psi < PSI_THRESHOLDS["stable"]:
        return "stable"
    if psi < PSI_THRESHOLDS["moderate"]:
        return "moderate_drift"
    return "significant_drift"


# ---------------------------------------------------------------------------
# Outlier detection
# ---------------------------------------------------------------------------
def outlier_rate(reference: np.ndarray, production: np.ndarray, z_threshold: float = 3.0) -> Dict:
    """
    Calculate fraction of production samples that fall beyond z_threshold
    standard deviations of the reference distribution.
    """
    ref_mean = float(np.mean(reference))
    ref_std = float(np.std(reference, ddof=1))
    if ref_std == 0:
        return {"outlier_rate": 0.0, "outlier_count": 0, "n": int(len(production))}
    z_scores = np.abs((production - ref_mean) / ref_std)
    n_out = int(np.sum(z_scores > z_threshold))
    return {
        "outlier_rate": round(n_out / len(production), 4),
        "outlier_count": n_out,
        "n": int(len(production)),
        "z_threshold": z_threshold,
    }


# ---------------------------------------------------------------------------
# Per-feature pipeline
# ---------------------------------------------------------------------------
def analyze_numeric(name: str, ref: pd.Series, prod: pd.Series) -> Dict:
    psi = population_stability_index(ref.values, prod.values)
    ks_stat, ks_p = stats.ks_2samp(ref.values, prod.values)
    outliers = outlier_rate(ref.values, prod.values)

    return {
        "feature": name,
        "type": "numeric",
        "ref_mean": round(float(ref.mean()), 2),
        "ref_std": round(float(ref.std(ddof=1)), 2),
        "prod_mean": round(float(prod.mean()), 2),
        "prod_std": round(float(prod.std(ddof=1)), 2),
        "mean_shift_pct": round((prod.mean() - ref.mean()) / ref.mean() * 100, 2)
            if ref.mean() else None,
        "psi": round(psi, 4),
        "psi_label": psi_label(psi),
        "ks_statistic": round(float(ks_stat), 4),
        "ks_p_value": float(ks_p),
        "ks_significant_at_001": bool(ks_p < 0.001),
        "outliers": outliers,
    }


def analyze_binary(name: str, ref: pd.Series, prod: pd.Series) -> Dict:
    """
    For binary features (cache_hit), drift = absolute difference in rate.
    Uses a two-proportion z-test for significance.
    """
    ref_rate = float(ref.mean())
    prod_rate = float(prod.mean())
    diff = prod_rate - ref_rate

    # Two-proportion z-test
    n1, n2 = len(ref), len(prod)
    p_pool = (ref.sum() + prod.sum()) / (n1 + n2)
    se = np.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
    z = diff / se if se > 0 else 0.0
    p_value = 2 * (1 - stats.norm.cdf(abs(z)))

    # PSI for a binary: compare the two outcome rates directly.
    # Generic histogram-based PSI breaks on 0/1 data because quantile bin edges collapse.
    eps = 1e-6
    ref_p = max(ref_rate, eps); ref_n = max(1 - ref_rate, eps)
    prod_p = max(prod_rate, eps); prod_n = max(1 - prod_rate, eps)
    psi = (prod_p - ref_p) * np.log(prod_p / ref_p) + (prod_n - ref_n) * np.log(prod_n / ref_n)

    return {
        "feature": name,
        "type": "binary",
        "ref_rate": round(ref_rate, 4),
        "prod_rate": round(prod_rate, 4),
        "absolute_difference": round(diff, 4),
        "relative_change_pct": round(diff / ref_rate * 100, 2) if ref_rate else None,
        "psi": round(psi, 4),
        "psi_label": psi_label(psi),
        "z_statistic": round(float(z), 4),
        "p_value": float(p_value),
        "significant_at_001": bool(p_value < 0.001),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ref = pd.read_csv(REF_PATH)
    prod = pd.read_csv(PROD_PATH)

    print(f"Reference  : {len(ref)} rows")
    print(f"Production : {len(prod)} rows")
    print()

    results = {
        "settings": {
            "reference_path": REF_PATH,
            "production_path": PROD_PATH,
            "psi_thresholds": PSI_THRESHOLDS,
            "ks_significance_level": 0.001,
            "outlier_z_threshold": 3.0,
        },
        "features": [],
    }

    for feat in NUMERIC_FEATURES:
        results["features"].append(analyze_numeric(feat, ref[feat], prod[feat]))

    for feat in BINARY_FEATURES:
        results["features"].append(analyze_binary(feat, ref[feat], prod[feat]))

    # Save
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(results, f, indent=2)

    # Print summary
    print(f"{'Feature':<28} {'PSI':>8} {'Label':<22} {'Mean shift':>14} {'Outlier %':>12}")
    print("-" * 90)
    for r in results["features"]:
        if r["type"] == "numeric":
            shift = f"{r['mean_shift_pct']:+.1f}%" if r["mean_shift_pct"] is not None else "—"
            outl = f"{r['outliers']['outlier_rate'] * 100:.2f}%"
        else:
            shift = f"{r['relative_change_pct']:+.1f}%" if r["relative_change_pct"] is not None else "—"
            outl = "—"
        print(f"{r['feature']:<28} {r['psi']:>8.4f} {r['psi_label']:<22} {shift:>14} {outl:>12}")

    print()
    print(f"Detailed results: {OUTPUT}")

    # Headline finding
    significant = [
        r for r in results["features"]
        if r["psi_label"] == "significant_drift"
    ]
    print()
    print("=" * 90)
    if significant:
        print(f"DRIFT DETECTED on {len(significant)} feature(s):")
        for r in significant:
            print(f"  - {r['feature']}: PSI={r['psi']:.3f} ({r['psi_label']})")
    else:
        print("No significant drift detected.")
    print("=" * 90)


if __name__ == "__main__":
    main()
