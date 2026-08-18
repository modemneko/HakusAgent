"""对话视图 — 流式渲染消息.

设计：
- 用 ``RichLog`` 作为底层容器, 自动追加, 不维护虚拟列表 (Phase 1 简化).
- 用户消息和 assistant 消息分别用不同的样式气泡.
- 工具调用作为单独的折叠卡片插入.
- 流式 token 实时追加到最后一个 assistant 气泡.

Phase 5 升级路径：换成 ``ScrollAreaContainer`` + 虚拟列表 + 自动 stick-to-bottom.
"""
from __future__ import annotations

from typing import Optional

from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import RichLog, Static

from ..theme import Theme


class ConversationView(VerticalScroll):
    """对话历史容器.

    内部用 ``RichLog`` 拼接每条消息, 提供 ``add_user`` / ``add_assistant``
    / ``append_delta`` / ``add_tool_call`` / ``add_system`` API.
    """

    DEFAULT_CSS = """
    ConversationView {
        background: $surface;
        color: $foreground;
        padding: 1 2;
        scrollbar-size: 1 1;
        scrollbar-color: $accent 40%;
    }
    ConversationView:focus {
        border: none;
    }
    """

    def __init__(self, theme: Theme) -> None:
        super().__init__()
        self.theme = theme
        self._current_assistant_log: Optional[RichLog] = None
        self._assistant_buffer: str = ""

    # ── 添加消息 ──────────────────────────────────────────

    def add_user(self, text: str) -> None:
        """添加用户消息气泡."""
        bubble = RichLog(
            markup=True,
            auto_scroll=False,
            highlight=False,
            wrap=True,
            classes="msg-user",
        )
        bubble.border_title = "你"
        bubble.write(Text(f"  {text}", style=self.theme.user_text))
        self.mount(bubble)
        self._scroll_to_bottom()

    def start_assistant(self) -> None:
        """开始一条新的 assistant 消息气泡. 后续 ``append_delta`` 追加到这里."""
        log = RichLog(
            markup=True,
            auto_scroll=False,
            highlight=False,
            wrap=True,
            classes="msg-assistant",
        )
        log.border_title = "HakusAI"
        self.mount(log)
        self._current_assistant_log = log
        self._assistant_buffer = ""
        self._scroll_to_bottom()

    def append_delta(self, text: str) -> None:
        """流式追加到当前 assistant 气泡."""
        if self._current_assistant_log is None:
            self.start_assistant()
        self._assistant_buffer += text
        # Phase 1: 简单策略 — 每次重新渲染 markdown. 优化版本应该做 diff-only.
        self._rerender_assistant()
        self._scroll_to_bottom()

    def _rerender_assistant(self) -> None:
        """重渲染当前 assistant 气泡 (Phase 1 简化实现)."""
        log = self._current_assistant_log
        if log is None:
            return
        log.clear()
        # 用 Markdown 渲染 buffer
        md = Markdown(self._assistant_buffer or "…")
        log.write(md)

    def end_assistant(self) -> None:
        """结束当前 assistant 消息气泡."""
        if self._current_assistant_log and not self._assistant_buffer:
            self._current_assistant_log.write(Text("[dim]（无响应）[/]", style=""))
        self._current_assistant_log = None
        self._assistant_buffer = ""

    def add_tool_call(
        self, name: str, args: dict, call_id: str
    ) -> None:
        """添加一个工具调用卡片 (开始状态)."""
        card = Static(
            f"[dim]⟳ 调用工具[/]  [yellow]{name}[/]\n"
            f"[dim]参数：[/] {args}",
            classes="tool-call-pending",
        )
        card.border_title = f"tool:{name}"
        self.mount(card)
        self._scroll_to_bottom()

    def update_tool_call(
        self, name: str, success: bool, result: str, duration: float
    ) -> None:
        """在最新一条 tool call 卡片上追加结果."""
        # Phase 1: 简化 — 直接追加一个结果行
        icon = "✓" if success else "✗"
        color = "green" if success else "red"
        tail = Static(
            f"[{color}]{icon} 完成 ({duration:.1f}s)[/]\n"
            f"[dim]结果：[/] {(result[:200] + '…') if len(result) > 200 else result}",
            classes="tool-call-done",
        )
        self.mount(tail)
        self._scroll_to_bottom()

    def add_system(self, text: str, *, kind: str = "info") -> None:
        """添加系统提示消息."""
        color = {
            "info": "cyan",
            "warn": "yellow",
            "error": "red",
            "success": "green",
        }.get(kind, "cyan")
        sys = Static(f"[{color}]{text}[/]", classes="msg-system")
        self.mount(sys)
        self._scroll_to_bottom()

    def add_error(self, friendly: str, detail: Optional[str] = None) -> None:
        """添加错误气泡: 友好中文 + 可折叠技术细节."""
        err = Static(
            f"[red]✗ {friendly}[/]"
            + (f"\n[dim]技术细节：{detail}[/]" if detail else ""),
            classes="msg-error",
        )
        err.border_title = "错误"
        self.mount(err)
        self._scroll_to_bottom()

    def clear_all(self) -> None:
        """清空对话历史."""
        for child in list(self.children):
            child.remove()
        self._current_assistant_log = None
        self._assistant_buffer = ""

    def _scroll_to_bottom(self) -> None:
        """滚动到底部 (call_after_refresh 避免 layout 还没算完)."""
        try:
            self.scroll_end(animate=False)
        except Exception:
            pass


__all__ = ["ConversationView"]
