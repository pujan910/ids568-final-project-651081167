# Drift Diagnostic Report — OPT-125m Inference Service

**Reference window:** 1,000 requests representative of the Component 1 baseline (mean prompt length 44.5 chars, cache hit rate 76.9%, response length 90.2 chars).
**Production window:** 1,000 requests from a later (synthetic) operational period.
**Detection method:** Population Stability Index + Kolmogorov–Smirnov test + z-score outlier rate.
**Tooling:** Custom implementation in `src/drift/drift_detection.py`; Evidently was installed as a fallback but was not required to surface the drift signals seen here.
**Reproducibility:** All scripts deterministic with `seed=42`. Reference and production CSVs are checked in under `src/drift/data/`.

---
## Scope note: label distribution drift is not applicable

The Component 4 brief asks for label distribution drift "if available." This service is a **generative LLM inference endpoint with no ground-truth labels** — there is no classification target, no regression target, and no human-labeled correctness signal collected at request time. Standard label drift therefore does not apply. The closest analogues are tracked instead: response-length distribution drift (a proxy for output-shape change), latency drift (a proxy for cost regression), and cache hit rate (a proxy for prompt-pattern change). All three are evaluated below.

## Headline finding

**Significant drift on all five tracked features.** Every numeric feature crossed the PSI > 0.25 threshold, and the binary cache-hit feature is also drifted (PSI = 0.481, p < 0.001). The drift is stable across all four production sub-windows, indicating a sustained shift in the input distribution rather than transient noise.

| Feature | PSI | Label | Mean / rate shift | Outliers (z>3) | Action |
|---|---:|---|---:|---:|---|
| `prompt_length_chars` | **1.591** | significant_drift | +344.6% (44.5 → 197.9 chars) | 32.2% | Investigate; retune cache & batching |
| `prompt_token_count` | **1.587** | significant_drift | +356.6% | 32.2% | (correlated with prompt length) |
| `response_length_chars` | **0.994** | significant_drift | +53.1% (90.2 → 138.1 chars) | 24.8% | Investigate; possible decode degeneration |
| `latency_ms` | **0.523** | significant_drift | +152.0% | 0% | Caused by the upstream feature drift |
| `cache_hit` | **0.481** | significant_drift | −43.0% (76.9% → 43.8%) | n/a | **Leading indicator — alert here first** |

PSI ≥ 0.25 is the industry-standard "act on it" threshold. The largest values here (1.59, 1.59, 0.99) are not borderline — they are 4–6× over the threshold, which means the production distribution and the reference distribution are essentially different populations.

---

## Which features drifted most, and why that matters

**1. Prompt length (PSI = 1.591) — the upstream cause.**
Mean prompt length grew from 44.5 to 197.9 characters (+344%). The full distribution shifted right and developed a fat tail of very-long prompts: 32.2% of production requests exceed three reference-standard-deviations from the reference mean, and the maximum observed prompt is in the 1,500–5,000 character range (the injected outlier band).

This is the *upstream* drift. Most of the other shifts are downstream consequences:
- **Cache hit rate dropped** because longer, more varied prompts are less likely to match cached entries.
- **Response length grew** because longer prompts induce longer continuations, especially under greedy decoding which is prone to repetition on high-context inputs.
- **Latency mean increased** because the cache hit rate dropped, sending more requests through the cold-path model.

**2. Cache hit rate (PSI = 0.481) — the highest-value alert.**
The cache hit rate fell from 76.9% to 43.8% — a 43-percentage-point absolute drop. Statistically the change is overwhelming (z ≈ 19, p < 10⁻⁵⁰). Operationally this is the single most actionable signal because:
- It is **observable in real time** via the Component 1 dashboard (no need to label or score outputs).
- It is **causal upstream** — when hit rate drops, throughput and latency immediately follow.
- It does **not require ground truth** — we don't need to know what "good" output looks like to know the workload changed.

This is exactly why `CacheHitRateDropped` (in `dashboards/alert_rules.yml`) fires at 30%: the alert is intentionally tighter than the current 43.8% so that further decline triggers paging.

**3. Response length (PSI = 0.994) — a quality risk, not just a cost risk.**
The response length distribution has both moved right (mean +53%) and developed a long tail (5% of responses exceed 400 characters, vs <1% in the reference). This is consistent with greedy decoding falling into repetition loops on novel inputs — a known OPT-125m failure mode flagged in the model card (Limitations §5, B-03 in the risk register). Beyond cost, the long-tail responses likely contain degenerate output that would degrade user experience if this were a real product.

