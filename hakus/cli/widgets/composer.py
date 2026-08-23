"""输入框 — 多行输入 + / 命令补全.

键位：
- ``Enter``       — 提交 (单行)
- ``Ctrl+J``      — 换行 (多行)
- ``Esc``         — 取消自动补全 / 中断正在跑的 turn

实现说明：Textual 8.x 的 ``TextArea._on_key`` 会把 ``enter`` 当作插入
换行并 ``event.stop()``，事件不会冒泡到容器 — 所以必须在 TextArea
子类里拦截，不能靠容器的 ``on_key``。同理，提交回调是 async 的，
必须 await，否则协程被创建但从不执行（表现为"按发送没反应"）。
"""
from __future__ import annotations

import inspect
from typing import Awaitable, Callable, Optional, Union

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import TextArea

from ..commands.registry import all_commands


class ComposerArea(TextArea):
    """提交型 TextArea — Enter 提交而不是换行."""

    def __init__(
        self,
        on_submit: Callable[[str], Union[None, Awaitable[None]]],
        on_interrupt: Callable[[], None],
    ) -> None:
        super().__init__("", soft_wrap=True, classes="composer-area")
        self.cursor_blink = True
        self._submit_cb = on_submit
        self._interrupt_cb = on_interrupt

    async def _on_key(self, event: events.Key) -> None:
        # Enter — 提交。必须在 super() 之前拦截，否则 TextArea 插入换行
        # 并 stop 事件。
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            text = self.text.strip()
            if not text:
                return
            result = self._submit_cb(text)
            if inspect.isawaitable(result):
                await result
            self.text = ""
            return

        # Esc — 取消补全 / 中断 turn
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._interrupt_cb()
            return

        # Ctrl+J — 换行（TextArea 默认不处理这个键）
        if event.key == "ctrl+j":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return

        await super()._on_key(event)


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
        self._area: Optional[ComposerArea] = None

    def compose(self) -> ComposeResult:
        self._area = ComposerArea(self._on_submit, self._on_interrupt)
        yield self._area

    def on_mount(self) -> None:
        self._area.focus()

    @property
    def text(self) -> str:
        return self._area.text if self._area else ""

    def clear(self) -> None:
        if self._area:
            self._area.text = ""

    def focus_input(self) -> None:
        if self._area:
            self._area.focus()


__all__ = ["Composer", "ComposerArea"]
