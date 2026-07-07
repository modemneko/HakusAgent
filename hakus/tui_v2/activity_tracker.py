"""
ActivityTracker Bridge — 把 hakus.status_display.TRACKER 适配到 Textual ActivityStrip

不在 widget 里直接 import TRACKER (避免循环依赖),
而是通过订阅回调方式让 App 主动把 phase 变化传给 widget.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .widgets.activity import ActivityStrip
    from .app import HakusApp


def bind_tracker_to_strip(app: "HakusApp", strip: "ActivityStrip") -> None:
    """订阅 TRACKER 状态变化, 推送到 strip."""
    from ..status_display import TRACKER

    def on_change(state) -> None:
        # Textual 必须用 call_from_thread 或 call_later 跨线程
        try:
            app.call_from_thread(
                strip.set_phase,
                state.phase,
                state.detail,
                state.tool_name,
            )
        except Exception:
            # 非线程场景下的 fallback
            strip.set_phase(state.phase, state.detail, state.tool_name)

    TRACKER.subscribe(on_change)
