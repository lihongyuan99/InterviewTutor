"""Per-reply latency and aggregate LLM token accounting."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel, Field


class ReplyMetrics(BaseModel):
    """Metrics shown alongside one assistant reply."""

    elapsed_ms: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    return None


def _token_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_usage(value: Any) -> tuple[int, int, int] | None:
    usage = _as_mapping(value)
    if not usage:
        return None

    for nested_key in ("usage_metadata", "token_usage", "usage"):
        nested = _as_mapping(usage.get(nested_key))
        if nested:
            usage = nested
            break

    known_keys = {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
    }
    if not known_keys.intersection(usage):
        return None

    input_tokens = _token_count(
        usage.get("input_tokens", usage.get("prompt_tokens", 0))
    )
    output_tokens = _token_count(
        usage.get("output_tokens", usage.get("completion_tokens", 0))
    )
    total_tokens = _token_count(usage.get("total_tokens", 0))
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens


def _usage_from_value(
    value: Any,
    visited: set[int] | None = None,
) -> tuple[int, int, int] | None:
    """Find usage in callback results or ``astream_events`` payloads."""
    if value is None:
        return None

    if visited is None:
        visited = set()
    marker = id(value)
    if marker in visited:
        return None
    visited.add(marker)

    usage = _normalize_usage(value)
    if usage is not None:
        return usage

    for attribute in (
        "usage_metadata",
        "response_metadata",
        "generation_info",
        "llm_output",
        "message",
        "generations",
    ):
        usage = _usage_from_value(getattr(value, attribute, None), visited)
        if usage is not None:
            return usage

    mapping = _as_mapping(value)
    if mapping is not None:
        for key in (
            "output",
            "message",
            "chunk",
            "response",
            "result",
            "generations",
            "llm_output",
        ):
            usage = _usage_from_value(mapping.get(key), visited)
            if usage is not None:
                return usage

    if isinstance(value, (list, tuple)):
        for item in value:
            usage = _usage_from_value(item, visited)
            if usage is not None:
                return usage

    return None


class ReplyMetricsCallback(BaseCallbackHandler):
    """Aggregate usage from every LLM run belonging to one user request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen_runs: set[str] = set()
        self._usage_by_run: dict[str, tuple[int, int, int] | None] = {}
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._llm_calls = 0

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        self.record_llm_end(response, run_id=run_id)

    def record_llm_end(self, response: Any, *, run_id: Any) -> None:
        """Record one model-end payload, deduplicating callback and event paths."""
        run_key = str(run_id) if run_id is not None else f"anonymous:{id(response)}"
        usage = _usage_from_value(response)
        with self._lock:
            if run_key in self._seen_runs:
                previous = self._usage_by_run.get(run_key)
                if usage is None or usage == previous:
                    return
                previous = previous or (0, 0, 0)
                merged = tuple(max(old, new) for old, new in zip(previous, usage))
                self._input_tokens += merged[0] - previous[0]
                self._output_tokens += merged[1] - previous[1]
                self._total_tokens += merged[2] - previous[2]
                self._usage_by_run[run_key] = merged
                return
            self._seen_runs.add(run_key)
            self._usage_by_run[run_key] = usage
            self._llm_calls += 1
            if usage is None:
                return
            input_tokens, output_tokens, total_tokens = usage
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens
            self._total_tokens += total_tokens

    def snapshot(self, started_at: float) -> ReplyMetrics:
        elapsed_ms = max(0, round((time.perf_counter() - started_at) * 1000))
        with self._lock:
            return ReplyMetrics(
                elapsed_ms=elapsed_ms,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                total_tokens=self._total_tokens,
                llm_calls=self._llm_calls,
            )


_active_callback: ContextVar[ReplyMetricsCallback | None] = ContextVar(
    "active_reply_metrics_callback",
    default=None,
)


def get_active_reply_metrics_callback() -> ReplyMetricsCallback | None:
    """Return the metrics collector bound to the current request context."""
    return _active_callback.get()


def activate_reply_metrics_callback(callback: ReplyMetricsCallback | None):
    """Bind a collector and return the token needed to restore the context."""
    return _active_callback.set(callback)


def reset_reply_metrics_callback(token: Any) -> None:
    """Restore the request context returned by ``activate_reply_metrics_callback``."""
    _active_callback.reset(token)


@contextmanager
def bind_reply_metrics_callback(callback: ReplyMetricsCallback):
    """Expose a collector to models created by nested graph functions."""
    token = activate_reply_metrics_callback(callback)
    try:
        yield
    finally:
        reset_reply_metrics_callback(token)