**4. Latency (PSI = 0.523) — a derived signal.**
Mean latency more than doubled (+152%), which reads dramatic but is mostly mechanical: dropping cache hit rate from 77% to 44% pushes 33 more percent of requests through the ~3.5 s cold path instead of the ~25 ms warm path. The latency drift will resolve automatically if cache hit rate recovers; it is not the primary problem to fix.

**No outliers in latency itself** (z>3 = 0.0%). Latency variance is bounded by the bimodal cache structure, so even though the mean shifted, the per-bucket spreads are similar.

---

## Impact on model performance

The OPT-125m model itself is not retrained or fine-tuned by this drift — but **the operational performance of the system absolutely is**, in three concrete ways:

| Impact | Mechanism | Quantified expectation |
|---|---|---|
| Throughput collapse | Cache hit rate −43pp ⇒ ~2× more requests hitting the cold path ⇒ batcher saturation under the same arrival rate | At constant QPS, expect 30–40% throughput drop versus the reference baseline |
| Latency SLO breach | More cold-path traffic ⇒ user-facing p50 rises from ~25 ms toward ~3.4 s | If a 1-second p95 SLO existed, it would be breached |
| Cost / resource pressure | Same cold-path requests + longer prompts ⇒ longer forward passes, more memory churn | Memory utilization (already 82.5% in Component 1) would rise, with `HighMemoryUsage` alert at risk of firing |

There is no claim about *output quality* drift here, because this service has no quality evaluation harness (acknowledged in Model Card §4). The response length growth is a correlate of quality regression but not proof. A real production deployment would add an output evaluator (BLEU/ROUGE on a golden set, or an LLM-as-judge sample) to make the quality claim directly.

---

## Recommended action plan

Ranked in order of operational priority:

1. **Tighten the cache hit-rate alert.** The current `CacheHitRateDropped` rule fires below 30%. Given the 76.9% reference baseline, fire a *warning* at 60% as well, so the on-call sees the drift before it has fully unwound. This is a one-line change in `dashboards/alert_rules.yml`.

2. **Investigate the upstream cause of prompt-length growth.**
   The drift is most likely caused by one of three things, all worth a 30-minute investigation:
   - A new client that is sending verbose prompts.
   - A bug that is concatenating context into prompts unintentionally.
   - A genuine product change (e.g., a new feature that uses longer queries).

   The shape of the production distribution — bimodal, with a heavy outlier tail — points toward the first or second cause.

3. **Add input integrity checks at the ingress.**
   The 32.2% outlier rate at z>3 includes prompts in the 1,500–5,000 character range. A simple `if len(prompt) > 1000: return 400` at the FastAPI layer would reject the worst tail and protect downstream cost, with no model change required. This should be added before the next monitoring run.

4. **Re-tune batching parameters under the new workload.**
   The Component 2 A/B test concluded "RUN MORE DATA" at the reference workload. Under this drifted workload — much higher prompt length, much lower hit rate — the conclusion may differ. Re-run the A/B test on the production-window distribution before making any tuning decision, per the experiment specification's reproducibility clause.

5. **Do NOT retrain the model.**
   OPT-125m is a pre-trained checkpoint we do not fine-tune. The right intervention to drift here is *operational* (cache, batching, ingress validation), not a model swap. A model swap would be the last resort if quality regression were measured directly, which we cannot currently do.

6. **Log this drift event in the audit trail.**
   Append a `DRIFT_DETECTED` event to `logs/audit-trail.json` referencing this report (slot `EVT-009` was reserved for exactly this purpose). The audit trail is the historical record of what changed in production and why.

---

## Tie-back to the rest of the system

- **Component 1 (monitoring):** every feature in this report is already instrumented in `/metrics`. The alert rules in `dashboards/alert_rules.yml` would have caught `cache_hit` and `prompt_length` drift in real time.
- **Component 2 (A/B test):** the reference workload is what the existing A/B test was run against. The production drift invalidates that test's external validity until rerun.
- **Component 3 (model card / risk register):** drift was anticipated by the risk register entry **R-04** (premature optimization without evidence) and **B-02** (English-only assumption could be violated by drift). Both turned out to be relevant in different ways.
- **Component 5 (system risk):** the upstream cause (an unknown client behavior change) is a system-level concern, not a model concern, and is reflected in the risk matrix.

---

## Files

- Detection logic: `src/drift/drift_detection.py`
- Data generators: `src/drift/generate_data.py`
- Visualizations: `src/drift/plot_drift.py`
- Reference / production data: `src/drift/data/reference.csv`, `src/drift/data/production.csv`
- Numeric results: `src/drift/results.json`
- Charts: `visualizations/drift_distributions.png`, `visualizations/drift_psi_summary.png`, `visualizations/drift_time_windows.png`
