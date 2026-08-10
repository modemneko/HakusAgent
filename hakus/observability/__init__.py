"""P5 Observability — structlog structured logging + Prometheus metrics.

This package provides:
  1. `get_structlog()` — structlog logger with JSON renderer + rich console fallback
  2. `MetricsRegistry` — Prometheus-style counters / histograms / gauges with /metrics export
  3. `metrics_middleware()` — FastAPI middleware that tracks HTTP request latency / errors
  4. `instrument_llm_call()` — Context manager for LLM call duration tracking
  5. `instrument_tool_call()` — Context manager for tool execution tracking
"""
from .structlog_setup import get_structlog, bind_context, clear_context
from .prometheus_metrics import (
    MetricsRegistry,
    metrics_registry,
    instrument_llm_call,
    instrument_tool_call,
    instrument_guardian_eval,
    instrument_checkpoint,
    instrument_p1_hook,
)

__all__ = [
    "get_structlog",
    "bind_context",
    "clear_context",
    "MetricsRegistry",
    "metrics_registry",
    "instrument_llm_call",
    "instrument_tool_call",
    "instrument_guardian_eval",
    "instrument_checkpoint",
    "instrument_p1_hook",
]
