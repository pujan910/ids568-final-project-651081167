# Recommendation Memo: Batching Configuration A/B Test

**To:** Engineering leadership
**From:** ML Platform team
**Re:** Proposed change to dynamic batching parameters on the LLM inference server
**Date:** Final Project, IDS568
**Decision:** **Run more data — do not ship the change as specified**

---

## TL;DR

We A/B tested a proposal to increase the batching window from `(max_batch_size=4, batch_timeout_ms=20)` to `(max_batch_size=8, batch_timeout_ms=50)` on the `facebook/opt-125m` inference server. Across 40 simulated trials (20 per variant, 4,000 total request observations), the larger batch window did **not** produce a statistically significant throughput improvement, and the guardrail latency metric was unaffected. We recommend keeping Variant A in production and collecting more data before reconsidering the change.

---

## What we measured

| | Variant A (control) | Variant B (treatment) |
|---|---|---|
| Configuration | size=4, timeout=20ms | size=8, timeout=50ms |
| Mean throughput | **3.72 ± 0.27 req/s** | **3.65 ± 0.24 req/s** |
| Mean p99 latency | 26,096 ms | 26,649 ms |

After Bonferroni correction (α = 0.025 across two tests):

- **Primary test (throughput):** Welch's t = −0.92, p = 0.36. **Not significant.** B is 2.1% slower in point estimate, but the 95% CI on the difference is [−0.28, +0.12] req/s, which crosses zero — the data does not support a directional conclusion.
- **Guardrail test (p99 latency):** B shifted by +552 ms (+2.1%), well within the +25% guardrail. The change is benign with respect to tail latency.

## Why we are not shipping B

The proposed change increases queuing time at low load (the larger timeout makes requests wait longer to fill larger batches) without a compensating throughput gain in this experiment's traffic profile. With a 4,000-request sample we had ≥80% power to detect a 15% throughput effect; the observed effect is closer to 2%, in the opposite direction. Shipping a 2% change that is statistically indistinguishable from noise risks introducing a regression we would never be able to confirm.

Importantly, the guardrail metric did **not** flag this as harmful — so the change is safe, just unjustified. There is no operational reason to choose between A and B on this evidence; the smaller, faster-flushing config (A) is the simpler default.

## What we recommend instead

1. **Keep Variant A in production.** It is the current default and shows no measurable disadvantage.
2. **Re-run the test under heavier load.** This experiment ran at moderate concurrency where batches rarely filled regardless of `max_batch_size`. The hypothesis that larger batches help is more likely to be detectable when QPS is high enough that batches reach their size cap before timing out. We propose re-running at 2–3× the current arrival rate.
3. **Instrument batch-fill ratio in production.** The Component 1 dashboard already tracks `llm_batch_size`. Adding a derived metric `batches_full / batches_total` would tell us in real time whether the batcher is throughput-limited (fills) or latency-limited (timeouts), which is the single most useful signal for tuning these parameters.
4. **If we revisit, test the timeout independently of size.** This experiment changed two parameters at once. A future test should change one at a time so we can attribute the effect.

## Tie-back to the rest of the system

This decision feeds Component 3 (model card): the model card's "Performance metrics" section will continue to cite the Variant A throughput numbers as the official baseline. It also feeds Component 5 (risk register): "premature optimization without statistical evidence" is recorded as an organizational risk under the *robustness* category.

---

**Files:**
- Experiment specification: `docs/experiment-specification.md`
- Simulation source: `src/ab_test/simulation.py`
- Raw per-trial data: `src/ab_test/results.csv`
- Statistical results: `src/ab_test/results.json`
- Visualization: `visualizations/ab_test_results.png`
