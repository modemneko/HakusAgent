"""
HakusAI TUI v2 — OpenCode 精确布局 (源码级对齐)

基于 OpenCode packages/tui/src 源码分析:
- Session 页面: 水平分屏, 左侧 flexGrow=1 + 右侧 width=42
- 侧边栏: 宽度 42 字符, paddingTop/Bottom=1, paddingLeft/Right=2
- 宽屏(>120)自动显示侧边栏, 窄屏叠加覆盖
- 消息区: paddingLeft/Right=2, paddingBottom=1, gap=1
- Prompt: flexShrink=0, maxHeight=max(6, H/3)
- 无独立状态栏 — 状态在 Prompt 底部行
- 侧边栏内容: Context / Modified Files / Footer

快捷键对齐 OpenCode:
- Tab: build/plan 切换
- Ctrl+O: 模型选择
- Ctrl+K: 命令面板
- Ctrl+H: 帮助
- Ctrl+S: 会话切换
- Ctrl+T: 主题切换
- Ctrl+F: 文件选择器
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static

from .messages import Message, Part, PartType
from .session import TUISession
from .streaming import StreamingSink
from .widgets.activity import ActivityStrip
from .widgets.message_list import MessageList
from .widgets.notification_bar import NotificationBar
from .widgets.prompt_input import PromptInput
from .widgets.welcome_panel import WelcomePanel
from .commands import SlashCommandRegistry, build_default_registry, CommandContext
from utils.hakus_config import get_config, save_default_model
from utils.logger import get_logger
from utils.turn_debug import is_debug_enabled, init_debug_logger, shutdown_debug_logger

logger = get_logger(__name__)

# OpenCode 侧边栏宽度: 固定 42 字符
SIDEBAR_WIDTH = 42
# OpenCode 宽屏阈值: width > 120 自动显示侧边栏
WIDE_THRESHOLD = 120


# ============================================================
# Sidebar — OpenCode 右侧边栏 (width=42, 源码级精确)
# ============================================================
class Sidebar(Static):
    """右侧边栏 — OpenCode 源码精确对齐: width=42, padding 1 2"""

    DEFAULT_CSS = f"""
    Sidebar {{
        width: {SIDEBAR_WIDTH};
        background: #0a0a0a;
        border-left: solid #1e1e1e;
        padding: 1 2;
        overflow: auto;
        height: 100%;
    }}

    Sidebar .sidebar-header {{
        color: #5c9cf5;
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }}

    Sidebar .sidebar-section {{
        color: #808080;
        text-style: bold;
        height: 1;
        margin-top: 1;
    }}

    Sidebar .sidebar-item {{
        color: #606060;
        height: 1;
        padding-left: 1;
    }}

    Sidebar .sidebar-item.modified {{
        color: #e5c07b;
    }}

    Sidebar .sidebar-footer {{
        color: #606060;
        height: 1;
        margin-top: 1;
        border-top: solid #1e1e1e;
        padding-top: 1;
    }}
    """

    def __init__(self, session: TUISession, agent: Any, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session = session
        self._agent = agent
        self._modified_files: list[dict] = []

    def compose(self) -> ComposeResult:
        # Context section (order=100)
        yield Static("Context", classes="sidebar-section")
        yield Static(f"  {self._session.model_name}", classes="sidebar-item")
        workdir = self._session.working_dir or os.getcwd()
        if len(workdir) > 35:
            workdir = "..." + workdir[-32:]
        yield Static(f"  {workdir}", classes="sidebar-item")

        # Modified Files section (order=500)
        yield Static("Modified Files", classes="sidebar-section", id="modified-section")
        yield Static("  (none)", classes="sidebar-item", id="modified-placeholder")

        # Footer (order=100) — 版本号
        yield Static("", classes="sidebar-footer", id="sidebar-footer")

    def on_mount(self) -> None:
        self._update_footer()

    def _update_footer(self) -> None:
        try:
            footer = self.query_one("#sidebar-footer", Static)
            footer.update("  v2 · OpenCode Layout")
        except Exception:
            pass

    def update_modified_files(self, files: list[dict]) -> None:
        self._modified_files = files
        try:
            section = self.query_one("#modified-section", Static)
            for child in list(section.parent.children):
                if hasattr(child, 'has_class') and child.has_class("sidebar-file-item"):
                    child.remove()

            placeholder = self.query_one("#modified-placeholder", Static)
            if not files:
                placeholder.update("  (none)")
                return
            placeholder.update("")

            for f in files[:10]:
                path = f.get("path", "?")
                adds = f.get("adds", 0)
                dels = f.get("dels", 0)
                name = os.path.basename(path)
                diff_str = f"+{adds}/-{dels}" if adds or dels else ""
                item = Static(f"  {name} {diff_str}", classes="sidebar-item sidebar-file-item modified")
                section.mount_after(item)
        except Exception:
            pass


# ============================================================
# StatusBar Stub — 兼容旧 command 对 _status_bar 的写入
# ============================================================
class _StatusBarStub:
    """OpenCode 风格已取消独立状态栏，但旧 /model /context /voice
    等命令仍会写入 _status_bar 属性。此 stub 避免 AttributeError。
    """

    def __init__(self) -> None:
        self.model_name: str = ""
        self.context_pct: Optional[int] = None
        self.context_tokens: int = 0
        self.context_max: int = 0
        self.total_tokens: int = 0
        self.permission_mode: str = "auto"
        self.voice_enabled: bool = False


# ============================================================
# Permission Dialog — OpenCode 风格 (中文本地化 + 鼠标支持)
# ============================================================
class PermissionDialog(ModalScreen[str]):
    """权限确认 — OpenCode 风格, 支持键盘与鼠标."""

    BINDINGS = [
        Binding("escape", "dismiss('deny')", "拒绝"),
        Binding("left,h", "prev_option", "上一个", show=False, priority=True),
        Binding("right,l", "next_option", "下一个", show=False, priority=True),
        Binding("enter", "select_option", "确认", priority=True),
    ]

    DEFAULT_CSS = """
    PermissionDialog { align: center middle; background: $surface 90%; }
    PermissionDialog > .modal {
        width: 70; max-width: 84; height: auto;
        background: #0a0a0a; border: tall #d4a017; padding: 1 2;
    }
    PermissionDialog .modal-header { width: 100%; height: auto; }
    PermissionDialog .modal-warning { color: #d4a017; text-style: bold; }
    PermissionDialog .modal-title { color: #eeeeee; margin-top: 1; }
    PermissionDialog .modal-body { color: #aaaaaa; margin: 1 0; }
    PermissionDialog .modal-body .key { color: #606060; }
    PermissionDialog .modal-body .value { color: #eeeeee; }
    PermissionDialog .modal-actions {
        width: 100%; height: auto;
        margin-top: 1;
        layout: grid;
        grid-size: 3;
        grid-columns: 1fr 1fr 1fr;
        grid-gutter: 1;
    }
    PermissionDialog .action-btn {
        width: 100%; height: 1;
        background: #1e1e1e;
        color: #aaaaaa;
        text-align: center;
        content-align: center middle;
    }
    PermissionDialog .action-btn:hover { background: #2a2a2a; }
    PermissionDialog .action-btn.selected {
        background: #d4a017;
        color: #0a0a0a;
        text-style: bold;
    }
    PermissionDialog .modal-hint { color: #606060; text-align: center; margin-top: 1; }
    """

    _OPTIONS = ["once", "session", "deny"]
    _OPTION_LABELS = {
        "once": "允许一次",
        "session": "始终允许",
        "deny": "拒绝",
    }
    _TOOL_ICONS = {
        "bash": "#",
        "shell": "#",
        "read": "→",
        "edit": "→",
        "write": "→",
        "glob": "✱",
        "grep": "✱",
        "list": "→",
        "webfetch": "%",
        "websearch": "◈",
        "search": "◈",
    }
    _TOOL_NAMES = {
        "bash": "Shell 命令",
        "shell": "Shell 命令",
        "read": "读取文件",
        "edit": "编辑文件",
        "write": "写入文件",
        "glob": "Glob 匹配",
        "grep": "Grep 搜索",
        "list": "列出目录",
        "webfetch": "抓取网页",
        "websearch": "联网搜索",
        "search": "搜索",
        "task": "子任务",
        "tool": "工具调用",
    }

    def __init__(self, tool_name: str, args: dict) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._args = args
        self._selected = 0

    @staticmethod
    def _tool_label(tool_name: str) -> tuple[str, str]:
        key = tool_name.lower()
        icon = PermissionDialog._TOOL_ICONS.get(key, "⚙")
        name = PermissionDialog._TOOL_NAMES.get(key, tool_name)
        return icon, name

    @staticmethod
    def _translate_reason(reason: str) -> str:
        # 将常见英文 reason 翻译为中文, 无法识别则原样返回
        reason = reason.lower()
        if "dangerous tool execution" in reason:
            return "危险工具执行"
        if "edit" in reason and "file" in reason:
            return "请求编辑文件"
        if "read" in reason and "file" in reason:
            return "请求读取文件"
        if "bash" in reason or "shell" in reason:
            return "请求执行 Shell 命令"
        return reason

    def compose(self) -> ComposeResult:
        icon, title = self._tool_label(self._tool_name)
        with Vertical(classes="modal"):
            with Vertical(classes="modal-header"):
                yield Static("⚠ 需要权限", classes="modal-warning")
                yield Static(f"{icon} {title}", classes="modal-title")
            body = self._args.get("detail") or self._args.get("reason") or ""
            if body:
                translated = self._translate_reason(body)
                yield Markdown(
                    f"<span class='key'>原因:</span> <span class='value'>{translated}</span>",
                    classes="modal-body",
                )
            with Horizontal(classes="modal-actions"):
                for i, opt in enumerate(self._OPTIONS):
                    classes = "action-btn"
                    if i == self._selected:
                        classes += " selected"
                    yield Static(self._OPTION_LABELS[opt], classes=classes, id=f"action-{opt}")
            yield Static("⇆ 选择  Enter 确认  Esc 拒绝", classes="modal-hint")

    def _refresh_actions(self) -> None:
        for i, opt in enumerate(self._OPTIONS):
            btn = self.query_one(f"#action-{opt}", Static)
            btn.set_class(i == self._selected, "selected")

    def action_prev_option(self) -> None:
        self._selected = (self._selected - 1) % len(self._OPTIONS)
        self._refresh_actions()

    def action_next_option(self) -> None:
        self._selected = (self._selected + 1) % len(self._OPTIONS)
        self._refresh_actions()

    def action_select_option(self) -> None:
        self.dismiss(self._OPTIONS[self._selected])

    def on_click(self, event) -> None:
        # 鼠标点击按钮时根据点击位置选择最近按钮
        target = event.control
        if target is None or not target.id or not target.id.startswith("action-"):
            return
        opt = target.id.replace("action-", "")
        if opt in self._OPTIONS:
            self.dismiss(opt)


# ============================================================
# Main App — OpenCode 精确布局 (源码级对齐)
# ============================================================
class HakusApp(App):
    """HakusAI TUI — OpenCode 源码级精确布局

    基于 packages/tui/src/routes/session/index.tsx:
    - 水平分屏: flexDirection="row"
    - 左侧: flexGrow=1, minHeight=0, paddingLeft=2, paddingRight=2, paddingBottom=1
    - 右侧: width=42 (侧边栏, 宽屏自动显示)
    - 消息区: flexGrow=1 (scrollbox)
    - Prompt: flexShrink=0, maxHeight=max(6, H/3)
    - 无独立状态栏
    """

    CSS_PATH = "theme.tcss"
    TITLE = "HakusAI"

    DEFAULT_CSS = """
    Screen {
        background: #0a0a0a;
        color: #eeeeee;
    }

    #top-pane {
        height: 1fr;
        background: #0a0a0a;
    }

    #messages-pane {
        width: 1fr;
        background: #0a0a0a;
        padding: 0 2 1 2;
        overflow: hidden;
    }

    #sidebar {
        width: 42;
        background: #0a0a0a;
        border-left: solid #1e1e1e;
        padding: 1 2;
        overflow: auto;
    }

    #sidebar.hidden {
        display: none;
    }

    #message-list {
        padding: 0;
        background: #0a0a0a;
        scrollbar-size: 1 0;
        height: 1fr;
        overflow: auto;
    }

    #prompt-input {
        dock: bottom;
        height: auto;
        min-height: 1;
        max-height: 24;
        background: #0a0a0a;
        border-top: solid #1e1e1e;
        padding: 0 1;
    }

    #activity-strip {
        height: 1;
        background: #0a0a0a;
        color: #56b6c2;
        padding: 0 1;
        display: none;
        dock: top;
    }

    #activity-strip.active {
        display: block;
    }

    #notification-bar {
        height: 1;
        background: #0a0a0a;
        color: #56b6c2;
        padding: 0 1;
    }

    WelcomePanel {
        background: transparent;
        padding: 1 2;
        height: auto;
        max-width: 75;
        margin: 1 0;
    }

    UserBubble {
        background: #0a0a0a;
        margin: 1 0;
        padding: 0 1;
        height: auto;
        border-left: tall #3c3c3c;
    }

    AssistantText {
        margin: 1 0;
        padding: 0 1;
        height: auto;
        background: transparent;
    }

    ToolResult {
        margin: 0;
        padding: 0 1;
        height: auto;
        background: transparent;
        border-left: tall #1e1e1e;
    }

    ToolResult.expanded {
        border-left: tall #e5c07b;
    }

    ToolResult.error {
        border-left: tall #e06c75;
    }

    CommandResult {
        margin: 0;
        padding: 0 1;
        background: transparent;
        border-left: tall #282828;
        height: auto;
    }

    ErrorBlock {
        margin: 1 0;
        padding: 0 1;
        background: transparent;
        border-left: tall #e06c75;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit_or_cancel", "Quit", show=False),
        Binding("ctrl+l", "clear_screen", "Clear", show=False),
        Binding("escape", "cancel_streaming", "Cancel", show=False),
        Binding("ctrl+k", "show_command_palette", "Commands", show=True),
        Binding("ctrl+o", "show_model_overlay", "Model", show=True),
        Binding("ctrl+shift+o", "show_model_config", "Config", show=True),
        Binding("tab", "toggle_agent_mode", "Build/Plan", show=True),
        Binding("ctrl+t", "cycle_theme", "Theme", show=False),
        Binding("ctrl+s", "switch_session", "Session", show=False),
        Binding("ctrl+h", "show_help", "Help", show=False),
        Binding("ctrl+f", "file_picker", "Files", show=False),
        Binding("ctrl+b", "toggle_details", "Details", show=False),
    ]

    def __init__(
        self,
        agent: Any,
        voice_enabled: bool = False,
        session_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        agent._tui_mode = True
        self._session = TUISession(
            model_name=getattr(agent, "_model_type", "opencode"),
            working_dir=os.getcwd(),
            voice_enabled=voice_enabled,
            permission_mode="bypass",
        )
        if session_id:
            self._session.session_id = session_id

        self._debug_enabled = is_debug_enabled()
        if self._debug_enabled:
            self._debug_logger = init_debug_logger(session_id=session_id)

        self._command_registry = build_default_registry()
        self._sink: Optional[StreamingSink] = None
        self._streaming_in_progress = False
        self._agent_mode = "build"
        self._show_details = False
        self._last_model = ""
        self._sidebar_visible = True

        # 子组件
        self._sidebar: Optional[Sidebar] = None
        self._message_list: Optional[MessageList] = None
        self._activity: Optional[ActivityStrip] = None
        self._prompt_input: Optional[PromptInput] = None
        self._notification_bar: Optional[NotificationBar] = None
        self._status_bar = _StatusBarStub()
        self._welcome_shown = False

    def compose(self) -> ComposeResult:
        """OpenCode 精确布局: 水平分屏(flexGrow+width=42)+底部Prompt"""

        # ── 水平分屏: 左侧内容(flexGrow=1) + 右侧侧边栏(width=42) ──
        with Horizontal(id="top-pane"):
            # 左侧: 消息区 (flexGrow=1, paddingLeft=2, paddingRight=2, paddingBottom=1)
            with Vertical(id="messages-pane"):
                self._message_list = MessageList(id="message-list")
                yield self._message_list

            # 右侧: 侧边栏 (width=42, 宽屏>120自动显示)
            self._sidebar = Sidebar(self._session, self._agent, id="sidebar")
            yield self._sidebar

        # ── Prompt (flexShrink=0, 底部固定) ──
        self._prompt_input = PromptInput(id="prompt-input")
        yield self._prompt_input

        # 浮动组件
        self._notification_bar = NotificationBar(id="notification-bar")
        yield self._notification_bar

        self._activity = ActivityStrip(id="activity-strip")
        yield self._activity

    def on_mount(self) -> None:
        from .screens.setup_wizard import SetupWizard, needs_setup
        if needs_setup():
            self.push_screen(SetupWizard(), callback=lambda _: self._show_welcome())
            return
        self._show_welcome()
        self._bind_permissions()
        self._notification_bar.show("^K commands · ^O model · Tab mode · ^H help")

    def on_resize(self, event) -> None:
        """OpenCode 行为: width > 120 自动显示侧边栏, 否则隐藏"""
        if self._sidebar is None:
            return
        try:
            should_show = event.size.width > WIDE_THRESHOLD
            if should_show != self._sidebar_visible:
                self._sidebar_visible = should_show
                self._sidebar.set_class(not should_show, "hidden")
        except Exception:
            pass

    def _show_welcome(self) -> None:
        if self._welcome_shown:
            return
        self._welcome_shown = True
        welcome = WelcomePanel(
            model_name=self._session.model_name,
            working_dir=self._session.working_dir,
        )
        self._message_list.mount_widget(welcome)

    # ============================================================
    # OpenCode 快捷键 Actions
    # ============================================================

    def action_toggle_agent_mode(self) -> None:
        self._agent_mode = "plan" if self._agent_mode == "build" else "build"
        label = "build (read/write)" if self._agent_mode == "build" else "plan (read-only)"
        self._notification_bar.show(f"Mode: {label}")

    def action_cycle_theme(self) -> None:
        self._notification_bar.show("Theme: default")

    def action_switch_session(self) -> None:
        self._notification_bar.show("Session: current")

    def action_file_picker(self) -> None:
        self._notification_bar.show("File picker: not yet implemented")

    def action_toggle_details(self) -> None:
        from .widgets.tool_result import ToolResult
        ToolResult.show_details = not ToolResult.show_details
        state = "on" if ToolResult.show_details else "off"
        self._notification_bar.show(f"Details: {state}")

    def action_show_model_overlay(self) -> None:
        from .overlays import ModelOverlay
        current = getattr(self._agent, "_model_type", "opencode")
        self.push_screen(ModelOverlay(current), callback=lambda m: self._switch_model(m) if m and m != current else None)

    def action_show_model_config(self) -> None:
        from .overlays import ModelConfigOverlay
        current = getattr(self._agent, "_model_type", "opencode")
        self.push_screen(ModelConfigOverlay(current), callback=self._apply_model_config)

    def action_show_command_palette(self) -> None:
        from .overlays import CommandPalette
        self.push_screen(CommandPalette(self._command_registry), callback=self._on_palette_command)

    def action_show_help(self) -> None:
        from .overlays import HelpOverlay
        self.push_screen(HelpOverlay())

    def _switch_model(self, model: str) -> None:
        current = getattr(self._agent, "_model_type", "opencode")
        if model == current:
            return
        self._last_model = current
        try:
            self._agent._model_type = model
            self._agent._init_model()
            actual = self._agent._model_type
            self._session.model_name = actual
            self._status_bar.model_name = actual
            # 持久化默认模型, 重启后仍保持选择
            try:
                save_default_model(actual)
            except Exception as save_err:
                logger.debug(f"save_default_model failed: {save_err}")
            self._notification_bar.show(f"Model: {actual}")
        except Exception as e:
            self._agent._model_type = current
            self._notification_bar.show(f"Switch failed: {e}")

    def _apply_model_config(self, new_default: str) -> None:
        """ModelConfigOverlay 保存后的回调：重新加载并应用模型配置."""
        if not new_default:
            return
        try:
            config = get_config()
            actual = config.models.default_model or new_default
            current = getattr(self._agent, "_model_type", "opencode")
            # 总是重新初始化以应用新的 api_key/base_url/model_name
            self._last_model = current
            try:
                self._agent._model_type = actual
                self._agent._init_model()
                actual = self._agent._model_type
            except Exception as e:
                self._agent._model_type = current
                self._notification_bar.show(f"Model init failed: {e}")
                return
            self._session.model_name = actual
            self._notification_bar.show(f"Config saved · model: {actual}")
        except Exception as e:
            self._notification_bar.show(f"Config reload failed: {e}")

    # ============================================================
    # Permission Binding
    # ============================================================

    def _bind_permissions(self) -> None:
        try:
            perm = self._agent._permission

            async def async_confirm(action_key: str, reason: str) -> str:
                parts = action_key.split(":", 1)
                tool_name = parts[0] if parts else action_key
                args = {"reason": reason}
                if len(parts) > 1:
                    args["detail"] = parts[1]
                future = asyncio.get_running_loop().create_future()

                def _on_result(result: str) -> None:
                    if not future.done():
                        future.set_result(result)

                self.push_screen(PermissionDialog(tool_name, args), _on_result)
                return await future

            perm.set_async_confirm_callback(async_confirm)
        except Exception as e:
            logger.debug(f"Permission binding failed: {e}")

    # ============================================================
    # Message API
    # ============================================================

    def _mount_message(self, message: Message) -> None:
        if self._message_list is None:
            return
        if message.role == "error" or message.is_error:
            self._message_list.mount_error(message)
        elif message.role == "tool":
            self._message_list.mount_tool(message)
        elif message.role in ("command", "system"):
            self._message_list.mount_command(message)
        else:
            self._message_list.add_message(message)

    def get_available_tools(self) -> list[str]:
        try:
            return self._agent._tool_registry.list_tools()
        except Exception:
            return []

    # ============================================================
    # Input Handling
    # ============================================================

    async def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        text = event.value
        attachments = event.attachments or []
        editor_context = event.editor_context or ""

        if not text and not attachments and not editor_context:
            return
        if self._streaming_in_progress:
            self._mount_message(Message.error("Reply in progress — Esc to cancel"))
            return

        parts = []
        if text:
            parts.append(Part(type=PartType.TEXT, text=text))
        if editor_context:
            parts.append(Part(type=PartType.TEXT, text=f"\n\n[Editor context]\n{editor_context}", synthetic=True))
        for att in attachments:
            ptype = PartType.IMAGE if att.is_image else PartType.FILE
            parts.append(Part(type=ptype, file_path=att.name, file_mime=att.mime, file_data=att.data, file_size=len(att.data)))

        user_msg = Message.user_with_parts(parts)
        self._mount_message(user_msg)

        if text.startswith("/"):
            await self._handle_slash(text)
            return

        if self._agent_mode == "plan":
            text = f"[PLAN MODE — read-only]\n{text}"

        await self._run_stream(text)

    async def _run_stream(self, user_input: str) -> None:
        self._streaming_in_progress = True
        self._sink = StreamingSink(self)
        try:
            await self._sink.run(user_input, self._agent.run_turn)
        except Exception as e:
            self._mount_message(Message.error(f"Error: {e}"))
        finally:
            self._streaming_in_progress = False
            self._sink = None

    async def _handle_slash(self, raw: str) -> None:
        parts = raw[1:].split(maxsplit=1)
        cmd_name = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        cmd = self._command_registry.get(cmd_name)
        if cmd is None:
            self._mount_message(Message.error(f"Unknown: /{cmd_name} — /help for list"))
            return
        ctx = CommandContext(app=self, args=args, parts=args.split() if args else [], raw=raw)
        try:
            await cmd.execute(ctx)
        except Exception as e:
            self._mount_message(Message.error(f"Error: {e}"))

    # ============================================================
    # Other Actions
    # ============================================================

    def action_quit_or_cancel(self) -> None:
        if self._streaming_in_progress and self._sink:
            self._sink.cancel()
            self._mount_message(Message.system("Cancelled"))
        else:
            self.exit()

    def action_clear_screen(self) -> None:
        if self._message_list:
            self._message_list.clear_messages()
        self._mount_message(Message.system("Cleared"))

    def action_cancel_streaming(self) -> None:
        if self._streaming_in_progress and self._sink:
            self._sink.cancel()
            self._mount_message(Message.system("Cancelled"))

    def _on_palette_command(self, cmd: str) -> None:
        if cmd:
            asyncio.create_task(self._handle_slash(cmd))


def run(agent: Any, voice_enabled: bool = False, session_id: Optional[str] = None) -> None:
    app = HakusApp(agent, voice_enabled=voice_enabled, session_id=session_id)
    app.run()
