"""HelpOverlay — 全屏帮助面板 (OpenCode 风格)"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static


HELP_CONTENT = """## ⌨ 快捷键

| 按键 | 功能 |
|------|------|
| `Enter` | 发送消息 |
| `Shift+Enter` | 换行 (多行输入) |
| `Esc` | 中断流式输出 |
| `Ctrl+C` | 退出应用 |
| `Ctrl+L` | 清屏 |
| `Ctrl+M` | 切换模型 |
| `Ctrl+P` | 命令面板 |
| `F1` | 显示帮助 |
| `↑ / ↓` | 浏览历史 |

## 📝 命令列表

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/model` | 切换模型 |
| `/clear` | 清屏 |
| `/compact` | 压缩上下文 |
| `/permission` | 切换权限模式 |
| `/cost` | 查看 Token 用量 |
| `/context` | 查看上下文信息 |
| `/tools` | 列出可用工具 |
| `/diff` | 查看 Git Diff |
| `/git` | Git 操作 |
| `/status` | 查看状态 |
| `/debug` | 切换调试模式 |
| `/voice` | 切换语音输入 |
| `/plan` | 启用 Plan 模式 |
| `/todos` | 查看待办列表 |
| `/tree` | 显示项目目录树 |
| `/memory` | 查看已保存的项目记忆 |
| `/task` | 查看/管理后台任务 |
| `/spec` | Spec 模式 |
| `/orchestrate` | 多智能体协同 |
| `/exit` | 退出 |

**Tip:** 按 `Ctrl+P` 打开命令面板快速执行命令
"""


class HelpOverlay(ModalScreen[None]):
    """帮助面板 Overlay."""

    BINDINGS = [
        Binding("escape", "dismiss(None)", "关闭"),
        Binding("q", "dismiss(None)", "关闭", show=False),
    ]

    DEFAULT_CSS = """
    HelpOverlay {
        align: center middle;
    }

    HelpOverlay > .modal {
        width: 70%;
        max-width: 100;
        height: auto;
        max-height: 30;
        background: #141414;
        border: thick #9d7cd8;
        padding: 1 2;
    }

    HelpOverlay .modal-title {
        color: #fab283;
        text-style: bold;
        width: 100%;
        height: 1;
        margin-bottom: 1;
    }

    HelpOverlay Markdown {
        background: transparent;
    }

    HelpOverlay MarkdownH2 {
        color: #9d7cd8;
        text-style: bold;
    }

    HelpOverlay MarkdownTable {
        width: 100%;
    }

    HelpOverlay .hint {
        color: #606060;
        width: 100%;
        height: 1;
        margin-top: 1;
        text-align: center;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static("快捷键与命令", classes="modal-title")
            yield Markdown(HELP_CONTENT)
            yield Static("按 Esc 关闭", classes="hint")
