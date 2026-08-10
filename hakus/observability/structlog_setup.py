"""structlog setup — structured logging with JSON renderer for sidecar.

Design goals:
  1. Every log line is valid JSON (NDJSON), parseable by jq / Grafana Loki / ELK
  2. Context binding: bind_request_id / bind_session_id adds fields to all subsequent logs
  3. Drop-in replacement for stdlib logging — same `log.info()` / `log.error()` API
  4. Console: Rich human-readable format during dev; JSON in production
  5. File: Always JSON — sidecar.log / agent.log / tools.log / llm.log
  6. Backward compatible: existing `utils.logger.get_logger()` still works

Usage::

    from hakus.observability import get_structlog, bind_context

    log = get_structlog("hakus.agent")
    log.info("turn_started", turn_id="t-42", provider="opencode")
    # → {"event":"turn_started","turn_id":"t-42","provider":"opencode","ts":"...","level":"info","logger":"hakus.agent"}

    # Bind context that appears in ALL subsequent log lines from this logger:
    with bind_context(session_id="s-1", request_id="r-1"):
        log.info("llm_call", model="mimo-v2.5")
        # → {"event":"llm_call","model":"mimo-v2.5","session_id":"s-1","request_id":"r-1",...}
"""
from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

import structlog

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_IS_PROD = os.environ.get("HAKUSAI_ENV", "dev") != "dev"
_LOG_LEVEL = os.environ.get("HAKUSAI_LOG_LEVEL", "INFO").upper()

# Thread-local context storage for bind_context
_context_local = threading.local()


def _get_bound_context() -> Dict[str, Any]:
    """Return the current thread-local bound context fields."""
    return getattr(_context_local, "fields", {})


@contextmanager
def bind_context(**fields: Any):
    """Context manager that adds fields to all structlog log lines within scope.

    Example::

        with bind_context(session_id="s-1", turn_id="t-42"):
            log.info("step", action="compress")  # includes session_id + turn_id
    """
    old = getattr(_context_local, "fields", {}).copy()
    current = old.copy()
    current.update(fields)
    _context_local.fields = current
    try:
        yield
    finally:
        _context_local.fields = old


def clear_context() -> None:
    """Clear all bound context fields for the current thread."""
    _context_local.fields = {}


# ---------------------------------------------------------------------------
# Processors (shared between console and file)
# ---------------------------------------------------------------------------

def _add_timestamp(
    logger: Any, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Add ISO-8601 timestamp with milliseconds."""
    event_dict["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"
    return event_dict


def _add_log_level(
    logger: Any, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Normalize level name to uppercase string."""
    event_dict["level"] = method_name.upper()
    return event_dict


def _add_logger_name(
    logger: Any, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Add the logger name (from stdlib logger binding)."""
    if "logger" not in event_dict and hasattr(logger, "name"):
        event_dict["logger"] = logger.name
    return event_dict


def _add_bound_context(
    logger: Any, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge thread-local bound context into every log line."""
    ctx = _get_bound_context()
    if ctx:
        # Don't overwrite explicitly passed fields
        for k, v in ctx.items():
            event_dict.setdefault(k, v)
    return event_dict


def _rename_event_msg(
    logger: Any, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Rename structlog's default 'event' key to 'msg' for backward compat with existing NDJSON format."""
    if "event" in event_dict:
        event_dict["msg"] = event_dict.pop("event")
    return event_dict


# ---------------------------------------------------------------------------
# Renderer chains
# ---------------------------------------------------------------------------

# JSON renderer (always used for file output, and for console in prod)
_json_processors = [
    structlog.contextvars.merge_contextvars,
    _add_timestamp,
    _add_log_level,
    _add_logger_name,
    _add_bound_context,
    _rename_event_msg,
    structlog.processors.format_exc_info,
    structlog.processors.JSONRenderer(ensure_ascii=False),
]

# Console renderer (human-readable, used in dev)
_console_processors = [
    structlog.contextvars.merge_contextvars,
    _add_timestamp,
    _add_log_level,
    _add_logger_name,
    _add_bound_context,
    structlog.dev.ConsoleRenderer(
        colors=hasattr(sys.stdout, "isatty") and sys.stdout.isatty(),
        level_styles={
            "debug": "\033[36m",     # cyan
            "info": "\033[32m",      # green
            "warning": "\033[33m",   # yellow
            "error": "\033[31m",     # red
            "critical": "\033[1;31m", # bold red
        },
    ),
]


# ---------------------------------------------------------------------------
# Logger cache
# ---------------------------------------------------------------------------

_logger_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()


def _configure_structlog() -> None:
    """One-time structlog configuration. Safe to call multiple times."""
    if getattr(_configure_structlog, "_done", False):
        return

    processors = _json_processors if _IS_PROD else _console_processors

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(sys.modules.get("logging", None), _LOG_LEVEL, 20)  # default INFO=20
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,  # We manage our own cache
    )
    _configure_structlog._done = True  # type: ignore[attr-defined]


def get_structlog(name: str) -> Any:
    """Get a structlog logger with the given name.

    In dev mode: console output uses Rich human-readable format.
    In prod mode: all output is JSON NDJSON.
    File output is always JSON (handled by sidecar's logging_config.py).

    Args:
        name: Logger name, e.g. "hakus.agent", "hakus.llm.call"

    Returns:
        A structlog BoundLogger with info/debug/warning/error methods.
    """
    if name in _logger_cache:
        return _logger_cache[name]

    with _cache_lock:
        if name in _logger_cache:
            return _logger_cache[name]

        _configure_structlog()
        log = structlog.get_logger(name)
        _logger_cache[name] = log
        return log
