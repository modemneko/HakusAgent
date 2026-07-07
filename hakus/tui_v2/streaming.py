"""
StreamingSink — event-driven bridge between agent and TUI

设计 (参照 openai/codex codex-rs/tui 模式):
- **事件驱动** — 订阅 ``AgentEvent`` 流, 不再字符串嗅探 ``[Tool Results]``
  或 ``**[*`` (见 hakus/protocol/events.py).
- **Op 队列** — 接收 :class:`InterruptOp` / :class:`ApprovalOp`,
  注入回 agent core.
- **Handler 注入** — 默认 :class:`DefaultEventHandler`, 负责把
  事件映射到 widget 状态. 自定义 UI (例如 dashboard) 可注入自己的
  :class:`EventHandler`.

Public API (保持与旧版兼容):
    sink = StreamingSink(app)
    await sink.run(user_input, agent.run_turn)
    sink.cancel()

``run`` 的第二个参数 ``run_turn`` 来自 :class:`hakus.protocol` 的
新事件协议 (返回 :class:`AgentEvent` 的 async iterator).
旧版 ``agent.process_stream`` 字符串 token 接口已删除.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Awaitable, Callable, List, Optional

from utils.logger import get_logger
from .messages import Message
from hakus.protocol import (
    AgentEvent,
    Cancelled as CancelledEvent,
    DefaultEventHandler,
    EventHandler,
    InterruptOp,
    Op,
    PauseOp,
    ResumeOp,
    TextDelta,
    ToolCallStarted,
    ToolCallFinished,
    TurnCompleted,
    TurnFailed,
    ActivityChanged,
)
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

logger = get_logger(__name__)

# 与旧版 streaming.py _display_tool_results 一致的阈值
COLLAPSE_THRESHOLD = 800
PREVIEW_LINES = 12

# run_turn 签名: (user_input, op_receiver) -> AsyncIterator[AgentEvent]
RunTurnFn = Callable[[str, Optional[asyncio.Queue[Op]]], AsyncIterator[AgentEvent]]


class StreamingSink:
    """把 agent 事件流喂到 Textual widget.

    旧版 (字符串版) 通过 ``if "[Tool Results]" in self._full_content``
    切流. 新版通过 :class:`AgentEvent` 的 ``isinstance`` 路由, 完全
    消除字符串嗅探.

    See Also:
        :class:`DefaultEventHandler` — 默认事件→widget 映射
        :mod:`hakus.protocol` — 事件 / Op schema
    """

    def __init__(
        self,
        app: Any,
        event_handler: Optional[EventHandler] = None,
    ) -> None:
        self._app = app
        self._handler: EventHandler = event_handler or DefaultEventHandler(app)
        self._cancelled: bool = False
        self._op_queue: Optional[asyncio.Queue[Op]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """请求取消当前 turn.

        通过 op_queue 推 :class:`InterruptOp`, agent core 在下一个
        chunk 处理时检测到并 yield ``Cancelled`` 事件.
        """
        self._cancelled = True
        if self._op_queue is not None:
            try:
                self._op_queue.put_nowait(
                    InterruptOp(reason="user_cancelled")
                )
            except asyncio.QueueFull:
                logger.warning("op_queue full when sending InterruptOp")
            except Exception as e:
                logger.debug(f"Failed to push InterruptOp: {e}")

    def pause(self) -> None:
        """请求暂停当前 orchestrator 长时任务.

        通过 op_queue 推 :class:`PauseOp`, agent core 在下一个
        orchestrator 事件处理时检测到并调用 orchestrator.pause().
        """
        if self._op_queue is not None:
            try:
                self._op_queue.put_nowait(PauseOp())
            except asyncio.QueueFull:
                logger.warning("op_queue full when sending PauseOp")
            except Exception as e:
                logger.debug(f"Failed to push PauseOp: {e}")

    def resume(self, workspace_dir: str = "") -> None:
        """请求恢复暂停的 orchestrator 长时任务.

        通过 op_queue 推 :class:`ResumeOp`, agent core 在 turn
        开始时检测到并从检查点恢复.

        Args:
            workspace_dir: 可选的工作区路径, 用于指定恢复哪个
                工作区的检查点.
        """
        if self._op_queue is not None:
            try:
                self._op_queue.put_nowait(ResumeOp(workspace_dir=workspace_dir))
            except asyncio.QueueFull:
                logger.warning("op_queue full when sending ResumeOp")
            except Exception as e:
                logger.debug(f"Failed to push ResumeOp: {e}")

    @property
    def op_queue(self) -> Optional[asyncio.Queue[Op]]:
        """外部可访问的 op_queue — 用于权限弹窗响应.

        Returns:
            The asyncio.Queue for this sink, or None if run() hasn't
            been called yet.
        """
        return self._op_queue

    async def run(
        self,
        user_input: str,
        run_turn: RunTurnFn,
    ) -> None:
        """订阅事件流, 把事件分派给 handler.

        Args:
            user_input: 用户输入文本
            run_turn: agent core 的 ``run_turn`` 方法 (或兼容签名
                的 callable). 必须返回 :class:`AgentEvent` 的
                async iterator.
        """
        self._cancelled = False
        self._op_queue = asyncio.Queue()

        # 1) 挂载 streaming AssistantText widget
        try:
            ml = self._app.query_one("#message-list")
            streaming_widget = ml.append_assistant_stream()
        except Exception as e:
            logger.debug(f"Failed to mount streaming widget: {e}")
            streaming_widget = None

        # 2) Activity 切到 thinking — handler 收到 TurnStarted 也会切,
        #    这里预先切是为了让用户立刻看到 "正在思考"
        try:
            activity = self._app.query_one("#activity-strip")
            activity.set_phase("thinking", detail="正在准备回复")
        except Exception as e:
            logger.debug(f"Activity thinking phase set failed: {e}")

        # 3) 订阅事件流
        try:
            async for event in run_turn(user_input, self._op_queue):
                self._handler.handle(event)
                # Yield control back to the Textual event loop so UI
                # updates (scrolling, activity strip, cancel button)
                # can be processed during long tool executions.
                await asyncio.sleep(0)
                # If we got a terminal event, stop iterating
                if isinstance(
                    event, (CancelledEvent, TurnCompleted, TurnFailed)
                ):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"StreamingSink.run error: {e}")
            try:
                self._app._mount_message(
                    Message.error(f"流式输出错误: {e}")
                )
            except Exception:
                pass
        finally:
            # 4) Finalize handler (token count, activity → idle)
            try:
                self._handler.flush()
            except Exception as e:
                logger.debug(f"Handler flush failed: {e}")
            self._op_queue = None

    async def run_with_engine(
        self,
        user_input: str,
        query_engine: Any,
    ) -> None:
        """使用 :class:`hakus.engine.QueryEngine` 的 StreamEvent 流.

        这是 ``run()`` 的并行路径, 消费新的 :class:`StreamEvent`
        协议事件而非旧的 :class:`AgentEvent`. 两个路径共存,
        不影响现有 ``run()`` 的行为.

        Args:
            user_input: 用户输入文本
            query_engine: :class:`hakus.engine.QueryEngine` 实例,
                需提供 ``submit_message(prompt)`` 方法.
        """
        self._cancelled = False
        self._op_queue = asyncio.Queue()

        # 1) 挂载 streaming AssistantText widget
        try:
            ml = self._app.query_one("#message-list")
            streaming_widget = ml.append_assistant_stream()
        except Exception as e:
            logger.debug(f"Failed to mount streaming widget: {e}")
            streaming_widget = None

        # 2) Activity 切到 thinking
        try:
            activity = self._app.query_one("#activity-strip")
            activity.set_phase("thinking", detail="正在准备回复")
        except Exception as e:
            logger.debug(f"Activity thinking phase set failed: {e}")

        # 3) 订阅 StreamEvent 流
        try:
            async for event in query_engine.submit_message(user_input):
                if isinstance(event, AssistantTextDelta):
                    self._handler.handle(TextDelta(text=event.text))
                elif isinstance(event, AssistantTurnComplete):
                    self._handler.handle(TurnCompleted(
                        content=event.text,
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                    ))
                    break
                elif isinstance(event, ToolExecutionStarted):
                    self._handler.handle(ToolCallStarted(
                        name=event.tool_name,
                        arguments=event.tool_input,
                    ))
                elif isinstance(event, ToolExecutionCompleted):
                    self._handler.handle(ToolCallFinished(
                        name=event.tool_name,
                        result=event.output,
                        success=not event.is_error,
                    ))
                elif isinstance(event, ErrorEvent):
                    self._handler.handle(TurnFailed(
                        error=event.message,
                    ))
                    break
                elif isinstance(event, StatusEvent):
                    self._handler.handle(ActivityChanged(
                        detail=event.message,
                    ))
                elif isinstance(event, OrchestratorProgressEvent):
                    self._handler.handle(ActivityChanged(
                        phase=event.phase,
                        detail=event.message,
                    ))
                # Yield control back to the Textual event loop so UI
                # updates can be processed during long tool executions.
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"StreamingSink.run_with_engine error: {e}")
            try:
                self._app._mount_message(
                    Message.error(f"流式输出错误: {e}")
                )
            except Exception:
                pass
        finally:
            try:
                self._handler.flush()
            except Exception as e:
                logger.debug(f"Handler flush failed: {e}")
            self._op_queue = None

    # ------------------------------------------------------------------
    # Compatibility helpers used by DefaultEventHandler
    # ------------------------------------------------------------------

    def _format_tool_display(
        self,
        tool_name: str,
        result_str: str,
        success: bool,
        exec_time: Optional[float] = None,
        arguments: Optional[dict] = None,
    ) -> str:
        """格式化工具结果 (与旧 _display_tool_results 行为一致).

        Called by :class:`DefaultEventHandler` when rendering a
        ``ToolCallFinished`` event into a Message.

        Returns:
            Markdown-formatted string for display in the message list.
        """
        status_icon = "✓" if success else "✗"
        duration_str = ""
        if exec_time and float(exec_time) >= 0.05:
            duration_str = f"  {float(exec_time):.1f}s"
        header = f"{status_icon} {tool_name}{duration_str}"

        if len(result_str) <= COLLAPSE_THRESHOLD:
            display_text = (
                f"**{header}**\n\n"
                f"```\n{result_str}\n```"
            )
        else:
            lines = result_str.splitlines()
            preview = "\n".join(lines[:PREVIEW_LINES])
            omitted = len(lines) - PREVIEW_LINES
            display_text = (
                f"**{header}**  ·  {len(result_str):,} chars  ·  {len(lines)} lines\n\n"
                f"```\n{preview}\n```\n"
                f"*[已折叠 {omitted} 行 · 内容已存入会话供模型参考]*"
            )

        # Unknown tool 错误
        if not success and "Unknown tool" in result_str:
            try:
                available = self._app.get_available_tools()
            except Exception:
                available = []
            display_text = (
                f"**{header}**\n\n"
                f"模型请求了未注册的工具 `{tool_name}`。\n\n"
                f"可用工具 ({len(available)} 个): "
                f"{', '.join(sorted(available)[:15])}"
                f"{'...' if len(available) > 15 else ''}\n\n"
                f"*这是模型的命名错误, 不是 TUI 缺少工具。*"
            )
        # 其他错误
        elif not success and (
            "BadRequestError" in result_str or "Error:" in result_str
        ):
            error_lines = result_str.splitlines()
            error_summary = error_lines[0][:200] if error_lines else result_str[:200]
            display_text = (
                f"**{header}**\n\n"
                f"工具执行出错:\n> {error_summary}\n\n"
                f"*详情已存入会话。可重试或切换模型。*"
            )

        return display_text
