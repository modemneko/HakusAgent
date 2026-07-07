"""High-level conversation engine."""
from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Optional

from hakus.engine.stream_events import (
    StreamEvent,
    AssistantTextDelta,
    AssistantTurnComplete,
    ToolExecutionStarted,
    ToolExecutionCompleted,
    ErrorEvent,
    StatusEvent,
    OrchestratorProgressEvent,
)
from hakus.hooks_v2.executor import HookExecutor
from hakus.hooks_v2.events import HookEvent
from utils.turn_debug import get_debug_logger as _get_dbg


class QueryEngine:
    """Owns conversation history and the tool-aware model loop.

    This is the single entry point for all agent interactions.
    For now it delegates to AgentCore; logic will be migrated incrementally.
    """

    def __init__(self, agent_core: Any) -> None:
        self._agent = agent_core
        self._cwd = Path(agent_core._context.working_dir or ".").resolve()
        self._hook_executor = HookExecutor()

    @property
    def cwd(self) -> Path:
        return self._cwd

    async def submit_message(self, prompt: str) -> AsyncIterator[StreamEvent]:
        """Append a user message and execute the query loop."""
        from hakus.protocol.events import AgentEventType

        # Execute USER_PROMPT_SUBMIT hooks
        if self._hook_executor.has_hooks(HookEvent.USER_PROMPT_SUBMIT):
            await self._hook_executor.execute(HookEvent.USER_PROMPT_SUBMIT, {"prompt": prompt})

        async for event in self._agent.run_turn(prompt):
            # ── Debug: log event ──
            _dbg = _get_dbg()
            if _dbg:
                etype = getattr(event, 'event_type', None)
                etype_name = etype.name if etype else type(event).__name__
                detail_parts = []
                for attr in ('text', 'name', 'content', 'error', 'reason', 'phase', 'path'):
                    val = getattr(event, attr, None)
                    if val:
                        detail_parts.append(f"{attr}={str(val)[:80]}")
                _dbg.log_event(etype_name, " | ".join(detail_parts))

            # Convert AgentEvent to StreamEvent
            if event.event_type == AgentEventType.TURN_STARTED:
                # TurnStarted 不需要转为 StreamEvent，仅标记 turn 开始
                pass
            elif event.event_type == AgentEventType.TEXT_DELTA:
                yield AssistantTextDelta(text=event.text)
            elif event.event_type == AgentEventType.TURN_COMPLETED:
                yield AssistantTurnComplete(
                    text=getattr(event, 'content', ''),
                    input_tokens=getattr(event, 'input_tokens', 0),
                    output_tokens=getattr(event, 'output_tokens', 0),
                )
            elif event.event_type == AgentEventType.TOOL_CALL_STARTED:
                yield ToolExecutionStarted(
                    tool_name=event.name,
                    tool_input=getattr(event, 'arguments', {}),
                )
            elif event.event_type == AgentEventType.TOOL_CALL_FINISHED:
                yield ToolExecutionCompleted(
                    tool_name=event.name,
                    output=getattr(event, 'result', ''),
                    is_error=not getattr(event, 'success', True),
                )
            elif event.event_type == AgentEventType.TURN_FAILED:
                yield ErrorEvent(message=getattr(event, 'error', 'Unknown error'))
            elif event.event_type == AgentEventType.CANCELLED:
                yield ErrorEvent(
                    message=getattr(event, 'reason', 'Cancelled'),
                    recoverable=False,
                )
            elif event.event_type == AgentEventType.REASONING_DELTA:
                # 推理链内容 — 作为 StatusEvent 透传，TUI 可选择性显示
                text = getattr(event, 'text', '')
                if text:
                    yield StatusEvent(message=f"💭 {text[:200]}")
            elif event.event_type == AgentEventType.ORCHESTRATOR_PHASE_CHANGED:
                phase = getattr(event, 'phase', getattr(event, 'to_phase', ''))
                yield OrchestratorProgressEvent(
                    phase=phase,
                    message=getattr(event, 'detail', ''),
                )
            elif event.event_type == AgentEventType.ACTIVITY_CHANGED:
                yield StatusEvent(message=getattr(event, 'detail', ''))
            elif event.event_type == AgentEventType.CHECKPOINT_SAVED:
                cp_id = getattr(event, 'checkpoint_id', '')
                yield StatusEvent(message=f"📌 检查点已保存: {cp_id}")
            elif event.event_type == AgentEventType.TASK_PROGRESS:
                progress = getattr(event, 'progress', 0)
                msg = getattr(event, 'message', '')
                yield StatusEvent(message=f"📊 {progress:.0%} {msg}")
            elif event.event_type == AgentEventType.PATCH_APPLIED:
                path = getattr(event, 'path', '')
                yield StatusEvent(message=f"📝 文件已变更: {path}")
            elif event.event_type == AgentEventType.TOKEN_USAGE:
                # Token usage 不需要转为 StreamEvent，由 handler 直接处理
                pass
            # Reflection 事件 — 二期功能，暂作为 StatusEvent 透传
            elif event.event_type == AgentEventType.REFLECTION_STARTED:
                yield StatusEvent(message="🔍 正在反思...")
            elif event.event_type == AgentEventType.REFLECTION_COMPLETED:
                decision = getattr(event, 'decision', None)
                if decision and getattr(decision, 'action', ''):
                    yield StatusEvent(message=f"🔍 反思结论: {decision.action}")
            # PATCH_APPROVAL 需要用户交互，暂不在此处理
            elif event.event_type == AgentEventType.PATCH_APPROVAL:
                pass
            # 兜底: 未知事件类型用 StatusEvent 透传
            elif hasattr(event, 'message') and getattr(event, 'message', ''):
                yield StatusEvent(message=event.message)
            elif hasattr(event, 'detail') and getattr(event, 'detail', ''):
                yield StatusEvent(message=event.detail)

    async def continue_pending(self) -> AsyncIterator[StreamEvent]:
        """Continue an interrupted tool loop without appending a new user message."""
        # Not yet implemented - will be done when QueryLoop is extracted
        return
        yield  # make it an async generator
