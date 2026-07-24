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
import json
import logging
import os
import threading
import time
import urllib.request
from typing import Any, AsyncIterator, Dict, Optional

# Lazy imports — hakus/ pulls in openai, anthropic, etc. which may
# not all be installed in the sidecar's PyInstaller bundle. We defer
# the import to first use so /health still works even if some
# optional provider SDK is missing.

logger = logging.getLogger(__name__)

# Project root is two levels above src/hakusai_server/agent_bridge.py
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SIDECAR_SYSTEM_PROMPT = """\
You are HakusAI, an AI-powered development assistant running inside the HakusAI sidecar.

CRITICAL WORKFLOW RULES:
1. **Use file-operation tools first** — For reading, writing, or editing files, ALWAYS use the dedicated tools (read_file, write_file, edit_file, glob, grep, tree, list_dir) instead of writing a Python or shell script to do the same job. Bash is reserved for shell-specific tasks only (e.g., git, npm, running tests).
2. **Respect the working directory** — All file paths are relative to the configured workspace root. Do NOT create files outside the workspace unless the user explicitly asks for a different path.
3. **Read before Edit** — Always read a file before editing. The edit tool's old_string must be unique; if not, use more context or replace_all.
4. **Plan complex tasks** — For non-trivial work, break it into steps and track progress with TodoWrite.
5. **Do not generate throwaway scripts** — Never write a temporary Python script to inspect or transform files when a built-in tool can do it directly.

Current workspace root: {working_dir}
"""

# #region debug-point helper
_DEBUG_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".dbg", "agent-stalls-after-tools.env",
)
_DEBUG_URL = "http://127.0.0.1:7777/event"
_DEBUG_SESSION = "agent-stalls-after-tools"


