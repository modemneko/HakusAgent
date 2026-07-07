"""ModelOverlay — 全屏模型选择面板 (Codex 风格)"""
from __future__ import annotations

from typing import Any, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Static

from ...models.provider_registry import PROVIDERS


class ModelOverlay(ModalScreen[str]):
    """模型选择 Overlay — 返回选中的模型名或空字符串(取消)."""

    BINDINGS = [
        Binding("escape", "dismiss('')", "取消"),
        Binding("up", "cursor_up", "上一个", show=False),
        Binding("down", "cursor_down", "下一个", show=False),
        Binding("enter", "select_model", "确认"),
        Binding("j", "cursor_down", "下一个", show=False),
        Binding("k", "cursor_up", "上一个", show=False),
    ]

    DEFAULT_CSS = """
    ModelOverlay {
        align: center middle;
    }

    ModelOverlay > .modal {
        width: 50%;
        max-width: 80;
        height: auto;
        max-height: 20;
        background: #141414;
        border: thick #9d7cd8;
        padding: 1 2;
    }

    ModelOverlay .modal-title {
        color: #fab283;
        text-style: bold;
        width: 100%;
        height: 1;
        margin-bottom: 1;
    }

    ModelOverlay .model-item {
        width: 100%;
        height: 1;
        padding: 0 1;
    }

    ModelOverlay .model-item.selected {
        background: #1e1e1e;
    }

    ModelOverlay .model-item .model-name {
        color: #eeeeee;
    }

    ModelOverlay .model-item.selected .model-name {
        color: #9d7cd8;
        text-style: bold;
    }

    ModelOverlay .model-item .model-desc {
        color: #606060;
    }

    ModelOverlay .hint {
        color: #606060;
        width: 100%;
        height: 1;
        margin-top: 1;
        text-align: center;
    }
    """

    selected_index: reactive[int] = reactive(0)

    def __init__(self, current_model: str = "deepseek") -> None:
        super().__init__()
        self._current_model = current_model
        self._models = PROVIDERS  # 从统一注册表读取
        # Find current model index
        for i, p in enumerate(self._models):
            if p["id"] == current_model:
                self.selected_index = i
                break

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static("选择模型", classes="modal-title")
            for i, p in enumerate(self._models):
                prefix = "> " if i == self.selected_index else "  "
                current = " (当前)" if p["id"] == self._current_model else ""
                style_class = "model-item"
                if i == self.selected_index:
                    style_class += " selected"
                if p["id"] == self._current_model:
                    style_class += " current"
                yield Static(
                    f"{prefix}[bold]{p['name']}[/bold]  [#606060]{p['desc']}[/]{current}",
                    classes=style_class,
                    markup=True,
                )
            yield Static("↑↓ 选择  Enter 确认  Esc 取消", classes="hint")

    def action_cursor_up(self) -> None:
        if self.selected_index > 0:
            self.selected_index -= 1
            self._refresh_items()

    def action_cursor_down(self) -> None:
        if self.selected_index < len(self._models) - 1:
            self.selected_index += 1
            self._refresh_items()

    def action_select_model(self) -> None:
        key = self._models[self.selected_index]["id"]
        self.dismiss(key)

    def _refresh_items(self) -> None:
        """Re-render the model list with updated selection."""
        try:
            items = self.query(".model-item")
            for i, item in enumerate(items):
                p = self._models[i]
                prefix = "> " if i == self.selected_index else "  "
                current = " (当前)" if p["id"] == self._current_model else ""
                item.set_class(i == self.selected_index, "selected")
                item.update(
                    f"{prefix}[bold]{p['name']}[/bold]  [#606060]{p['desc']}[/]{current}"
                )
        except Exception:
            pass
