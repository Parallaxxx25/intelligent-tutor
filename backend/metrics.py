"""
In-process metrics for the lab session — no Prometheus, no Grafana.

A single supervised 2-hour lab with one person watching a screen doesn't
need a scrape pipeline: a JSON snapshot polled by `watch curl` (or a small
panel in the Streamlit playground) is enough to see the two numbers that
actually matter — hint fallback rate by reason, and whether the LLM
semaphore is saturated. Counters are process-local; with two containers
behind a proxy, that means two snapshots, not one aggregate — acceptable
for a two-hour supervised session where one person is watching both.

Not thread-safe against high-contention writers by construction — reads
are eventually-consistent snapshots, which is the only guarantee a JSON
endpoint watched by a human needs.
"""

from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict
from typing import Any

_lock = threading.Lock()

_grade_latencies: list[float] = []
_hint_latencies: dict[str, list[float]] = defaultdict(list)
_hint_fallback_reasons: Counter[str] = Counter()
_gemini_call_seconds: dict[tuple[str, str], list[float]] = defaultdict(list)
_pg_exec_seconds: dict[tuple[str, str], list[float]] = defaultdict(list)
_llm_semaphore_in_flight = 0
_llm_semaphore_limit = 0
_request_errors: Counter[str] = Counter()
# Keyed by problem_id — how often our Postgres verdict and the integrating
# platform's own SQLite verdict disagree on the same submission (see
# docs/adr/0006-partner-primary-dual-grade.md). A live measurement of
# MySQL/Postgres dialect divergence, not just the pre-lab gold_audit estimate.
_grader_disagreement_total: Counter[int] = Counter()

# Cap per-series sample retention so a long-running process doesn't grow
# these lists unboundedly — a lab session's total request volume (a few
# hundred) never gets close to this.
_MAX_SAMPLES = 5000


def _record(series: list[float], value: float) -> None:
    series.append(value)
    if len(series) > _MAX_SAMPLES:
        del series[: len(series) - _MAX_SAMPLES]


def record_grade_latency(seconds: float) -> None:
    with _lock:
        _record(_grade_latencies, seconds)


def record_hint_latency(seconds: float, source: str) -> None:
    with _lock:
        _record(_hint_latencies[source], seconds)


def record_hint_fallback(reason: str) -> None:
    """reason: 'semaphore' | 'timeout' | 'gemini_4xx' | 'gemini_5xx' | 'guardrail'"""
    with _lock:
        _hint_fallback_reasons[reason] += 1


def record_gemini_call(seconds: float, kind: str, status: str) -> None:
    with _lock:
        _record(_gemini_call_seconds[(kind, status)], seconds)


def record_pg_exec(seconds: float, kind: str, cache: str) -> None:
    """kind: 'student' | 'gold'. cache: 'hit' | 'miss'."""
    with _lock:
        _record(_pg_exec_seconds[(kind, cache)], seconds)


def record_request_error(endpoint: str) -> None:
    with _lock:
        _request_errors[endpoint] += 1


def record_grader_disagreement(problem_id: int) -> None:
    with _lock:
        _grader_disagreement_total[problem_id] += 1


def set_llm_semaphore(in_flight: int, limit: int) -> None:
    global _llm_semaphore_in_flight, _llm_semaphore_limit
    with _lock:
        _llm_semaphore_in_flight = in_flight
        _llm_semaphore_limit = limit


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    idx = min(int(len(s) * pct), len(s) - 1)
    return round(s[idx], 4)


def _histogram_summary(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": round(max(values), 4) if values else None,
    }


def snapshot() -> dict[str, Any]:
    """A point-in-time view of everything recorded since process start."""
    with _lock:
        total_hints = sum(len(v) for v in _hint_latencies.values())
        total_fallbacks = sum(_hint_fallback_reasons.values())

        return {
            "timestamp": time.time(),
            "grade_latency_seconds": _histogram_summary(_grade_latencies),
            "hint_latency_seconds": {
                source: _histogram_summary(values)
                for source, values in _hint_latencies.items()
            },
            "hint_fallback_total": dict(_hint_fallback_reasons),
            "hint_fallback_rate": (
                round(total_fallbacks / total_hints, 4) if total_hints else 0.0
            ),
            "gemini_call_seconds": {
                f"{kind}:{status}": _histogram_summary(values)
                for (kind, status), values in _gemini_call_seconds.items()
            },
            "pg_exec_seconds": {
                f"{kind}:{cache}": _histogram_summary(values)
                for (kind, cache), values in _pg_exec_seconds.items()
            },
            "llm_semaphore_in_flight": _llm_semaphore_in_flight,
            "llm_semaphore_limit": _llm_semaphore_limit,
            "request_errors": dict(_request_errors),
            "grader_disagreement_total": dict(_grader_disagreement_total),
        }
