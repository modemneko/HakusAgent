"""Bridge between hakusai_server (FastAPI sidecar) and hakus.AgentCore.

The sidecar used to use ``hakusai_core.agent.BaseAgent`` — a thin
chat-only wrapper with no tools, no permissions, no AgentEvent
stream. That meant the desktop client could only do single-turn
chat; all the SWE coding-agent machinery (24 tools, orchestrator,
checkpoint, recovery) was unreachable from the desktop.

This module adapts :class:`hakus.agent.AgentCore` to the sidecar's
existing HTTP/SSE shape:

  - ``run_turn_stream(message, session_id)`` is an async generator
    that yields dicts in the **old chunk format** the desktop client
    already understands (``{content, emotion, actions, done}``),
    PLUS a new ``event_type`` field for the future AgentEvent-aware
    client (which already has the TypeScript types ready).

  - The agent runs in ``PermissionMode.ASK`` with an auto-approve
    callback that allows every dangerous call. This matches the
    previous behavior (sidecar has no UI to prompt the user), but
    is now an *explicit* choice — the permission flow is wired and
    can be tightened later by adding an approval-pending HTTP
    endpoint + a frontend dialog.

Why not just call ``AgentCore.run_turn()`` directly from server.py?
Two reasons:
  1. ``run_turn()`` yields :class:`AgentEvent` dataclasses, not
     JSON dicts. We need to serialize + remap to the legacy chunk
     shape so the existing client keeps working.
  2. ``AgentCore`` is a long-lived, stateful object (it owns the
     LLM client, tool registry, context manager, etc.). We need a
     per-session cache so different sessions don't share context.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, AsyncIterator, Dict, Optional

# Lazy imports — hakus/ pulls in openai, anthropic, etc. which may
# not all be installed in the sidecar's PyInstaller bundle. We defer
# the import to first use so /health still works even if some
# optional provider SDK is missing.

logger = logging.getLogger(__name__)


# Per-session AgentCore cache. Each (session_id, provider) pair gets its
# own AgentCore with its own ContextManager — sessions are isolated, and
# switching provider mid-session creates a fresh agent (so the user's
# "switch to OpenCode" actually takes effect instead of being ignored).
_agent_cache: Dict[tuple, Any] = {}
_agent_cache_lock = threading.Lock()


def _resolve_provider(explicit: Optional[str] = None) -> str:
    """Pick the provider name to pass to AgentCore.

    Priority:
      1. ``explicit`` — per-request override from ChatRequest.provider
         (this is what makes the TopBar "switch provider" dropdown work)
      2. ``HAKUSAI_SIDECAR_PROVIDER`` env var (set by electron launcher)
      3. ``models.default_model`` in config.yaml (via BASE_CONFIG)
      4. Fallback to "opencode" (the repo default, free models)
    """
    if explicit:
        return explicit.lower()
    env = os.environ.get("HAKUSAI_SIDECAR_PROVIDER")
    if env:
        return env.lower()
    try:
        from utils.config import BASE_CONFIG
        return str(BASE_CONFIG.get("DEFAULT_MODEL", "opencode")).lower()
    except Exception:
        return "opencode"


def _make_confirm_callback():
    """Auto-approve every dangerous tool call.

    The sidecar has no UI to show a permission dialog, so we
    approve everything. This is the same effective behavior as
    the old BaseAgent (which had no permission system at all),
    but now goes through the full permission pipeline — meaning
    the strict always-deny rules in PermissionChecker still apply
    (e.g. writing to ``.aws/credentials`` will still be blocked).

    Future: replace this with an async callback that pushes an
    ApprovalOp to a per-session queue and waits for the frontend
    to respond via a new ``/api/approval/{session_id}`` endpoint.
    """

    def _cb(action_key: str, reason: str) -> str:
        logger.info(f"[sidecar-perm] auto-approve: {action_key} ({reason})")
        return "session"

    return _cb


def _make_async_confirm_callback():
    """Async version of _make_confirm_callback (for TUI mode off)."""

    async def _cb(action_key: str, reason: str) -> str:
        logger.info(f"[sidecar-perm] auto-approve (async): {action_key} ({reason})")
        return "session"

    return _cb


def get_or_create_agent(session_id: str, provider: Optional[str] = None) -> Any:
    """Return a cached AgentCore for the (session_id, provider) pair,
    or create a new one.

    Creation is lazy and fault-tolerant: if hakus/ can't be imported
    (missing dep), or if the LLM client factory fails (bad API key),
    we raise — the caller (server.py) catches and surfaces the error
    via /health's ``degraded`` state.

    The cache key is ``(session_id, provider)`` so that switching
    provider mid-session (via TopBar dropdown) creates a fresh agent
    bound to the new provider, instead of silently reusing the old one.
    """
    resolved_provider = _resolve_provider(provider)
    cache_key = (session_id, resolved_provider)
    if cache_key in _agent_cache:
        return _agent_cache[cache_key]

    with _agent_cache_lock:
        if cache_key not in _agent_cache:
            # Local imports — see module docstring
            from hakus.agent import AgentCore
            from hakus.permission import PermissionMode

            logger.info(f"Creating AgentCore for session={session_id} provider={resolved_provider}")

            agent = AgentCore(
                model_type=resolved_provider,
                permission_mode=PermissionMode.ASK,
                confirm_callback=_make_confirm_callback(),
                session_id=session_id,
                # Sidecar runs headless — no Textual event loop. The
                # async confirm callback path is used because run_turn
                # is async. The sync callback would also work (it's
                # called from the async path when no async callback
                # is set), but setting both keeps the behavior
                # identical regardless of which code path runs.
            )
            # Install async callback too — AgentCore uses it when
            # _tui_mode is False (which is the case here).
            try:
                agent._permission.set_async_confirm_callback(_make_async_confirm_callback())
            except Exception as e:
                logger.warning(f"Could not set async confirm callback: {e}")

            _agent_cache[cache_key] = agent
    return _agent_cache[cache_key]


def drop_agent(session_id: str, provider: Optional[str] = None) -> None:
    """Drop a session's agent from the cache (used on /api/memory/clear).

    If ``provider`` is None, drops ALL agents for this session_id
    (across all providers). Otherwise drops only the matching pair.
    """
    with _agent_cache_lock:
        if provider is None:
            # Drop all entries whose session_id matches
            keys_to_drop = [k for k in _agent_cache if k[0] == session_id]
            for k in keys_to_drop:
                _agent_cache.pop(k, None)
        else:
            resolved = _resolve_provider(provider)
            _agent_cache.pop((session_id, resolved), None)


# Legacy chunk shape:
#   {"content": str, "emotion": null, "actions": [], "done": False, "event_type": str}
#
# The first four fields keep the existing desktop client working.
# ``event_type`` is added so the future AgentEvent-aware client can
# route on it (the TS types already exist in api/types.ts).
async def run_turn_stream(
    message: str,
    session_id: str = "default",
    provider: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Run one AgentCore turn, yielding legacy-shape chunks.

    Yields dicts with these fields:
      - ``content`` (str): accumulated assistant text (incremental)
      - ``emotion`` (str|None): always None for now (TTS plugin may set later)
      - ``actions`` (list): always [] for now
      - ``done`` (bool): False during stream, True at end
      - ``event_type`` (str): the AgentEvent type tag

    Terminal events (``turn_completed`` / ``turn_failed`` / ``cancelled``)
    set ``done=True`` and end the generator.

    ``provider`` is a per-request override — if set (e.g. "opencode"),
    a fresh AgentCore bound to that provider is used. If None, falls
    back to config.yaml's models.default_model.
    """
    from hakus.protocol.serialization import serialize_event

    agent = get_or_create_agent(session_id, provider=provider)

    accumulated = ""
    input_tokens = 0
    output_tokens = 0
    iterations = 0

    try:
        async for event in agent.run_turn(message):
            try:
                evt_dict = serialize_event(event)
            except Exception as e:
                logger.warning(f"Failed to serialize event {type(event).__name__}: {e}")
                continue

            etype = evt_dict.get("event_type", "")

            if etype == "text_delta":
                text = evt_dict.get("text", "")
                accumulated += text
                yield {
                    "content": text,           # incremental delta (matches old stream format)
                    "emotion": None,
                    "actions": [],
                    "done": False,
                    "event_type": etype,
                }
            elif etype == "reasoning_delta":
                # Pass through but mark as reasoning — frontend can choose
                # to render it differently (CollapsibleReasoning widget).
                yield {
                    "content": evt_dict.get("text", ""),
                    "emotion": None,
                    "actions": [],
                    "done": False,
                    "event_type": etype,
                    "reasoning": True,
                }
            elif etype == "tool_call_started":
                yield {
                    "content": "",
                    "emotion": None,
                    "actions": [],
                    "done": False,
                    "event_type": etype,
                    "tool_call": {
                        "call_id": evt_dict.get("call_id", ""),
                        "name": evt_dict.get("name", ""),
                        "arguments": evt_dict.get("arguments", {}),
                    },
                }
            elif etype == "tool_call_finished":
                yield {
                    "content": "",
                    "emotion": None,
                    "actions": [],
                    "done": False,
                    "event_type": etype,
                    "tool_call": {
                        "call_id": evt_dict.get("call_id", ""),
                        "name": evt_dict.get("name", ""),
                        "arguments": evt_dict.get("arguments", {}),
                    },
                    "result": evt_dict.get("result", ""),
                    "success": evt_dict.get("success", True),
                    "duration": evt_dict.get("duration", 0.0),
                }
            elif etype == "token_usage":
                input_tokens += evt_dict.get("input_tokens", 0)
                output_tokens += evt_dict.get("output_tokens", 0)
                # Don't yield token_usage as a content chunk — it's metadata.
                # The terminal event will include totals.
            elif etype == "turn_completed":
                iterations = evt_dict.get("iterations", 0)
                yield {
                    "content": "",  # already streamed via text_delta
                    "emotion": None,
                    "actions": [],
                    "done": True,
                    "event_type": etype,
                    "iterations": iterations,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "compressed": evt_dict.get("compressed", False),
                }
                return
            elif etype == "turn_failed":
                yield {
                    "content": "",
                    "emotion": None,
                    "actions": [],
                    "done": True,
                    "event_type": etype,
                    "error": evt_dict.get("error", "unknown error"),
                    "code": evt_dict.get("code", "unknown"),
                }
                return
            elif etype == "cancelled":
                yield {
                    "content": accumulated,
                    "emotion": None,
                    "actions": [],
                    "done": True,
                    "event_type": etype,
                    "reason": evt_dict.get("reason", ""),
                    "partial_content": evt_dict.get("partial_content", ""),
                }
                return
            else:
                # Pass through unknown event types as-is (with empty content)
                # so future events don't break the stream.
                yield {
                    "content": "",
                    "emotion": None,
                    "actions": [],
                    "done": False,
                    "event_type": etype,
                    **{k: v for k, v in evt_dict.items() if k != "event_type"},
                }

    except asyncio.CancelledError:
        # Client disconnected — let AgentCore clean up via its own cancel path.
        logger.info(f"run_turn cancelled by client (session={session_id})")
        raise
    except Exception as e:
        logger.exception(f"run_turn_stream error (session={session_id}): {e}")
        yield {
            "content": "",
            "emotion": None,
            "actions": [],
            "done": True,
            "event_type": "turn_failed",
            "error": str(e),
            "code": "stream_error",
        }


