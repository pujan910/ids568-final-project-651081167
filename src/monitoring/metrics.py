"""
Prometheus metrics for the LLM inference server.

Defines all observable metrics:
- Latency (histograms with proper buckets for LLM workloads)
- Throughput / error rate (counters labeled by status)
- Cache hit/miss counters
- Batch size, prompt length, response length (drift signals)
- Active in-flight requests gauge
- System resource gauges (CPU, memory)

These are scraped by Prometheus at /metrics on the FastAPI server.
"""
from prometheus_client import Counter, Histogram, Gauge

# ---------------------------------------------------------------------------
# Latency: histogram with buckets tuned for small-LLM inference (50ms–10s)
# ---------------------------------------------------------------------------
REQUEST_LATENCY = Histogram(
    "llm_request_latency_seconds",
    "End-to-end latency of /generate requests (seconds)",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
    labelnames=("cached",),  # "true" / "false" — split warm vs cold latency
)

# ---------------------------------------------------------------------------
# Throughput + error rate
# ---------------------------------------------------------------------------
REQUESTS_TOTAL = Counter(
    "llm_requests_total",
    "Total /generate requests received",
    labelnames=("status",),  # "success" / "error"
)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
CACHE_HITS = Counter("llm_cache_hits_total", "Total cache hits")
CACHE_MISSES = Counter("llm_cache_misses_total", "Total cache misses")

# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------
BATCH_SIZE = Histogram(
    "llm_batch_size",
    "Number of requests grouped per inference batch",
    buckets=(1, 2, 3, 4, 5, 6, 7, 8, 16),
)

# ---------------------------------------------------------------------------
# Input / output integrity & drift signals
# ---------------------------------------------------------------------------
PROMPT_LENGTH = Histogram(
    "llm_prompt_length_chars",
    "Character length of incoming prompts (drift signal)",
    buckets=(10, 25, 50, 100, 200, 400, 800, 1600),
)
RESPONSE_LENGTH = Histogram(
    "llm_response_length_chars",
    "Character length of generated responses (drift signal)",
    buckets=(10, 25, 50, 100, 200, 400, 800, 1600),
)

# ---------------------------------------------------------------------------
# Saturation / concurrency
# ---------------------------------------------------------------------------
ACTIVE_REQUESTS = Gauge(
    "llm_active_requests",
    "Number of requests currently in-flight",
)

# ---------------------------------------------------------------------------
# System resources
# ---------------------------------------------------------------------------
CPU_PERCENT = Gauge("llm_cpu_percent", "Process CPU utilization percent")
MEMORY_PERCENT = Gauge("llm_memory_percent", "Host memory utilization percent")
