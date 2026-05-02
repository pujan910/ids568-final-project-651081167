# Production Monitoring Dashboard — Interpretation

**System under observation:** LLM inference server serving `facebook/opt-125m` via FastAPI, with dynamic batching (`max_batch_size=8`, `batch_timeout_ms=50`) and an in-process cache (`ttl=300s`, `max_entries=1000`).

**Data window:** 200 synthetic requests at concurrency 8, ~70/30 unique-vs-popular prompt mix.

---

## Design choices

**Stack: Prometheus client library + matplotlib renderer.** I chose `prometheus-client` for instrumentation because it is the de-facto standard for Python-native metric emission and integrates cleanly with FastAPI's request lifecycle. Rather than running a live Prometheus + Grafana stack inside Docker (heavyweight for a single-node demo), I scrape the `/metrics` endpoint into a snapshot file and render it through matplotlib in a Grafana-style layout. The `prometheus.yml` and `alert_rules.yml` files in `dashboards/` are wired correctly and would work against a live Prometheus instance — the rendering script simply replaces Grafana for offline review.

**Metric selection.** I instrumented six categories that map directly to the four golden signals (latency, traffic, errors, saturation) plus two LLM-specific concerns (cache effectiveness and input drift):

| Metric | Type | Purpose |
|---|---|---|
| `llm_request_latency_seconds` | Histogram, label `cached` | Latency, split by cache hit/miss to expose the bimodal distribution |
| `llm_requests_total` | Counter, label `status` | Throughput + error rate |
| `llm_cache_hits_total` / `llm_cache_misses_total` | Counter | Cache effectiveness |
| `llm_batch_size` | Histogram | Batching efficiency |
| `llm_prompt_length_chars` / `llm_response_length_chars` | Histogram | Input/output drift signals |
| `llm_active_requests`, `llm_cpu_percent`, `llm_memory_percent` | Gauge | Saturation and resource health |

The `cached` label on the latency histogram is the most important design decision — without it, cached and cold requests get averaged together and the dashboard tells a misleading story about end-user experience.

---

## What the dashboard reveals about system health

**The system is working as designed, but its latency profile is sharply bimodal.** Three observations stand out:

1. **Cache is the dominant latency lever.** With a 78.1% hit rate, the *median* user request returns in roughly 25 ms. The remaining 22% miss the cache, hit the model, and take 3.3–5.0 s to complete (p50 = 3.35 s, p95 = 4.83 s, p99 = 4.97 s on this hardware). The 130× spread between cached and cold requests means an aggregate "average latency" number would be deeply misleading — only percentile-based, label-split views are diagnostic.

2. **Batching is engaging but not at full efficiency.** The batch-size histogram shows the hot bands at sizes ≤3 and ≤5, with no batches reaching the configured `max_batch_size=8`. This means the 50 ms `batch_timeout_ms` is firing before 8 concurrent requests accumulate at this load level. Throughput would improve under heavier load, or with a larger timeout (at the cost of per-request latency).

3. **Memory pressure is the leading saturation risk.** Memory is at 82.5% on a MacBook Air running an OPT-125m process plus the OS. CPU is moderate at 55.4%. On this host, the next failure mode is OOM, not CPU starvation — a meaningful signal for capacity planning.

**Zero errors across 201 requests** confirms the API is stable under concurrency, with the asyncio batcher and cache lock primitives functioning correctly.

---

## Bottlenecks and risks

- **Cold-path latency is the user-experience cliff.** If a real production workload has a less repetitive prompt distribution than this synthetic mix, the cache hit rate will drop and median latency will jump from ~25 ms toward ~3 s. The dashboard's Cache Hit Rate panel is the leading indicator for this — it would degrade *before* user-visible latency does.
- **Batch starvation under low load.** Because batches rarely fill, GPU/CPU compute is being amortized across only 3–5 requests instead of 8. At higher QPS this resolves itself; at lower QPS, the timeout is the binding constraint.
- **Memory headroom is thin.** 82.5% utilized leaves ~17% before OOM territory. A second model variant loaded for an A/B test (Component 2) or a memory leak in long-running cache entries would push this over.
- **Prompt-length distribution is currently narrow** (the ≤50-char bucket dominates). This is what makes it a *useful baseline* for drift detection — a future shift toward the ≤200 or ≤800 buckets would be immediately visible and would also silently hurt cache hit rate (longer prompts are less likely to match).

---

## Alert trigger conditions

Defined formally in `dashboards/alert_rules.yml`. Summary:

| Alert | Condition | Severity | Why this threshold |
|---|---|---|---|
| `HighColdLatency` | p95 cold latency > 5 s for 2 min | warning | Just above measured baseline (4.83 s); fires on real degradation, not jitter |
| `CriticalColdLatency` | p99 cold latency > 10 s for 1 min | critical | 2× baseline — indicates the server is queueing or thrashing |
| `ElevatedErrorRate` | error_rate > 1% over 5 min | warning | Current rate is 0%; any sustained errors warrant investigation |
| `CacheHitRateDropped` | hit rate < 30% over 10 min | warning | Current rate is 78%; a drop below 30% means user latency has tripled |
| `PromptLengthDrift` | p95 prompt length > 800 chars over 10 min | info | Current p95 is in the ≤50 bucket; this fires when input distribution has materially shifted |
| `HighMemoryUsage` | memory > 90% for 5 min | warning | Currently 82.5%; 90% leaves only minutes of runway before OOM |

The cache-hit-rate alert is the link to Component 4 (drift detection): a sudden drop in hit rate is operationally indistinguishable from prompt drift, so this alert would be the first signal that triggers a deeper drift investigation.