async def run_turn_collect(
    message: str,
    session_id: str = "default",
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a turn and return the full response as a single dict.

    Used by the non-streaming ``/api/chat`` endpoint.
    """
    full_content = ""
    iterations = 0
    input_tokens = 0
    output_tokens = 0
    error: Optional[str] = None
    failed = False

    async for chunk in run_turn_stream(message, session_id, provider=provider):
        if chunk.get("content"):
            full_content += chunk["content"]
        if chunk.get("input_tokens"):
            input_tokens += chunk["input_tokens"]
        if chunk.get("output_tokens"):
            output_tokens += chunk["output_tokens"]
        if chunk.get("iterations"):
            iterations = chunk["iterations"]
        if chunk.get("event_type") == "turn_failed":
            failed = True
            error = chunk.get("error", "unknown error")

    return {
        "content": full_content,
        "emotion": None,
        "actions": [],
        "session_id": session_id,
        "iterations": iterations,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "failed": failed,
        "error": error,
    }


def clear_session_history(session_id: str) -> bool:
    """Clear a session's conversation context across ALL providers.

    Returns True if at least one agent existed and was cleared,
    False otherwise.
    """
    # Find any agent for this session_id (across all providers).
    # Cache key is now (session_id, provider) tuple, so we look up by prefix.
    matching = [v for k, v in _agent_cache.items() if k[0] == session_id]
    if not matching:
        return False
    cleared_any = False
    for agent in matching:
        try:
            # AgentCore has a clear_history-like path via ContextManager reset
            ctx = getattr(agent, "_context", None)
            if ctx is not None and hasattr(ctx, "reset"):
                ctx.reset()
                cleared_any = True
                continue
            # Fall back: drop the agent entirely (next call recreates fresh)
            # (handled below — we don't drop here because we'd need provider too)
        except Exception as e:
            logger.warning(f"clear_session_history failed for {session_id}: {e}")
    # If nothing had a reset method, drop everything for this session
    if not cleared_any:
        drop_agent(session_id)
        return True
    return cleared_any or True
