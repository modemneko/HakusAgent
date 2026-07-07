"""
StatusBar — 底部状态栏 (OpenCode 风格按钮式)

布局: [⚡ HakusAI] [deepseek ▾] [0 tok] [⏱ 00:01] [⟳ auto ▾]
每个字段是一个可点击的按钮
"""
from __future__ import annotations

import time
from typing import Optional

from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Static

from ...tui_v2.theme import context_pct_color, context_pct_glyph


class StatusBar(Horizontal):
    """底部状态栏 (固定 1 行, 输入框上方).

    CSS: #status-bar (在 theme.tcss 中定义).
    """

    class ModelClicked(Message):
        """点击模型按钮."""
        pass

    class PermClicked(Message):
        """点击权限按钮."""
        pass

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: #141414;
        color: #eeeeee;
        padding: 0 1;
    }

    StatusBar .status-brand {
        color: #fab283;
        text-style: bold;
        width: auto;
    }

    StatusBar .status-btn {
        min-width: 0;
        height: 1;
        padding: 0 1;
        margin: 0;
        background: transparent;
        border: none;
        color: #eeeeee;
        width: auto;
    }

    StatusBar .status-btn:hover {
        background: #1e1e1e;
    }

    StatusBar .status-model {
        color: #5c9cf5;
    }

    StatusBar .status-tokens {
        color: #e5c07b;
    }

    StatusBar .status-time {
        color: #56b6c2;
    }

    StatusBar .status-perm {
        color: #56b6c2;
    }

    StatusBar .status-sep {
        color: #606060;
        width: auto;
        padding: 0;
    }
    """

    model_name: reactive[str] = reactive("deepseek")
    working_dir: reactive[str] = reactive("")
    context_pct: reactive[Optional[int]] = reactive(None)
    context_tokens: reactive[int] = reactive(0)
    context_max: reactive[int] = reactive(0)
    total_tokens: reactive[int] = reactive(0)
    started_at: reactive[float] = reactive(0.0)
    permission_mode: reactive[str] = reactive("auto")
    voice_enabled: reactive[bool] = reactive(False)

    def compose(self):
        yield Static("⚡ HakusAI", classes="status-brand")
        yield Static("·", classes="status-sep")
        yield Button("deepseek", id="status-model", classes="status-btn status-model")
        yield Static("·", classes="status-sep")
        yield Button("0 tok", id="status-tokens", classes="status-btn status-tokens")
        yield Static("·", classes="status-sep")
        yield Static("⏱ 00:00", id="status-time", classes="status-btn status-time")
        yield Static("·", classes="status-sep")
        yield Button("⟳ auto", id="status-perm", classes="status-btn status-perm")

    def on_mount(self) -> None:
        if not self.started_at:
            self.started_at = time.time()
        self._refresh()
        self.set_interval(1.0, self._refresh)

    def _refresh(self) -> None:
        try:
            model_btn = self.query_one("#status-model", Button)
            model_btn.label = self.model_name or "deepseek"
        except Exception:
            pass

        try:
            tokens = int(self.total_tokens or 0)
            token_str = f"{tokens/1000:.1f}k" if tokens >= 1000 else str(tokens)
            tokens_btn = self.query_one("#status-tokens", Button)
            tokens_btn.label = f"{token_str} tok"
        except Exception:
            pass

        try:
            started = float(self.started_at or 0)
            elapsed = int(time.time() - started) if started else 0
            m, s = divmod(elapsed, 60)
            h, m = divmod(m, 60)
            time_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            time_label = self.query_one("#status-time", Static)
            time_label.update(f"⏱ {time_str}")
        except Exception:
            pass

        try:
            perm_icons = {"auto": "⟳", "ask": "?", "bypass": "⚡"}
            perm_icon = perm_icons.get(self.permission_mode, "?")
            perm_btn = self.query_one("#status-perm", Button)
            perm_btn.label = f"{perm_icon} {self.permission_mode}"
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "status-model":
            self.post_message(self.ModelClicked())
        elif event.button.id == "status-perm":
            self.post_message(self.PermClicked())
