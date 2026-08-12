"""Prometheus-compatible metrics registry with histogram/counter/gauge support.

Design goals:
  1. Thread-safe metric increments with labels (provider, tool, path, etc.)
  2. Histogram buckets for latency tracking (LLM call, tool exec, HTTP request)
  3. /metrics Prometheus text format export alongside existing /api/metrics JSON
  4. Minimal overhead — no external dependency on prometheus_client at import time
     (imported lazily so sidecar still works without it)
  5. Wireable into both FastAPI middleware and agent internals

Metric naming follows Prometheus conventions:
  - hakus_http_request_duration_seconds  (histogram)
  - hakus_http_request_total             (counter by method/path/status)
  - hakus_llm_call_duration_seconds      (histogram by provider/model)
  - hakus_llm_call_total                 (counter by provider/model/status)
  - hakus_tool_call_duration_seconds     (histogram by tool_name)
  - hakus_tool_call_total                (counter by tool_name/status)
  - hakus_guardian_eval_duration_seconds (histogram)
  - hakus_guardian_eval_total            (counter by verdict)
  - hakus_checkpoint_total               (counter by trigger)
  - hakus_p1_hook_total                  (counter by hook_name/status)
  - hakus_active_sessions                (gauge)
  - hakus_active_websockets              (gauge)
  - hakus_context_tokens_total           (counter by level)
  - hakus_doomloop_detected_total        (counter)

Usage::

    from hakus.observability.prometheus_metrics import (
        metrics_registry, instrument_llm_call, instrument_tool_call
    )

    # LLM call tracking
    with instrument_llm_call(provider="opencode", model="mimo-v2.5"):
        response = await llm_client.chat(messages)

    # Tool call tracking
    with instrument_tool_call(tool_name="shell"):
        result = await executor.run("git status")

    # Prometheus /metrics endpoint
    from fastapi import FastAPI
    app = FastAPI()
    metrics_registry.mount_metrics_endpoint(app)
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

try:
    import prometheus_client as prom
    from prometheus_client import (
        Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST,
        CollectorRegistry, REGISTRY,
    )
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False


# ---------------------------------------------------------------------------
# Default histogram buckets (seconds)
# ---------------------------------------------------------------------------

# HTTP request latency — typical API calls 10ms-30s
HTTP_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# LLM call latency — typical 0.5s-120s
LLM_BUCKETS = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 90.0, 120.0, 180.0)

# Tool call latency — typical 0.1s-60s
TOOL_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0)

# Guardian eval — typical 0.5s-10s
GUARDIAN_BUCKETS = (0.5, 1.0, 2.0, 3.0, 5.0, 10.0)


# ---------------------------------------------------------------------------
# Metrics Registry
# ---------------------------------------------------------------------------

class MetricsRegistry:
    """Central registry for all HakusAgent Prometheus metrics.

    Lazily creates metrics on first access. Thread-safe.
    If prometheus_client is not installed, all operations are no-ops.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._created: Dict[str, Any] = {}
        self._custom_registry = CollectorRegistry() if HAS_PROMETHEUS else None

        if HAS_PROMETHEUS:
            self._init_core_metrics()

    def _init_core_metrics(self) -> None:
        """Create the standard set of HakusAgent metrics."""
        r = self._custom_registry

        # --- HTTP ---
        self.http_request_duration = Histogram(
            "hakus_http_request_duration_seconds",
            "HTTP request latency in seconds",
            labelnames=["method", "path", "status_code"],
            buckets=HTTP_BUCKETS,
            registry=r,
        )
        self.http_request_total = Counter(
            "hakus_http_request_total",
            "Total HTTP requests",
            labelnames=["method", "path", "status_code"],
            registry=r,
        )

        # --- LLM ---
        self.llm_call_duration = Histogram(
            "hakus_llm_call_duration_seconds",
            "LLM API call latency in seconds",
            labelnames=["provider", "model"],
            buckets=LLM_BUCKETS,
            registry=r,
        )
        self.llm_call_total = Counter(
            "hakus_llm_call_total",
            "Total LLM API calls",
            labelnames=["provider", "model", "status"],
            registry=r,
        )
        self.llm_tokens_total = Counter(
            "hakus_llm_tokens_total",
            "Total LLM tokens processed",
            labelnames=["provider", "model", "direction"],  # direction: input/output
            registry=r,
        )

        # --- Tool ---
        self.tool_call_duration = Histogram(
            "hakus_tool_call_duration_seconds",
            "Tool execution latency in seconds",
            labelnames=["tool_name"],
            buckets=TOOL_BUCKETS,
            registry=r,
        )
        self.tool_call_total = Counter(
            "hakus_tool_call_total",
            "Total tool calls",
            labelnames=["tool_name", "status"],
            registry=r,
        )

        # --- Guardian ---
        self.guardian_eval_duration = Histogram(
            "hakus_guardian_eval_duration_seconds",
            "Guardian AI evaluation latency in seconds",
            labelnames=[],
            buckets=GUARDIAN_BUCKETS,
            registry=r,
        )
        self.guardian_eval_total = Counter(
            "hakus_guardian_eval_total",
            "Total Guardian evaluations",
            labelnames=["verdict"],
            registry=r,
        )

        # --- Checkpoint ---
        self.checkpoint_total = Counter(
            "hakus_checkpoint_total",
            "Total checkpoints saved",
            labelnames=["trigger"],
            registry=r,
        )

        # --- P1 Hooks ---
        self.p1_hook_total = Counter(
            "hakus_p1_hook_total",
            "Total P1 enhancement hook invocations",
            labelnames=["hook_name", "status"],
            registry=r,
        )

        # --- Gauges ---
        self.active_sessions = Gauge(
            "hakus_active_sessions",
            "Number of active agent sessions",
            registry=r,
        )
        self.active_websockets = Gauge(
            "hakus_active_websockets",
            "Number of active WebSocket connections",
            registry=r,
        )

        # --- Context ---
        self.context_tokens_total = Counter(
            "hakus_context_tokens_total",
            "Total context tokens processed",
            labelnames=["level"],  # level: raw/compressed/summary
            registry=r,
        )

        # --- Doom Loop ---
        self.doomloop_detected_total = Counter(
            "hakus_doomloop_detected_total",
            "Number of doom loops detected",
            registry=r,
        )

        # --- Agent turns ---
        self.agent_turn_duration = Histogram(
            "hakus_agent_turn_duration_seconds",
            "Agent turn total duration in seconds",
            labelnames=["provider"],
            buckets=LLM_BUCKETS,
            registry=r,
        )
        self.agent_turn_total = Counter(
            "hakus_agent_turn_total",
            "Total agent turns completed",
            labelnames=["provider", "status"],
            registry=r,
        )

    def generate_prometheus_output(self) -> bytes:
        """Generate Prometheus text format output for /metrics endpoint."""
        if not HAS_PROMETHEUS or self._custom_registry is None:
            return b"# prometheus_client not available\n"
        return generate_latest(self._custom_registry)

    def mount_metrics_endpoint(self, app: Any) -> None:
        """Mount /metrics Prometheus endpoint onto a FastAPI app."""
        if not HAS_PROMETHEUS:
            return

        from fastapi import Response

        @app.get("/metrics")
        async def prometheus_metrics():
            """Prometheus text format metrics export.

            Standard endpoint for Prometheus scraping.
            Returns text/plain with HELP + TYPE headers for each metric.
            """
            output = self.generate_prometheus_output()
            return Response(
                content=output,
                media_type=CONTENT_TYPE_LATEST,
            )

    def get_json_snapshot(self) -> Dict[str, Any]:
        """Return a JSON-friendly snapshot of all metric values.

        Complements the existing /api/metrics JSON endpoint with
        richer data (histogram quantiles, gauge values, etc.).
        """
        if not HAS_PROMETHEUS:
            return {"error": "prometheus_client not installed"}

        snapshot: Dict[str, Any] = {}

        # Counters
        for name in [
            "hakus_http_request_total",
            "hakus_llm_call_total",
            "hakus_llm_tokens_total",
            "hakus_tool_call_total",
            "hakus_guardian_eval_total",
            "hakus_checkpoint_total",
            "hakus_p1_hook_total",
            "hakus_context_tokens_total",
            "hakus_doomloop_detected_total",
            "hakus_agent_turn_total",
        ]:
            try:
                metric = self._custom_registry._names_to_collectors.get(name)
                if metric:
                    snapshot[name] = self._serialize_metric(metric)
            except Exception:
                pass

        # Gauges
        for name in ["hakus_active_sessions", "hakus_active_websockets"]:
            try:
                metric = self._custom_registry._names_to_collectors.get(name)
                if metric:
                    snapshot[name] = self._serialize_metric(metric)
            except Exception:
                pass

        # Histograms — include sum/count/bucket counts
        for name in [
            "hakus_http_request_duration_seconds",
            "hakus_llm_call_duration_seconds",
            "hakus_tool_call_duration_seconds",
            "hakus_guardian_eval_duration_seconds",
            "hakus_agent_turn_duration_seconds",
        ]:
            try:
                metric = self._custom_registry._names_to_collectors.get(name)
                if metric:
                    snapshot[name] = self._serialize_metric(metric)
            except Exception:
                pass

        return snapshot

    @staticmethod
    def _serialize_metric(metric: Any) -> Any:
        """Best-effort serialization of a Prometheus metric to JSON."""
        try:
            # For labeled metrics, iterate samples
            samples = {}
            for s in metric.collect()[0].samples:
                key = ",".join(f"{k}={v}" for k, v in sorted(s.labels.items())) if s.labels else "_total"
                samples[key] = s.value
            return samples
        except Exception:
            return "<unavailable>"


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

