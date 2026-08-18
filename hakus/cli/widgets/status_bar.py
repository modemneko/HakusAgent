"""状态栏 — 模型/模式/思考强度/token 计数/墙钟.

布局：``[mode] [effort] [model] | [tools:N] [tokens:i/o cache%] | [time]``
"""
from __future__ import annotations

import time
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from ..session import TurnStats


class StatusBar(Horizontal):
    """底部状态栏."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $accent 20%;
        color: $foreground;
        padding: 0 1;
        layout: horizontal;
    }
    StatusBar > Static {
        height: 1;
        padding: 0 1;
        border: none;
        background: transparent;
    }
    StatusBar .sep {
        color: $text-muted;
        padding: 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._mode_label: Optional[Static] = None
        self._effort_label: Optional[Static] = None
        self._model_label: Optional[Static] = None
        self._tools_label: Optional[Static] = None
        self._token_label: Optional[Static] = None
        self._time_label: Optional[Static] = None
        self._turn_start: float = 0.0

    def compose(self) -> ComposeResult:
        self._mode_label = Static("[cyan]Work[/]", classes="sb-mode")
        yield self._mode_label
        yield Static("│", classes="sep")
        self._effort_label = Static("[dim]快速[/]", classes="sb-effort")
        yield self._effort_label
        yield Static("│", classes="sep")
        self._model_label = Static("[green]deepseek[/]", classes="sb-model")
        yield self._model_label
        yield Static("│", classes="sep")
        self._tools_label = Static("[dim]tools:0[/]", classes="sb-tools")
        yield self._tools_label
        yield Static("│", classes="sep")
        self._token_label = Static(
            "[dim]tokens: 0/0 cache:0%[/]", classes="sb-tokens"
        )
        yield self._token_label
        yield Static("│", classes="sep")
        self._time_label = Static("[dim]0.0s[/]", classes="sb-time")
        yield self._time_label

    # ── 更新接口 ────────────────────────────────────────────

    def update_mode(self, mode: str) -> None:
        if self._mode_label is None:
            return
        label = "Work" if mode == "swift" else ("Code" if mode == "deep" else mode)
        self._mode_label.update(f"[cyan]{label}[/]")

    def update_effort(self, effort: Optional[str]) -> None:
        if self._effort_label is None:
            return
        mapping = {
            None: "快速",
            "low": "快速(L)",
            "high": "深度",
            "max": "极致",
        }
        label = mapping.get(effort, str(effort))
        self._effort_label.update(f"[dim]{label}[/]")

    def update_model(self, model: str) -> None:
        if self._model_label is None:
            return
        self._model_label.update(f"[green]{model}[/]")

    def update_tool_count(self, count: int) -> None:
        if self._tools_label is None:
            return
        self._tools_label.update(f"[dim]tools:{count}[/]")

    def update_stats(self, stats: TurnStats) -> None:
        """更新 token / 工具计数 / 时间."""
        if self._token_label is None:
            return
        cache_total = stats.cache_hit_tokens + stats.cache_miss_tokens
        cache_pct = (
            (stats.cache_hit_tokens / cache_total * 100) if cache_total > 0 else 0
        )
        self._token_label.update(
            f"[dim]tokens: {stats.input_tokens}/{stats.output_tokens}"
            f" cache:{cache_pct:.0f}%[/]"
        )
        self.update_tool_count(stats.tool_calls)
        if self._time_label is not None:
            elapsed = time.time() - (stats.started_at or time.time())
            self._time_label.update(f"[dim]{elapsed:.1f}s[/]")


__all__ = ["StatusBar"]
