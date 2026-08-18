"""输入框 — 多行输入 + / 命令补全.

键位：
- ``Enter``       — 提交 (单行)
- ``Ctrl+J``      — 换行 (多行)
- ``Shift+Enter`` — 换行 (部分终端支持)
- ``/``           — 开头触发命令选择器
- ``Tab``         — 接受自动补全
- ``Esc``         — 取消自动补全 / 中断正在跑的 turn
"""
from __future__ import annotations

from typing import Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, TextArea

from ..commands.registry import all_commands


class Composer(Horizontal):
    """多行输入框."""

    DEFAULT_CSS = """
    Composer {
        height: auto;
        max-height: 8;
        border: round $accent 60%;
        padding: 0 1;
        background: $panel;
    }
    Composer:focus-within {
        border: round $accent;
    }
    Composer TextArea {
        border: none;
        background: transparent;
        height: auto;
        max-height: 7;
        min-height: 1;
        scrollbar-size: 0 0;
    }
    Composer:focus-within TextArea:focus {
        border: none;
    }
    """

    def __init__(self, on_submit, on_interrupt) -> None:
        super().__init__()
        self._on_submit = on_submit
        self._on_interrupt = on_interrupt
        self._area: Optional[TextArea] = None

    def compose(self) -> ComposeResult:
        self._area = TextArea(
            "",
            soft_wrap=True,
            classes="composer-area",
        )
        self._area.cursor_blink = True
        yield self._area

    def on_mount(self) -> None:
        self._area.focus()

    def on_key(self, event: events.Key) -> None:
        # Esc — 取消补全 / 中断 turn
        if event.key == "escape":
            self._on_interrupt()
            event.prevent_default()
            return
        # Ctrl+J — 换行
        if event.key == "ctrl+j":
            self._area.insert("\n")
            event.prevent_default()
            return
        # Enter — 提交 (Shift+Enter 由 TextArea 默认行为处理为换行)
        if event.key == "enter":
            text = self._area.text.strip()
            if not text:
                event.prevent_default()
                return
            # 命令补全候选（如果用户输入是已知命令前缀，提示）
            self._on_submit(text)
            self._area.text = ""
            event.prevent_default()

    @property
    def text(self) -> str:
        return self._area.text if self._area else ""

    def clear(self) -> None:
        if self._area:
            self._area.text = ""

    def focus_input(self) -> None:
        if self._area:
            self._area.focus()


__all__ = ["Composer"]
