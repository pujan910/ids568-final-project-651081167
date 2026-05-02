# Risk Register: OPT-125m Inference Service

**Scope:** This register covers risks specific to *this deployment* — the OPT-125m model, the FastAPI serving layer, the in-process cache, and the dynamic batcher. System-level risks (retrieval, tool use, agentic risks) are addressed in `docs/risk-matrix.md` (Component 5).

**Scoring:** Likelihood × Severity, each on a 1–5 scale. Risk score = L × S. Scores ≥ 12 are *high*, 6–11 are *medium*, ≤ 5 are *low*.

**Framework reference:** Categories align with NIST AI RMF (Govern, Map, Measure, Manage) and the four risk classes called out by the assignment: bias, robustness, privacy, compliance.

---

## Bias risks

| ID | Risk | L | S | Score | Mitigation | Owner | Detection signal |
|---|---|---|---|---|---|---|---|
| B-01 | OPT-125m reproduces gender, racial, and religious stereotypes from pretraining data | 5 | 4 | 20 | (1) Block any user-facing deployment of this model; service is dev-only. (2) Out-of-scope statement in Model Card §2 prohibits decision-making use. (3) For any future production use, add a bias-eval suite (e.g., StereoSet, BBQ) gated on minimum scores before promotion. | ML Platform | Manual eval; no automated detection in this build |
| B-02 | English-only model serves users expecting multilingual capability and silently degrades quality on non-English input | 4 | 3 | 12 | (1) Document English-only constraint in Model Card §2 and §5. (2) Future: detect input language at ingress and reject non-English with a structured 400 response. | ML Platform | Prompt-language drift would surface in Component 4's prompt-distribution panel |
| B-03 | Greedy decoding (`do_sample=False`) amplifies the most-likely-token bias and produces repetitive, mode-collapsed outputs | 3 | 2 | 6 | (1) Document the decoding choice in Model Card §1. (2) Expose `temperature` / `top_p` as configurable per-request fields in a future revision (gated on cache-key update — see B-04 below). | ML Platform | Response-length distribution panel (Component 1) — degenerate loops show up as outlier-long responses |

## Robustness risks

| ID | Risk | L | S | Score | Mitigation | Owner | Detection signal |
|---|---|---|---|---|---|---|---|
| R-01 | Memory pressure (currently 82.5% utilized) escalates to OOM under sustained load or with a second model variant loaded | 4 | 5 | 20 | (1) Alert `HighMemoryUsage` in `dashboards/alert_rules.yml` fires at 90% sustained for 5 min. (2) A/B testing of model variants is run as offline simulation (Component 2), not via dual-loaded models. (3) Future: containerize with a hard memory limit so OOM is bounded. | Platform | `llm_memory_percent` gauge |
| R-02 | Batcher is timeout-bound at low load; throughput tuning decisions made on small samples will be statistically invalid | 4 | 3 | 12 | Component 2's experiment specification mandates power calculation, Bonferroni correction, and an explicit "RUN MORE DATA" branch in the decision rule. The current A/B test landed on this branch and we did **not** ship the change. | ML Platform | A/B test framework is the mitigation; logged in `src/ab_test/results.json` |
| R-03 | Cold start is ~1 s for model load + first-token generation; users on the cold path see this latency | 5 | 2 | 10 | (1) Model is loaded once at server startup (not per-request) — see `src/server.py` lifespan handler. (2) Cache makes repeated prompts effectively free. | ML Platform | Bimodal latency in the Component 1 dashboard (cached vs cold) |
| R-04 | Premature optimization without statistical evidence (e.g., shipping the proposed B variant despite p=0.36) | 3 | 3 | 9 | A/B test framework with Bonferroni correction enforces α=0.025 threshold. Decision rule explicitly handles "RUN MORE DATA" outcomes. | ML Platform | `src/ab_test/simulation.py` decision logic |
| R-05 | Single-replica deployment has no redundancy; any process crash takes the service down | 4 | 3 | 12 | (1) Documented as out-of-scope for this academic deployment in Model Card §2. (2) For production: deploy ≥2 replicas behind a load balancer, with shared Redis cache. | Platform | Process-up monitoring (out of scope here) |

