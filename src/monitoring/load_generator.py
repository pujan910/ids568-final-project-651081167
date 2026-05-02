"""
Synthetic load generator for the LLM inference server.

Sends a realistic mix of traffic to populate Prometheus metrics:
- ~70% unique prompts (cache misses)
- ~30% repeated prompts (cache hits)
- Variable concurrency to exercise batching
- Variable prompt length to exercise drift signals

Usage:
    python src/monitoring/load_generator.py --requests 200 --concurrency 8
"""
import argparse
import asyncio
import random
import time

import aiohttp

# A pool of unique prompts (varied length to make prompt-length histogram interesting)
UNIQUE_PROMPTS = [
    "Hello, my name is",
    "The capital of France is",
    "Once upon a time in a faraway kingdom",
    "Explain quantum computing in simple terms.",
    "Write a haiku about autumn leaves falling.",
    "The best programming language for data science is",
    "In machine learning, a transformer model is",
    "The recipe for a classic margherita pizza requires",
    "Climate change affects global weather patterns by",
    "The history of the Roman Empire begins with",
    "A neural network learns by",
    "The difference between supervised and unsupervised learning is",
    "In the year 2050, humanity will likely",
    "The most efficient sorting algorithm for large datasets is",
    "Photosynthesis in plants converts",
    "The Mona Lisa was painted by",
    "Black holes form when",
    "The Pythagorean theorem states that",
    "Renewable energy sources include",
    "DNA is structured as",
    "The Industrial Revolution began in",
    "Cryptocurrency works by using",
    "The water cycle on Earth involves",
    "Shakespeare's most famous tragedy is",
    "The speed of light in a vacuum is",
    "An ecosystem is defined as",
    "The mitochondria of a cell is responsible for",
    "Newton's three laws of motion describe",
    "The Great Wall of China was built to",
    "A chemical reaction occurs when",
]

# A small pool of "popular" prompts that get repeated a lot — drives cache hits
POPULAR_PROMPTS = [
    "What is artificial intelligence?",
    "How does machine learning work?",
    "Tell me a fun fact.",
]


def pick_prompt(unique_ratio: float) -> str:
    """With probability `unique_ratio`, pick a unique prompt; else a popular one."""
    if random.random() < unique_ratio:
        return random.choice(UNIQUE_PROMPTS)
    return random.choice(POPULAR_PROMPTS)


async def fire_one(session: aiohttp.ClientSession, url: str, prompt: str, max_tokens: int):
    """Send a single /generate request and return its (status, latency_ms)."""
    start = time.time()
    try:
        async with session.post(
            url,
            json={"prompt": prompt, "max_tokens": max_tokens},
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            await resp.json()
            return resp.status, (time.time() - start) * 1000
    except Exception as e:
        return 0, (time.time() - start) * 1000


async def run_load(
    base_url: str,
    total_requests: int,
    concurrency: int,
    unique_ratio: float,
    max_tokens: int,
):
    """Drive `total_requests` through the server with `concurrency` in-flight at once."""
    url = f"{base_url}/generate"
    semaphore = asyncio.Semaphore(concurrency)
    completed = []

    async def bound_request():
        async with semaphore:
            prompt = pick_prompt(unique_ratio)
            status, latency = await fire_one(session, url, prompt, max_tokens)
            completed.append((status, latency))
            if len(completed) % 10 == 0:
                print(f"  Completed: {len(completed)}/{total_requests}")

    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(bound_request()) for _ in range(total_requests)]
        start = time.time()
        await asyncio.gather(*tasks)
        elapsed = time.time() - start

    # Quick summary
    successes = sum(1 for s, _ in completed if s == 200)
    latencies = sorted(l for _, l in completed)
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    throughput = total_requests / elapsed

    print()
    print("=" * 50)
    print(f"Load Generator Summary")
    print("=" * 50)
    print(f"  Total requests:    {total_requests}")
    print(f"  Successes:         {successes}")
    print(f"  Errors:            {total_requests - successes}")
    print(f"  Concurrency:       {concurrency}")
    print(f"  Wall time:         {elapsed:.2f}s")
    print(f"  Throughput:        {throughput:.2f} req/s")
    print(f"  Latency p50:       {p50:.1f} ms")
    print(f"  Latency p95:       {p95:.1f} ms")
    print(f"  Latency p99:       {p99:.1f} ms")


def main():
    parser = argparse.ArgumentParser(description="LLM server load generator")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--unique-ratio",
        type=float,
        default=0.7,
        help="Probability of picking a unique prompt (1-this = cache-hit ratio target)",
    )
    parser.add_argument("--max-tokens", type=int, default=30)
    args = parser.parse_args()

    print(f"Firing {args.requests} requests at {args.url} (concurrency={args.concurrency})")
    asyncio.run(
        run_load(
            args.url,
            args.requests,
            args.concurrency,
            args.unique_ratio,
            args.max_tokens,
        )
    )


if __name__ == "__main__":
    main()
