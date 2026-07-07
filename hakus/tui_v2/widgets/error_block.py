"""
ErrorBlock — 错误消息 (Claude Code 风格: 单行 + 颜色)
"""
from __future__ import annotations

from textual.containers import Container
from textual.widgets import Markdown, Static

from ..messages import Message


class ErrorBlock(Container):
    """错误消息块.

    CSS 类: ErrorBlock (在 theme.tcss 中定义).
    """

    DEFAULT_CSS = """
    ErrorBlock {
        margin: 1 0;
        padding: 0 1;
        background: #141414;
        border-left: thick #e06c75;
        height: auto;
    }

    ErrorBlock .err-prefix {
        color: #e06c75;
        text-style: bold;
        width: 100%;
        height: 1;
    }
    """

    def __init__(self, message: Message, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._message = message

    def compose(self):
        yield Static("✗ Error", classes="err-prefix")
        yield Markdown(self._message.content)