metrics_registry = MetricsRegistry()


# ---------------------------------------------------------------------------
# Instrumentation helpers (context managers)
# ---------------------------------------------------------------------------

@contextmanager
def instrument_llm_call(provider: str = "unknown", model: str = "unknown"):
    """Context manager that tracks LLM call duration and result.

    Usage::

        with instrument_llm_call(provider="opencode", model="mimo-v2.5"):
            response = await llm_client.chat(messages)
    """
    start = time.monotonic()
    status = "success"
    try:
        yield
    except Exception as e:
        status = "error"
        raise
    finally:
        if HAS_PROMETHEUS:
            duration = time.monotonic() - start
            try:
                metrics_registry.llm_call_duration.labels(
                    provider=provider, model=model
                ).observe(duration)
                metrics_registry.llm_call_total.labels(
                    provider=provider, model=model, status=status
                ).inc()
            except Exception:
                pass


@contextmanager
def instrument_tool_call(tool_name: str = "unknown"):
    """Context manager that tracks tool execution duration and result.

    Usage::

        with instrument_tool_call(tool_name="shell"):
            result = await executor.run("git status")
    """
    start = time.monotonic()
    status = "success"
    try:
        yield
    except Exception as e:
        status = "error"
        raise
    finally:
        if HAS_PROMETHEUS:
            duration = time.monotonic() - start
            try:
                metrics_registry.tool_call_duration.labels(
                    tool_name=tool_name
                ).observe(duration)
                metrics_registry.tool_call_total.labels(
                    tool_name=tool_name, status=status
                ).inc()
            except Exception:
                pass


