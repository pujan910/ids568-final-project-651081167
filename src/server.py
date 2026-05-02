"""
LLM Inference Server (Final Project edition).

Builds on the Milestone 5 server by adding full Prometheus instrumentation:
- Latency histograms (split cached vs cold)
- Throughput / error counters
- Cache hit/miss counters
- Batch size, prompt length, response length histograms (drift signals)
- Active-request gauge
- System resource gauges

Exposes /metrics for Prometheus to scrape.
"""
import asyncio
import time
import psutil
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from transformers import pipeline

from src.config import settings
from src.caching import cache
from src.batching import batcher
from src.monitoring.metrics import (
    REQUEST_LATENCY,
    REQUESTS_TOTAL,
    CACHE_HITS,
    CACHE_MISSES,
    BATCH_SIZE,
    PROMPT_LENGTH,
    RESPONSE_LENGTH,
    ACTIVE_REQUESTS,
    CPU_PERCENT,
    MEMORY_PERCENT,
)

# Internal stats (kept for /stats endpoint — Prometheus is the source of truth for monitoring)
stats = {"requests": 0, "cache_hits": 0, "cache_misses": 0, "start_time": time.time()}


def run_model(prompts: list, max_tokens: int) -> list:
    """Single batch forward pass through the HuggingFace pipeline."""
    BATCH_SIZE.observe(len(prompts))  # record actual batch size
    outputs = generator(
        prompts,
        max_new_tokens=max_tokens,
        do_sample=False,
        batch_size=len(prompts),
    )
    results = []
    for out in outputs:
        if isinstance(out, list):
            results.append(out[0]["generated_text"])
        else:
            results.append(out["generated_text"])
    return results


@asynccontextmanager
async def lifespan(app: FastAPI):
    global generator
    print(f"Loading model: {settings.model_name}")
    generator = pipeline("text-generation", model=settings.model_name)
    print("Model loaded!")
    await batcher.start(run_model)
    # Background task to refresh resource gauges
    refresh_task = asyncio.create_task(_refresh_resource_gauges())
    yield
    refresh_task.cancel()


async def _refresh_resource_gauges():
    """Updates CPU / memory gauges every 2 seconds."""
    while True:
        try:
            CPU_PERCENT.set(psutil.cpu_percent(interval=None))
            MEMORY_PERCENT.set(psutil.virtual_memory().percent)
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            break


app = FastAPI(title="LLM Inference Server", lifespan=lifespan)


class InferenceRequest(BaseModel):
    prompt: str
    max_tokens: int = 100


class InferenceResponse(BaseModel):
    text: str
    cached: bool
    latency_ms: float


@app.post("/generate", response_model=InferenceResponse)
async def generate(request: InferenceRequest):
    """Main inference endpoint. Cache-checks first, then submits to batcher."""
    start = time.time()
    stats["requests"] += 1
    ACTIVE_REQUESTS.inc()
    PROMPT_LENGTH.observe(len(request.prompt))

    try:
        # Cache lookup
        cached_result = await cache.get(
            request.prompt, settings.model_name, request.max_tokens
        )
        if cached_result:
            stats["cache_hits"] += 1
            CACHE_HITS.inc()
            latency = time.time() - start
            REQUEST_LATENCY.labels(cached="true").observe(latency)
            REQUESTS_TOTAL.labels(status="success").inc()
            RESPONSE_LENGTH.observe(len(cached_result))
            return InferenceResponse(
                text=cached_result, cached=True, latency_ms=latency * 1000
            )

        stats["cache_misses"] += 1
        CACHE_MISSES.inc()

        # Submit to batcher
        result = await batcher.submit(request.prompt, request.max_tokens)
        await cache.set(
            request.prompt, settings.model_name, request.max_tokens, result
        )

        latency = time.time() - start
        REQUEST_LATENCY.labels(cached="false").observe(latency)
        REQUESTS_TOTAL.labels(status="success").inc()
        RESPONSE_LENGTH.observe(len(result))
        return InferenceResponse(
            text=result, cached=False, latency_ms=latency * 1000
        )

    except Exception as e:
        REQUESTS_TOTAL.labels(status="error").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.dec()


@app.get("/health")
async def health():
    return {"status": "ok", "model": settings.model_name}


@app.get("/metrics")
async def metrics():
    """Prometheus scrape endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/stats")
async def get_stats():
    """Human-readable JSON stats (kept from M5 for convenience)."""
    cache_stats = await cache.stats()
    uptime = time.time() - stats["start_time"]
    hit_rate = stats["cache_hits"] / max(stats["requests"], 1)
    return {
        "uptime_seconds": uptime,
        "total_requests": stats["requests"],
        "cache_hits": stats["cache_hits"],
        "cache_misses": stats["cache_misses"],
        "cache_hit_rate": hit_rate,
        "cache": cache_stats,
        "batching": {
            "total_batches": batcher.total_batches,
            "total_requests": batcher.total_requests,
        },
        "system": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
        },
    }
