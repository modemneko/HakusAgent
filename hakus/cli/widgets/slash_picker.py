"""Slash 命令浮动选择器.

当用户在 Composer 中输入 ``/`` 时弹出, 显示候选命令列表.
键盘上下选, Enter 接受, Esc 取消.

Phase 1 简化版：直接放在主界面上方, 不做浮动. 仍可用.
"""
from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from ..commands.registry import all_commands, SlashCommand


class SlashPicker(Vertical):
    """Slash 命令选择器 (简化版, 立式列表)."""

    DEFAULT_CSS = """
    SlashPicker {
        height: auto;
        max-height: 10;
        background: $panel;
        border: round $accent;
        padding: 0 1;
        display: none;
    }
    SlashPicker.visible {
        display: block;
    }
    SlashPicker Static {
        height: 1;
        padding: 0 1;
    }
    SlashPicker .selected {
        background: $accent 40%;
        color: $foreground;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._items: list[SlashCommand] = []
        self._selected: int = 0
        self._filter: str = ""

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self, filter_str: str = "") -> None:
        self._filter = filter_str
        all_cmds = all_commands()
        if filter_str:
            f = filter_str.lower()
            all_cmds = [
                c for c in all_cmds
                if c.hidden is False and (
                    f in c.name or
                    any(f in a for a in c.aliases) or
                    f in c.description.lower()
                )
            ]
        else:
            all_cmds = [c for c in all_cmds if not c.hidden]
        self._items = all_cmds
        self._selected = 0
        self._render()

    def _render(self) -> None:
        """重新渲染列表."""
        # 清掉所有子节点
        for child in list(self.children):
            child.remove()
        if not self._items:
            self.mount(Static("[dim]无匹配命令[/]"))
            return
        for i, cmd in enumerate(self._items):
            selected = i == self._selected
            prefix = "▶ " if selected else "  "
            aliases = (
                f" [dim]({', '.join('/' + a for a in cmd.aliases)})[/]"
                if cmd.aliases else ""
            )
            style_cls = "selected" if selected else ""
            self.mount(Static(
                f"{prefix}[green]/{cmd.name}[/]{aliases}  [dim]— {cmd.description}[/]",
                classes=style_cls,
            ))

    def show(self) -> None:
        self.refresh_list()
        self.add_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")

    @property
    def visible(self) -> bool:
        return self.has_class("visible")

    def move_cursor(self, delta: int) -> None:
        if not self._items:
            return
        self._selected = (self._selected + delta) % len(self._items)
        self._render()

    def current(self) -> Optional[SlashCommand]:
        if not self._items:
            return None
        return self._items[self._selected]


__all__ = ["SlashPicker"]
