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
import re
import threading
import time
import urllib.request
from typing import Any, AsyncIterator, Dict, Optional

from hakus.modes import DEFAULT_RUN_MODE, DEEP_MODE, FLEET_MODE, SWIFT_MODE, normalize_run_mode

from .logging_config import get_logger, structured

# Lazy imports — hakus/ pulls in openai, anthropic, etc. which may
# not all be installed in the sidecar's PyInstaller bundle. We defer
# the import to first use so /health still works even if some
# optional provider SDK is missing.

logger = get_logger("haku.agent.bridge")

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
6. **Windows path rule** — On Windows, absolute paths such as `E:\\dir\\file.py` must be handled with create_directory, write_file, read_file, list_dir, or edit_file. Do not use bash/cmd for mkdir/dir/copy on Windows absolute paths; only use bash for running verifiers such as `python -m pytest ...`.

PERSISTENCE RULES (IMPORTANT — do not stop prematurely):
7. **Keep working until the task is fully done** — Do NOT produce a "summary" response and stop while there are still steps remaining. If you have read files and identified the issue, you MUST proceed to fix it, not just describe it.
8. **Always call tools to make changes** — A turn ends only when (a) the task is complete and verified, or (b) you genuinely need user input. Do NOT end the turn by writing a prose summary of "what I would do next" — actually do it.
9. **Verify after changes** — After editing code, run the relevant tests / build / type-check to confirm your change works. Only report "done" after verification passes.
10. **Recover from errors** — If a tool call fails, read the error, fix the root cause, and retry. Do NOT give up after a single failure. Only surface the failure to the user after 3 genuine attempts with different approaches.
11. **Use TodoWrite for multi-step tasks** — Break down complex work into todo items and check them off as you go. This prevents the context from filling up with unrelated exploration.

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
      3. ``models.default_model`` in config.yaml — read LIVE via
         ``hakus_config.get_config()`` so that a default-model change
         performed via ``POST /api/config/default-model`` takes effect
         immediately (without requiring a process restart).
         Falls back to the module-level ``BASE_CONFIG`` if the live
         config layer is unavailable.
      4. Fallback to "opencode" (the repo default, free models)
    """
    if explicit:
        return explicit.lower()
    env = os.environ.get("HAKUSAI_SIDECAR_PROVIDER")
    if env:
        return env.lower()
    try:
        # Prefer the live config (reloaded by hakus_config.reload_config()
        # whenever the default model is changed). This avoids the historic
        # bug where BASE_CONFIG was frozen at process start and a provider
        # switch didn't take effect until restart.
        from utils.hakus_config import get_config
        live = get_config().models.default_model
        if live:
            return str(live).lower()
    except Exception:
        pass
    try:
        from utils.config import BASE_CONFIG
        return str(BASE_CONFIG.get("DEFAULT_MODEL", "opencode")).lower()
    except Exception:
        return "opencode"


def _extract_benchmark_output_dir(message: str) -> Optional[str]:
    """Return the isolated benchmark workspace embedded in benchmark prompts."""
    if "Benchmark isolation rules:" not in message:
        return None
    match = re.search(
        r"(?mi)^-\s*Only create or modify files under this output directory:\s*(.+?)\s*$",
        message,
    )
    if not match:
        return None
    output_dir = match.group(1).strip().strip("`").strip()
    if not output_dir or not os.path.isabs(output_dir):
        return None
    return os.path.normpath(output_dir)


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


def drop_all_agents() -> None:
    """Drop every cached AgentCore.

    Called when the default provider is changed via
    ``POST /api/config/default-model`` (or via ``update_provider`` with
    ``set_as_default: true``). Without this, paths that call
    ``run_turn_*`` without an explicit ``provider`` (e.g. the WeChat
    handler, the voice-call handler) would keep reusing the cached
    ``(session_id, old_provider)`` agent instead of picking up the new
    default.
    """
    with _agent_cache_lock:
        _agent_cache.clear()


async def _fleet_event_stream(
    agent: Any,
    message: str,
    workspace_dir: str,
) -> AsyncIterator[Any]:
    """Fleet 模式事件流适配器.

    把 FleetOrchestrator.run() 适配成 AsyncIterator[AgentEvent]，
    这样 SSE 流处理逻辑可以统一处理 Swift/Deep/Fleet 三种模式。

    yield 的事件:
      - TextDelta: 进度更新 + 最终汇总
      - TurnCompleted: Fleet 完成信号
    """
    import asyncio as _asyncio

    from hakus.fleet import FleetOrchestrator
    from hakus.fleet.scheduler import TaskStatus
    from hakus.protocol.events import Cancelled, TextDelta, TurnCompleted, TurnFailed

    fleet = FleetOrchestrator(
        root_agent=agent,
        workspace_dir=workspace_dir,
        concurrency=int(os.environ.get("HAKUS_FLEET_CONCURRENCY", "10")),
    )

    # 进度队列：ParallelScheduler 回调 → 事件流
    progress_queue: _asyncio.Queue = _asyncio.Queue()

    def _on_progress(task: Any) -> None:
        icons = {
            TaskStatus.RUNNING: "▶",
            TaskStatus.COMPLETED: "✓",
            TaskStatus.FAILED: "✗",
            TaskStatus.TIMEOUT: "⏱",
        }
        icon = icons.get(task.status, "?")
        if task.status == TaskStatus.RUNNING:
            text = f"{icon} {task.id} ({task.role}) 启动...\n"
        elif task.status == TaskStatus.COMPLETED:
            text = f"{icon} {task.id} ({task.role}) 完成 ({task.elapsed:.1f}s)\n"
        elif task.status == TaskStatus.FAILED:
            text = f"{icon} {task.id} ({task.role}) 失败: {task.error}\n"
        elif task.status == TaskStatus.TIMEOUT:
            text = f"{icon} {task.id} ({task.role}) 超时\n"
        else:
            return
        try:
            progress_queue.put_nowait(text)
        except Exception:
            pass

    fleet._scheduler.on_progress(_on_progress)

    # 发送启动消息
    yield TextDelta(text="🚢 Fleet 模式启动，正在分析任务...\n\n")

    # 后台运行 Fleet
    fleet_task = _asyncio.create_task(fleet.run(message))

    # 从队列读取进度，直到 Fleet 完成
    while not fleet_task.done():
        if getattr(agent, "_cancelled", False):
            fleet.cancel()
            fleet_task.cancel()
            yield Cancelled(reason="user_interrupted", partial_content="Fleet cancelled by user")
            return
        try:
            progress = await _asyncio.wait_for(progress_queue.get(), timeout=0.5)
            yield TextDelta(text=progress)
        except _asyncio.TimeoutError:
            pass
        except Exception:
            pass

    # 获取最终结果
    try:
        result = await fleet_task
    except _asyncio.CancelledError:
        fleet.cancel()
        yield Cancelled(reason="user_interrupted", partial_content="Fleet cancelled by user")
        return
    except Exception as e:
        yield TextDelta(text=f"\n❌ Fleet 执行出错: {e}\n")
        yield TurnFailed(code="fleet_error", error=str(e))
        return

    # 发送汇总
    summary_header = (
        f"\n📊 Fleet 完成: {result.completed}/{result.expert_count} 专家成功, "
        f"耗时 {result.elapsed:.1f}s\n\n"
    )
    yield TextDelta(text=summary_header)
    yield TextDelta(text=result.summary)

    if result.success:
        yield TurnCompleted(
            content=result.summary,
            total_time=result.elapsed,
            output_tokens=result.tokens_estimate,
        )
    else:
        yield TurnFailed(
            code="fleet_incomplete",
            error=(
                f"Fleet incomplete: {result.completed}/{result.expert_count} "
                f"experts completed, {result.failed} failed, {result.timeout} timed out"
            ),
        )


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
    run_mode: Optional[str] = None,
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

    structured(
        logger,
        logging.INFO,
        "stream_start",
        session_id=session_id,
        provider=provider or "default",
        message_length=len(message),
    )

    # #region debug-point E:stream-start
    _debug_log("E", "agent_bridge.py:run_turn_stream", "stream start", {"session_id": session_id, "provider": provider})
    # #endregion

    # ── Tri-mode routing (Swift / Deep / Fleet) ────────────────────────
    # Swift 模式 (default): 单 AgentCore 循环 + 规则 Tester (零 LLM)
    #   - 省 ~84% token：合并 Planner+Dev，Tester 改规则检测
    #   - 适合日常编码、快速修复、token 敏感场景
    # Deep 模式: Orchestrator + 多 Agent 集群 (Planner→Dev→3×DimTester)
    #   - 质量最高但 token 消耗大 (4-5x)
    #   - 适合关键任务、需要多维审查的复杂项目
    # Fleet 模式: 自组织蜂群 (Commander→N×Expert 全局并行)
    #   - 学习 Kimi Agent Swarm: 动态专家 + 全局并行 + 经验库
    #   - 30+ 专家并行，Semaphore 限速，适合大规模复杂任务
    #
    # 通过环境变量 HAKUS_MODE 或前端 run_mode 参数切换
    _run_mode = normalize_run_mode(
        run_mode or os.environ.get("HAKUS_MODE"),
        default=DEFAULT_RUN_MODE,
    )

    use_orchestrator = False
    use_rule_tester = False
    use_fleet = False
    use_deep_single_task = False
    deep_workspace_dir: Optional[str] = None
    orch: Optional["Any"] = None

    if _run_mode == FLEET_MODE:
        # Fleet 模式：Commander 动态拆解 + N 专家全局并行
        use_fleet = True
        structured(
            logger,
            logging.INFO,
            "route_fleet_mode",
            session_id=session_id,
            mode="fleet",
        )
    elif _run_mode == DEEP_MODE:
        benchmark_workspace = _extract_benchmark_output_dir(message)
        # Deep 模式：复杂度路由 → Orchestrator 或 AgentCore
        try:
            from hakus.complexity_scorer import TaskComplexityScorer
            _scorer = TaskComplexityScorer()
            _score = _scorer.score(message)
            use_orchestrator = _score.should_orchestrate
            structured(
                logger,
                logging.INFO,
                "route_deep_mode",
                session_id=session_id,
                mode="deep",
                use_orchestrator=use_orchestrator,
                score=_score.total,
            )
        except Exception as _route_err:
            logger.warning(f"Complexity routing failed, falling back to AgentCore: {_route_err}")
            use_orchestrator = False
        if benchmark_workspace is not None or os.environ.get("HAKUS_DEEP_SKIP_PLANNER", "0") == "1":
            agent_context = getattr(agent, "_context", None)
            deep_workspace_dir = (
                benchmark_workspace
                or getattr(agent_context, "working_dir", None)
                or _REPO_ROOT
            )
            use_deep_single_task = True
            use_orchestrator = True
            structured(
                logger,
                logging.INFO,
                "route_deep_single_task",
                session_id=session_id,
                mode="deep",
                workspace_dir=deep_workspace_dir,
            )
    else:
        # Swift 模式：单 Agent + 规则 Tester
        _run_mode = SWIFT_MODE
        use_orchestrator = False
        use_rule_tester = os.environ.get("HAKUS_SWIFT_RULE_TESTER", "0") == "1"
        structured(
            logger,
            logging.INFO,
            "route_swift_mode",
            session_id=session_id,
            mode="swift",
            rule_tester=use_rule_tester,
        )

    try:
        if use_fleet:
            # Fleet mode: Commander 动态拆解 + N 专家全局并行
            agent_context = getattr(agent, "_context", None)
            workspace_dir = getattr(agent_context, "working_dir", None) or _REPO_ROOT
            event_source = _fleet_event_stream(agent, message, workspace_dir)
        elif use_orchestrator:
            # Orchestrator mode: multi-agent pipeline (Plan→Develop→Test→Fix)
            from hakus.orchestrator import Orchestrator, OrchestratorConfig
            workspace_dir = deep_workspace_dir or _REPO_ROOT
            orch = Orchestrator(
                root_agent=agent,
                workspace_dir=workspace_dir,
                config=OrchestratorConfig(
                    batch_size=int(os.environ.get("HAKUS_DEEP_BATCH_SIZE", "1")),
                    max_fix_rounds=int(os.environ.get("HAKUS_DEEP_MAX_FIX_ROUNDS", "2")),
                    dev_timeout=int(os.environ.get("HAKUS_DEEP_DEV_TIMEOUT", "240")),
                    tester_timeout=int(os.environ.get("HAKUS_DEEP_TESTER_TIMEOUT", "120")),
                    planner_timeout=int(os.environ.get("HAKUS_DEEP_PLANNER_TIMEOUT", "120")),
                    auto_recover=os.environ.get("HAKUS_DEEP_AUTO_RECOVER", "0") == "1",
                    use_multi_dim_test=os.environ.get("HAKUS_DEEP_MULTI_DIM", "0") == "1",
                    enable_final_test=os.environ.get("HAKUS_DEEP_FINAL_TEST", "0") == "1",
                    use_deterministic_verifier=(
                        use_deep_single_task
                        and os.environ.get("HAKUS_DEEP_DETERMINISTIC_VERIFIER", "1") == "1"
                    ),
                ),
            )
            # stream_execute*_v2 yields AgentEvent directly (no need for adapter)
            if use_deep_single_task:
                event_source = orch.stream_execute_single_task_v2(
                    message, title="Benchmark isolated task"
                )
            else:
                event_source = orch.stream_execute_v2(message)
        else:
            # AgentCore mode: standard single-agent loop
            event_source = agent.run_turn(message, op_receiver=op_receiver)

        async for event in event_source:
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
                structured(
                    logger,
                    logging.INFO,
                    "tool_call_started",
                    session_id=session_id,
                    call_id=evt_dict.get("call_id", ""),
                    tool_name=evt_dict.get("name", ""),
                    arguments=evt_dict.get("arguments", {}),
                    mode="orchestrator" if use_orchestrator else "agentcore",
                )
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
                _tc_duration = evt_dict.get("duration", 0.0)
                _tc_success = evt_dict.get("success", True)
                structured(
                    logger,
                    logging.INFO if _tc_success else logging.WARNING,
                    "tool_call_finished",
                    session_id=session_id,
                    call_id=evt_dict.get("call_id", ""),
                    tool_name=evt_dict.get("name", ""),
                    success=_tc_success,
                    duration_ms=round(_tc_duration * 1000, 2),
                    result_length=len(str(evt_dict.get("result", ""))),
                    mode="orchestrator" if use_orchestrator else "agentcore",
                )
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
                    "success": _tc_success,
                    "duration": _tc_duration,
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
                structured(
                    logger,
                    logging.INFO,
                    "turn_completed",
                    session_id=session_id,
                    iterations=iterations,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    accumulated_length=len(accumulated),
                    mode="orchestrator" if use_orchestrator else "agentcore",
                )
                if use_rule_tester:
                    try:
                        from hakus.rule_tester import RuleBasedTester
                        _working_dir = getattr(agent, "_context", None)
                        _workspace = getattr(_working_dir, "working_dir", None) if _working_dir else None
                        if _workspace and os.path.isdir(_workspace):
                            _rtester = RuleBasedTester(_workspace)
                            _passed, _results = _rtester.run_all()
                            _report = _rtester.format_report(_results)
                            structured(
                                logger, logging.INFO, "rule_tester_done",
                                session_id=session_id,
                                passed=_passed,
                                rules_total=len(_results),
                                rules_passed=sum(r.passed for r in _results),
                            )
                            yield {
                                "content": f"\n\n--- Rule-Based Test Results ---\n{_report}\n",
                                "emotion": None,
                                "actions": [],
                                "done": False,
                                "event_type": "rule_test_result",
                                "rule_passed": _passed,
                                "rule_report": _report,
                            }
                    except Exception as _rt_err:
                        logger.warning(f"Rule tester failed: {_rt_err}")
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
                structured(
                    logger,
                    logging.ERROR,
                    "turn_failed",
                    session_id=session_id,
                    error=evt_dict.get("error", "unknown error"),
                    code=evt_dict.get("code", "unknown"),
                    mode="orchestrator" if use_orchestrator else "agentcore",
                )
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
                structured(
                    logger,
                    logging.WARNING,
                    "turn_cancelled",
                    session_id=session_id,
                    reason=evt_dict.get("reason", ""),
                    accumulated_length=len(accumulated),
                    mode="orchestrator" if use_orchestrator else "agentcore",
                )
                yield {
                    "content": accumulated,
                    "emotion": None,
                    "actions": [],
                    "done": True,
                    "event_type": etype,
                    "reason": evt_dict.get("reason", ""),
                    "partial_content": evt_dict.get("partial_content", ""),
                }

                # 效率模式：AgentCore 完成后运行规则 Tester (零 LLM)
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
        structured(logger, logging.WARNING, "stream_cancelled_by_client", session_id=session_id)
        raise
    except Exception as e:
        structured(
            logger,
            logging.ERROR,
            "stream_error",
            session_id=session_id,
            error=str(e),
            error_type=type(e).__name__,
            mode="orchestrator" if use_orchestrator else "agentcore",
        )
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