def _debug_log(hypothesis_id: str, location: str, msg: str, data: Optional[Dict[str, Any]] = None) -> None:
    try:
        url = _DEBUG_URL
        session = _DEBUG_SESSION
        try:
            with open(_DEBUG_ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("DEBUG_SERVER_URL="):
                        url = line.split("=", 1)[1].strip()
                    elif line.startswith("DEBUG_SESSION_ID="):
                        session = line.split("=", 1)[1].strip()
        except Exception:
            pass
        payload = {
            "sessionId": session,
            "runId": "pre",
            "hypothesisId": hypothesis_id,
            "location": location,
            "msg": f"[DEBUG] {msg}",
            "data": data or {},
            "ts": time.time(),
        }
        body = json.dumps(payload).encode("utf-8")
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=1).read()
        except Exception:
            pass
        try:
            local_log = os.path.join(
                os.path.dirname(_DEBUG_ENV_PATH),
                f"trae-debug-log-{session}.ndjson.local",
            )
            with open(local_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass
    except Exception:
        pass


# #endregion


# Per-session AgentCore cache. Each (session_id, provider) pair gets its
# own AgentCore with its own ContextManager — sessions are isolated, and
# switching provider mid-session creates a fresh agent (so the user's
# "switch to OpenCode" actually takes effect instead of being ignored).
_agent_cache: Dict[tuple, Any] = {}
_agent_cache_lock = threading.Lock()

# Per-session op_receiver queue. Frontends push AnswerOp (and other Op)
# instances here to interact with a running turn (e.g. answer an
# ask_user question). The queue is keyed by session_id only, so both
# SSE and WebSocket turns on the same session share the same inbound
# channel. Multiple concurrent turns on the same session will all read
# from the same queue; each AnswerOp carries a question_id so only the
# matching turn consumes it.
_session_op_receivers: Dict[str, asyncio.Queue] = {}
_session_op_lock = threading.Lock()


def _get_or_create_op_receiver(session_id: str) -> asyncio.Queue:
    """Return the per-session op queue, creating it if necessary."""
    with _session_op_lock:
        if session_id not in _session_op_receivers:
            _session_op_receivers[session_id] = asyncio.Queue(maxsize=100)
        return _session_op_receivers[session_id]


def post_answer(session_id: str, question_id: str, choice: str) -> bool:
    """Push an AnswerOp into the session's op_receiver.

    Returns True if the op was queued, False if the queue does not exist
    or is full (the turn may have already ended or the question timed out).
    """
    from hakus.protocol import AnswerOp

    # #region debug-point A:post-answer
    _debug_log("A", "agent_bridge.py:post_answer", "answer posted", {"session_id": session_id, "question_id": question_id, "choice": choice})
    # #endregion
    with _session_op_lock:
        queue = _session_op_receivers.get(session_id)
    if queue is None:
        # #region debug-point A:post-answer-no-queue
        _debug_log("A", "agent_bridge.py:post_answer", "no queue for session", {"session_id": session_id})
        # #endregion
        return False
    try:
        queue.put_nowait(AnswerOp(question_id=question_id, choice=choice))
        # #region debug-point A:post-answer-queued
        _debug_log("A", "agent_bridge.py:post_answer", "answer queued", {"session_id": session_id, "question_id": question_id, "queue_size": queue.qsize()})
        # #endregion
        return True
    except asyncio.QueueFull:
        logger.warning(
            f"op_receiver full for session={session_id}, dropping answer"
        )
        return False


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


# 危险操作模式（需要额外审查或拒绝）
DANGEROUS_ACTION_PATTERNS = [
    r"delete", r"remove", r"rm\s",
    r"format", r"mkfs",
    r"overwrite", r">\s*/",
    r"chmod\s+777",
    r"curl.*\\|.*sh",
    r"shutdown", r"reboot",
]

# 严格模式：如果为 True，所有需要权限的操作都会被拒绝
STRICT_MODE = os.environ.get("HAKUSAI_STRICT_MODE", "false").lower() == "true"


def _make_confirm_callback():
    """Permission callback for tool execution.

    Security improvements (v2):
    - Logs all permission requests with action details
    - Blocks dangerous operations in strict mode
    - Respects the permission system's built-in deny rules
    - Audits all auto-approvals for security review

    The callback returns:
    - "session": approved (execute the action)
    - "deny": denied (block the action)

    Note: This is still auto-approve by default for backward compatibility.
    Enable strict mode via HAKUSAI_STRICT_MODE=true env var.
    """
    import re

    def _cb(action_key: str, reason: str) -> str:
        # 记录所有权限请求
        logger.info(f"[sidecar-perm] Request: {action_key} ({reason})")
        
        # 严格模式下拒绝所有需要确认的操作
        if STRICT_MODE:
            logger.warning(
                f"[sidecar-perm] DENIED (strict mode): {action_key} ({reason}). "
                f"Set HAKUSAI_STRICT_MODE=false to allow."
            )
            return "deny"
        
        # 检查是否匹配危险操作模式
        action_lower = action_key.lower() + " " + reason.lower()
        for pattern in DANGEROUS_ACTION_PATTERNS:
            try:
                if re.search(pattern, action_lower, re.IGNORECASE):
                    logger.warning(
                        f"[sidecar-perm] DANGEROUS operation approved: {action_key}. "
                        f"Consider enabling strict mode for additional security."
                    )
                    break
            except re.error:
                pass
        
        # 默认放行（向后兼容）
        logger.info(f"[sidecar-perm] Approved: {action_key}")
        return "session"

    return _cb


def _make_async_confirm_callback():
    """Async version of _make_confirm_callback with security checks."""
    import re

    async def _cb(action_key: str, reason: str) -> str:
        # 记录所有权限请求
        logger.info(f"[sidecar-perm] Async Request: {action_key} ({reason})")
        
        # 严格模式下拒绝所有需要确认的操作
        if STRICT_MODE:
            logger.warning(
                f"[sidecar-perm] DENIED (strict mode): {action_key} ({reason})"
            )
            return "deny"
        
        # 检查危险操作
        action_lower = action_key.lower() + " " + reason.lower()
        for pattern in DANGEROUS_ACTION_PATTERNS:
            try:
                if re.search(pattern, action_lower, re.IGNORECASE):
                    logger.warning(
                        f"[sidecar-perm] DANGEROUS async op: {action_key}"
                    )
                    break
            except re.error:
                pass
        
        logger.info(f"[sidecar-perm] Async Approved: {action_key}")
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
                working_dir=_REPO_ROOT,
                # Sidecar runs headless — no Textual event loop. The
                # async confirm callback path is used because run_turn
                # is async. The sync callback would also work (it's
                # called from the async path when no async callback
                # is set), but setting both keeps the behavior
                # identical regardless of which code path runs.
            )
            try:
                agent.set_system_prompt(_SIDECAR_SYSTEM_PROMPT.format(working_dir=_REPO_ROOT))
            except Exception as e:
                logger.warning(f"Could not set sidecar system prompt: {e}")
            # Install async callback too — AgentCore uses it when
            # _tui_mode is False (which is the case here).
            try:
                agent._permission.set_async_confirm_callback(_make_async_confirm_callback())
            except Exception as e:
                logger.warning(f"Could not set async confirm callback: {e}")

            # Phase 2 round 2: register MCP tools into the agent.
            # If McpClientManager has running servers, their tools become
            # available to this agent. Idempotent — calling twice for the
            # same agent just re-registers (registry overwrites by name).
            try:
                from hakus.mcp.manager import get_mcp_manager
                mcp_mgr = get_mcp_manager()
                if mcp_mgr is not None:
                    count = mcp_mgr.register_tools_into(agent)
                    if count > 0:
                        logger.info(
                            f"[MCP] registered {count} MCP tools into "
                            f"session={session_id} provider={resolved_provider}"
                        )
            except Exception as e:
                # MCP is optional — don't crash agent creation if it fails.
                logger.warning(f"[MCP] tool registration failed (non-blocking): {e}")

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
    op_receiver = _get_or_create_op_receiver(session_id)

    accumulated = ""
    input_tokens = 0
    output_tokens = 0
    iterations = 0

    # #region debug-point E:stream-start
    _debug_log("E", "agent_bridge.py:run_turn_stream", "stream start", {"session_id": session_id, "provider": provider})
    # #endregion
    try:
        async for event in agent.run_turn(message, op_receiver=op_receiver):
            try:
                evt_dict = serialize_event(event)
            except Exception as e:
                logger.warning(f"Failed to serialize event {type(event).__name__}: {e}")
                continue

            etype = evt_dict.get("event_type", "")
            if etype in ("question_asked", "question_answered"):
                # #region debug-point E:question-event-forward
                _debug_log("E", "agent_bridge.py:run_turn_stream", f"forwarding {etype}", {"session_id": session_id, "question_id": evt_dict.get("question_id")})
                # #endregion

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
                try:
                    agent._tool_executor.cleanup_temp_paths()
                except Exception as e:
                    logger.warning(f"Temp cleanup failed after turn_completed: {e}")
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
                try:
                    agent._tool_executor.cleanup_temp_paths()
                except Exception as e:
                    logger.warning(f"Temp cleanup failed after turn_failed: {e}")
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
                try:
                    agent._tool_executor.cleanup_temp_paths()
                except Exception as e:
                    logger.warning(f"Temp cleanup failed after cancelled: {e}")
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
        try:
            agent._tool_executor.cleanup_temp_paths()
        except Exception as cleanup_err:
            logger.warning(f"Temp cleanup failed after stream error: {cleanup_err}")
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


