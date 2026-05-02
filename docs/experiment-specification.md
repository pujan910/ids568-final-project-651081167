# A/B Test Experiment Specification

**System:** LLM inference server serving `facebook/opt-125m` via FastAPI with dynamic batching and in-process caching.
**Experiment owner:** Final Project, IDS568.
**Status:** Specification — to be executed via offline simulation in `src/ab_test/simulation.py`.

---

## 1. Background and motivation

The Milestone 5 server uses dynamic batching with two tunable parameters: `max_batch_size` (how many requests to group per forward pass) and `batch_timeout_ms` (how long the scheduler waits to fill a batch). These parameters trade per-request latency for aggregate throughput. The current production configuration was chosen by single-run benchmarks in M5 without statistical validation. This experiment formalizes that comparison.

## 2. Hypothesis

> **H₁:** Increasing the batching window from `(size=4, timeout=20ms)` to `(size=8, timeout=50ms)` will improve mean throughput on the `/generate` endpoint by at least **+15%**, without inflating p99 latency by more than **+25%**.

> **H₀ (null):** The two configurations have equivalent mean throughput and equivalent p99 latency.

A two-tailed test is used because either direction is operationally meaningful: throughput regression in B would mean the larger batches are *waiting* rather than *amortizing*, and a latency regression would mean p99 has shifted into SLO-breach territory.

## 3. Variants

| | Variant A (control) | Variant B (treatment) |
|---|---|---|
| `max_batch_size` | 4 | 8 |
| `batch_timeout_ms` | 20 | 50 |
| All other settings | identical | identical |

Both variants serve the same model (`facebook/opt-125m`), use the same in-process cache (TTL=300s, max_entries=1000), and run on the same hardware. Cache state is reset between trials so warm-cache leakage cannot bias the comparison.

## 4. Metrics

### Primary metric (decision metric)
- **Throughput**, in requests per second, measured over a fixed-duration trial.

### Guardrail metric (must not regress)
- **p99 end-to-end latency**, in milliseconds, on cold-cache requests only.

### Secondary metrics (descriptive)
- Mean latency, p50, p95
- Cache hit rate (sanity check that cache state is matched between trials)
- Error rate (must be ≈ 0 on both variants for the test to be valid)

### Why split decision vs. guardrail
A naive A/B that ships on the highest-throughput variant can silently triple p99 and degrade user experience for the long tail. The guardrail enforces that we only ship B if it wins on throughput AND does not lose unacceptably on latency. This is the standard production pattern.

## 5. Randomization

Each simulated trial draws an independent random seed and an independent prompt sample from a shared pool. Trials alternate variants in a balanced design (`A, B, A, B, ...`) to prevent any time-correlated noise (warm-up effects, memory pressure drift, OS scheduling jitter) from being confounded with the variant assignment. Within each trial, requests are dispatched at a fixed concurrency to remove client-side variability.

In a real online deployment this would translate to per-request hash-based bucketing (`hash(request_id) mod 2`), which produces a 50/50 split with no ordering bias.

## 6. Sample size and power calculation

We use a **two-sample t-test for difference of means** on per-trial throughput.

**Assumed parameters (informed by Component 1's load test):**
- Baseline (Variant A) mean throughput: ≈ 8 req/s
- Baseline standard deviation: ≈ 1.2 req/s (estimated from request-level latency variance)
- Minimum detectable effect (MDE): **+15%** absolute improvement → +1.2 req/s
- Significance level α = 0.05 (two-sided)
- Statistical power (1 − β) = 0.80

**Required sample size per arm**, using the standard formula for two-sample mean comparison:

$$
n = \frac{2\sigma^2 (z_{1-\alpha/2} + z_{1-\beta})^2}{\Delta^2}
= \frac{2 \cdot 1.2^2 \cdot (1.96 + 0.84)^2}{1.2^2}
\approx 16
$$

We round up to **n = 20 trials per variant** to add margin for the guardrail metric (which has a tighter MDE) and to absorb any single-trial outlier.

**Each trial sends 100 requests at concurrency 4**, so the full experiment delivers 40 trials × 100 = 4,000 simulated request observations.

## 7. Stopping rule and multiple-comparison handling

The experiment is run to its planned 40 trials before any statistical test is computed; we do not peek mid-experiment. We test two metrics (throughput, p99 latency), so we apply a **Bonferroni correction** to control family-wise error: each test is evaluated at α/2 = 0.025.

## 8. Decision rule

| Throughput test (primary) | p99 guardrail | Decision |
|---|---|---|
| B > A, p < 0.025 | p99 not regressed > 25% | **Ship B** |
| B > A, p < 0.025 | p99 regressed > 25% | **Hold** — investigate latency |
| Inconclusive (p ≥ 0.025) | — | **Run more data** or **keep A** |
| A > B, p < 0.025 | — | **Keep A** |

## 9. Validity threats and mitigations

- **Cache leakage between trials** → mitigated by resetting cache state between every trial.
- **Hardware contention** (background processes on the dev machine) → mitigated by running balanced ABAB ordering, so any drift averages out across variants.
- **Cold-start of the model** → first 2 trials per variant discarded as warm-up.
- **Prompt distribution skew** → the same prompt pool and the same RNG draw scheme is used for both variants.

## 10. Reproducibility

The simulation seed is fixed at `42`. Re-running `python src/ab_test/simulation.py` produces identical results. Raw per-trial data is written to `src/ab_test/results.csv` and statistical output to `src/ab_test/results.json`.
