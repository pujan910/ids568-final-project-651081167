# Model Card: OPT-125m Inference Service

**Last updated:** Final Project, IDS568
**Owner:** Pujan Agarwal (`pujan910`)
**Service version:** v1.0.0
**System repository:** `ids568-final-project-651081167`

---

## 1. Model details

| Field | Value |
|---|---|
| Model name | `facebook/opt-125m` |
| Model family | OPT (Open Pre-trained Transformer) |
| Architecture | Decoder-only causal language model, 12 layers, 12 attention heads, 768 hidden size |
| Parameters | ~125 million |
| Released by | Meta AI, May 2022 |
| License | OPT-175B License Agreement (research-only, non-commercial) |
| Distribution | Hugging Face Hub |
| Loaded via | `transformers.pipeline("text-generation", model="facebook/opt-125m")` |
| Runtime | PyTorch 2.5, CPU inference (Apple Silicon, no GPU) |
| Decoding | Greedy (`do_sample=False`) by default; configurable per-request `max_tokens` |

This service does **not** modify or fine-tune the model — it serves the upstream Hugging Face checkpoint as-is, wrapped in a FastAPI HTTP layer with dynamic batching and an in-process LRU+TTL cache.

---

## 2. Intended use

### Intended primary uses
- Educational and research demos of LLM inference serving patterns: dynamic batching, caching, observability.
- Coursework deliverable for IDS568 (MLOps).
- Synthetic load and capacity testing of the surrounding monitoring/governance stack.

### Intended users
Course staff, peer reviewers, and the author. The service is single-tenant, runs on localhost, and is not exposed to the public internet.

### Out-of-scope uses (explicitly NOT supported)
- **Production deployment of any kind.** OPT-125m is too small and too unfiltered to support real users.
- **Generating user-facing content** in any product — the model has no safety alignment and will reproduce harmful, biased, or factually wrong text without warning.
- **Any decision-making.** Medical, legal, financial, hiring, lending, educational assessment, or any other domain where outputs influence outcomes for real people.
- **Code execution or agentic tool use.** This service generates text only. There is no tool-calling layer.
- **Use with any non-English input.** OPT was trained predominantly on English.

---

## 3. Training data

OPT-125m was pre-trained by Meta on a curated mixture of publicly available text datasets (per the OPT paper, Zhang et al. 2022):

- BookCorpus
- CC-Stories (a curated subset of CommonCrawl)
- The Pile (subset: USPTO, Project Gutenberg, OpenSubtitles, Wikipedia EN, DM Mathematics, HackerNews)
- Pushshift.io Reddit (filtered)
- CCNewsV2

This service does **no additional training, fine-tuning, RLHF, or safety post-training**. The biases and behaviors of the public Hugging Face checkpoint are inherited verbatim.

---

## 4. Performance metrics

Measured on this service in the Component 1 monitoring run (200 requests, concurrency 8, ~70/30 unique-vs-popular prompts) and the Component 2 A/B simulation (40 trials × 100 requests).

### Latency (Component 1 dashboard)
| Metric | Cold cache (cache miss) | Warm cache (cache hit) |
|---|---|---|
| p50 | 3,350 ms | 25 ms |
| p95 | 4,835 ms | ~50 ms |
| p99 | 4,967 ms | ~50 ms |

The warm/cold split is bimodal because cache hits skip the model entirely. **Cached p50 is 130× faster than cold p50.**

