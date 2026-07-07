"""
CommandResult — Slash 命令输出 (无 Panel 边框)

- 用 `⚡ /cmd` 前缀 + Markdown
- 与 ToolResult 视觉一致, 但左边框用品牌紫
"""
from __future__ import annotations

from textual.containers import Container
from textual.widgets import Markdown, Static

from ..messages import Message


class CommandResult(Container):
    """Slash 命令输出.

    CSS 类: CommandResult (在 theme.tcss 中定义).
    """

    DEFAULT_CSS = """
    CommandResult {
        margin: 1 0;
        padding: 0 1;
        background: #141414;
        border-left: thick #9d7cd8;
        height: auto;
    }

    CommandResult .cmd-prefix {
        color: #9d7cd8;
        text-style: bold;
        width: 100%;
        height: 1;
    }

    CommandResult .cmd-content {
        background: transparent;
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, message: Message, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._message = message

    def compose(self):
        cmd = self._message.metadata.get("cmd", "/")
        yield Static(f"⚡ {cmd}", classes="cmd-prefix")
        yield Markdown(self._message.content, classes="cmd-content")