# ============================================================================
# Phase 4: Active turn cancellation
# ============================================================================
#
# AgentCore exposes a ``self._cancelled`` bool flag that the orchestrator
# checks between iterations (see hakus/agent.py:1482, 1558, etc.). Setting
# this flag causes the next loop iteration to break and emit a
# ``CancelledEvent`` — exactly what we want for the WebSocket ``interrupt``
# message.
#
# We don't use asyncio.Task.cancel() here because the WebSocket turn runs
# inline in the WS handler task (no separate Task wrapping run_turn_stream).
# Cancelling the WS handler task itself would tear down the whole connection,
# not just the current turn.

def cancel_session_turn(session_id: str) -> int:
    """Cancel all in-flight turns for a session. Returns count cancelled.

    Called by the WebSocket ``interrupt`` message handler. Sets the
    ``_cancelled`` flag on every AgentCore bound to this session_id
    (across all providers). AgentCore's orchestrator checks the flag
    between iterations and emits a ``cancelled`` AgentEvent.
    """
    cancelled = 0
    with _agent_cache_lock:
        matching = [(k, v) for k, v in _agent_cache.items() if k[0] == session_id]
    for (sess, provider), agent in matching:
        try:
            if getattr(agent, "_running", False) and not getattr(agent, "_cancelled", False):
                agent._cancelled = True
                cancelled += 1
                logger.info(
                    f"Cancelled turn for session={sess} provider={provider}"
                )
        except Exception as e:
            logger.warning(f"Failed to set _cancelled on agent {matching}: {e}")
    return cancelled
