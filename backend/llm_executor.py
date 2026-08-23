"""
Dedicated thread pool + semaphore for Gemini-calling work.

``fastapi.concurrency.run_in_threadpool`` uses anyio's shared default
``CapacityLimiter(40)`` — the same pool every other sync-in-async call in
this app uses. If /api/v1/hint's Gemini call went through that pool too,
one Gemini stall would park threads until other requests (including
/api/v1/grade, which has no reason to be slow) queue behind it on the same
40-thread budget. This module exists so the LLM path has its own lane.

Semaphore gates at the *request* level (acquired once per /hint call, held
across both the diagnosis and hint Gemini calls), not per individual Gemini
call — gating per-call would let one request's second call queue behind
other requests' first calls, which defeats the point of a request-level
budget.
"""

from __future__ import annotations

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

from backend import metrics
from backend.config import get_settings

T = TypeVar("T")

_executor: ThreadPoolExecutor | None = None
_semaphore: asyncio.Semaphore | None = None
_in_flight = 0
_in_flight_lock = asyncio.Lock()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=get_settings().LLM_EXECUTOR_MAX_WORKERS,
            thread_name_prefix="llm-worker",
        )
    return _executor


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().LLM_SEMAPHORE_LIMIT)
    return _semaphore


async def run_llm_call(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a sync, Gemini-calling function off the dedicated executor,
    gated by the request-level semaphore. Never touches anyio's shared pool."""
    global _in_flight
    semaphore = _get_semaphore()
    async with semaphore:
        async with _in_flight_lock:
            _in_flight += 1
            metrics.set_llm_semaphore(_in_flight, get_settings().LLM_SEMAPHORE_LIMIT)
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                _get_executor(), functools.partial(fn, *args, **kwargs)
            )
        finally:
            async with _in_flight_lock:
                _in_flight -= 1
                metrics.set_llm_semaphore(_in_flight, get_settings().LLM_SEMAPHORE_LIMIT)
