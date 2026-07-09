"""DiffOverlay — 文件变更 Diff 查看器 (Codex 风格)

显示 unified diff 格式，删除行红色、添加行绿色。
支持滚动浏览和 Esc 关闭。
"""
from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Static


class DiffOverlay(ModalScreen[None]):
    """Diff 查看器 Overlay."""

    BINDINGS = [
        Binding("escape", "dismiss(None)", "关闭"),
        Binding("q", "dismiss(None)", "关闭", show=False),
    ]

    DEFAULT_CSS = """
    DiffOverlay {
        align: center middle;
    }

    DiffOverlay > .modal {
        width: 80%;
        max-width: 120;
        height: 70%;
        max-height: 40;
        background: #141414;
        border: thick #9d7cd8;
        padding: 1 2;
    }

    DiffOverlay .modal-title {
        color: #fab283;
        text-style: bold;
        width: 100%;
        height: 1;
        margin-bottom: 1;
    }

    DiffOverlay .diff-container {
        width: 100%;
        height: 1fr;
        background: #0a0a0a;
        padding: 0 1;
    }

    DiffOverlay .diff-line {
        width: 100%;
        height: 1;
    }

    DiffOverlay .diff-line-added {
        color: #56b6c2;
        background: #1e2e1e;
    }

    DiffOverlay .diff-line-removed {
        color: #e06c75;
        background: #2e1e1e;
    }

    DiffOverlay .diff-line-context {
        color: #eeeeee;
    }

    DiffOverlay .diff-line-header {
        color: #56b6c2;
        text-style: bold;
    }

    DiffOverlay .diff-line-meta {
        color: #606060;
    }

    DiffOverlay .hint {
        color: #606060;
        width: 100%;
        height: 1;
        margin-top: 1;
        text-align: center;
    }
    """

    def __init__(self, path: str = "", diff: str = "") -> None:
        super().__init__()
        self._path = path
        self._diff = diff

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static(f"Diff: {self._path}", classes="modal-title")
            with ScrollableContainer(classes="diff-container"):
                for line in self._render_diff_lines():
                    yield Static(line["text"], classes=f"diff-line {line['class']}", markup=True)
            yield Static("Esc 关闭 · ↑↓ 滚动", classes="hint")

    def _render_diff_lines(self) -> list[dict]:
        """Parse unified diff and return styled lines."""
        if not self._diff:
            return [{"text": "(无变更)", "class": "diff-line-meta"}]

        lines = []
        for line in self._diff.splitlines():
            if line.startswith("---") or line.startswith("+++"):
                lines.append({
                    "text": escape(line),
                    "class": "diff-line-header",
                })
            elif line.startswith("@@"):
                lines.append({
                    "text": escape(line),
                    "class": "diff-line-meta",
                })
            elif line.startswith("+"):
                lines.append({
                    "text": f"[#56b6c2]{escape(line)}[/]",
                    "class": "diff-line-added",
                })
            elif line.startswith("-"):
                lines.append({
                    "text": f"[#e06c75]{escape(line)}[/]",
                    "class": "diff-line-removed",
                })
            else:
                lines.append({
                    "text": escape(line),
                    "class": "diff-line-context",
                })

        return lines
