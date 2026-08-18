"""主题与配色方案.

支持三套预置主题：dark / light / auto (跟随终端)。
通过 ``/theme`` 命令切换。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from textual.design import ColorSystem


@dataclass(frozen=True, slots=True)
class Theme:
    """单套配色方案."""

    name: str
    label: str
    # 背景与文字
    background: str
    foreground: str
    # 角色
    user_bubble: str        # 用户消息背景
    user_text: str          # 用户消息文字
    assistant_bubble: str   # assistant 消息背景
    assistant_text: str     # assistant 消息文字
    # 强调
    accent: str             # 强调色（链接、关键数据）
    muted: str              # 次要文字
    # 状态
    success: str
    warning: str
    error: str
    # 工具调用卡片
    tool_bg: str
    tool_border: str


DARK: Final[Theme] = Theme(
    name="dark",
    label="深色（默认）",
    background="#0e0f13",
    foreground="#e6e6e6",
    user_bubble="#1c2733",
    user_text="#cfe3ff",
    assistant_bubble="#16181d",
    assistant_text="#e6e6e6",
    accent="#7aa2ff",
    muted="#7a7d85",
    success="#7ee787",
    warning="#f6c177",
    error="#ff6b6b",
    tool_bg="#0d1f1a",
    tool_border="#3a5a4a",
)


LIGHT: Final[Theme] = Theme(
    name="light",
    label="浅色",
    background="#fafaf7",
    foreground="#1c1c1c",
    user_bubble="#e3eefc",
    user_text="#0a3a7a",
    assistant_bubble="#f0eee8",
    assistant_text="#1c1c1c",
    accent="#1f6feb",
    muted="#6e7681",
    success="#1a7f37",
    warning="#bf8700",
    error="#cf222e",
    tool_bg="#e8f5ee",
    tool_border="#7ab391",
)


# Auto: 跟随终端背景色（由 Textual 自动检测）
AUTO: Final[Theme] = Theme(
    name="auto",
    label="跟随终端",
    background="",  # 空 = 用终端默认
    foreground="",
    user_bubble="$accent 20%",
    user_text="$foreground",
    assistant_bubble="$panel",
    assistant_text="$foreground",
    accent="$accent",
    muted="$text-muted",
    success="$success",
    warning="$warning",
    error="$error",
    tool_bg="$boost",
    tool_border="$accent 50%",
)


THEMES: Final[dict[str, Theme]] = {t.name: t for t in (DARK, LIGHT, AUTO)}
DEFAULT_THEME: Final[str] = "dark"


def get_theme(name: str | None) -> Theme:
    """按名字取主题，未找到则回退到 dark."""
    if not name or name not in THEMES:
        return THEMES[DEFAULT_THEME]
    return THEMES[name]


def to_color_system(theme: Theme) -> ColorSystem:
    """将 Theme 转成 Textual ColorSystem (用于 App 的 design 参数)."""
    if theme.name == "auto":
        return ColorSystem()
    return ColorSystem(
        primary=theme.accent,
        secondary=theme.muted,
        background=theme.background or "#0e0f13",
        surface=theme.assistant_bubble,
        panel=theme.user_bubble,
        warning=theme.warning,
        error=theme.error,
        success=theme.success,
        accent=theme.accent,
    )
