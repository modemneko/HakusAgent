"""FastAPI metrics middleware — HTTP request latency / error / counter tracking.

Mounts into the sidecar's FastAPI app to automatically track:
  - Request count by (method, path, status_code)
  - Request latency histogram by (method, path, status_code)
  - Error rate (5xx responses)

Also enriches the existing /api/metrics JSON response with histogram data.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

try:
    from prometheus_client import Counter, Histogram
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False


# ---------------------------------------------------------------------------
# Metrics middleware
# ---------------------------------------------------------------------------

class MetricsMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that records HTTP request metrics.

    Tracks:
      - hakus_http_request_duration_seconds{method, path, status_code}
      - hakus_http_request_total{method, path, status_code}

    Skips /metrics endpoint itself to avoid recursive metrics.
    """

    # Paths to skip (avoid self-referential metrics noise)
    SKIP_PATHS = {"/metrics", "/health", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        method = request.method

        # Skip metrics self-collection
        if path in self.SKIP_PATHS:
            return await call_next(request)

        # Normalize path to avoid label cardinality explosion
        # e.g. /api/sessions/s-42/checkpoints → /api/sessions/{id}/checkpoints
        normalized_path = _normalize_path(path)

        start = time.monotonic()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            # Unhandled exception → 500
            status_code = 500
            raise
        finally:
            if HAS_PROMETHEUS:
                duration = time.monotonic() - start
                try:
                    from hakus.observability.prometheus_metrics import metrics_registry
                    metrics_registry.http_request_duration.labels(
                        method=method,
                        path=normalized_path,
                        status_code=str(status_code),
                    ).observe(duration)
                    metrics_registry.http_request_total.labels(
                        method=method,
                        path=normalized_path,
                        status_code=str(status_code),
                    ).inc()
                except Exception:
                    pass  # Never let metrics break the request

        return response


def _normalize_path(path: str) -> str:
    """Normalize URL path to reduce label cardinality.

    Replaces dynamic segments (UUIDs, numeric IDs) with placeholders.

    Examples:
        /api/sessions/s-42abc/checkpoints → /api/sessions/{id}/checkpoints
        /api/chat/123                     → /api/chat/{id}
        /api/sessions/default/messages    → /api/sessions/{id}/messages
    """
    parts = path.strip("/").split("/")
    normalized = []

    # Known path patterns where the Nth segment is a dynamic ID
    # (prefix, index_of_id_segment)
    _DYNAMIC_SEGMENTS = {
        ("api", "sessions"): 2,   # /api/sessions/{id}/...
        ("api", "chat"): 2,       # /api/chat/{id}
    }

    id_index = None
    for prefix, idx in _DYNAMIC_SEGMENTS.items():
        if len(parts) >= len(prefix) and tuple(parts[:len(prefix)]) == prefix:
            id_index = idx
            break

    for i, part in enumerate(parts):
        if id_index is not None and i == id_index:
            normalized.append("{id}")
        elif _looks_like_id(part):
            normalized.append("{id}")
        else:
            normalized.append(part)

    return "/" + "/".join(normalized) if normalized else "/"


def _looks_like_id(segment: str) -> bool:
    """Heuristic: does this path segment look like a dynamic ID?"""
    # UUID-like: 8-4-4-4-12 hex chars with dashes
    if len(segment) >= 8 and "-" in segment:
        hex_chars = segment.replace("-", "")
        if len(hex_chars) >= 12 and all(c in "0123456789abcdefABCDEF" for c in hex_chars):
            return True
    # Pure numeric
    if segment.isdigit():
        return True
    # Long alphanumeric (session IDs, etc.)
    if len(segment) > 20 and any(c.isdigit() for c in segment) and any(c.isalpha() for c in segment):
        return True
    return False
