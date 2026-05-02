"""
Generate reference and production datasets for drift detection.

Reference window:   matches the Component 1 baseline (mostly short prompts,
                    ~78% cache hit rate, narrow response length distribution).
Production window:  injects realistic drift:
                      - Prompt length shifts upward (users sending longer queries)
                      - Cache hit rate drops (more unique prompts)
                      - Response length distribution widens (more repetition / refusals)
                      - Outlier prompts appear (very long, malformed inputs)

Output:
    src/drift/data/reference.csv
    src/drift/data/production.csv

Each row represents one observed request with features:
    prompt_length_chars, prompt_token_count, response_length_chars,
    cache_hit, latency_ms, hour_bucket
"""
import os
import numpy as np
import pandas as pd

SEED = 42
OUTPUT_DIR = "src/drift/data"
N_REFERENCE = 1000
N_PRODUCTION = 1000


def generate_reference(rng):
    """Reference window: ~matches Component 1 baseline."""
    # Prompt length: log-normal centered around ~50 chars (the dominant bucket in C1)
    prompt_len = rng.lognormal(mean=3.7, sigma=0.5, size=N_REFERENCE)
    prompt_len = np.clip(prompt_len, 5, 400).astype(int)

    # Token count ≈ chars / 4 (rough rule of thumb)
    token_count = (prompt_len / 4).astype(int)

    # Cache hits ~78% (matches C1 measurement)
    cache_hit = rng.random(N_REFERENCE) < 0.78

    # Response length: narrow distribution, ~60-120 chars
    response_len = rng.normal(loc=90, scale=20, size=N_REFERENCE)
    response_len = np.clip(response_len, 20, 250).astype(int)

    # Latency: bimodal — cache hits ~25ms, misses ~3500ms
    latency = np.where(
        cache_hit,
        rng.normal(25, 5, N_REFERENCE),
        rng.normal(3500, 400, N_REFERENCE),
    )
    latency = np.clip(latency, 5, 8000)

    # Hour bucket: requests evenly spread across a 24h reference window
    hour_bucket = rng.integers(0, 24, N_REFERENCE)

    return pd.DataFrame({
        "prompt_length_chars": prompt_len,
        "prompt_token_count": token_count,
        "response_length_chars": response_len,
        "cache_hit": cache_hit,
        "latency_ms": latency,
        "hour_bucket": hour_bucket,
    })


def generate_production(rng):
    """Production window: drifted distribution."""
    # Prompt length: shifted upward (users sending longer, more complex queries)
    prompt_len = rng.lognormal(mean=4.4, sigma=0.6, size=N_PRODUCTION)
    prompt_len = np.clip(prompt_len, 5, 800).astype(int)

    # Inject 3% outliers — extremely long prompts (potential abuse / malformed inputs)
    n_outliers = int(N_PRODUCTION * 0.03)
    outlier_idx = rng.choice(N_PRODUCTION, n_outliers, replace=False)
    prompt_len[outlier_idx] = rng.integers(1500, 5000, n_outliers)

    token_count = (prompt_len / 4).astype(int)

    # Cache hit rate dropped from 78% to 45% — major drift signal
    cache_hit = rng.random(N_PRODUCTION) < 0.45

    # Response length: widened, with occasional very-long degenerate responses
    response_len = rng.normal(loc=110, scale=45, size=N_PRODUCTION)
    response_len = np.clip(response_len, 20, 400).astype(int)
    # Long-response outliers (greedy decoding loops)
    long_resp_idx = rng.choice(N_PRODUCTION, int(N_PRODUCTION * 0.05), replace=False)
    response_len[long_resp_idx] = rng.integers(400, 1000, len(long_resp_idx))

    # Latency: same bimodal pattern but more cold-path requests
    latency = np.where(
        cache_hit,
        rng.normal(25, 5, N_PRODUCTION),
        rng.normal(3700, 500, N_PRODUCTION),  # slightly slower cold path due to longer prompts
    )
    latency = np.clip(latency, 5, 10000)

    hour_bucket = rng.integers(0, 24, N_PRODUCTION)

    return pd.DataFrame({
        "prompt_length_chars": prompt_len,
        "prompt_token_count": token_count,
        "response_length_chars": response_len,
        "cache_hit": cache_hit,
        "latency_ms": latency,
        "hour_bucket": hour_bucket,
    })


def main():
    rng = np.random.default_rng(SEED)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    ref = generate_reference(rng)
    prod = generate_production(rng)

    ref_path = os.path.join(OUTPUT_DIR, "reference.csv")
    prod_path = os.path.join(OUTPUT_DIR, "production.csv")
    ref.to_csv(ref_path, index=False)
    prod.to_csv(prod_path, index=False)

    print(f"Reference window:  {len(ref)} rows -> {ref_path}")
    print(f"  prompt_length mean = {ref['prompt_length_chars'].mean():.1f} chars")
    print(f"  cache_hit rate     = {ref['cache_hit'].mean():.1%}")
    print(f"  response_length mean = {ref['response_length_chars'].mean():.1f} chars")
    print()
    print(f"Production window: {len(prod)} rows -> {prod_path}")
    print(f"  prompt_length mean = {prod['prompt_length_chars'].mean():.1f} chars")
    print(f"  cache_hit rate     = {prod['cache_hit'].mean():.1%}")
    print(f"  response_length mean = {prod['response_length_chars'].mean():.1f} chars")


if __name__ == "__main__":
    main()
