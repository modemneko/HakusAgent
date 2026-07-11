"""ModelOverlay — 模型选择面板 (OpenCode 风格).

支持键盘 (↑↓/Enter/Esc) 和鼠标点击确认，并带实时过滤搜索框.
"""
from __future__ import annotations

from typing import List

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from ...models.provider_registry import PROVIDERS


class _ModelListItem(ListItem):
    """可显示当前选中标记的模型列表项."""

    def __init__(self, provider: dict, is_current: bool = False) -> None:
        super().__init__()
        self._provider = provider
        self._is_current = is_current

    def compose(self) -> ComposeResult:
        marker = "● " if self._is_current else "  "
        with Horizontal(classes="model-row"):
            yield Static(marker, classes="model-marker")
            yield Label(self._provider["name"], classes="model-name")
            yield Label(self._provider["desc"], classes="model-desc")


class ModelOverlay(ModalScreen[str]):
    """模型选择 Overlay — 返回选中的模型 id 或空字符串(取消)."""

    BINDINGS = [
        Binding("escape", "dismiss('')", "取消"),
        Binding("up", "cursor_up", "上一个", show=False, priority=True),
        Binding("down", "cursor_down", "下一个", show=False, priority=True),
        Binding("enter", "select_model", "确认", priority=True),
        Binding("j", "cursor_down", "下一个", show=False, priority=True),
        Binding("k", "cursor_up", "上一个", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    ModelOverlay {
        align: center middle;
        background: $surface 90%;
    }

    ModelOverlay > .modal {
        width: 60;
        max-width: 80;
        height: auto;
        max-height: 22;
        background: #0a0a0a;
        border: tall #5c9cf5;
        padding: 1 2;
    }

    ModelOverlay .modal-header {
        width: 100%;
        height: 1;
        margin-bottom: 1;
    }

    ModelOverlay .modal-title {
        color: #5c9cf5;
        text-style: bold;
    }

    ModelOverlay .modal-esc {
        color: #606060;
        text-align: right;
    }

    ModelOverlay .filter-input {
        height: 1;
        margin-bottom: 1;
        border: none;
        background: #141414;
        color: #eeeeee;
    }

    ModelOverlay .filter-input:focus {
        border: none;
    }

    ModelOverlay .model-list {
        width: 100%;
        height: auto;
        max-height: 12;
        border: none;
        background: transparent;
    }

    ModelOverlay .model-list:focus {
        border: none;
    }

    ModelOverlay .model-list > ListItem {
        height: 1;
        padding: 0 1;
        background: transparent;
    }

    ModelOverlay .model-list > ListItem:hover {
        background: #1e1e1e;
    }

    ModelOverlay .model-list > ListItem.--highlight {
        background: #5c9cf5;
    }

    ModelOverlay .model-list > ListItem.--highlight .model-name {
        color: #0a0a0a;
        text-style: bold;
    }

    ModelOverlay .model-list > ListItem.--highlight .model-desc {
        color: #1a1a1a;
    }

    ModelOverlay .model-row {
        width: 100%;
        height: 1;
    }

    ModelOverlay .model-marker {
        width: 2;
        color: #5c9cf5;
    }

    ModelOverlay .model-name {
        width: 18;
        color: #eeeeee;
    }

    ModelOverlay .model-desc {
        color: #606060;
    }

    ModelOverlay .modal-hint {
        width: 100%;
        height: 1;
        margin-top: 1;
        color: #606060;
        text-align: center;
    }
    """

    def __init__(self, current_model: str = "opencode") -> None:
        super().__init__()
        self._current_model = current_model
        self._models = PROVIDERS
        self._filtered: List[dict] = list(self._models)

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            with Horizontal(classes="modal-header"):
                yield Static("选择模型", classes="modal-title")
                yield Static("esc", classes="modal-esc")
            yield Input(
                placeholder="搜索模型...",
                classes="filter-input",
                id="model-filter",
            )
            yield ListView(
                *[_ModelListItem(p, is_current=p["id"] == self._current_model) for p in self._models],
                classes="model-list",
                id="model-list",
            )
            yield Static("↑↓ 选择  Enter 确认  Esc 取消  / 输入过滤", classes="modal-hint")

    def on_mount(self) -> None:
        list_view = self.query_one("#model-list", ListView)
        for i, p in enumerate(self._models):
            if p["id"] == self._current_model:
                list_view.index = i
                break
        else:
            list_view.index = 0
        self.query_one("#model-filter", Input).focus()

    async def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.lower()
        list_view = self.query_one("#model-list", ListView)
        self._filtered = [
            p for p in self._models
            if query in p["id"].lower()
            or query in p["name"].lower()
            or query in p["desc"].lower()
        ]
        await list_view.clear()
        for p in self._filtered:
            await list_view.mount(_ModelListItem(p, is_current=p["id"] == self._current_model))
        if self._filtered:
            list_view.index = 0

    def action_cursor_up(self) -> None:
        list_view = self.query_one("#model-list", ListView)
        if list_view.index is not None and list_view.index > 0:
            list_view.index -= 1

    def action_cursor_down(self) -> None:
        list_view = self.query_one("#model-list", ListView)
        if list_view.index is None:
            list_view.index = 0
        elif list_view.index < len(self._filtered) - 1:
            list_view.index += 1

    def action_select_model(self) -> None:
        list_view = self.query_one("#model-list", ListView)
        index = list_view.index
        if index is None or index < 0 or index >= len(self._filtered):
            return
        key = self._filtered[index]["id"]
        self.dismiss(key)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # 鼠标点击或 Enter 触发选择
        index = self.query_one("#model-list", ListView).index
        if index is None or index < 0 or index >= len(self._filtered):
            return
        key = self._filtered[index]["id"]
        self.dismiss(key)
