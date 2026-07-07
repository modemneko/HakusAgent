"""
ActivityStrip — 活动指示器 (Claude Code Spinner 风格)

- 显示当前 phase: `✦ Thinking… · 3s`
- idle 时不显示 (避免噪音)
- 每 100ms 切换 glyph 帧 (shimmer 动画)
"""
from __future__ import annotations

import time
from typing import Optional

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static

from ...tui_v2.theme import PHASE_LABELS, SPINNER_FRAMES


class ActivityStrip(Horizontal):
    """活动指示器 (固定 1 行, idle 时隐藏).

    CSS: #activity-strip (在 theme.tcss 中定义).
    """

    DEFAULT_CSS = """
    ActivityStrip {
        height: 1;
        background: #0a0a0a;
        padding: 0 1;
        display: none;
    }

    ActivityStrip.active {
        display: block;
    }

    ActivityStrip #activity-glyph {
        color: #9d7cd8;
        text-style: bold;
        width: auto;
    }

    ActivityStrip #activity-label {
        color: #eeeeee;
        text-style: bold;
        width: auto;
    }

    ActivityStrip #activity-detail {
        color: #56b6c2;
        width: auto;
    }

    ActivityStrip #activity-elapsed {
        color: #606060;
        width: auto;
    }

    ActivityStrip #activity-tool {
        color: #56b6c2;
        width: auto;
    }
    """

    phase: reactive[str] = reactive("idle")
    detail: reactive[str] = reactive("")
    tool_name: reactive[str] = reactive("")
    started_at: reactive[float] = reactive(0.0)
    _frame: reactive[int] = reactive(0)

    def compose(self):
        yield Static("", id="activity-glyph")
        yield Static("", id="activity-label")
        yield Static("", id="activity-detail")
        yield Static("", id="activity-elapsed")
        yield Static("", id="activity-tool")

    def on_mount(self) -> None:
        # 启动 100ms 动画帧
        self.set_interval(0.1, self._tick)

    def set_phase(self, phase: str, detail: str = "", tool_name: str = "") -> None:
        """切换 phase (来自 activity tracker)."""
        if phase != self.phase:
            self.started_at = time.time()
        self.phase = phase
        self.detail = detail
        self.tool_name = tool_name
        if phase != "idle":
            self.add_class("active")
        else:
            self.remove_class("active")
        self._tick()

    def _tick(self) -> None:
        try:
            glyph_w = self.query_one("#activity-glyph", Static)
            label_w = self.query_one("#activity-label", Static)
            detail_w = self.query_one("#activity-detail", Static)
            elapsed_w = self.query_one("#activity-elapsed", Static)
            tool_w = self.query_one("#activity-tool", Static)
        except Exception:
            return

        if self.phase == "idle":
            glyph_w.update("")
            label_w.update("")
            detail_w.update("")
            elapsed_w.update("")
            tool_w.update("")
            return

        # glyph 帧
        frame = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
        self._frame += 1
        glyph_w.update(f" {frame} ")

        label = PHASE_LABELS.get(self.phase, self.phase.capitalize())
        label_w.update(label)

        if self.detail:
            detail_w.update(f"  {self.detail}")
        else:
            detail_w.update("")

        if self.started_at > 0:
            elapsed = int(time.time() - self.started_at)
            elapsed_w.update(f"  ·  {elapsed}s")
        else:
            elapsed_w.update("")

        if self.tool_name:
            tool_w.update(f"  ·  {self.tool_name}")
        else:
            tool_w.update("")

    def watch_phase(self, _: object) -> None:
        self._tick()

    def watch_detail(self, _: object) -> None:
        self._tick()

    def watch_tool_name(self, _: object) -> None:
        self._tick()
