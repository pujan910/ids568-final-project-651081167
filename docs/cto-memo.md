# Memo to the CTO: OPT-125m Inference Service Risk Assessment

**To:** CTO
**From:** ML Platform — Pujan Agarwal
**Date:** Final Project, IDS568
**Re:** System-level risk review of the OPT-125m inference service
**Length:** 1 page

---

## Bottom line

The service is well-built within its scope. **Its current "scope" — localhost only, academic, single user — is doing the majority of the risk-management work**. Five of nine high-tier risks become acceptable specifically because we are not exposing this system to real users. Any expansion beyond the current scope requires the mitigations listed below to be implemented first, not after.

## What we shipped

A FastAPI inference server that wraps Meta's `facebook/opt-125m` (a 125M-parameter open-source language model). The system has dynamic request batching, an in-process cache with TTL, full Prometheus instrumentation, alert rules, an A/B testing framework, drift detection, a model card, an audit trail, and this risk review. No real user data passes through it.

## Headline metrics (from this build)

- **Latency:** cached requests return in ~25 ms; cold-cache requests in 3.4–5.0 s.
- **Throughput:** 9.7 req/s under our synthetic load; zero errors over 200 concurrent requests.
- **Cache effectiveness:** 78% hit rate at our tested workload.
- **Memory utilization:** 82% on consumer hardware — the leading saturation indicator.

## The five things you should know

1. **Hallucination is the model's defining characteristic.** OPT-125m has minimal world knowledge and will produce confident, plausible, false statements. We mitigate this by *not* using the service for any user-facing or decision-making purpose. Production use would require a retrieval-grounded architecture; this build is not that.

2. **The model's license is research-only.** Any commercial deployment is a license violation. This is documented in the Model Card and recorded in the audit trail; it constrains where we can take this codebase next.

3. **Authentication does not exist.** No auth on `/generate`, `/metrics`, `/health`. We accept this only because the service runs on localhost. The moment that changes, auth is a precondition.

4. **Workload drift is the operational risk to watch.** Component 4 demonstrates that a shift in incoming prompt distribution (longer prompts, less repetition) cuts cache hit rate from 77% to 44%, doubles latency, and would breach a 1-second SLO if one existed. Our drift detector and cache-hit-rate alert are the live guardrails.

5. **A/B testing discipline already saved a regression.** The proposed batching change (size 4→8, timeout 20→50 ms) was statistically indistinguishable from noise (p = 0.36) — and we did not ship it. The framework that surfaced this answer is the model for any future tuning decision.

## Risk profile at a glance

| Tier | Count | Examples |
|---|---:|---|
| **High** (score 12–25) | 9 | Open ingress, hallucination, license, OOM, toxic output |
| **Medium** (6–11) | 6 | Stale cache after model swap, batcher races, single replica |
| **Low** (≤5) | 1 | Cold-start latency |

Heatmap: `visualizations/risk_heatmap.png`. Full register: `docs/risk-matrix.md`.

## Recommended actions (priority order)

| # | Action | Owner | Trigger | Why |
|---|---|---|---|---|
| 1 | Maintain the out-of-scope policy in writing (Model Card §2) | ML Platform | Now | This single document is the precondition for half the high-tier risks being acceptable |
| 2 | Add a `len(prompt) > 1000` ingress check | ML Platform | Before the next monitoring run | Component 4 found 32% of production-window prompts in the long-outlier band; cheap to block, expensive to allow |
| 3 | Tighten `CacheHitRateDropped` alert from 30% to 60% | ML Platform | This sprint | Earlier signal on workload drift; keeps us ahead of an SLO breach |
| 4 | If we ever deploy non-locally: add TLS, API-key auth, output PII filter, output toxicity filter | Platform / ML Platform | Any deployment outside localhost | The four mitigations that move the high-tier risks (S-01, S-05, S-06, S-07) into the green |
| 5 | If we ever deploy commercially: replace OPT-125m with a commercial-license model | ML Platform | Any commercial deployment | The license constraint is binary |
| 6 | Re-run the A/B test under the drifted workload from Component 4 | ML Platform | Next quarter | The reference-workload conclusion does not generalize to this drifted distribution |

## What we did NOT do, and why

- **No retrieval augmentation.** This is a generative-only endpoint. Adding RAG would unlock real-world utility but introduces a new class of risks (retrieval contamination, exposure) that we have not yet sized. Documented in `docs/governance-review.md` §2.
- **No agentic / tool-calling layer.** The service returns a string. No tools are called, no code is executed. Agentic risks are out of scope. Documented in `docs/governance-review.md` §4.
- **No quality evaluation harness.** We measure latency and cost, not output quality. Any user-facing deployment must add this before launch.

## Where the evidence is

- **Build:** `src/server.py`, `src/batching.py`, `src/caching.py`
- **Monitoring:** `dashboards/prometheus.yml`, `dashboards/alert_rules.yml`, `screenshots/dashboard.png`, `docs/dashboard-interpretation.md`
- **A/B test:** `src/ab_test/simulation.py`, `docs/experiment-specification.md`, `docs/recommendation-memo.md`
- **Governance:** `docs/model-card.md`, `docs/lineage-diagram.png`, `docs/risk-register.md`, `logs/audit-trail.json`
- **Drift:** `src/drift/`, `docs/drift-diagnostic-report.md`, `visualizations/drift_*.png`
- **System risk:** `docs/governance-review.md`, `docs/risk-matrix.md`, `docs/system-boundary-diagram.png`, `visualizations/risk_heatmap.png`, this memo

---

**One-sentence summary for the board:** *The service is fit for academic purpose; it is not fit for any user-facing deployment until six specific mitigations are implemented, and those mitigations are documented and prioritized in the attached risk matrix.*
