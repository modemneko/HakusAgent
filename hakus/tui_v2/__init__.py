"""
HakusAI TUI v2 — Textual 框架重写

借鉴 Claude Code (https://github.com/claude-code-best/claude-code) 的 UI 模式:
- FullscreenLayout: 顶部状态栏 + 中部可滚动消息 + 底部输入
- VirtualMessageList: 长会话虚拟化
- Dispatcher: 消息按 role 分发到不同 widget
- 无 Panel 边框, 用背景色 + 左侧粗边框

入口:
    from hakus.tui_v2.app import HakusApp
    app = HakusApp(agent)
    app.run()
"""
from .app import HakusApp, run
from .session import TUISession
from .messages import Message
from .commands import SlashCommand, SlashCommandRegistry, CommandContext

__all__ = [
    "HakusApp",
    "run",
    "TUISession",
    "Message",
    "SlashCommand",
    "SlashCommandRegistry",
    "CommandContext",
]