@contextmanager
def instrument_guardian_eval():
    """Context manager that tracks Guardian AI evaluation duration.

    Usage::

        with instrument_guardian_eval():
            decision = await guardian.evaluate(tool_name, args)
    """
    start = time.monotonic()
    try:
        yield
    finally:
        if HAS_PROMETHEUS:
            duration = time.monotonic() - start
            try:
                metrics_registry.guardian_eval_duration.observe(duration)
            except Exception:
                pass


@contextmanager
def instrument_checkpoint(trigger: str = "auto"):
    """Context manager that tracks checkpoint save operations.

    Usage::

        with instrument_checkpoint(trigger="auto"):
            await checkpoint_mgr.save(state)
    """
    try:
        yield
    finally:
        if HAS_PROMETHEUS:
            try:
                metrics_registry.checkpoint_total.labels(trigger=trigger).inc()
            except Exception:
                pass


@contextmanager
def instrument_p1_hook(hook_name: str = "unknown"):
    """Context manager that tracks P1 enhancement hook invocations.

    Usage::

        with instrument_p1_hook(hook_name="pre_tool"):
            await p1.pre_tool_check(tool_call)
    """
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        if HAS_PROMETHEUS:
            try:
                metrics_registry.p1_hook_total.labels(
                    hook_name=hook_name, status=status
                ).inc()
            except Exception:
                pass