## Privacy risks

| ID | Risk | L | S | Score | Mitigation | Owner | Detection signal |
|---|---|---|---|---|---|---|---|
| P-01 | Model regurgitates personal information from its pretraining corpus (CommonCrawl, Reddit) | 3 | 4 | 12 | (1) Out-of-scope statement prohibits user-facing use. (2) Future: add an output PII detector (e.g., Microsoft Presidio) before returning text to clients. (3) Drift detection on response content (Component 4) would flag unusual sequence patterns indicative of memorization. | ML Platform | Manual review only |
| P-02 | Prompts are stored verbatim in the cache, indexed by SHA hash. If the cache file is ever exported, the prompts (potentially including user PII) leak | 3 | 4 | 12 | (1) Cache is in-process memory, not disk-backed in this deployment. (2) Cache key is `hash(prompt + model + max_tokens)`; no user identifier is stored alongside (per M5 design). (3) TTL of 300 s bounds exposure window. (4) For production: encrypt at rest if Redis-backed. | ML Platform | Code review; cache implementation in `src/caching.py` |
| P-03 | Logs from uvicorn / FastAPI may capture request bodies (containing prompts) at ERROR or DEBUG verbosity | 2 | 4 | 8 | (1) Default log level is INFO; FastAPI does not log bodies at INFO. (2) For production: configure structured logging with explicit body redaction. | Platform | Manual log review |

## Compliance risks

| ID | Risk | L | S | Score | Mitigation | Owner | Detection signal |
|---|---|---|---|---|---|---|---|
| C-01 | OPT-125m license is research-only; any commercial use is a license violation | 4 | 5 | 20 | (1) License terms documented in Model Card §1. (2) Out-of-scope statement (§2) prohibits any production / commercial deployment. (3) Repository is academic coursework, distributed under the same constraint. | Author | License review on any model swap |
| C-02 | GDPR / CCPA: if deployed to EU/CA users, the lack of right-to-deletion mechanics on the cache and the model's training-data memorization could constitute a violation | 2 | 5 | 10 | (1) Service is localhost-only in this deployment, so no GDPR/CCPA scope. (2) For production: implement cache eviction on user request, log deletion timestamps in audit trail, and conduct a DPIA. | Legal / Platform | N/A in this deployment |
| C-03 | No documented data retention policy for cached prompts | 3 | 3 | 9 | TTL of 300 s is the de facto retention window. Documented in Model Card §1 and the M5 governance memo. For production: explicit retention policy review. | Platform | Cache TTL config in `src/config.py` |
| C-04 | No content policy or output filter; service will generate any text the model produces | 4 | 4 | 16 | (1) Out-of-scope statement (§2) prohibits user-facing deployment. (2) For production: integrate an output classifier (e.g., toxicity, PII) before returning generated text. | ML Platform | Manual review only in this deployment |

---

## Summary

| Category | High (≥12) | Medium (6–11) | Low (≤5) | Total |
|---|---|---|---|---|
| Bias | 2 | 1 | 0 | 3 |
| Robustness | 3 | 2 | 0 | 5 |
| Privacy | 2 | 1 | 0 | 3 |
| Compliance | 2 | 2 | 0 | 4 |
| **Total** | **9** | **6** | **0** | **15** |

The dominant risk pattern is **inheritance from the upstream model** (B-01, P-01, C-01) and **operational fragility on consumer hardware** (R-01, R-02, R-05). Both classes are mitigated by the same single decision: keeping this service strictly out of any user-facing or commercial deployment. That decision is recorded in the Model Card §2 (Out-of-scope uses) and is enforced by the localhost-only deployment configuration.

The medium-severity risks (B-02, R-04, P-02, C-03) are all mitigated by **operational artifacts already present in this project**: drift detection (Component 4), the A/B test framework (Component 2), the cache key design from Milestone 5, and the audit trail (`logs/audit-trail.json`).

No risk in this register is currently *unmitigated*. All high-severity risks have either preventive mitigations (out-of-scope policy, alert rules, cache key design) or detective mitigations (Component 1 dashboard, Component 4 drift signals).
