"""
WelcomePanel — 欢迎面板 (Claude Code 风格双栏布局)

左栏: 羽汐图片 (rich_pixels 像素渲染) + 欢迎语 + 模型/目录信息
右栏: Tips for getting started + What's new
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from rich_pixels import Pixels
    _HAS_RICH_PIXELS = True
except ImportError:
    _HAS_RICH_PIXELS = False

from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

# 图片路径: 仅使用 assets 目录下的副本
_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_YUXI_IMG = _ASSETS_DIR / "yuxi.png"


class WelcomePanel(Container):
    """欢迎面板 — 赛博朋克风格双栏布局."""

    DEFAULT_CSS = """
    WelcomePanel {
        background: transparent;
        padding: 1 2;
        height: auto;
        max-width: 75;
    }

    WelcomePanel .welcome-left {
        width: 1fr;
        height: auto;
        padding: 0 2 0 4;
    }

    WelcomePanel .welcome-right {
        width: 1fr;
        height: auto;
        padding: 0 0 0 2;
    }

    WelcomePanel .welcome-image {
        text-align: center;
        width: 100%;
        height: 40;
    }

    WelcomePanel .welcome-title {
        color: #fab283;
        text-style: bold;
        text-align: center;
        width: 100%;
        height: 1;
    }

    WelcomePanel .welcome-model {
        color: #5c9cf5;
        text-align: center;
        width: 100%;
        height: 1;
    }

    WelcomePanel .welcome-dir {
        color: #56b6c2;
        text-align: center;
        width: 100%;
        height: 1;
    }

    WelcomePanel .section-header {
        color: #e5c07b;
        text-style: bold;
        width: 100%;
        height: 1;
        margin-top: 1;
        margin-bottom: 1;
    }

    WelcomePanel .tip-item {
        color: #eeeeee;
        width: 100%;
        height: auto;
    }

    WelcomePanel .news-item {
        color: #eeeeee;
        width: 100%;
        height: auto;
    }
    """

    def __init__(
        self,
        model_name: str = "deepseek",
        working_dir: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._model_name = model_name
        self._working_dir = working_dir

    def compose(self):
        with Horizontal():
            # 左栏
            with Vertical(classes="welcome-left"):
                # 用 rich_pixels 直接渲染图片
                if _HAS_RICH_PIXELS and _YUXI_IMG.exists():
                    try:
                        pixels = Pixels.from_image_path(
                            str(_YUXI_IMG), resize=(35, 36)
                        )
                        yield Static(pixels, classes="welcome-image")
                    except Exception:
                        pass
                yield Static("Welcome back!", classes="welcome-title")
                yield Static(
                    f"[#00d4ff]Model: {self._model_name}[/]",
                    classes="welcome-model",
                    markup=True,
                )
                workdir = self._working_dir or ""
                if len(workdir) > 40:
                    workdir = "..." + workdir[-37:]
                yield Static(
                    f"[#00f5ff]Dir: {workdir}[/]",
                    classes="welcome-dir",
                    markup=True,
                )
            # 右栏
            with Vertical(classes="welcome-right"):
                yield Static("Tips for getting started", classes="section-header")
                yield Static(
                    "  Run /init to create a HAKUS.md file",
                    classes="tip-item",
                )
                yield Static(
                    "  Use /model to switch AI models",
                    classes="tip-item",
                )
                yield Static(
                    "  Type /help for all commands",
                    classes="tip-item",
                )
                yield Static("What's new", classes="section-header")
                yield Static(
                    "  OpenCode-style dark theme",
                    classes="news-item",
                )
                yield Static(
                    "  Character pixel art welcome panel",
                    classes="news-item",
                )
                yield Static(
                    "  Command palette (Ctrl+P)",
                    classes="news-item",
                )
