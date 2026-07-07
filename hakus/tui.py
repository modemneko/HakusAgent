r"""
HakusAI Fullscreen Terminal UI
Claude Code 风格的终端交互界面

布局:
+--------------------------------------------------------------+
| HakusAI v2.0 · deepseek · D:\project · Tokens: 1.2k · auto  |  <- StatusBar
+--------------------------------------------------------------+
|                                                              |
|  ▶ 用户消息                                                  |  <- Conversation
|                                                              |
|  HakusAI  回复内容（支持 Markdown / 代码高亮）                |
|                                                              |
|  ---- · · · ----                                            |  <- Turn separator
|                                                              |
+--------------------------------------------------------------+
| > 输入框                                      Ctrl+S 发送    |  <- InputBar
+--------------------------------------------------------------+
"""
import asyncio
import os
import re
import sys
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.config import BASE_CONFIG
from utils.logger import get_logger
from .status_display import (
    TRACKER, ActivityState, format_phase, activity, install_root_logging_policy,
)

logger = get_logger(__name__)

# 启动时立即生效 — Claude Code 风格: 不让任何 logger 污染 stdout
install_root_logging_policy()

try:
    from rich.console import Console, Group, RenderableType
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.live import Live
    from rich.text import Text
    from rich import box
    from rich.rule import Rule
    from rich.columns import Columns
    from rich.align import Align
    from rich.layout import Layout
    from rich.style import Style
    from rich.spinner import Spinner
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion, CompleteEvent
    from prompt_toolkit.document import Document
    from prompt_toolkit.styles import Style as PTStyle
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.formatted_text import HTML
    _HAS_PROMPT = True
except ImportError:
    _HAS_PROMPT = False


_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

_COLORS = {
    "border": "#313244",
    "header_bg": "#181825",
    "dim": "#585b70",
    "accent": "#cba6f7",
    "cyan": "#89dceb",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "red": "#f38ba8",
    "blue": "#89b4fa",
    "text": "#cdd6f4",
    "user": "#89b4fa",
    "ai": "#a6e3a1",
    "tool": "#f9e2af",
    "error": "#f38ba8",
}

HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".hakus")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history")
SESSION_FILE = os.path.join(HISTORY_DIR, "last_session.json")


@dataclass
class Message:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    tool_calls: List[Dict] = field(default_factory=list)
    is_error: bool = False


@dataclass
class TUISession:
    model_name: str = ""
    permission_mode: str = "auto"
    voice_enabled: bool = False
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    message_count: int = 0
    start_time: float = field(default_factory=time.time)
    turn_count: int = 0
    working_dir: str = ""
    messages: List[Message] = field(default_factory=list)
    fullscreen: bool = True
    todos: List[Dict[str, str]] = field(default_factory=list)


class SlashCompleter(Completer):
    COMMANDS = {
        "/help": "显示可用命令",
        "/model": "切换模型 (deepseek/qwen/gemini/glm/mimo)",
        "/permission": "设置权限模式 (auto/ask/bypass)",
        "/clear": "清除对话历史",
        "/compact": "压缩上下文",
        "/cost": "显示Token用量",
        "/checkpoint": "查看检查点",
        "/rollback": "回退到检查点",
        "/task": "查看/管理后台任务",
        "/task start": "启动后台任务",
        "/init": "初始化项目 .hakus.md",
        "/memory": "查看已加载的项目记忆",
        "/plan": "进入 Plan 模式",
        "/approve": "批准当前计划",
        "/reject": "拒绝当前计划",
        "/todos": "查看任务列表",
        "/tree": "显示项目目录树",
        "/tools": "列出所有可用工具",
        "/git": "查看 Git 状态",
        "/diff": "查看未暂存差异",
        "/voice": "切换语音模式",
        "/status": "显示会话状态",
        "/spec": "查看当前会话规格 (含模型名)",
        "/db": "数据库管理 (Navicat 风格: 连接/查询/导入/导出)",
        "/db list": "列出已保存的数据库连接",
        "/db navicat [name]": "进入 Navicat REPL 模式",
        "/db connect <name>": "连接数据库 (使用保存的连接)",
        "/db tables <name>": "列出连接的所有表",
        "/db desc <name> <table>": "查看表结构",
        "/db query <name> <sql>": "执行 SQL 查询",
        "/db execute <name> <sql>": "执行 SQL 写操作",
        "/db remove <name>": "删除已保存的连接",
        "/exit": "退出 HakusAI",
    }
    MODELS = ["deepseek", "qwen", "gemini", "glm", "mimo"]
    MODES = ["auto", "ask", "bypass"]

    def __init__(self, tui: Optional["HakusTUI"] = None):
        super().__init__()
        self._tui = tui
        if tui is not None and hasattr(tui, "SLASH_COMMANDS"):
            self.COMMANDS = dict(tui.SLASH_COMMANDS)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return

        parts = text.split()

        # 1. Top-level command completion with description meta
        if len(parts) == 1:
            prefix = parts[0]
            for cmd, desc in self.COMMANDS.items():
                if cmd.startswith(prefix):
                    yield Completion(
                        cmd,
                        start_position=-len(prefix),
                        display=cmd,
                        display_meta=desc or "",
                    )

        # 2. Sub-command and parameter completion
        elif len(parts) >= 2:
            cmd_base = parts[0]
            sub_prefix = parts[1] if len(parts) >= 2 else ""

            # /model <model_name>
            if cmd_base == "/model" and len(parts) == 2:
                for m in self.MODELS:
                    if m.startswith(sub_prefix):
                        yield Completion(
                            m, start_position=-len(sub_prefix),
                            display=m, display_meta="模型",
                        )

            # /permission <mode>
            elif cmd_base == "/permission" and len(parts) == 2:
                for p in self.MODES:
                    if p.startswith(sub_prefix):
                        yield Completion(
                            p, start_position=-len(sub_prefix),
                            display=p, display_meta="权限模式",
                        )

            # /db <subcommand>
            elif cmd_base == "/db" and len(parts) == 2:
                db_subs = ["list", "connect", "tables", "desc", "query", "execute", "remove", "navicat"]
                for sub in db_subs:
                    if sub.startswith(sub_prefix):
                        desc_map = {
                            "list": "列出连接", "connect": "连接数据库",
                            "tables": "列出表", "desc": "表结构",
                            "query": "查询", "execute": "写操作",
                            "remove": "删除连接", "navicat": "REPL 模式",
                        }
                        yield Completion(
                            sub, start_position=-len(sub_prefix),
                            display=sub, display_meta=desc_map.get(sub, ""),
                        )

            # /db connect <name> — complete from saved DB connections
            elif cmd_base == "/db" and len(parts) >= 3 and parts[1] in ("connect", "tables", "desc", "query", "execute", "remove", "navicat"):
                name_prefix = parts[2] if len(parts) >= 3 else ""
                try:
                    from .db import DB_MANAGER
                    saved = DB_MANAGER.list_configs()
                    for cfg in saved:
                        if cfg.name.startswith(name_prefix):
                            yield Completion(
                                cfg.name, start_position=-len(name_prefix),
                                display=cfg.name,
                                display_meta=f"{cfg.db_type.value}",
                            )
                except Exception:
                    pass


