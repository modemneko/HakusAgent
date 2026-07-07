"""
HakusAI TUI v2 — OpenCode 风格主题

参考 OpenCode 默认主题 (opencode.json):
- 深色背景 + 灰阶层次
- 暖橙色主色 + 蓝色次要色 + 紫色强调色
- 干净、专业的设计语言
"""

# OpenCode 风格配色
COLORS = {
    # 背景层次 (从深到浅)
    "base": "#0a0a0a",         # 最深背景
    "mantle": "#141414",       # 面板背景
    "surface0": "#1e1e1e",     # 元素背景
    "surface1": "#282828",     # 悬停背景
    "surface2": "#323232",     # 选中背景
    "overlay0": "#3c3c3c",     # 边框
    "overlay1": "#484848",     # 活动边框
    "overlay2": "#606060",     # 亮边框

    # 文字
    "text": "#eeeeee",         # 主文字
    "textMuted": "#808080",    # 次要文字
    "textDim": "#484848",      # 暗淡文字

    # 主色调
    "primary": "#fab283",      # 暖橙色 (品牌/主色)
    "secondary": "#5c9cf5",    # 蓝色 (次要)
    "accent": "#9d7cd8",       # 紫色 (强调)

    # 状态色
    "error": "#e06c75",        # 红色
    "warning": "#f5a742",      # 橙色
    "success": "#7fd88f",      # 绿色
    "info": "#56b6c2",         # 青色
    "yellow": "#e5c07b",       # 黄色
}

# 语义角色
SEMANTIC = {
    "border": COLORS["overlay0"],
    "borderActive": COLORS["overlay2"],
    "borderSubtle": COLORS["overlay0"],
    "header_bg": COLORS["mantle"],
    "user_bg": COLORS["surface0"],
    "user_fg": COLORS["secondary"],
    "user_accent": COLORS["secondary"],
    "assistant_fg": COLORS["text"],
    "assistant_accent": COLORS["accent"],
    "tool_fg": COLORS["yellow"],
    "tool_accent": COLORS["yellow"],
    "error_fg": COLORS["error"],
    "error_accent": COLORS["error"],
    "dim": COLORS["textDim"],
    "muted": COLORS["textMuted"],
    "success": COLORS["success"],
    "thinking": COLORS["accent"],
    "streaming": COLORS["info"],
    "context_safe": COLORS["success"],
    "context_warn": COLORS["warning"],
    "context_crit": COLORS["error"],
}


# 旋转动画帧
SPINNER_FRAMES = [
    "\u280b", "\u2819", "\u2839", "\u2838",
    "\u283c", "\u2834", "\u2836", "\u2837",
    "\u283f", "\u281f",
]

# 阶段图标
PHASE_GLYPHS = {
    "idle": "\u00b7",
    "thinking": "\u2726",
    "streaming": "\u258c",
    "tool_use": "\u2699",
    "orchestrator": "\u27c1",
    "compact": "\u25d0",
    "permission": "\u23f5",
}
PHASE_LABELS = {
    "idle": "Ready",
    "thinking": "Thinking",
    "streaming": "Streaming",
    "tool_use": "Tool",
    "orchestrator": "Orchestrating",
    "compact": "Compacting",
    "permission": "Awaiting approval",
    "fetching": "Fetching",
    "searching": "Searching",
    "writing": "Writing",
    "reading": "Reading",
    "executing": "Executing",
    "retrying": "Retrying",
    "calibrating": "Calibrating",
}


def context_pct_color(pct: int) -> str:
    """上下文使用百分比对应的颜色."""
    if pct >= 75:
        return SEMANTIC["context_crit"]
    if pct >= 50:
        return SEMANTIC["context_warn"]
    return SEMANTIC["context_safe"]


def context_pct_glyph(pct: int) -> str:
    if pct >= 75:
        return "\u2588"
    if pct >= 50:
        return "\u2593"
    return "\u2591"
