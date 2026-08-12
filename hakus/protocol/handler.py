"""EventHandler: subscription base for frontends.

Frontend 通过继承 :class:`EventHandler` (或直接使用
:class:`DefaultEventHandler`) 来处理 ``AgentEvent`` 流.

设计要点:

1. **不直接 yield 字符串**: 所有 UI 状态变更都由 handler 显式触发.
   ``DefaultEventHandler`` 把每个事件映射到具体的 widget 状态.
2. **不依赖 Textual / Rich**: 抽象基类 ``EventHandler`` 与具体 TUI
   handler 解耦 — 未来 MCP-server / headless CLI 也可以用同一协议.
3. **可重写**: 想要自定义渲染 (例如 dashboard / 移动端) 时,
   继承 :class:`EventHandler` 并覆盖 ``handle()`` 即可.

典型用法::

    class MyHandler(EventHandler):
        def __init__(self, sink):
            self._sink = sink

        def handle(self, event):
            if isinstance(event, TextDelta):
                self._sink.write(event.text)
            elif isinstance(event, TurnFailed):
                self._sink.notify(event.error)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from .events import (
    AgentEvent,
    TurnStarted,
    TurnCompleted,
    TurnFailed,
    Cancelled,
    TextDelta,
    ReasoningDelta,
    ToolCallStarted,
    ToolCallFinished,
    OrchestratorPhaseChanged,
    ActivityChanged,
    TokenUsage,
    PatchApplied,
    PatchApproval,
)


MODEL_MAX_CONTEXT = {
    "deepseek": 128000,
    "openai": 128000,
    "ollama": 32000,
}


class EventHandler(ABC):
    """Abstract base class for event subscriptions.

    Frontends implement :meth:`handle` (and optionally :meth:`flush`
    for end-of-stream cleanup) to map typed events to UI state
    changes.

    The default implementation is a no-op (for tests that just want
    to collect events). :class:`DefaultEventHandler` provides the
    concrete TUI mapping.
    """

    @abstractmethod
    def handle(self, event: AgentEvent) -> None:
        """Process one event. Called by StreamingSink in order."""
        raise NotImplementedError

    def flush(self) -> None:
        """Called once after the event stream ends.

        Use this to finalize UI state (e.g. switch activity to idle,
        save session totals). Default is a no-op.
        """


class DefaultEventHandler(EventHandler):
    """Default TUI event handler.

    Maps :class:`AgentEvent` subclasses to the existing Textual
    widget state changes that the legacy ``StreamingSink`` did via
    string sniffing. The intent: same observable TUI behavior, but
    with the event source of truth being typed events, not string
    markers.

    The handler holds **no direct Textual coupling** beyond the
    activity-strip ``set_phase`` call — that one exception exists
    because the activity strip is the only widget that absolutely
    must receive inline updates during streaming. All other widget
    mutations go through the owning ``HakusApp`` (passed as
    ``app``), which keeps the handler testable in isolation.
    """

    def __init__(self, app: Any) -> None:
        self._app = app
        # Cumulative state for the current turn
        self._clean_content: str = ""
        self._tool_count: int = 0
        self._has_text: bool = False

    # ------------------------------------------------------------------
    # Public EventHandler interface
    # ------------------------------------------------------------------

    def handle(self, event: AgentEvent) -> None:
        # Use isinstance dispatch (Python has no native sum type;
        # match/case works too but isinstance is more compatible).
        if isinstance(event, TurnStarted):
            self._on_turn_started(event)
        elif isinstance(event, TextDelta):
            self._on_text_delta(event)
        elif isinstance(event, ReasoningDelta):
            # Folded into reasoning area in future — silently ignore for now
            self._on_reasoning_delta(event)
        elif isinstance(event, ToolCallStarted):
            self._on_tool_call_started(event)
        elif isinstance(event, ToolCallFinished):
            self._on_tool_call_finished(event)
        elif isinstance(event, OrchestratorPhaseChanged):
            self._on_orchestrator_phase_changed(event)
        elif isinstance(event, ActivityChanged):
            self._on_activity_changed(event)
        elif isinstance(event, TokenUsage):
            self._on_token_usage(event)
        elif isinstance(event, PatchApplied):
            self._on_patch_applied(event)
        elif isinstance(event, PatchApproval):
            self._on_patch_approval(event)
        elif isinstance(event, TurnCompleted):
            self._on_turn_completed(event)
        elif isinstance(event, TurnFailed):
            self._on_turn_failed(event)
        elif isinstance(event, Cancelled):
            self._on_cancelled(event)
        # ReflectionStarted / ReflectionCompleted: stage 2, no-op
        # for now (events are defined but not emitted by core yet).

    def flush(self) -> None:
        """Finalize token counts and switch activity to idle."""
        # Token count is already updated by TokenUsage events;
        # flush just guarantees we land back at idle even if
        # TurnCompleted was missed (e.g. due to an exception).
        try:
            activity = self._app.query_one("#activity-strip")
            activity.set_phase("idle")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Per-event handlers
    # ------------------------------------------------------------------

    def _on_turn_started(self, event: TurnStarted) -> None:
        self._clean_content = ""
        self._tool_count = 0
        self._has_text = False
        self._activity_streaming = False
        try:
            activity = self._app.query_one("#activity-strip")
            activity.set_phase("thinking")
        except Exception:
            pass
        # 重置 inline activity block
        try:
            ml = self._app.query_one("#message-list")
            streaming_widget = ml._streaming_widget
            if streaming_widget is not None and hasattr(streaming_widget, "update_activity"):
                streaming_widget.update_activity("Thinking...")
        except Exception:
            pass

    def _on_text_delta(self, event: TextDelta) -> None:
        if not event.text:
            return
        self._has_text = True
        self._clean_content += event.text
        # Switch activity to streaming the first time we see text
        if not getattr(self, '_activity_streaming', False):
            self._activity_streaming = True
            try:
                activity = self._app.query_one("#activity-strip")
                activity.set_phase("streaming", detail="正在生成回复")
            except Exception:
                pass
        # Append to the current streaming widget
        try:
            ml = self._app.query_one("#message-list")
            streaming_widget = ml._streaming_widget
            if streaming_widget is not None:
                if hasattr(streaming_widget, 'append_delta'):
                    streaming_widget.append_delta(event.text)
                else:
                    streaming_widget.append_text(event.text)
        except Exception:
            pass

    def _on_reasoning_delta(self, event: ReasoningDelta) -> None:
        # Stage 2: render to a collapsible "reasoning" area.
        # For now, fold into the main content so it's not lost.
        if event.text:
            self._clean_content += event.text
            try:
                ml = self._app.query_one("#message-list")
                streaming_widget = ml._streaming_widget
                if streaming_widget is not None:
                    if hasattr(streaming_widget, 'append_delta'):
                        streaming_widget.append_delta(event.text)
                    else:
                        streaming_widget.append_text(event.text)
            except Exception:
                pass

    def _on_tool_call_started(self, event: ToolCallStarted) -> None:
        # 根据工具名映射到更具体的 phase — 让用户清楚看到当前在做什么.
        # 之前统一是 "tool_use" + 工具名, 用户感觉中断是因为看不出
        # 当前是 fetching/searching/writing 中的哪一个.
        tool = (event.name or "").lower()
        if any(k in tool for k in ("fetch", "download", "http", "url")):
            phase = "fetching"
        elif "search" in tool:
            phase = "searching"
        elif any(k in tool for k in ("read", "load", "view", "cat", "glob", "list")):
            phase = "reading"
        elif any(k in tool for k in ("write", "edit", "create", "save", "append", "delete", "remove", "mkdir")):
            phase = "writing"
        elif any(k in tool for k in ("bash", "shell", "exec", "run", "command", "powershell")):
            phase = "executing"
        elif "grep" in tool or "find" in tool or "ripgrep" in tool:
            phase = "searching"
        else:
            phase = "tool_use"

        # 优先显示工具名 (如 "Read"), detail 显示文件路径或参数简述
        detail = ""
        if event.arguments and isinstance(event.arguments, dict):
            for k in ("file_path", "path", "filepath", "url", "query", "command", "cmd"):
                if k in event.arguments and event.arguments[k]:
                    val = str(event.arguments[k])
                    if len(val) > 60:
                        val = val[:57] + "..."
                    detail = val
                    break
        try:
            activity = self._app.query_one("#activity-strip")
            activity.set_phase(phase, detail=detail, tool_name=event.name)
        except Exception:
            pass
        # 同步更新 AssistantText 内的 inline activity scroller
        try:
            ml = self._app.query_one("#message-list")
            streaming_widget = ml._streaming_widget
            if streaming_widget is not None and hasattr(streaming_widget, "update_activity"):
                label = f"{event.name}"
                if detail:
                    label = f"{label} · {detail}"
                phase_label = {
                    "fetching": "Fetching",
                    "searching": "Searching",
                    "reading": "Reading",
                    "writing": "Writing",
                    "executing": "Executing",
                    "tool_use": "Tool",
                }.get(phase, "Tool")
                streaming_widget.update_activity(f"{phase_label}: {label}")
        except Exception:
            pass

    def _on_tool_call_finished(self, event: ToolCallFinished) -> None:
        self._tool_count += 1
        # Render a ToolResult widget for this call.
        try:
            from hakus.tui_v2.widgets.tool_result import ToolResult  # type: ignore  # noqa: F401
            from hakus.tui_v2.messages import Message  # type: ignore
        except ImportError:
            return

        msg = Message.tool(
            name=event.name,
            args=event.arguments if isinstance(event.arguments, dict) else {},
            result=event.result,
            success=event.success,
            duration=float(event.duration) if event.duration else None,
        )
        # Apply the legacy display formatting (long-result collapse, etc.)
        # Reuse the existing helper on StreamingSink if available.
        sink = getattr(self._app, "_sink", None)
        if sink is not None and hasattr(sink, "_format_tool_display"):
            display_text = sink._format_tool_display(
                tool_name=event.name,
                result_str=event.result,
                success=event.success,
                exec_time=event.duration,
                arguments=event.arguments,
            )
            msg.content = display_text
        try:
            self._app._mount_message(msg)
        except Exception:
            pass

    def _on_orchestrator_phase_changed(self, event: OrchestratorPhaseChanged) -> None:
        # Map to activity strip with "orchestrator" phase
        try:
            activity = self._app.query_one("#activity-strip")
            activity.set_phase("orchestrator", detail=event.detail)
        except Exception:
            pass

    def _on_activity_changed(self, event: ActivityChanged) -> None:
        try:
            activity = self._app.query_one("#activity-strip")
            activity.set_phase(event.phase, detail=event.detail or None,
                              tool_name=event.tool_name)
        except Exception:
            pass

    def _on_token_usage(self, event: TokenUsage) -> None:
        # Update session totals; mirror the legacy _update_token_count logic
        try:
            session = self._app._session
            session.total_input_tokens += event.input_tokens
            session.total_output_tokens += event.output_tokens
            total = session.total_input_tokens + session.total_output_tokens
            self._app._status_bar.total_tokens = total
            # Context percentage: use current context usage (not cumulative tokens)
            # The latest input_tokens from the API reflects the actual context
            # size sent in this request, which is the correct measure of
            # "how full is the context window right now".
            try:
                ctx = self._app._agent._context
                estimated = ctx._total_estimated_tokens()
                budget = ctx.budget
                context_pct = min(100, int(estimated * 100 / max(1, budget)))
            except Exception:
                # Fallback: use input_tokens from this request vs model max
                model_type = getattr(self._app._agent, "_model_type", "deepseek")
                max_context = MODEL_MAX_CONTEXT.get(model_type, 128000)
                context_pct = min(100, int(event.input_tokens / max_context * 100))
            self._app._status_bar.context_pct = context_pct
        except Exception:
            pass

    def _on_patch_applied(self, event: PatchApplied) -> None:
        """Handle file patch applied — store for DiffOverlay access."""
        # Store the patch info on the app for DiffOverlay to access
        if not hasattr(self._app, '_recent_patches'):
            self._app._recent_patches = []
        self._app._recent_patches.append({
            'path': event.path,
            'diff': event.diff,
            'old_content': event.old_content,
            'new_content': event.new_content,
        })
        # Keep only last 50 patches
        if len(self._app._recent_patches) > 50:
            self._app._recent_patches = self._app._recent_patches[-50:]

    def _on_patch_approval(self, event: PatchApproval) -> None:
        """Handle patch approval request — show DiffOverlay."""
        # Future: auto-show DiffOverlay with accept/reject buttons
        pass

    def _hide_inline_activity(self) -> None:
        try:
            ml = self._app.query_one("#message-list")
            streaming_widget = ml._streaming_widget
            if streaming_widget is not None and hasattr(streaming_widget, "hide_activity"):
                streaming_widget.hide_activity()
        except Exception:
            pass

    def _on_turn_completed(self, event: TurnCompleted) -> None:
        # If we got text deltas, the streaming widget already has the
        # content. Replace it with the canonical (full) response so
        # the user sees the final cleaned text.
        self._hide_inline_activity()
        if event.content and self._has_text:
            try:
                ml = self._app.query_one("#message-list")
                streaming_widget = ml._streaming_widget
                if streaming_widget is not None:
                    if hasattr(streaming_widget, 'finalize'):
                        streaming_widget.finalize(event.content)
                    else:
                        streaming_widget.set_markdown(event.content)
                ml.replace_last_assistant(event.content)
            except Exception:
                pass
        # Token totals
        if event.input_tokens or event.output_tokens:
            self._on_token_usage(TokenUsage(
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
            ))
        # Activity → idle
        try:
            activity = self._app.query_one("#activity-strip")
            activity.set_phase("idle")
        except Exception:
            pass

    def _on_turn_failed(self, event: TurnFailed) -> None:
        self._hide_inline_activity()
        try:
            from hakus.tui_v2.messages import Message  # type: ignore
            self._app._mount_message(
                Message.error(f"[{event.code}] {event.error}")
            )
        except Exception:
            pass
        try:
            activity = self._app.query_one("#activity-strip")
            activity.set_phase("idle")
        except Exception:
            pass

    def _on_cancelled(self, event: Cancelled) -> None:
        self._hide_inline_activity()
        partial = event.partial_content or self._clean_content
        if partial:
            try:
                ml = self._app.query_one("#message-list")
                streaming_widget = ml._streaming_widget
                if streaming_widget is not None:
                    marker = f"\n\n*[已中断: {event.reason}]*"
                    if hasattr(streaming_widget, 'finalize'):
                        streaming_widget.finalize(partial + marker)
                    else:
                        streaming_widget.set_markdown(partial + marker)
                ml.replace_last_assistant(partial + marker)
            except Exception:
                pass
        try:
            activity = self._app.query_one("#activity-strip")
            activity.set_phase("idle")
        except Exception:
            pass
