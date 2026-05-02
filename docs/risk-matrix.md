# Risk Matrix — OPT-125m Inference Service (System-Level)

System-level risks identified during the Component 5 governance review. Risks are scored on **Likelihood (1–5) × Severity (1–5)**, where 1 = rare/minor and 5 = near-certain/catastrophic.

- **Score 1–5:** low. Monitor only.
- **Score 6–11:** medium. Mitigation required before any expansion of deployment scope.
- **Score 12–25:** high. Mitigation required *now*, regardless of deployment scope.

Visual: `visualizations/risk_heatmap.png`.

| ID | Risk | Category | L | S | Score | Tier | Mitigation | Detection / monitoring |
|---|---|---|---|---|---|---|---|---|
| **S-01** | Open ingress with no authentication on `/generate` and `/metrics` allows any local process to consume compute or scrape metrics | Security | 5 | 4 | **20** | High | Add API-key auth at FastAPI dependency layer; restrict `/metrics` to a separate scrape credential. Acceptable as-is *only* because deployment is localhost-only. | n/a (preventive control) |
| **S-02** | OPT-125m hallucination produces confidently wrong factual content if outputs are ever shown to users | Quality / Trust | 5 | 4 | **20** | High | Out-of-scope statement in Model Card §2 prohibits user-facing use. Real production build needs retrieval grounding + answerability classifier. | Manual review only in this build |
| **S-03** | OPT-125m commercial-use license violation if the service is ever used outside research scope | Compliance | 3 | 5 | **15** | High | Documented in Model Card §1 and audit trail (EVT-001). Would need a relicensed or differently-licensed model for commercial use. | License clause review on any model swap |
| **S-04** | Memory pressure (currently 82.5%) escalates to OOM under load, taking the service down | Robustness | 4 | 4 | **16** | High | `HighMemoryUsage` alert in `dashboards/alert_rules.yml` fires at 90% sustained. Single-replica deployment is documented out-of-scope. | `llm_memory_percent` gauge |
| **S-05** | Toxic / biased output from OPT-125m is returned verbatim with no policy filter | Bias / Safety | 4 | 4 | **16** | High | Out-of-scope statement (§2). Real production would add an output classifier (toxicity, PII) before response. | Manual review |
| **S-06** | Plaintext prompts traversing HTTP can be sniffed on the local interface | Security | 3 | 4 | **12** | High | TLS at a reverse proxy in any non-local deployment. Localhost-only mitigates today. | n/a |
| **S-07** | Memorized PII from pretraining corpus regurgitated by the model | Privacy | 3 | 4 | **12** | High | Out-of-scope statement; localhost-only; no real user prompts. Production: PII output detector. | Manual review |
| **S-08** | Workload drift silently degrades user experience (cache hit rate collapse, latency rise) | Operations | 4 | 3 | **12** | High | Drift detector (Component 4) + `CacheHitRateDropped` alert. Demonstrated working in `docs/drift-diagnostic-report.md`. | Component 4 PSI/KS pipeline |
| **S-09** | Prompt-injection-style abuse delivering very long inputs to inflate cost / latency | Security / Cost | 4 | 3 | **12** | High | Add `len(prompt) > 1000 → 400` ingress check. Component 4 outlier rate (32% at z>3) shows this is realistic. | `llm_prompt_length_chars` histogram + `PromptLengthDrift` alert |
| **S-10** | Premature parameter tuning without statistical evidence ships a regression | Process | 2 | 3 | **6** | Medium | A/B test framework with Bonferroni correction (Component 2). Decision rule includes "RUN MORE DATA" branch — and was used. | `src/ab_test/results.json` |
| **S-11** | Cache returns stale entry after model swap because cache key does not include model version | Robustness | 3 | 2 | **6** | Medium | Cache key already includes `model_name`. Model swap would change the key, so cache invalidates implicitly. | Code review of `src/caching.py` |
| **S-12** | Race conditions in batcher under high concurrency cause dropped or duplicated requests | Robustness | 2 | 3 | **6** | Medium | M5 design uses `asyncio.Lock`; verified by zero-error rate over 200 concurrent requests in Component 1. | Component 1 `llm_requests_total{status="error"}` |
| **S-13** | Logs at DEBUG verbosity inadvertently capture prompts | Privacy | 2 | 3 | **6** | Medium | Log level is INFO by default. Documented as a setting that must not be raised in any deployment. | Manual config review |
| **S-14** | English-only model serves non-English input and returns degraded output silently | Quality | 3 | 2 | **6** | Medium | Documented in Model Card §2 and §5. Future: language detection at ingress. | Component 4 prompt-distribution drift |
| **S-15** | Cold-start latency (~1 s for first generation) confuses users on the first request | UX | 5 | 1 | **5** | Low | Model loaded once at server startup (FastAPI lifespan). Cache makes subsequent identical requests instant. | Bimodal latency in Component 1 |
| **S-16** | A single-replica deployment has no redundancy; any process crash takes the service down | Availability | 3 | 3 | **9** | Medium | Documented out-of-scope for academic deployment. Production: ≥ 2 replicas behind LB. | Process-up monitoring (out of scope) |

## Mitigation summary

- **Out-of-scope policy** (S-01, S-02, S-03, S-05, S-06, S-07): the single most important mitigation in this deployment. Several high-tier risks become acceptable specifically because the deployment is localhost-only and academic.
- **Operational monitoring** (S-04, S-08, S-09, S-10, S-12, S-15): Component 1's dashboard and alert rules + Component 4's drift detector are the live detective controls.
- **Process / experimental discipline** (S-10): the A/B test framework is itself a mitigation.
- **Code-level design** (S-11, S-12): inherited from the Milestone 5 design.

## What the matrix shows about the risk profile

| Tier | Count |
|---|---|
| High (12–25) | 9 |
| Medium (6–11) | 6 |
| Low (≤5) | 1 |

The high-tier risks fall into a clear pattern: **most of them are model- or scope-dependent rather than implementation-dependent**. Hallucination, license, toxic output, PII memorization, and plaintext HTTP all become acceptable the moment the service is restricted to a localhost academic deployment, and all of them become severe the moment that scope is broken.

This is the central message of `docs/cto-memo.md`: the service is well-built within its scope, and the scope itself is doing most of the risk-management work.
