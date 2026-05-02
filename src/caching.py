import hashlib
import json
import time
import asyncio
from typing import Optional
from src.config import settings

class InMemoryCache:
    def __init__(self, ttl_seconds: int = None, max_entries: int = None):
        self.ttl = ttl_seconds or settings.cache_ttl_seconds
        self.max_entries = max_entries or settings.cache_max_entries
        self._cache: dict = {}
        self._timestamps: dict = {}
        self._lock = asyncio.Lock()

    def _make_key(self, prompt: str, model: str, max_tokens: int) -> str:
        # Never store plaintext user identifiers - hash only
        raw = json.dumps({"prompt": prompt, "model": model, "max_tokens": max_tokens}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get(self, prompt: str, model: str, max_tokens: int) -> Optional[str]:
        key = self._make_key(prompt, model, max_tokens)
        async with self._lock:
            if key not in self._cache:
                return None
            if time.time() - self._timestamps[key] > self.ttl:
                del self._cache[key]
                del self._timestamps[key]
                return None
            return self._cache[key]

    async def set(self, prompt: str, model: str, max_tokens: int, response: str):
        key = self._make_key(prompt, model, max_tokens)
        async with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_entries:
                oldest = min(self._timestamps, key=lambda k: self._timestamps[k])
                del self._cache[oldest]
                del self._timestamps[oldest]
            self._cache[key] = response
            self._timestamps[key] = time.time()

    async def stats(self) -> dict:
        async with self._lock:
            now = time.time()
            valid = sum(1 for k in self._cache if now - self._timestamps[k] <= self.ttl)
            return {"total_entries": len(self._cache), "valid_entries": valid, "max_entries": self.max_entries, "ttl_seconds": self.ttl}

cache = InMemoryCache()