### Throughput (Component 2 simulation)
- Variant A (current production: `max_batch_size=4, batch_timeout_ms=20`): **3.72 ± 0.27 req/s**
- Variant B (proposed: `max_batch_size=8, batch_timeout_ms=50`): **3.65 ± 0.24 req/s**
- A/B test result: no statistically significant difference (Welch's t, p=0.36 with Bonferroni correction). Decision: keep Variant A. See `docs/recommendation-memo.md`.

### Other observed metrics
- Cache hit rate: 78.1% (synthetic mix; production rate will differ)
- Error rate: 0.00% across 201 requests
- Active hardware: Apple Silicon CPU, ~55% CPU utilization, ~82% memory utilization at load

### Quality metrics (NOT measured)
This service does not measure generation quality, factuality, toxicity, or bias on a held-out evaluation set. **No quality benchmarks have been run.** Any deployment that requires quality assurance must add this evaluation layer before serving users.

---

## 5. Limitations and failure modes

### Known limitations of OPT-125m (the underlying model)
- **Hallucination at scale.** A 125M-parameter model has very limited factual knowledge. Outputs frequently invent plausible-sounding but false facts.
- **No instruction following.** OPT-125m is a base language model, not an instruction-tuned chat model. It completes text rather than answering questions.
- **No safety alignment.** The model has not undergone RLHF or safety fine-tuning. It will produce toxic, biased, or offensive outputs when prompted, and sometimes when not prompted.
- **English only.** Performance on non-English inputs is severely degraded.
- **Stale knowledge.** Pre-training data has a hard cutoff in 2022; nothing newer is known to the model.
- **Repetition under greedy decoding.** With `do_sample=False`, OPT-125m can fall into degenerate loops on certain prompts.

### Known limitations of this serving layer
- **Cache key is a hash of `(prompt, model_name, max_tokens)`.** Two requests with identical prompts but different sampling parameters (when introduced) will not collide today, but a future change to add temperature/top-p without updating the cache key would cause silent cross-request leakage.
- **In-process cache is not shared across replicas.** Horizontal scaling would require a Redis-backed cache (the M5 design supports this; this deployment uses in-memory).
- **No rate limiting.** A single client can monopolize the queue.
- **No authentication.** The endpoint is open. Acceptable for localhost development; unacceptable elsewhere.

### Failure modes observed during development
- **Memory pressure at 82.5% on consumer hardware** (MacBook Air 16GB). Adding a second model variant for live A/B testing would exceed memory and trigger OOM.
- **Batching is timeout-bound at low load.** Batches rarely fill; throughput improvements from larger `max_batch_size` are not realized until QPS rises (see Component 2 memo).

---

## 6. Ethical considerations and risks

| Category | Risk |
|---|---|
| **Bias** | OPT-125m inherits biases from internet-scale pretraining: gender, race, religion, geography, language. Outputs about specific demographic groups may be stereotyped or harmful. The OPT paper itself acknowledges this and recommends against deployment without bias evaluation. |
| **Toxicity** | The model will generate toxic content on adversarial prompts and occasionally on benign ones. There is no output filter in this service. |
| **Misinformation** | Hallucinations are frequent. Users who treat outputs as factual will be misled. |
| **Privacy** | The pretraining corpus contains scraped Reddit and CommonCrawl text. The model may regurgitate personal information from its training data. The cache layer in this service hashes prompts before storage and does not log user identifiers (per M5 design), but the model itself is the privacy risk surface, not the cache. |
| **Misuse** | The service has no content policy and will attempt any prompt. In a real deployment this would enable spam, scam, and disinformation generation at scale. |

A full risk register with likelihood × severity scoring and mitigation plans is in `docs/risk-register.md` and the system-level risk matrix is in `docs/risk-matrix.md` (Component 5).

---

## 7. Operational characteristics

### Monitoring
The service exposes a Prometheus-compatible `/metrics` endpoint with latency histograms (split cached vs cold), request counters, cache hit/miss counters, batch size distribution, prompt/response length distributions, and system gauges. Scrape config: `dashboards/prometheus.yml`. Alert rules: `dashboards/alert_rules.yml`. Dashboard: `screenshots/dashboard.png`. Interpretation: `docs/dashboard-interpretation.md`.

### Drift detection
Component 4 of this project implements feature-distribution drift checks on prompt length, response length, and cache hit rate. See `docs/drift-diagnostic-report.md`.

### Change control
All configuration changes (batching parameters, model swap, cache TTL, etc.) must be:
1. Recorded in `logs/audit-trail.json`.
2. Validated via A/B test before promotion (see `docs/experiment-specification.md` for the template).
3. Reflected in this Model Card via a version bump.

---

## 8. Maintenance

| Action | Trigger | Owner |
|---|---|---|
| Re-run A/B test | Any change to batching parameters, model, or decoding strategy | ML Platform |
| Update model card performance section | Material change in observed latency or throughput in production | ML Platform |
| Re-evaluate model selection | Memory pressure breaches 90% sustained, or hit rate drops below 30% | ML Platform |
| Drift retraining | Any drift signal (Component 4) crosses its threshold | Data team (out of scope for this academic deployment) |

---

## 9. Citation

If referring to the underlying model:

> Zhang, S. et al. (2022). *OPT: Open Pre-trained Transformer Language Models.* arXiv:2205.01068.

Hugging Face model card: https://huggingface.co/facebook/opt-125m