class HakusTUI:
    """HakusAI 全屏终端交互界面"""

    SLASH_COMMANDS = {
        "/help": "显示可用命令",
        "/model <name>": "切换模型 (deepseek/qwen/gemini/glm/mimo)",
        "/permission <mode>": "设置权限模式 (auto/ask/bypass)",
        "/clear": "清除对话历史",
        "/compact": "压缩上下文",
        "/cost": "显示Token用量",
        "/context": "显示上下文窗口使用情况",
        "/verify": "让模型自我检查最近的工作 (避免幻觉/错误)",
        "/btw <note>": "在不动当前任务的情况下添加旁注 (Claude Code /btw)",
        "/checkpoint": "查看检查点",
        "/rollback <id>": "回退到检查点",
        "/task": "查看后台任务",
        "/task start <desc>": "启动后台任务",
        "/init": "初始化项目 .hakus.md",
        "/memory": "查看已加载的项目记忆",
        "/plan": "进入 Plan 模式 (先规划后执行)",
        "/plan exit": "退出 Plan 模式并提交计划",
        "/doctor": "系统健康检查 — 诊断配置、依赖、模型连接等",
        "/recap": "总结当前会话 — 回顾已完成的工作和待办事项",
        "/approve": "批准当前计划",
        "/reject [reason]": "拒绝当前计划",
        "/todos": "查看任务列表",
        "/tree [path]": "显示项目目录树",
        "/tools": "列出所有可用工具",
        "/git": "查看 Git 状态",
        "/diff": "查看未暂存差异",
        "/voice": "切换语音模式",
        "/status": "显示会话状态",
        "/spec": "查看当前会话规格 (含模型名)",
        "/exit": "退出 HakusAI",
    }

    def __init__(self, agent: Any, voice_enabled: bool = False):
        from .agent import AgentCore
        from .protocol import (
            TextDelta,
            TurnCompleted,
            TurnFailed,
            Cancelled as CancelledEvent,
        )
        self._agent: AgentCore = agent
        self._session = TUISession(voice_enabled=voice_enabled)
        self._session.model_name = agent._model_type
        self._session.permission_mode = agent._permission.mode.value
        self._session.working_dir = getattr(agent._context, 'working_dir', os.getcwd())
        self._running = False
        self._console: Optional[Console] = None
        # Bound protocol types as attributes so they're available in
        # _process_stream without re-importing (and for isinstance checks).
        self._TextDelta = TextDelta
        self._TurnCompleted = TurnCompleted
        self._TurnFailed = TurnFailed
        self._CancelledEvent = CancelledEvent
        self._prompt_session: Optional[PromptSession] = None
        self._streaming = False
        self._cancelled = False
        self._live: Optional[Live] = None
        self._last_response_text = ""
        self._pending_tool_results: List[Dict] = []
        self._kb = KeyBindings() if _HAS_PROMPT else None
        self._setup_input()

        if _HAS_RICH:
            self._console = Console(
                color_system="truecolor",
                force_interactive=True,
                highlight=False,
            )
        agent._permission.set_confirm_callback(self._permission_confirm)

    def _setup_input(self):
        if not _HAS_PROMPT:
            return
        os.makedirs(HISTORY_DIR, exist_ok=True)

        @self._kb.add('escape', eager=True)
        def _(event):
            self._cancelled = True
            self._streaming = False

        @self._kb.add('c-c', eager=True)
        def _(event):
            if self._streaming:
                self._cancelled = True
                self._streaming = False
            else:
                self._running = False
                event.app.exit()

        pt_style = PTStyle.from_dict({
            'prompt': 'bold #cba6f7',
            '': '#cdd6f4',
            'bottom-toolbar': 'bg:#181825 #585b70',
        })
        self._prompt_session = PromptSession(
            history=FileHistory(HISTORY_FILE),
            auto_suggest=AutoSuggestFromHistory(),
            style=pt_style,
            multiline=False,
            completer=SlashCompleter(self),
            key_bindings=self._kb,
            bottom_toolbar=HTML(
                ' <b>Esc</b>中断  <b>Ctrl+C</b>退出  '
                '<b>↑↓</b>历史  <b>/help</b>帮助'
            ),
        )

    def _render_status_bar(self) -> RenderableType:
        elapsed = int(time.time() - self._session.start_time)
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        time_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

        total_tokens = self._session.total_input_tokens + self._session.total_output_tokens
        if total_tokens >= 1000:
            token_str = f"{total_tokens/1000:.1f}k"
        else:
            token_str = str(total_tokens)

        perm_icon = {"auto": "⟳", "ask": "?", "bypass": "⚡"}.get(
            self._session.permission_mode, "?")

        # Claude Code 风格: 左侧 brand, 右侧 status, 中间模型/工作目录
        workdir = self._session.working_dir or ""
        if len(workdir) > 28:
            workdir = "..." + workdir[-25:]

        # Context window usage — Claude Code shows a progress bar in status.
        # We compute it from the agent's ContextManager if available.
        ctx_pct = None
        ctx_tokens = None
        ctx_max = None
        agent_ctx = getattr(self._agent, "_context", None) if self._agent else None
        if agent_ctx and hasattr(agent_ctx, "max_tokens"):
            try:
                used = agent_ctx._total_estimated_tokens()
                ctx_max = agent_ctx.budget
                ctx_tokens = used
                ctx_pct = min(100, int(used * 100 / max(1, ctx_max)))
            except Exception:
                pass

        # Choose context bar color: green < 50, yellow 50-75, red > 75
        if ctx_pct is None:
            ctx_str = ""
            ctx_style = "dim"
        else:
            bar_full = 8
            filled = max(0, min(bar_full, int(ctx_pct / 100 * bar_full)))
            if ctx_pct >= 75:
                ctx_style = "bold #f38ba8"
                glyph = "█"
            elif ctx_pct >= 50:
                ctx_style = "bold #f9e2af"
                glyph = "▓"
            else:
                ctx_style = "#a6e3a1"
                glyph = "░"
            bar = glyph * filled + "·" * (bar_full - filled)
            ctx_str = f"  ▕{bar}▏ {ctx_pct}% "

        parts = [
            ("bold #cba6f7", " ⚡ HakusAI "),
            ("dim", "  v2.0  "),
            ("#585b70", "│ "),
            ("#89dceb", f"{self._session.model_name} "),
            ("dim", "·  "),
            ("#a6e3a1", f"{workdir} "),
            ("dim", "·  "),
            (ctx_style, ctx_str),
            ("dim", "·  "),
            ("#f9e2af", f"◈ {token_str} tok "),
            ("dim", "·  "),
            ("#a6e3a1", f"⏱ {time_str} "),
            ("dim", "  │  "),
            ("#f38ba8" if self._session.permission_mode == "ask" else "#a6e3a1",
             f"{perm_icon} {self._session.permission_mode}"),
        ]

        # Voice indicator — Claude Code shows active features in status
        if self._session.voice_enabled:
            parts.append(("dim", "  │  "))
            parts.append(("#89dceb", "🎤 voice"))

        # Streaming indicator — show when actively streaming
        if self._streaming:
            parts.append(("dim", "  │  "))
            parts.append(("bold #cba6f7", "✦ streaming"))
        text = Text()
        for style, s in parts:
            text.append(s, style=style)

        return Panel(
            Align.center(text),
            style=Style(color=_COLORS["border"], bgcolor=_COLORS["header_bg"]),
            box=box.SIMPLE,
            padding=(0, 1),
            height=1,
        )

    def _render_activity_strip(self) -> Optional[RenderableType]:
        """Claude Code 风格: 在状态栏下方显示一行动态 activity strip.
        仅当有活动时显示, idle 时不显示 (避免视觉噪音)."""
        state = TRACKER.get()
        if state.phase == "idle" and not state.detail:
            return None
        glyph_map = {
            "thinking": "✦",
            "streaming": "▌",
            "tool_use": "⚙",
            "orchestrator": "⟁",
            "compact": "◐",
            "permission": "⏵",
        }
        label_map = {
            "thinking": "Thinking",
            "streaming": "Streaming",
            "tool_use": "Tool",
            "orchestrator": "Orchestrating",
            "compact": "Compacting",
            "permission": "Awaiting approval",
        }
        glyph = glyph_map.get(state.phase, "·")
        label = label_map.get(state.phase, state.phase.capitalize())
        elapsed = int(state.elapsed())
        detail = state.detail or ""
        text = Text()
        text.append(f" {glyph} ", style="bold #cba6f7")
        text.append(f"{label}", style="bold #cdd6f4")
        if detail:
            text.append(f"  {detail}", style="#a6e3a1")
        text.append(f"  ·  {elapsed}s", style="dim #585b70")
        if state.tool_name:
            text.append(f"  ·  {state.tool_name}", style="#89b4fa")
        return Panel(
            text,
            style=Style(color=_COLORS["border"], bgcolor="#1e1e2e"),
            box=box.SIMPLE,
            padding=(0, 1),
            height=1,
        )

    def _render_message(self, msg: Message, max_width: int = 100) -> RenderableType:
        if msg.role == "user":
            prefix = Text("▸ ", style="bold #89b4fa")
            content = Text(msg.content, style="#89b4fa")
            return Group(prefix, content)

        if msg.is_error:
            return Panel(
                Markdown(msg.content, code_theme="one-dark"),
                border_style=_COLORS["red"],
                box=box.ROUNDED,
                title="✗ Error",
                title_align="left",
            )

        if msg.role == "tool":
            return Panel(
                Markdown(msg.content, code_theme="one-dark"),
                border_style=_COLORS["yellow"],
                box=box.ROUNDED,
                title="⚙ Tool",
                title_align="left",
            )

        return Panel(
            Markdown(msg.content, code_theme="one-dark"),
            border_style=_COLORS["accent"],
            box=box.ROUNDED,
            title="🤖 HakusAI",
            title_align="left",
        )

    def _render_conversation(self) -> RenderableType:
        if not self._session.messages:
            return Group(
                Text(""),
                Align.center(
                    Group(
                        Text("\n\n", style=""),
                        Text("⚡", style="bold #cba6f7"),
                        Text("\nHakusAI · 智能终端助手\n", style="bold #cdd6f4"),
                        Text("输入消息开始对话  ·  /help 查看命令\n", style="dim"),
                        Text("", style=""),
                    )
                ),
                Text(""),
            )

        renders: List[RenderableType] = []
        for i, msg in enumerate(self._session.messages):
            renders.append(self._render_message(msg))
            if i < len(self._session.messages) - 1:
                renders.append(Rule(style=Style(color=_COLORS["border"], dim=True), characters="·"))

        return Group(*renders)

    def _render_streaming(self, text: str) -> RenderableType:
        return Panel(
            Markdown(text, code_theme="one-dark"),
            border_style=_COLORS["accent"],
            box=box.ROUNDED,
            title="🤖 HakusAI",
            title_align="left",
        )

    def _render_spinner(self) -> RenderableType:
        return Panel(
            Group(
                Spinner("dots", text=" Thinking...", style=_COLORS["accent"]),
            ),
            border_style=_COLORS["accent"],
            box=box.ROUNDED,
        )

    def _render_input_bar(self) -> RenderableType:
        # Dynamic hint based on current state
        if self._streaming:
            hint = "✦ 生成中...  ·  Esc 中断  ·  Ctrl+C 退出"
        elif self._session.todos:
            todo_count = len(self._session.todos)
            pending = sum(1 for t in self._session.todos if t.get("status") != "completed")
            hint = f"输入消息  ·  Esc 中断  ·  Ctrl+C 退出  ·  📋 {pending}/{todo_count} tasks"
        else:
            hint = "输入消息或 /命令  ·  Esc 中断  ·  Ctrl+C 退出"
        return Panel(
            Text(hint, style=f"dim {_COLORS['dim']}", justify="center"),
            style=Style(color=_COLORS["border"], bgcolor=_COLORS["header_bg"]),
            box=box.SIMPLE,
            padding=(0, 1),
            height=1,
        )

    def _build_layout(self, conversation_content: RenderableType) -> Layout:
        layout = Layout()
        layout.split(
            Layout(name="status", size=1),
            Layout(name="body"),
            Layout(name="input_bar", size=1),
        )
        layout["status"].update(self._render_status_bar())
        layout["body"].update(conversation_content)
        layout["input_bar"].update(self._render_input_bar())
        return layout

    def _show_fullscreen(self) -> None:
        if not self._console:
            return
        self._console.clear()
        self._console.print(self._render_status_bar())
        self._console.print(self._render_welcome())
        self._console.print(self._render_input_bar())

    def _render_welcome(self) -> RenderableType:
        return Panel(
            Group(
                Text("", style=""),
                Align.center(
                    Group(
                        Text("⚡", style="bold #cba6f7"),
                        Text("\nHakusAI · 长时任务 & 个人助手\n", style="bold #cdd6f4"),
                        Text("\n自然语言直接对话  ·  /help 查看命令\n", style="dim"),
                        Text("模式: Agent (默认 — 工具 + 长任务 + 多智能体)\n", style="dim #585b70"),
                    )
                ),
                Text("", style=""),
            ),
            border_style=_COLORS["border"],
            box=box.ROUNDED,
            padding=(1, 2),
        )

    def _print_user_message(self, content: str) -> None:
        if self._console:
            self._console.print()
            self._console.print(Text("▸ ", style="bold #89b4fa") + Text(content, style="#89b4fa"))
        else:
            print(f"\n> {content}")

    def _print_assistant_message(self, content: str) -> None:
        if self._console:
            self._console.print()
            self._console.print(Panel(
                Markdown(content, code_theme="one-dark"),
                border_style=_COLORS["accent"],
                box=box.ROUNDED,
                title="🤖 HakusAI",
                title_align="left",
            ))
        else:
            print(f"\n[AI]: {content}\n")

    def _print_tool_message(self, content: str, is_error: bool = False) -> None:
        if self._console:
            self._console.print()
            self._console.print(Panel(
                Markdown(content, code_theme="one-dark"),
                border_style=_COLORS["error"] if is_error else _COLORS["yellow"],
                box=box.ROUNDED,
                title="✗ Error" if is_error else "⚙ Tool",
                title_align="left",
            ))
        else:
            prefix = "[ERR]" if is_error else "[TOOL]"
            print(f"\n{prefix}: {content}\n")

    def _print_thinking(self) -> None:
        if self._console:
            self._console.print()
            self._console.print(f"[dim]⏳ HakusAI 思考中...[/dim]")
        else:
            print("\n思考中...")

    def _update_screen(self, content: RenderableType = None) -> None:
        if content is not None and self._console:
            self._console.print(content)

    def _render_full(self) -> None:
        if not self._console:
            return
        self._console.print(self._render_status_bar())

    def _build_status_bar(self) -> Text:
        workdir = self._session.working_dir or os.getcwd()
        if len(workdir) > 40:
            workdir = "..." + workdir[-37:]
        return Text.assemble(
            (" HakusAI ", "bold #cba6f7"),
            (f"· {self._session.model_name} ", "#89b4fa"),
            (f"· {workdir} ", "#585b70"),
            (f"· ~{self._session.total_input_tokens + self._session.total_output_tokens} tok ", "#585b70"),
            (f"· {self._session.permission_mode} ", "#a6e3a1"),
        )

    def _accumulate_tokens(self, user_input: str, assistant_output: str) -> None:
        """Use the ContextManager's estimate_tokens for more accurate token counting.

        Falls back to character-based estimation if context is unavailable.
        CJK characters ~2 tokens, ASCII ~0.25 tokens (much more accurate than len/4).
        """
        ctx = getattr(self._agent, "_context", None)
        if ctx and hasattr(ctx, "estimate_tokens"):
            self._session.total_input_tokens += ctx.estimate_tokens(user_input)
            self._session.total_output_tokens += ctx.estimate_tokens(assistant_output)
        else:
            # Fallback: naive estimation (CJK=2, ASCII=0.25)
            import re
            def _estimate(text):
                cjk = len(re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', text))
                ascii_chars = len(text) - cjk
                return max(1, int(cjk * 2 + ascii_chars * 0.25))
            self._session.total_input_tokens += _estimate(user_input)
            self._session.total_output_tokens += _estimate(assistant_output)

    def _show_banner(self) -> None:
        if not self._console:
            return
        self._show_fullscreen()

    def _show_help(self) -> None:
        content = "# 📋 可用命令\n\n" + "\n".join(
            f"- **`{cmd}`** — {desc}" for cmd, desc in self.SLASH_COMMANDS.items()
        )
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    def _show_status(self) -> None:
        elapsed = int(time.time() - self._session.start_time)
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        time_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

        status_lines = [
            f"**模型:** `{self._session.model_name}`",
            f"**工作目录:** `{self._session.working_dir}`",
            f"**权限模式:** `{self._session.permission_mode}`",
            f"**语音:** {'开' if self._session.voice_enabled else '关'}",
            f"**会话时长:** {time_str}",
            f"**消息数:** {self._session.message_count}",
            f"**对话轮次:** {self._session.turn_count}",
            f"**输入Token:** {self._session.total_input_tokens:,}",
            f"**输出Token:** {self._session.total_output_tokens:,}",
        ]
        content = "# 📊 会话状态\n\n" + "\n".join(f"- {line}" for line in status_lines)
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    def _show_spec(self) -> None:
        elapsed = int(time.time() - self._session.start_time)
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        time_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
        voice = "开" if self._session.voice_enabled else "关"
        model = self._session.model_name or "(未设置)"
        workdir = self._session.working_dir or os.getcwd()

        content = (
            "# ⚙️ HakusAI Spec\n\n"
            f"- **HakusAI 版本**: `v2.0`\n"
            f"- **Model**: `{model}`\n"
            f"- **Working dir**: `{workdir}`\n"
            f"- **Permission mode**: `{self._session.permission_mode}`\n"
            f"- **Voice**: {voice}\n"
            f"- **Session uptime**: {time_str}\n"
            f"- **Messages**: {self._session.message_count}\n"
            f"- **Turns**: {self._session.turn_count}\n"
            f"- **Input tokens**: {self._session.total_input_tokens:,}\n"
            f"- **Output tokens**: {self._session.total_output_tokens:,}\n"
        )
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    def _show_cost(self) -> None:
        elapsed = int(time.time() - self._session.start_time)
        lines = [
            "# 💰 Token 用量",
            "",
            f"| 指标 | 值 |",
            f"|---|---|",
            f"| 消息数 | {self._session.message_count} |",
            f"| 输入Token | {self._session.total_input_tokens:,} |",
            f"| 输出Token | {self._session.total_output_tokens:,} |",
            f"| 会话时长 | {elapsed}s |",
        ]
        content = "\n".join(lines)
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    async def _run_doctor(self) -> None:
        """系统健康检查 — 诊断配置、依赖、模型连接等 (inspired by Claude Code /doctor)."""
        checks = []
        warnings = []
        errors = []

        # 1. Python version
        import sys
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info < (3, 10):
            warnings.append(f"Python 版本 {py_ver} 较低，建议使用 Python 3.10+")
        checks.append(f"Python: `{py_ver}`")

        # 2. 依赖检查
        missing_deps = []
        optional_deps = []
        required = ["rich", "prompt_toolkit", "pyyaml", "httpx"]
        for dep in required:
            try:
                __import__(dep.replace("-", "_"))
            except ImportError:
                missing_deps.append(dep)
        optional = ["tiktoken", "edge_tts", "websockets"]
        for dep in optional:
            try:
                __import__(dep.replace("-", "_"))
                optional_deps.append(dep)
            except ImportError:
                pass
        if missing_deps:
            errors.append(f"缺少必要依赖: {', '.join(missing_deps)}")
        checks.append(f"核心依赖: {'✓ 全部安装' if not missing_deps else '✗ 缺少 ' + ', '.join(missing_deps)}")
        checks.append(f"可选依赖: {', '.join(optional_deps) if optional_deps else '无'}")

        # 3. 环境变量
        env_vars = ["DEEPSEEK_API_KEY", "QWEN_API_KEY", "GEMINI_API_KEY", "GLM_API_KEY"]
        configured = []
        for ev in env_vars:
            if os.environ.get(ev):
                configured.append(ev.replace("_API_KEY", "").lower())
        checks.append(f"已配置模型 API: {', '.join(configured) if configured else '⚠ 未检测到 API Key'}")
        if not configured:
            warnings.append("未检测到任何 API Key，请确保在 .env 或环境变量中配置")

        # 4. 模型连接测试 (轻量级 — 检查 agent 的 model 是否可用)
        model_name = self._session.model_name or "(未设置)"
        checks.append(f"当前模型: `{model_name}`")
        if self._agent:
            try:
                model = getattr(self._agent, "_model", None)
                if model and hasattr(model, "model_type"):
                    checks.append(f"模型实例: ✓ 已初始化 (`{model.model_type}`)")
                else:
                    warnings.append("模型实例未初始化")
            except Exception as e:
                errors.append(f"模型检查失败: {e}")

        # 5. 上下文状态
        ctx = getattr(self._agent, "_context", None)
        if ctx:
            ctx_stats = ctx.get_stats()
            checks.append(f"上下文: {ctx_stats['total_tokens']:,} / {ctx_stats['budget']:,} tokens ({int(ctx_stats['total_tokens']*100/max(1,ctx_stats['budget']))}%)")
            checks.append(f"对话历史: {ctx_stats['messages_length']} 条消息")
            if ctx_stats['compression_count'] > 0:
                checks.append(f"已压缩: {ctx_stats['compression_count']} 次")
        else:
            warnings.append("上下文管理器未初始化")

        # 6. 工具注册
        if hasattr(self._agent, '_tool_registry'):
            tools = self._agent._tool_registry.list_tools()
            checks.append(f"已注册工具: {len(tools)} 个")
        else:
            checks.append("工具注册表: 未初始化")

        # 7. 工作目录 & Git
        workdir = self._session.working_dir or os.getcwd()
        checks.append(f"工作目录: `{workdir}`")
        try:
            import subprocess
            result = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                    capture_output=True, text=True, timeout=5, cwd=workdir)
            if result.returncode == 0:
                repo = result.stdout.strip()
                branch_result = subprocess.run(["git", "branch", "--show-current"],
                                               capture_output=True, text=True, timeout=5, cwd=workdir)
                branch = branch_result.stdout.strip() or "(detached)"
                checks.append(f"Git: ✓ `{repo}` (分支: `{branch}`)")
            else:
                checks.append("Git: 不在 Git 仓库中")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            checks.append("Git: 未安装或不可用")

        # 8. 内存 & 长时记忆
        if hasattr(self._agent, '_project_memory') and self._agent._project_memory:
            checks.append("项目记忆: ✓ 已启用")
        else:
            checks.append("项目记忆: 未启用")

        if hasattr(self._agent, '_memory_manager') and self._agent._memory_manager:
            checks.append("长时记忆: ✓ 已启用")
        else:
            checks.append("长时记忆: 未启用")

        # 9. TUI 状态
        checks.append(f"Rich: {'✓' if _HAS_RICH else '✗'}")
        checks.append(f"prompt_toolkit: {'✓' if _HAS_PROMPT else '✗'}")
        checks.append(f"会话时长: {int(time.time() - self._session.start_time)}s")
        checks.append(f"消息数: {self._session.message_count}")

        # 构建输出
        lines = [
            "# 🏥 HakusAI 健康检查",
            "",
            "## ✓ 系统状态",
        ]
        for c in checks:
            lines.append(f"- {c}")

        if warnings:
            lines.append("\n## ⚠ 警告")
            for w in warnings:
                lines.append(f"- {w}")

        if errors:
            lines.append("\n## ✗ 错误")
            for e in errors:
                lines.append(f"- {e}")

        if not warnings and not errors:
            lines.append("\n> 🟢 **一切正常!** 没有检测到问题。")
        elif not errors:
            lines.append("\n> 🟡 **基本正常** — 有一些警告可以关注。")
        else:
            lines.append("\n> 🔴 **存在问题** — 请检查上面的错误信息。")

        content = "\n".join(lines)
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    def _show_recap(self) -> None:
        """Summarize the current session — what's been done and what's pending.

        Inspired by Claude Code's session recap pattern.
        Shows: conversation summary, tool usage stats, todo status, and key decisions.
        """
        elapsed = int(time.time() - self._session.start_time)
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        time_str = f"{h}h {m}m" if h else f"{m}m {s}s"

        # Count messages by type
        user_msgs = [m for m in self._session.messages if m.role == "user"]
        assistant_msgs = [m for m in self._session.messages if m.role == "assistant"]
        tool_msgs = [m for m in self._session.messages if m.role == "tool"]
        error_msgs = [m for m in self._session.messages if m.is_error]

        # Tool usage summary
        tool_calls_count = 0
        total_tool_time = 0.0
        for m in self._session.messages:
            if hasattr(m, 'tool_calls') and m.tool_calls:
                tool_calls_count += len(m.tool_calls)
                for tc in m.tool_calls:
                    if hasattr(tc, 'execution_time') and tc.execution_time:
                        total_tool_time += tc.execution_time

        # Todo status
        todo_lines = []
        if self._session.todos:
            for t in self._session.todos:
                status_icon = {"completed": "✅", "in_progress": "🔄", "pending": "⏳"}.get(
                    t.get("status", "pending"), "⏳")
                todo_lines.append(f"  {status_icon} {t.get('content', '?')}")

        lines = [
            "# 📝 会话回顾",
            "",
            f"**会话时长:** {time_str}",
            f"**消息总数:** {self._session.message_count}",
            f"**对话轮次:** {self._session.turn_count}",
            f"**用户消息:** {len(user_msgs)}",
            f"**AI 回复:** {len(assistant_msgs)}",
            f"**工具调用:** {tool_calls_count} 次 ({total_tool_time:.1f}s 总耗时)",
            f"**错误数:** {len(error_msgs)}",
            "",
            f"**Token 用量:**",
            f"- 输入: {self._session.total_input_tokens:,}",
            f"- 输出: {self._session.total_output_tokens:,}",
            f"- 总计: {self._session.total_input_tokens + self._session.total_output_tokens:,}",
        ]

        if todo_lines:
            lines.append("\n**待办事项:**")
            lines.extend(todo_lines)
            pending = sum(1 for t in self._session.todos if t.get("status") != "completed")
            lines.append(f"\n*{pending} 项待完成*")

        # Show last few user queries as context
        if len(user_msgs) > 1:
            lines.append("\n**最近对话:**")
            recent = user_msgs[-3:]
            for i, msg in enumerate(recent):
                preview = msg.content[:80] + ("..." if len(msg.content) > 80 else "")
                lines.append(f"{i+1}. {preview}")

        content = "\n".join(lines)
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    def _show_context_window(self) -> None:
        """Claude Code-style /context — show context window usage breakdown.

        Helps the user decide when to /compact. Shows:
          - Total used / budget
          - Per-section breakdown (system prompt, conversation, tool results)
          - Visual bar
          - Recommendation
        """
        ctx = self._agent._context
        budget = ctx.budget
        used = ctx._total_estimated_tokens()
        pct = min(100, int(used * 100 / max(1, budget)))

        # Per-section estimate
        sys_tokens = ctx.estimate_tokens(ctx._assemble_system_prompt())
        conv_tokens = sum(
            ctx.estimate_tokens(m.get("content") or "")
            for m in ctx._messages
        )

        bar_full = 24
        filled = max(0, min(bar_full, int(pct / 100 * bar_full)))
        if pct >= 75:
            glyph, color = "█", "#f38ba8"
        elif pct >= 50:
            glyph, color = "▓", "#f9e2af"
        else:
            glyph, color = "░", "#a6e3a1"
        bar = glyph * filled + "·" * (bar_full - filled)

        if pct >= 85:
            advice = "⚠ 接近上限 — 建议 `/compact` 压缩或 `/clear` 重置"
        elif pct >= 60:
            advice = "🟡 使用较多 — 适当 `/compact` 可腾出空间"
        else:
            advice = "🟢 健康 — 上下文充足"

        lines = [
            "# 📊 上下文窗口使用",
            "",
            f"`{bar}` **{pct}%**",
            "",
            f"| 项目 | Tokens |",
            f"|---|---|",
            f"| 已使用 | **{used:,}** / {budget:,} |",
            f"| 系统提示 | {sys_tokens:,} |",
            f"| 对话历史 | {conv_tokens:,} |",
            f"| 工具结果 | {tool_tokens:,} |",
            f"| 模型最大 | {ctx.max_tokens:,} |",
            f"| 预留输出 | {ctx.reserved_output_tokens:,} |",
            "",
            f"**{advice}**",
        ]
        content = "\n".join(lines)
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    def _show_checkpoints(self) -> None:
        checkpoints = self._agent.get_checkpoints()
        if not checkpoints:
            content = "*暂无检查点*"
            self._session.messages.append(Message(role="tool", content=content))
            self._print_tool_message(content)
            return
        lines = ["# 📌 检查点", "", "| ID | 时间 | 触发 | 历史长度 |", "|---|---|---|---|"]
        for cp in checkpoints[:20]:
            lines.append(
                f"| `{cp.get('id','')[:12]}` | {cp.get('created_at','')} "
                f"| {cp.get('trigger','')} | {cp.get('history_length',0)} |"
            )
        content = "\n".join(lines)
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    def _show_tasks(self) -> None:
        sub_agents = self._agent._sub_agents
        if not sub_agents:
            content = "*暂无后台任务*"
            self._session.messages.append(Message(role="tool", content=content))
            self._print_tool_message(content)
            return
        lines = ["# 📋 后台任务", ""]
        for i, sa in enumerate(sub_agents, 1):
            status = "✓ 完成" if sa.completed else "● 运行中"
            result = (sa.result or "")[:60] if sa.completed else "..."
            lines.append(f"**#{i}** [{status}] {sa._task[:80]}")
            if result and result != "...":
                lines.append(f"  → {result}")
        content = "\n".join(lines)
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    def _init_project(self) -> None:
        from .memory import create_project_memory
        workdir = self._session.working_dir or os.getcwd()
        md_path = os.path.join(workdir, ".hakus.md")
        if os.path.exists(md_path):
            content = "`.hakus.md` 已存在"
            self._session.messages.append(Message(role="tool", content=content))
            self._print_tool_message(content)
            return
        try:
            create_project_memory(workdir)
            success = f"✓ 已创建 `.hakus.md` 在 `{workdir}`"
            self._session.messages.append(Message(role="tool", content=success))
            self._print_tool_message(success)
        except Exception as e:
            err = f"创建 .hakus.md 失败: {e}"
            self._session.messages.append(Message(role="error", content=err, is_error=True))
            self._print_tool_message(err, is_error=True)

    def _export_session(self, filepath: Optional[str] = None) -> None:
        if not filepath:
            filepath = os.path.join(HISTORY_DIR, f"session_{int(time.time())}.md")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# HakusAI 对话记录\n\n")
                f.write(f"**模型:** {self._session.model_name}\n")
                f.write(f"**时间:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("---\n\n")
                for msg in self._session.messages:
                    role_label = {"user": "▶ 用户", "assistant": "🤖 HakusAI",
                                  "tool": "⚙ 系统", "error": "✗ 错误"}.get(msg.role, msg.role)
                    f.write(f"### {role_label}\n\n{msg.content}\n\n---\n\n")
            success = f"✓ 对话已导出到 `{filepath}`"
            self._session.messages.append(Message(role="tool", content=success))
            self._print_tool_message(success)
        except Exception as e:
            err = f"导出失败: {e}"
            self._session.messages.append(Message(role="error", content=err, is_error=True))
            self._print_tool_message(err, is_error=True)

    async def _handle_slash_command(self, user_input: str) -> bool:
        parts = user_input.strip().split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "/help":
            self._show_help()
        elif cmd == "/model":
            if len(parts) < 2:
                content = (
                    f"当前模型: **{self._session.model_name}**\n"
                    f"可用: deepseek, qwen, gemini, glm, mimo"
                )
                self._session.messages.append(Message(role="tool", content=content))
                self._print_tool_message(content)
            else:
                new_model = parts[1]
                try:
                    old = self._agent._model_type
                    self._agent._model_type = new_model
                    self._agent._init_model()
                    self._session.model_name = new_model
                    content = f"✓ 已切换到模型: **{new_model}**"
                    self._session.messages.append(Message(role="tool", content=content))
                    self._print_tool_message(content)
                except Exception as e:
                    self._agent._model_type = old
                    err = f"切换失败: {e}"
                    self._session.messages.append(Message(role="error", content=err, is_error=True))
                    self._print_tool_message(err, is_error=True)
        elif cmd == "/permission":
            if len(parts) >= 2:
                from .permission import PermissionMode
                mode_str = parts[1].lower()
                try:
                    mode = PermissionMode(mode_str)
                    self._agent.set_permission_mode(mode)
                    self._session.permission_mode = mode_str
                    content = f"✓ 权限模式: **{mode_str}**"
                    self._session.messages.append(Message(role="tool", content=content))
                    self._print_tool_message(content)
                except ValueError:
                    err = f"无效模式: {mode_str}。可用: auto, ask, bypass"
                    self._session.messages.append(Message(role="error", content=err, is_error=True))
                    self._print_tool_message(err, is_error=True)
            else:
                content = (
                    f"当前权限模式: **{self._session.permission_mode}**\n"
                    f"可用: auto, ask, bypass"
                )
                self._session.messages.append(Message(role="tool", content=content))
                self._print_tool_message(content)
        elif cmd == "/clear":
            self._agent.reset()
            self._session.messages.clear()
            self._session.message_count = 0
            self._session.turn_count = 0
            content = "✓ 对话已清除"
            if self._console:
                self._console.print(f"\n[dim]{content}[/dim]")
            else:
                print(f"\n{content}")
            self._session.messages.append(Message(role="tool", content=content))
        elif cmd == "/compact":
            from .context import CompressionLevel
            level = await self._agent._context.force_compress(self._agent._model)
            content = f"✓ 上下文已压缩: **{level.name}**"
            self._session.messages.append(Message(role="tool", content=content))
            self._print_tool_message(content)
        elif cmd == "/cost":
            self._show_cost()
        elif cmd == "/context":
            self._show_context_window()
        elif cmd == "/doctor":
            await self._run_doctor()
        elif cmd == "/recap":
            self._show_recap()
        elif cmd == "/verify":
            # Claude Code style: ask the model to self-verify its last work.
            # Useful for catching hallucinations or mistakes before they
            # propagate.
            await self._process_user_input(
                "请回顾本次会话中你最近完成的工作,然后:\n"
                "1. 检查是否有逻辑错误、遗漏的需求、或者潜在的 bug\n"
                "2. 验证你引用的文件路径/函数名是否真实存在\n"
                "3. 给出 PASS / FAIL 结论和具体的改进建议\n"
                "请简洁回答 (不超过 200 字)。"
            )
        elif cmd == "/btw":
            # "by the way" — append a side-note to the session without
            # triggering the model. Useful for adding context the model
            # should remember but doesn't need to respond to right now.
            if len(parts) < 2:
                err = "用法: /btw <note>  (例如: /btw 用户的项目用 Python 3.11)"
                self._session.messages.append(Message(role="error", content=err, is_error=True))
                self._print_tool_message(err, is_error=True)
            else:
                note_text = " ".join(parts[1:])
                btw_msg = f"[旁注] {note_text}"
                self._session.messages.append(
                    Message(role="user", content=btw_msg)
                )
                if self._console:
                    self._console.print(
                        f"\n[dim]✓ 已记录旁注: {note_text[:80]}{'...' if len(note_text) > 80 else ''}[/dim]"
                    )
        elif cmd == "/checkpoint":
            self._show_checkpoints()
        elif cmd == "/rollback":
            if len(parts) < 2:
                err = "用法: /rollback <checkpoint_id>"
                self._session.messages.append(Message(role="error", content=err, is_error=True))
                self._print_tool_message(err, is_error=True)
            elif self._agent.rollback(parts[1]):
                content = f"✓ 已回退到: `{parts[1]}`"
                self._session.messages.append(Message(role="tool", content=content))
                self._print_tool_message(content)
            else:
                err = f"检查点未找到: `{parts[1]}`"
                self._session.messages.append(Message(role="error", content=err, is_error=True))
                self._print_tool_message(err, is_error=True)
        elif cmd == "/task":
            if len(parts) >= 2 and parts[1] == "start":
                desc = parts[2] if len(parts) >= 3 else "未命名任务"
                tool = self._agent._tool_registry.get("task_manage")
                if tool:
                    result = await tool.execute(action="start", description=desc)
                    content = str(result)
                    self._session.messages.append(Message(role="tool", content=content))
                    self._print_tool_message(content)
                else:
                    err = "任务管理工具不可用"
                    self._session.messages.append(Message(role="error", content=err, is_error=True))
                    self._print_tool_message(err, is_error=True)
            else:
                self._show_tasks()
        elif cmd == "/voice":
            self._session.voice_enabled = not self._session.voice_enabled
            state = "开" if self._session.voice_enabled else "关"
            content = f"✓ 语音模式: **{state}**"
            self._session.messages.append(Message(role="tool", content=content))
            self._print_tool_message(content)
        elif cmd == "/status":
            self._show_status()
        elif cmd == "/init":
            self._init_project()
        elif cmd == "/exit":
            self._running = False
            if self._console:
                self._console.print(f"\n[dim]👋 再见！[/dim]")
            else:
                print("\n再见！👋")
            return True
        elif cmd == "/memory":
            self._show_memory()
        elif cmd == "/plan":
            if len(parts) >= 2 and parts[1] == "exit":
                result = self._agent._plan_manager.exit_plan_mode() if hasattr(self._agent, '_plan_manager') else "Plan 模式未启用"
                self._print_tool_message(result)
            else:
                result = self._agent._plan_manager.enter_plan_mode() if hasattr(self._agent, '_plan_manager') else "Plan 模式未启用"
                self._print_tool_message(result)
        elif cmd == "/approve":
            result = self._agent._plan_manager.approve() if hasattr(self._agent, '_plan_manager') else "无计划可批准"
            self._print_tool_message(result)
        elif cmd == "/reject":
            reason = parts[1] if len(parts) >= 2 else ""
            result = self._agent._plan_manager.reject(reason) if hasattr(self._agent, '_plan_manager') else "无计划可拒绝"
            self._print_tool_message(result)
        elif cmd == "/todos":
            from .dev_tools import TodoWriteTool, TodoState
            state = TodoWriteTool._state or TodoState()
            result = state.to_markdown()
            self._print_tool_message(result if result else "*暂无待办*")
        elif cmd == "/tree":
            path = parts[1] if len(parts) >= 2 else "."
            result = self._run_tool("Tree", path=path, max_depth=3)
            self._print_tool_message(result)
        elif cmd == "/tools":
            self._show_tools()
        elif cmd == "/git":
            result = self._run_tool("GitStatus", cwd=self._session.working_dir)
            self._print_tool_message(result)
        elif cmd == "/diff":
            result = self._run_tool("GitDiff", cwd=self._session.working_dir)
            self._print_tool_message(result)
        elif cmd == "/spec":
            self._show_spec()
        elif cmd == "/db":
            await self._handle_db(parts[1:])
        else:
            err = f"未知命令: `{cmd}`。输入 `/help` 查看可用命令。"
            self._session.messages.append(Message(role="error", content=err, is_error=True))
            self._print_tool_message(err, is_error=True)
        return True

    def _run_tool(self, name: str, **kwargs) -> str:
        """同步执行单个工具, 用于 slash 命令 (TUI 处于运行中的事件循环, 使用独立线程跑新循环)"""
        tool = self._agent._tool_registry.get(name) if hasattr(self._agent, '_tool_registry') else None
        if not tool:
            return f"工具 '{name}' 未注册"
        try:
            return self._run_async_in_fresh_loop(tool.execute, **kwargs)
        except Exception as e:
            return f"执行错误: {e}"

    def _run_async_in_fresh_loop(self, coro_factory, *args, **kwargs):
        """
        安全地在一个**新的独立事件循环**中运行异步协程。

        设计原因：TUI 本身运行在一个 asyncio 事件循环中 (run_stream)。
        在该循环内直接 asyncio.run / loop.run_until_complete 会触发
        "Cannot run the event loop while another loop is running"。
        通过检测当前线程是否有正在运行的事件循环：
          - 若有：在子线程里启动新事件循环并跑协程；
          - 若无：直接在当前线程用 asyncio.run 跑。
        """
        import concurrent.futures
        try:
            asyncio.get_running_loop()
            has_running = True
        except RuntimeError:
            has_running = False

        if has_running:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro_factory(*args, **kwargs))
                return future.result()
        return asyncio.run(coro_factory(*args, **kwargs))

    def _show_memory(self) -> None:
        if not hasattr(self._agent, '_project_memory'):
            content = "*项目记忆未启用*"
            self._session.messages.append(Message(role="tool", content=content))
            self._print_tool_message(content)
            return
        loaded = self._agent._project_memory.list_loaded()
        if not loaded:
            content = (
                "*未加载项目记忆*\n\n"
                "在项目根目录创建 `.hakus.md` 或 `CLAUDE.md` 来添加项目上下文。\n"
                "使用 `/init` 自动生成模板。"
            )
            self._session.messages.append(Message(role="tool", content=content))
            self._print_tool_message(content)
            return
        lines = ["# 📚 项目记忆", ""]
        for item in loaded:
            lines.append(f"## [{item['scope']}] `{item['path']}`")
            lines.append("")
            preview = item["content"][:500]
            if len(item["content"]) > 500:
                preview += f"\n\n[... 总长度 {len(item['content'])} 字符]"
            lines.append(preview)
            lines.append("")
        content = chr(10).join(lines)
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    def _show_tools(self) -> None:
        if not hasattr(self._agent, '_tool_registry'):
            return
        registry = self._agent._tool_registry
        all_tools = registry.list_tools()
        categories = {}
        for name in all_tools:
            tool = registry.get(name)
            if tool:
                cat = tool.get_metadata().category
                categories.setdefault(cat, []).append(name)
        lines = ["# 🔧 可用工具", ""]
        for cat in sorted(categories.keys()):
            lines.append(f"## {cat}")
            for t in sorted(categories[cat]):
                lines.append(f"- `{t}`")
            lines.append("")
        lines.append(f"**总计 {len(all_tools)} 个工具**")
        content = chr(10).join(lines)
        self._session.messages.append(Message(role="tool", content=content))
        self._print_tool_message(content)

    def _review_file(self, file_path: Optional[str]) -> None:
        # /review 命令已移除, 但内部 review 能力仍可被 agent 自动调用
        if not file_path:
            return
        content = self._run_tool("Read", file_path=file_path)
        if not content or content.startswith("错误:"):
            return
        # 调用 agent 的 review 能力
        prompt = f"请对以下代码进行 code review:\n\n```\n{content[:4000]}\n```\n\n关注: bug/安全/性能/风格/错误处理/测试覆盖"
        try:
            response = self._run_async_in_fresh_loop(self._agent.process, prompt)
            if response.content:
                self._print_assistant_message(response.content)
        except Exception:
            pass

    def _export_session(self, filepath: Optional[str]) -> None:
        # /export 命令已移除, 但内部 export 能力保留
        import json
        from datetime import datetime
        from .session_store import save_session
        data = []
        for m in self._session.messages:
            data.append({
                "role": m.role.value if hasattr(m.role, "value") else str(m.role),
                "content": m.content,
                "timestamp": getattr(m, "timestamp", None),
            })
        if not filepath:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            filepath = f"hakus-session-{ts}.json"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._print_tool_message(f"✓ 已导出 {len(data)} 条消息到 `{filepath}`")
        except Exception as e:
            self._print_tool_message(f"导出失败: {e}", is_error=True)

    def _handle_orchestrate(self, args: List[str]) -> None:
        # /orchestrate 命令已移除 — 多智能体协同由 agent 在内部自动决定.
        # 如需手动触发, 请直接告诉 agent 你的需求, agent 会自动调度 sub-agents.
        self._print_tool_message(
            "💡 `/orchestrate` 命令已移除.\n"
            "直接用自然语言告诉 HakusAI 你的需求即可, 例如:\n"
            "  > 开发一个贪吃蛇游戏, 要求带 AI 测试和修复\n\n"
            "Agent 会自动判断是否需要多智能体协同.",
        )

    def _permission_confirm(self, action: str, detail: str) -> bool:
        from .permission_ui import sync_confirm_yes_no

        msg = (
            f"# ⚠ 权限确认\n\n"
            f"**操作:** {action}\n\n"
            f"**详情:** {detail}\n\n"
            f"*输入 y 允许，其他键拒绝*"
        )
        self._session.messages.append(Message(role="tool", content=msg))
        self._print_tool_message(msg)

        return sync_confirm_yes_no("Allow", action, detail)

    def _get_input(self) -> str:
        if self._streaming:
            return ""
        try:
            if self._prompt_session:
                return self._prompt_session.prompt(
                    HTML('<ansicyan>(HakusAI)</ansicyan> <b>></b> '),
                )
            return input("HakusAI > ")
        except (EOFError, KeyboardInterrupt):
            return "/exit"
        except RuntimeError as e:
            if "asyncio" in str(e) or "event loop" in str(e):
                return ""
            raise

    async def _get_input_async(self) -> str:
        if self._streaming:
            return ""
        try:
            if self._prompt_session:
                return await self._prompt_session.prompt_async(
                    HTML('<ansicyan>(HakusAI)</ansicyan> <b>></b> '),
                )
            return input("HakusAI > ")
        except (EOFError, KeyboardInterrupt):
            return "/exit"

    def _extract_code_blocks(self, text: str) -> List[Tuple[str, str]]:
        pattern = r"```(\w*)\n(.*?)```"
        return re.findall(pattern, text, re.DOTALL)

    def _display_tool_results(self, tool_calls: List[Any]) -> None:
        """Claude Code-style tool result display.

        - Each tool call shows as a brief one-liner (status + duration)
        - Smart per-tool summaries (file reads show file size/lines, searches show match count)
        - Content-type detection (code, JSON, text) for better preview formatting
        - For results exceeding COLLAPSE_THRESHOLD, the full content is
          stored in session history (for model context) but only a
          truncated preview is printed to the terminal.
        - File paths are hyperlinked when possible
        """
        COLLAPSE_THRESHOLD = 800  # chars — beyond this, collapse in display
        PREVIEW_LINES = 12
        for tc in tool_calls:
            if tc.tool_name == "TodoWrite" and isinstance(tc.arguments, dict):
                todos = tc.arguments.get("todos", [])
                if todos:
                    self._session.todos = todos

            # Smart per-tool summary
            summary = self._build_tool_summary(tc)

            # Full tool content kept in session for model context
            full_tool_content = (
                f"**工具调用:** `{tc.tool_name}`\n\n"
                f"```json\n{str(tc.arguments)[:300]}\n```\n\n"
                f"{summary}\n\n"
                f"{'✓ 成功' if tc.success else '✗ 失败'}"
                f"{' (' + f'{tc.execution_time:.1f}s' + ')' if tc.execution_time else ''}"
                f"\n\n```\n{tc.result[:500]}\n```"
            )
            self._session.messages.append(
                Message(role="tool", content=full_tool_content)
            )

            # Display: short summary by default, expanded only for short results
            result_str = str(tc.result) if tc.result else ""
            status_icon = "✓" if tc.success else "✗"
            duration = f"  {tc.execution_time:.1f}s" if tc.execution_time else ""
            header = f"{status_icon} {tc.tool_name}{duration}"

            if len(result_str) <= COLLAPSE_THRESHOLD:
                # Short — show full result in a compact panel
                display = (
                    f"**{header}**\n\n"
                    f"{summary}\n\n"
                    f"```\n{result_str}\n```"
                )
            else:
                # Long — show first N lines + collapse notice (Claude Code style)
                lines = result_str.splitlines()
                preview = "\n".join(lines[:PREVIEW_LINES])
                omitted = len(lines) - PREVIEW_LINES
                total_chars = len(result_str)
                # Detect content type for better label
                content_type = self._detect_content_type(result_str)
                type_label = f" · {content_type}" if content_type else ""
                display = (
                    f"**{header}**  ·  {total_chars:,} chars  ·  {len(lines)} lines{type_label}\n\n"
                    f"{summary}\n\n"
                    f"```\n{preview}\n```\n"
                    f"*[已折叠 {omitted} 行 · 内容已存入会话供模型参考]*"
                )
            self._print_tool_message(display, is_error=not tc.success)

    def _detect_content_type(self, text: str) -> str:
        """Detect content type for better display labeling."""
        stripped = text.strip()
        if not stripped:
            return ""
        # JSON detection
        if (stripped.startswith("{") or stripped.startswith("[")) and stripped.endswith(("}", "]")):
            try:
                import json
                json.loads(stripped)
                return "JSON"
            except (json.JSONDecodeError, ValueError):
                pass
        # Code detection (common keywords)
        code_indicators = ["def ", "class ", "import ", "function ", "const ", "let ", "var ", "pub ", "fn "]
        if any(ind in stripped[:200] for ind in code_indicators):
            return "Code"
        # Table/structured data
        if "|" in stripped and "---" in stripped:
            return "Table"
        return ""

    def _build_tool_summary(self, tc: Any) -> str:
        """Build a smart one-line summary for a tool call result.

        Inspired by Claude Code's per-tool summaries that show
        meaningful info instead of raw output.
        """
        args = tc.arguments if isinstance(tc.arguments, dict) else {}
        result_str = str(tc.result) if tc.result else ""
        tool = tc.tool_name

        # File read tools
        if tool in ("Read", "read_file", "file_read"):
            file_path = args.get("file_path", args.get("path", "unknown"))
            lines = result_str.count("\n") + 1 if result_str else 0
            size = len(result_str)
            return f"📄 `{file_path}` · {lines} 行 · {size:,} 字符"

        # File write tools
        if tool in ("Write", "write_file", "file_write"):
            file_path = args.get("file_path", args.get("path", "unknown"))
            size = len(result_str) if result_str else len(str(args.get("content", "")))
            return f"✏️ `{file_path}` · 写入 {size:,} 字符"

        # Search tools
        if tool in ("Search", "grep", "search"):
            query = args.get("pattern", args.get("query", ""))
            match_count = result_str.count("\n") if result_str else 0
            return f"🔍 搜索 `{query}` · {match_count} 个匹配"

        # Shell/command tools
        if tool in ("Shell", "run_command", "Exec", "bash"):
            cmd = args.get("command", args.get("cmd", ""))
            exit_code = 0
            if result_str:
                # Try to extract exit code from result
                code_match = re.search(r'exit[ _]?code[:\s]*(\d+)', result_str, re.IGNORECASE)
                if code_match:
                    exit_code = int(code_match.group(1))
            status = f"exit={exit_code}" if exit_code != 0 else "成功"
            return f"⚡ `{cmd[:50]}` · {status}"

        # Git tools
        if tool in ("GitStatus", "GitDiff", "git"):
            return "📊 Git 状态"

        # Tree/Directory tools
        if tool in ("Tree", "ls", "list_dir"):
            path = args.get("path", ".")
            dir_count = result_str.count("├") + result_str.count("└") if result_str else 0
            return f"📁 `{path}` · ~{dir_count} 个条目"

        # Default — no special summary
        return ""

    async def _process_stream(self, user_input: str) -> None:
        self._session.message_count += 1
        self._session.turn_count += 1
        self._session.messages.append(Message(role="user", content=user_input))

        self._render_full()
        self._streaming = True
        self._cancelled = False
        full_response = ""

        # 切换活动状态: thinking
        TRACKER.set(phase="thinking", detail="")

        try:
            if _HAS_RICH and self._console:
                # Direct console streaming (avoids Rich Live which is
                # unreliable on Windows consoles — every update gets
                # appended instead of redrawn in place).
                # 1. Stream tokens as raw text (Claude Code-style inline
                #    output — no separate spinner/indicator to confuse
                #    the user)
                # 2. After streaming, print the final result as a
                #    properly rendered Markdown panel

                streamed_any = False
                last_token_flush = time.monotonic()
                FLUSH_INTERVAL = 0.03  # seconds — throttle print to reduce flicker

                async for event in self._agent.run_turn(user_input):
                    if self._cancelled:
                        break
                    if isinstance(event, self._TextDelta):
                        full_response += event.text
                        if not streamed_any:
                            TRACKER.set(phase="streaming", detail="")
                            streamed_any = True
                        # Legacy fallback: in case the model output
                        # somehow still contains the marker (it shouldn't
                        # — the protocol layer strips it).
                        if "[Tool Results]" in full_response:
                            break
                        # Throttled raw token print (no Panel/Markdown overhead
                        # while streaming — final result will be re-rendered
                        # as Markdown after the loop)
                        now = time.monotonic()
                        if now - last_token_flush >= FLUSH_INTERVAL:
                            self._console.print(
                                event.text, end="", highlight=False, soft_wrap=True,
                            )
                            last_token_flush = now
                    elif isinstance(event, self._TurnFailed):
                        # Render error inline
                        self._console.print(
                            f"\n[red]Error [{event.code}]: {event.error}[/red]"
                        )
                    elif isinstance(event, self._CancelledEvent):
                        # Use partial content if available
                        full_response = event.partial_content or full_response
                        break
            else:
                async for event in self._agent.run_turn(user_input):
                    if self._cancelled:
                        break
                    if isinstance(event, self._TextDelta):
                        full_response += event.text
                        print(event.text, end="", flush=True)
                    elif isinstance(event, self._CancelledEvent):
                        break
                print()

            # After streaming completes, print the final result inside
            # a proper Markdown panel. The streamed raw text above is
            # the live output; the panel below is the canonical record.
            if _HAS_RICH and self._console and full_response and "[Tool Results]" not in full_response:
                self._console.print()
                self._console.print(Panel(
                    Markdown(full_response, code_theme="one-dark"),
                    border_style=_COLORS["accent"],
                    box=box.ROUNDED,
                    title="🤖 HakusAI",
                    title_align="left",
                ))

            last_response = getattr(self._agent, "_last_response", None)
            output_text = (last_response.content if last_response else None) or full_response

            if last_response and last_response.tool_calls:
                # 工具调用阶段: 显示每个工具的执行
                for tc in last_response.tool_calls:
                    TRACKER.set(
                        phase="tool_use",
                        detail=tc.tool_name,
                        tool_name=tc.tool_name,
                    )
                    self._display_tool_results([tc])
                if last_response.content:
                    self._session.messages.append(
                        Message(role="assistant", content=last_response.content)
                    )
                    self._print_assistant_message(last_response.content)
            elif full_response and "[Tool Results]" not in full_response:
                self._session.messages.append(Message(role="assistant", content=full_response))
                if not (_HAS_RICH and self._console):
                    self._print_assistant_message(full_response)
            elif self._cancelled:
                self._session.messages.append(Message(role="tool", content="*已中断*"))

            if output_text:
                self._accumulate_tokens(user_input, output_text)

            # Auto-compact suggestion — inspired by Claude Code's context pressure warnings.
            # When context usage exceeds 60%, show a subtle hint to /compact.
            self._maybe_suggest_compact()

            if last_response and last_response.compressed:
                self._session.messages.append(Message(
                    role="tool", content="*上下文已自动压缩*"
                ))

        except Exception as e:
            self._session.messages.append(Message(
                role="error", content=f"流式输出错误: {e}", is_error=True
            ))
            logger.error(f"Stream error: {e}", exc_info=True)
        finally:
            self._streaming = False
            # 恢复 idle
            TRACKER.reset()
            self._render_full()

    def _maybe_suggest_compact(self) -> None:
        """Automatically suggest /compact when context usage is getting high.

        Inspired by Claude Code's context pressure indicator in the status bar.
        Shows a subtle one-line hint when usage exceeds 60%.
        Only shows once per threshold crossing to avoid spam.
        """
        ctx = getattr(self._agent, "_context", None)
        if not ctx or not hasattr(ctx, "budget") or ctx.budget <= 0:
            return
        try:
            used = ctx._total_estimated_tokens()
            pct = int(used * 100 / ctx.budget)
        except Exception:
            return

        # Only suggest at certain thresholds
        if 60 <= pct < 65:
            self._console.print(f"\n[dim]💡 上下文使用 {pct}% — 考虑 `/compact` 压缩上下文[/dim]")
        elif 80 <= pct < 85:
            self._console.print(f"\n[dim]⚠ 上下文使用 {pct}% — 建议尽快 `/compact`[/dim]")
        elif pct >= 85:
            self._console.print(f"\n[dim]🔴 上下文使用 {pct}% — 即将到达上限, 立即 `/compact` 或 `/clear`[/dim]")

    async def _process_user_input(self, user_input: str) -> None:
        """Default input handler: 
        1. 检查是否在 plan 模式等待批准 (支持自然语言: 批准/approve/yes/ok/go 等)
        2. 检查是否在 plan 模式等待拒绝 (支持自然语言: 拒绝/reject/no/cancel 等)
        3. 否则正常流式处理
        """
        # 1. Plan 模式等待批准/拒绝 — 自然语言检测 (Claude Code 风格)
        if self._is_plan_pending_approval():
            decision = self._detect_plan_decision(user_input)
            if decision == "approve":
                result = self._agent._plan_manager.approve()
                self._print_tool_message(result)
                self._session.messages.append(Message(role="tool", content=result))
                # 批准后: 进入执行模式, 触发 agent 实际开始执行
                return
            elif decision == "reject":
                result = self._agent._plan_manager.reject(reason=user_input)
                self._print_tool_message(result)
                self._session.messages.append(Message(role="tool", content=result))
                return

        await self._process_stream(user_input)

    def _is_plan_pending_approval(self) -> bool:
        """是否在 plan 模式等待用户批准/拒绝."""
        pm = getattr(self._agent, "_plan_manager", None)
        if pm is None:
            return False
        if not pm.is_executing():
            return False
        plan = pm.current_plan
        if plan is None:
            return False
        from .plan_mode import PlanStatus
        return plan.status == PlanStatus.PENDING_APPROVAL

    def _detect_plan_decision(self, text: str) -> str:
        """检测用户输入是否是对 plan 的批准/拒绝 (Claude Code 风格)."""
        if text is None:
            return "none"
        t = text.strip().lower()
        # 移除常见标点
        t_clean = t.rstrip("。，.!！?？,.").strip()
        # 批准关键词
        approve_keywords = {
            "y", "yes", "ok", "okay", "go", "proceed", "approve", "approved",
            "确认", "批准", "同意", "好", "好呀", "好的", "可以", "行", "继续", "执行", "开始",
            "go ahead", "do it", "let's do it", "lets do it", "yep", "yeah",
            "sure", "确认执行", "执行吧", "开始吧", "开始执行", "干吧", "go ahead",
        }
        # 拒绝关键词
        reject_keywords = {
            "n", "no", "nope", "cancel", "reject", "rejected", "abort", "stop",
            "不", "不要", "拒绝", "不同意", "算了", "取消", "停", "不行", "别", "算了",
        }
        # 精确匹配
        if t_clean in approve_keywords or t in approve_keywords:
            return "approve"
        if t_clean in reject_keywords or t in reject_keywords:
            return "reject"
        # 前缀匹配: "批准, 谢谢" / "no, thanks" / "好的, 请开始" / "ok 请"
        for kw in approve_keywords:
            if t_clean.startswith(kw) or t.startswith(kw):
                return "approve"
        for kw in reject_keywords:
            if t_clean.startswith(kw) or t.startswith(kw):
                return "reject"
        # 包含匹配 (针对短输入: 整句 <= 12 字, 则子串也匹配)
        if len(t_clean) <= 12:
            for kw in approve_keywords:
                if len(kw) >= 2 and kw in t_clean:
                    return "approve"
            for kw in reject_keywords:
                if len(kw) >= 2 and kw in t_clean:
                    return "reject"
        return "none"

    async def _process_normal(self, user_input: str) -> None:
        self._session.message_count += 1
        self._session.turn_count += 1
        self._session.messages.append(Message(role="user", content=user_input))

        self._print_thinking()

        try:
            response = await self._agent.process(user_input)

            if response.tool_calls:
                for tc in response.tool_calls:
                    tool_content = (
                        f"**工具调用:** `{tc.tool_name}`\n\n"
                        f"```json\n{str(tc.arguments)[:300]}\n```\n\n"
                        f"{'✓ 成功' if tc.success else '✗ 失败'}"
                        f"{' (' + f'{tc.execution_time:.1f}s' + ')' if tc.execution_time else ''}"
                        f"\n\n```\n{tc.result[:500]}\n```"
                    )
                    self._session.messages.append(Message(role="tool", content=tool_content))
                    self._print_tool_message(tool_content, is_error=not tc.success)

            if response.content:
                self._session.messages.append(Message(role="assistant", content=response.content))
                self._print_assistant_message(response.content)

            if response.compressed:
                self._session.messages.append(Message(
                    role="tool", content="*上下文已自动压缩*"
                ))

        except Exception as e:
            err_msg = f"处理错误: {e}"
            self._session.messages.append(Message(
                role="error", content=err_msg, is_error=True
            ))
            self._print_tool_message(err_msg, is_error=True)
            logger.error(f"Process error: {e}", exc_info=True)

    async def _handle_db(self, args: List[str]) -> None:
        """Navicat 风格数据库管理命令."""
        from .db import DB_MANAGER
        from .db_tools import _format_table, _format_describe

        if not args:
            saved = DB_MANAGER.list_configs()
            active = DB_MANAGER.list_active()
            lines = ["# 🗄  数据库管理 (Navicat 风格)\n"]
            if saved:
                lines.append("## 已保存的连接")
                for c in saved:
                    mark = "🟢" if c.name in active else "⚪"
                    target = c.path if c.db_type.value == "sqlite" else f"{c.host}:{c.port or '?'}"
                    lines.append(
                        f"- {mark} **{c.name}** · `{c.db_type.value}` · {target} · db=`{c.database or '-'}`"
                    )
            else:
                lines.append("(无已保存连接 — 使用 `db_connect` 工具可创建)")
            lines.append("\n## 快捷命令")
            lines.append("- `/db connect <name>` — 打开已保存连接")
            lines.append("- `/db tables <name>` — 列出表")
            lines.append("- `/db desc <name> <table>` — 表结构")
            lines.append("- `/db query <name> <sql>` — 查询")
            lines.append("- `/db execute <name> <sql>` — 写操作")
            lines.append("- `/db remove <name>` — 删除连接")
            lines.append("- `/db navicat [name]` — 进入 Navicat REPL 交互模式")
            self._print_tool_message("\n".join(lines))
            return

        sub = args[0].lower()

        if sub == "list":
            saved = DB_MANAGER.list_configs()
            active = DB_MANAGER.list_active()
            lines = ["# 🗄  数据库连接\n"]
            for c in saved:
                mark = "🟢" if c.name in active else "⚪"
                target = c.path if c.db_type.value == "sqlite" else f"{c.host}:{c.port or '?'}"
                lines.append(
                    f"- {mark} **{c.name}** · `{c.db_type.value}` · {target} · db=`{c.database or '-'}`"
                )
            if not saved:
                lines.append("(无)")
            self._print_tool_message("\n".join(lines))
            return

        if sub == "connect":
            if len(args) < 2:
                self._print_tool_message("用法: /db connect <name>", is_error=True)
                return
            name = args[1]
            cfg = DB_MANAGER.get_config(name)
            if not cfg:
                self._print_tool_message(f"未找到连接: {name}", is_error=True)
                return
            ok, msg = DB_MANAGER.connect(cfg)
            self._print_tool_message(f"{'✓' if ok else '✗'} connect `{name}`: {msg}")
            return

        if sub == "remove":
            if len(args) < 2:
                self._print_tool_message("用法: /db remove <name>", is_error=True)
                return
            name = args[1]
            if DB_MANAGER.remove_config(name):
                self._print_tool_message(f"✓ 已删除 `{name}`")
            else:
                self._print_tool_message(f"未找到连接: {name}", is_error=True)
            return

        if sub == "tables":
            if len(args) < 2:
                self._print_tool_message("用法: /db tables <name>", is_error=True)
                return
            name = args[1]
            driver = DB_MANAGER.get_driver(name)
            if not driver:
                self._print_tool_message(f"连接 {name} 未打开", is_error=True)
                return
            try:
                tables = driver.list_tables()
                self._print_tool_message(
                    f"# 📋 {name} 的表/集合 (共 {len(tables)})\n\n" +
                    "\n".join(f"- `{t}`" for t in tables)
                )
            except Exception as e:
                self._print_tool_message(f"错误: {e}", is_error=True)
            return

        if sub == "desc":
            if len(args) < 3:
                self._print_tool_message("用法: /db desc <name> <table>", is_error=True)
                return
            name, table = args[1], " ".join(args[2:])
            driver = DB_MANAGER.get_driver(name)
            if not driver:
                self._print_tool_message(f"连接 {name} 未打开", is_error=True)
                return
            try:
                schema = driver.describe_table(table)
                self._print_tool_message(f"# 📐 `{table}`\n\n{_format_describe(schema)}")
            except Exception as e:
                self._print_tool_message(f"错误: {e}", is_error=True)
            return

        if sub == "query":
            if len(args) < 3:
                self._print_tool_message("用法: /db query <name> <sql>", is_error=True)
                return
            name = args[1]
            sql = " ".join(args[2:])
            driver = DB_MANAGER.get_driver(name)
            if not driver:
                self._print_tool_message(f"连接 {name} 未打开", is_error=True)
                return
            try:
                if "limit" not in sql.lower() and driver.name == "sqlite":
                    sql = sql.rstrip(";") + " LIMIT 100"
                cols, rows = driver.fetch_all(sql)
                self._print_tool_message(f"# 🔍 查询结果\n\n{_format_table(cols, rows)}")
            except Exception as e:
                self._print_tool_message(f"查询错误: {e}", is_error=True)
            return

        if sub == "execute":
            if len(args) < 3:
                self._print_tool_message("用法: /db execute <name> <sql>", is_error=True)
                return
            name = args[1]
            sql = " ".join(args[2:])
            driver = DB_MANAGER.get_driver(name)
            if not driver:
                self._print_tool_message(f"连接 {name} 未打开", is_error=True)
                return
            try:
                result = driver.execute(sql)
                self._print_tool_message(f"✓ 执行成功 · {result}")
            except Exception as e:
                self._print_tool_message(f"执行错误: {e}", is_error=True)
            return

        if sub == "navicat":
            await self._enter_navicat_repl(args[1] if len(args) >= 2 else None)
            return

        self._print_tool_message(
            f"未知子命令: {sub}\n可用: list / connect / tables / desc / query / execute / remove / navicat",
            is_error=True,
        )

    async def _enter_navicat_repl(self, name: Optional[str]) -> None:
        """进入 Navicat REPL 模式 — 短时循环, 处理用户输入直到 /exit."""
        from .db import DB_MANAGER
        from .db_tools import NavicatREPL

        repl = NavicatREPL(self._console)
        if name:
            ok, msg = repl.set_current(name)
            if not ok:
                self._print_tool_message(f"⚠ {msg}, 仍可继续 — 输入 `connect <name>` 激活")
            else:
                self._print_tool_message(f"✓ {msg}")

        self._print_tool_message(
            "# 🗄  Navicat REPL 模式\n\n"
            "输入 `help` 查看命令, `:q` 退出。\n"
        )

        if _HAS_PROMPT:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.formatted_text import HTML
            from prompt_toolkit.history import InMemoryHistory

            session = PromptSession(
                history=InMemoryHistory(),
            )
            while True:
                try:
                    line = await session.prompt_async(
                        HTML(f'<ansimagenta>{repl.prompt}</ansimagenta> <b>&gt;</b> ')
                    )
                except (EOFError, KeyboardInterrupt):
                    self._print_tool_message("\n👋 退出 Navicat")
                    return

                line = line.strip()
                if not line:
                    continue
                try:
                    output, should_exit = repl.run_line(line)
                    if output:
                        self._print_tool_message(output)
                    if should_exit:
                        return
                except Exception as e:
                    self._print_tool_message(f"错误: {e}", is_error=True)
        else:
            while True:
                try:
                    line = input(f"{repl.prompt} > ")
                except (EOFError, KeyboardInterrupt):
                    self._print_tool_message("\n👋 退出 Navicat")
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    output, should_exit = repl.run_line(line)
                    if output:
                        self._print_tool_message(output)
                    if should_exit:
                        return
                except Exception as e:
                    self._print_tool_message(f"错误: {e}", is_error=True)

    async def run_stream(self) -> None:
        self._running = True
        self._show_banner()

        self._session.messages.append(Message(
            role="tool",
            content=(
                f"**HakusAI v2.0 启动**\n\n"
                f"- 模型: `{self._session.model_name}`\n"
                f"- 目录: `{self._session.working_dir}`\n"
                f"- 权限: `{self._session.permission_mode}`\n\n"
                f"输入 `/help` 查看命令列表"
            ),
        ))

        consecutive_errors = 0
        while self._running:
            try:
                user_input = await self._get_input_async()
                user_input = user_input.strip() if user_input else ""

                if not user_input:
                    continue

                consecutive_errors = 0
                self._print_user_message(user_input)

                if user_input.startswith("/"):
                    await self._handle_slash_command(user_input)
                else:
                    await self._process_user_input(user_input)

            except KeyboardInterrupt:
                if self._streaming:
                    self._cancelled = True
                    self._streaming = False
                else:
                    self._running = False
                    if self._console:
                        self._console.print("\n[dim]退出 HakusAI...[/dim]")
                    break

            except (EOFError, SystemExit):
                self._running = False
                if self._console:
                    self._console.print("\n[dim]退出 HakusAI...[/dim]")
                break

            except Exception as e:
                consecutive_errors += 1
                err_msg = str(e)
                if "asyncio" in err_msg or "event loop" in err_msg:
                    if self._console:
                        self._console.print(f"[red]事件循环错误: {err_msg}[/red]")
                    logger.error(f"Event loop error: {e}")
                    self._running = False
                    break
                if consecutive_errors > 3:
                    if self._console:
                        self._console.print(f"[red]连续错误过多，退出[/red]")
                    self._running = False
                    break
                if self._console:
                    self._console.print(f"[red]未预期错误: {e}[/red]")
                logger.error(f"Loop error: {e}", exc_info=True)

        elapsed = int(time.time() - self._session.start_time)
        if self._console:
            self._console.print()
            self._console.print(Panel(
                f"[bold]会话结束[/bold]\n\n"
                f"时长: {elapsed}s  ·  消息: {self._session.message_count}  ·  "
                f"模型: {self._session.model_name}\n"
                f"输入Token: {self._session.total_input_tokens:,}  ·  "
                f"输出Token: {self._session.total_output_tokens:,}",
                border_style=_COLORS["accent"],
                box=box.ROUNDED,
            ))
            self._console.print("👋 Goodbye!\n")
        else:
            print(f"\n会话结束 · {elapsed}s · {self._session.message_count} 条消息\n再见！")

    async def run(self) -> None:
        await self.run_stream()