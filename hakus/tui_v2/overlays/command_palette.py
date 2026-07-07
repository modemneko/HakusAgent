"""CommandPalette — 命令面板 (OpenCode ^p 风格)"""
from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Static

from ..commands import SlashCommandRegistry


class CommandPalette(ModalScreen[str]):
    """命令面板 — 显示所有可用命令, 支持搜索.

    按 ^p 打开, 输入关键字过滤, Enter 执行.
    """

    BINDINGS = [
        Binding("escape", "dismiss('')", "取消"),
        Binding("up", "cursor_up", "上一个", show=False),
        Binding("down", "cursor_down", "下一个", show=False),
        Binding("enter", "execute_command", "执行"),
        Binding("j", "cursor_down", "下一个", show=False),
        Binding("k", "cursor_up", "上一个", show=False),
    ]

    DEFAULT_CSS = """
    CommandPalette {
        align: center middle;
    }

    CommandPalette > .modal {
        width: 60%;
        max-width: 100;
        height: auto;
        max-height: 30;
        background: #141414;
        border: thick #9d7cd8;
        padding: 1 2;
    }

    CommandPalette .modal-title {
        color: #fab283;
        text-style: bold;
        width: 100%;
        height: 1;
        margin-bottom: 1;
    }

    CommandPalette .search-input {
        width: 100%;
        height: 1;
        margin-bottom: 1;
        color: #eeeeee;
    }

    CommandPalette .cmd-item {
        width: 100%;
        height: 1;
        padding: 0 1;
    }

    CommandPalette .cmd-item.selected {
        background: #1e1e1e;
    }

    CommandPalette .cmd-name {
        color: #56b6c2;
    }

    CommandPalette .cmd-item.selected .cmd-name {
        color: #9d7cd8;
        text-style: bold;
    }

    CommandPalette .cmd-desc {
        color: #606060;
    }

    CommandPalette .cmd-shortcut {
        color: #808080;
    }

    CommandPalette .hint {
        color: #606060;
        width: 100%;
        height: 1;
        margin-top: 1;
        text-align: center;
    }
    """

    selected_index: reactive[int] = reactive(0)
    search_query: reactive[str] = reactive("")

    def __init__(self, registry: SlashCommandRegistry) -> None:
        super().__init__()
        self._registry = registry
        self._commands = registry.all()
        self._filtered = list(self._commands)

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static("命令面板", classes="modal-title")
            yield Static("_", id="search-input", classes="search-input")
            for i, cmd in enumerate(self._filtered):
                prefix = "> " if i == self.selected_index else "  "
                name = f"/{cmd.name}"
                desc = cmd.description or ""
                yield Static(
                    f"{prefix}[bold #56b6c2]{name}[/]  [#606060]{desc}[/]",
                    classes="cmd-item",
                    markup=True,
                )
            yield Static("↑↓ 选择  Enter 执行  Esc 取消  输入关键字过滤", classes="hint")

    def on_mount(self) -> None:
        try:
            self.query_one(".search-input", Static).update("")
        except Exception:
            pass

    def on_key(self, event) -> None:
        """处理键盘输入 — 过滤命令."""
        if event.key in ("escape", "up", "down", "enter", "j", "k"):
            return

        if event.key == "backspace":
            if self.search_query:
                self.search_query = self.search_query[:-1]
        elif len(event.key) == 1:
            self.search_query += event.key

        self._filter_commands()

    def _filter_commands(self) -> None:
        """根据搜索关键字过滤命令."""
        query = self.search_query.lower()
        if query:
            self._filtered = [
                cmd for cmd in self._commands
                if query in cmd.name.lower() or query in (cmd.description or "").lower()
            ]
        else:
            self._filtered = list(self._commands)

        self.selected_index = 0
        self._refresh_items()

    def _refresh_items(self) -> None:
        """重新渲染命令列表."""
        try:
            # 移除旧的命令项
            for item in self.query(".cmd-item"):
                item.remove()

            # 添加新的命令项
            modal = self.query_one(".modal", Vertical)
            hint = self.query_one(".hint", Static)

            for i, cmd in enumerate(self._filtered):
                prefix = "> " if i == self.selected_index else "  "
                name = f"/{cmd.name}"
                desc = cmd.description or ""
                item = Static(
                    f"{prefix}[bold #56b6c2]{name}[/]  [#606060]{desc}[/]",
                    classes="cmd-item",
                    markup=True,
                )
                hint.mount_before(item)
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        if self.selected_index > 0:
            self.selected_index -= 1
            self._refresh_items()

    def action_cursor_down(self) -> None:
        if self.selected_index < len(self._filtered) - 1:
            self.selected_index += 1
            self._refresh_items()

    def action_execute_command(self) -> None:
        """执行选中的命令."""
        if self._filtered:
            cmd = self._filtered[self.selected_index]
            self.dismiss(f"/{cmd.name}")
