import asyncio
import time
from typing import List
from src.config import settings

class BatchRequest:
    def __init__(self, prompt: str, max_tokens: int):
        self.prompt = prompt
        self.max_tokens = max_tokens
        self.future = asyncio.get_event_loop().create_future()
        self.created_at = time.time()

class DynamicBatcher:
    def __init__(self):
        self._queue: List[BatchRequest] = []
        self._lock = asyncio.Lock()
        self._batch_event = asyncio.Event()
        self._running = False
        self.total_batches = 0
        self.total_requests = 0

    async def start(self, model_fn):
        self._running = True
        self._model_fn = model_fn
        asyncio.create_task(self._batch_loop())

    async def submit(self, prompt: str, max_tokens: int) -> str:
        req = BatchRequest(prompt, max_tokens)
        async with self._lock:
            self._queue.append(req)
            self._batch_event.set()
        return await req.future

    async def _batch_loop(self):
        while self._running:
            # Wait for first request or timeout
            try:
                await asyncio.wait_for(self._batch_event.wait(), timeout=settings.batch_timeout_ms / 1000)
            except asyncio.TimeoutError:
                pass
            self._batch_event.clear()

            async with self._lock:
                if not self._queue:
                    continue
                batch = self._queue[:settings.max_batch_size]
                self._queue = self._queue[settings.max_batch_size:]

            if not batch:
                continue

            self.total_batches += 1
            self.total_requests += len(batch)

            try:
                prompts = [r.prompt for r in batch]
                max_tok = max(r.max_tokens for r in batch)
                results = await asyncio.get_event_loop().run_in_executor(
                    None, self._model_fn, prompts, max_tok
                )
                for req, result in zip(batch, results):
                    if not req.future.done():
                        req.future.set_result(result)
            except Exception as e:
                for req in batch:
                    if not req.future.done():
                        req.future.set_exception(e)

batcher = DynamicBatcher()
