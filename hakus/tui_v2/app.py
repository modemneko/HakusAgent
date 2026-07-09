"""
HakusAI TUI v2 — 借鉴 OpenCode 设计
- 响应式左侧边栏 (自动折叠/隐藏)
- 右侧主区: 消息列表 + 底部输入框
- 状态栏 + 活动指示条
- 命令面板、帮助、模型切换
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Markdown, RichLog, Static

from .messages import Message, Part, PartType
from .session import TUISession
from .streaming import StreamingSink
from .widgets.activity import ActivityStrip
from .widgets.message_list import MessageList
from .widgets.notification_bar import NotificationBar
from .widgets.prompt_input import PromptInput
from .widgets.status_bar import StatusBar
from .widgets.welcome_panel import WelcomePanel
from .commands import SlashCommandRegistry, build_default_registry, CommandContext
from utils.logger import get_logger
from utils.turn_debug import is_debug_enabled, init_debug_logger, shutdown_debug_logger

logger = get_logger(__name__)


# ============================================================
# Sidebar Toggle Button
# ============================================================
class SidebarToggle(Button):
    """边栏切换按钮"""

    DEFAULT_CSS = """
    SidebarToggle {
        width: 1;
        height: 1;
        background: #1e1e1e;
        color: #808080;
        border: none;
        margin: 0;
        padding: 0;
        content-align: center middle;
    }
    SidebarToggle:hover {
        background: #3c3c3c;
        color: #fab283;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("◀", **kwargs)


# ============================================================
# Permission Dialog
# ============================================================
class PermissionDialog(ModalScreen[str]):
    """权限确认对话框"""

    BINDINGS = [
        Binding("escape", "dismiss('deny')", "Cancel"),
        Binding("enter", "press_focused", "确认", show=False),
        Binding("space", "press_focused", "确认", show=False),
        Binding("left", "focus_prev", "上一个", show=False),
        Binding("right", "focus_next", "下一个", show=False),
    ]

    DEFAULT_CSS = """
    PermissionDialog { align: center middle; }
    PermissionDialog > .modal {
        width: 70%; max-width: 100; height: auto;
        background: #141414; border: tall #fab283; padding: 1 2;
    }
    PermissionDialog .modal-title { color: #fab283; text-style: bold; text-align: center; }
    PermissionDialog .modal-body { color: #eeeeee; margin: 1 0; }
    PermissionDialog .modal-buttons { height: 3; align-horizontal: center; }
    PermissionDialog Button { margin: 0 1; min-width: 14; }
    PermissionDialog #allow-once { background: #141414; color: #56b6c2; border: tall #56b6c2; }
    PermissionDialog #allow-session { background: #141414; color: #fab283; border: tall #fab283; }
    PermissionDialog #deny { background: #141414; color: #e06c75; border: tall #e06c75; }
    """

    def __init__(self, tool_name: str, args: dict) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._args = args

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static("⚠ 权限请求", classes="modal-title")
            args_str = "\n".join(f"  `{k}` = {v!r}" for k, v in self._args.items()) or "  (无参数)"
            yield Markdown(
                f"模型请求执行工具: **`{self._tool_name}`**\n\n**参数:**\n{args_str}\n\n是否允许?",
                classes="modal-body",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("✓ 允许 (1 次)", id="allow-once")
                yield Button("⚡ 本次会话允许", id="allow-session")
                yield Button("✗ 拒绝", id="deny")

    def on_mount(self) -> None:
        """自动聚焦第一个按钮, 确保键盘导航可用."""
        try:
            first_btn = self.query_one("#allow-once", Button)
            first_btn.focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id.replace("-", "_"))

    def action_press_focused(self) -> None:
        """按当前聚焦的按钮."""
        try:
            focused = self.focused
            if isinstance(focused, Button):
                focused.press()
        except Exception:
            pass

    def action_focus_next(self) -> None:
        """聚焦下一个按钮."""
        try:
            buttons = list(self.query("Button"))
            if not buttons:
                return
            focused = self.focused
            if isinstance(focused, Button):
                idx = buttons.index(focused)
                next_idx = (idx + 1) % len(buttons)
                buttons[next_idx].focus()
            elif buttons:
                buttons[0].focus()
        except Exception:
            pass

    def action_focus_prev(self) -> None:
        """聚焦上一个按钮."""
        try:
            buttons = list(self.query("Button"))
            if not buttons:
                return
            focused = self.focused
            if isinstance(focused, Button):
                idx = buttons.index(focused)
                prev_idx = (idx - 1) % len(buttons)
                buttons[prev_idx].focus()
            elif buttons:
                buttons[-1].focus()
        except Exception:
            pass


# ============================================================
# Sidebar Widget (左侧边栏) - 响应式、可折叠分区
# ============================================================
class Sidebar(Static):
    """左侧边栏：会话信息、工具、状态"""

    DEFAULT_CSS = """
    Sidebar {
        width: 42;
        background: #141414;
        border-right: solid #fab283;
        padding: 1 2;
        overflow: auto;
        transition: width 150ms in_out_cubic;
    }
    Sidebar.hidden {
        width: 0;
        padding: 1 0;
        border-right: none;
        overflow: hidden;
    }
    Sidebar.collapsed {
        width: 1;
        padding: 1 0;
        border-right: none;
        overflow: hidden;
    }
    Sidebar .section-title {
        color: #9d7cd8; text-style: bold; margin: 1 0 0 0;
    }
    Sidebar .session-title { color: #eeeeee; text-style: bold; }
    Sidebar .session-meta { color: #808080; margin-top: 1; }
    Sidebar .tool-item { color: #eeeeee; margin: 0 0 0 1; }
    Sidebar .tool-item:hover { color: #9d7cd8; }
    Sidebar .sidebar-section { margin: 1 0; }
    Sidebar .sidebar-section.hidden { display: none; }
    """

    def __init__(self, session: TUISession, agent: Any, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._session = session
        self._agent = agent
        self._expanded_sections = {"session": True, "tools": True, "status": True}

    def compose(self) -> ComposeResult:
        # 会话信息区
        with Vertical(classes="sidebar-section", id="section-session"):
            yield Static("📝 会话", classes="section-title")
            yield Static(self._session.model_name, classes="session-title")
            yield Static(f"📁 {self._session.working_dir}", classes="session-meta")
            yield Static(f"🔧 权限: {self._session.permission_mode}", classes="session-meta")

        # 工具区
        with Vertical(classes="sidebar-section", id="section-tools"):
            yield Static("🛠️ 可用工具", classes="section-title")
            tools = self._get_tools()
            for tool in tools:
                yield Static(f"  {tool}", classes="tool-item")

        # 状态区
        with Vertical(classes="sidebar-section", id="section-status"):
            yield Static("ℹ️ 状态", classes="section-title")
            yield Static("  准备就绪", id="status-line", classes="tool-item")

    def _get_tools(self) -> list[str]:
        try:
            return self._agent._tool_registry.list_tools()
        except Exception:
            return ["bash", "read", "write", "edit", "glob", "grep", "task", "web_search"]

    def toggle_section(self, section: str) -> None:
        """切换区域展开/折叠"""
        self._expanded_sections[section] = not self._expanded_sections.get(section, True)
        try:
            section_widget = self.query_one(f"#section-{section}", Vertical)
            if self._expanded_sections[section]:
                section_widget.remove_class("hidden")
            else:
                section_widget.add_class("hidden")
        except Exception:
            pass


# ============================================================
# Main App
# ============================================================
class HakusApp(App):
    """HakusAI 简洁 TUI - 借鉴 OpenCode 设计"""

    CSS_PATH = "theme.tcss"
    TITLE = "HakusAI"
    SUB_TITLE = "v2 — OpenCode Style"

    BINDINGS = [
        Binding("ctrl+c", "quit_or_cancel", "退出/取消", show=True),
        Binding("ctrl+l", "clear_screen", "清屏", show=True),
        Binding("escape", "cancel_streaming", "取消", show=False),
        Binding("ctrl+m", "show_model_overlay", "模型", show=False),
        Binding("ctrl+p", "show_command_palette", "命令面板", show=True),
        Binding("ctrl+b", "toggle_sidebar", "切换边栏", show=True),
        Binding("f1", "show_help", "帮助", show=False),
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
            model_name=getattr(agent, "_model_type", "deepseek"),
            working_dir=os.getcwd(),
            voice_enabled=voice_enabled,
            permission_mode="bypass",
        )
        if session_id:
            self._session.session_id = session_id

        self._debug_enabled = is_debug_enabled()
        if self._debug_enabled:
            self._debug_logger = init_debug_logger(session_id=session_id)
            logger.info(f"Debug mode ON — logs → {self._debug_logger.session_dir}")

        self._command_registry: SlashCommandRegistry = build_default_registry()
        self._sink: Optional[StreamingSink] = None
        self._streaming_in_progress: bool = False
        self._sidebar_visible = True
        self._sidebar_collapsed = False

        # 子组件 (在 compose 中赋值)
        self._sidebar: Optional[Sidebar] = None
        self._message_list: Optional[MessageList] = None
        self._status_bar: Optional[StatusBar] = None
        self._activity: Optional[ActivityStrip] = None
        self._prompt_input: Optional[PromptInput] = None
        self._notification_bar: Optional[NotificationBar] = None
        self._sidebar_toggle: Optional[SidebarToggle] = None
        self._welcome_shown: bool = False

    def compose(self) -> ComposeResult:
        # 活动指示条
        self._activity = ActivityStrip(id="activity-strip")
        yield self._activity

        # 主布局：左侧边栏 + 右侧内容区
        with Horizontal(id="main-layout"):
            # 边栏切换按钮
            self._sidebar_toggle = SidebarToggle(id="sidebar-toggle")
            yield self._sidebar_toggle

            self._sidebar = Sidebar(self._session, self._agent, id="sidebar")
            yield self._sidebar

            with Vertical(id="main-content"):
                self._message_list = MessageList(id="message-list")
                yield self._message_list

                # 状态栏 (消息列表下方)
                self._status_bar = StatusBar(id="status-bar")
                yield self._status_bar

        # 底部输入框
        self._prompt_input = PromptInput(id="prompt-input")
        yield self._prompt_input

        # 通知栏
        self._notification_bar = NotificationBar(id="notification-bar")
        yield self._notification_bar

        yield Footer()

    def on_mount(self) -> None:
        # 检查首次运行
        from .screens.setup_wizard import SetupWizard, needs_setup
        if needs_setup():
            self.push_screen(SetupWizard(), callback=self._on_setup_done)
            return

        self._show_welcome()
        self._bind_permissions()
        self._setup_responsive_sidebar()
        self._notification_bar.show("🌸 欢迎使用 HakusAI v2 · 输入 /help 查看命令 · Ctrl+B 切换边栏")

    def _on_setup_done(self, saved: bool) -> None:
        if saved:
            self._notification_bar.show("[bold cyan]配置已保存![/]")
        else:
            self._notification_bar.show("[yellow]跳过配置[/] · 可用 /config 重新设置")
        self._show_welcome()

    def _show_welcome(self) -> None:
        if self._welcome_shown:
            return
        self._welcome_shown = True
        welcome = WelcomePanel(
            model_name=self._session.model_name,
            working_dir=self._session.working_dir,
        )
        self._message_list.mount_widget(welcome)

    def _setup_responsive_sidebar(self) -> None:
        """设置响应式边栏：窄终端自动隐藏"""
        self.watch(self.app, "size", self._on_resize)
        self._on_resize(None)

    def _on_resize(self, event) -> None:
        """终端大小变化时自动调整边栏"""
        if not self._sidebar or not self._sidebar_toggle:
            return

        width = self.size.width
        # 小于 100 列自动折叠边栏
        if width < 100 and not self._sidebar_collapsed:
            self._collapse_sidebar()
        elif width >= 120 and self._sidebar_collapsed and self._sidebar_visible:
            self._expand_sidebar()

    def _collapse_sidebar(self) -> None:
        """折叠边栏到最小宽度"""
        self._sidebar.add_class("collapsed")
        self._sidebar.remove_class("hidden")
        self._sidebar_collapsed = True
        self._sidebar_toggle.label = "▶"

    def _expand_sidebar(self) -> None:
        """展开边栏到完整宽度"""
        self._sidebar.remove_class("collapsed")
        self._sidebar.remove_class("hidden")
        self._sidebar_collapsed = False
        self._sidebar_toggle.label = "◀"

    def _hide_sidebar(self) -> None:
        """完全隐藏边栏"""
        self._sidebar.add_class("hidden")
        self._sidebar.remove_class("collapsed")
        self._sidebar_visible = False
        self._sidebar_toggle.label = "▶"

    def _show_sidebar(self) -> None:
        """显示边栏"""
        self._sidebar.remove_class("hidden")
        self._sidebar.remove_class("collapsed")
        self._sidebar_visible = True
        self._sidebar_collapsed = False
        self._sidebar_toggle.label = "◀"

    def action_toggle_sidebar(self) -> None:
        """切换边栏显示/隐藏"""
        if self._sidebar_visible:
            if self._sidebar_collapsed:
                self._expand_sidebar()
            else:
                self._collapse_sidebar()
        else:
            self._show_sidebar()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """处理按钮点击"""
        if event.button.id == "sidebar-toggle":
            self.action_toggle_sidebar()
            event.stop()
        elif event.button.id == "status-model":
            self.action_show_model_overlay()
            event.stop()
        elif event.button.id == "status-perm":
            modes = ["bypass", "auto", "ask"]
            current = self._session.permission_mode
            try:
                idx = modes.index(current)
                next_mode = modes[(idx + 1) % len(modes)]
            except ValueError:
                next_mode = "bypass"
            self._session.permission_mode = next_mode
            if self._status_bar:
                self._status_bar.permission_mode = next_mode
            self._mount_message(Message.system(f"✓ 权限模式: **{next_mode}**"))
            event.stop()

    def _bind_permissions(self) -> None:
        try:
            perm = self._agent._permission

            async def async_confirm(action_key: str, reason: str) -> str:
                parts = action_key.split(":", 1)
                tool_name = parts[0] if parts else action_key
                args = {"reason": reason}
                if len(parts) > 1:
                    args["detail"] = parts[1]

                # Use a future to wait for the modal result
                future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

                def _on_result(result: str) -> None:
                    if not future.done():
                        future.set_result(result)

                # Push the screen and wait for dismissal
                screen = PermissionDialog(tool_name, args)
                self.push_screen(screen, _on_result)
                # Wait for user response — event loop processes the screen
                return await future

            perm.set_async_confirm_callback(async_confirm)
        except Exception as e:
            logger.debug(f"Permission binding failed: {e}")

    # ----- Message API (兼容 streaming.py) -----

    def _mount_message(self, message: Message) -> None:
        """挂载消息到 MessageList (streaming.py 调用)."""
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
        """获取可用工具列表 (streaming.py 调用)."""
        try:
            return self._agent._tool_registry.list_tools()
        except Exception:
            return []

    # ----- Input Handling -----

    async def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """处理 PromptInput 提交."""
        text = event.value
        attachments = event.attachments or []
        editor_context = event.editor_context or ""
        
        if not text and not attachments and not editor_context:
            return
        if self._streaming_in_progress:
            self._mount_message(Message.error("当前回复尚未完成，请先等待或按 Esc 取消"))
            return

        # 构建用户消息 (Part-based)
        from ..messages import Message, Part, PartType
        parts = []
        if text:
            parts.append(Part(type=PartType.TEXT, text=text))
        if editor_context:
            parts.append(Part(type=PartType.TEXT, text=f"\n\n[编辑器上下文]\n{editor_context}", synthetic=True))
        for att in attachments:
            if att.is_image:
                parts.append(Part(type=PartType.IMAGE, file_path=att.name, file_mime=att.mime, file_data=att.data, file_size=len(att.data)))
            elif att.is_pdf:
                parts.append(Part(type=PartType.FILE, file_path=att.name, file_mime=att.mime, file_data=att.data, file_size=len(att.data)))
            elif att.is_text:
                parts.append(Part(type=PartType.FILE, file_path=att.name, file_mime=att.mime, file_data=att.data, file_size=len(att.data)))
            else:
                parts.append(Part(type=PartType.FILE, file_path=att.name, file_mime=att.mime, file_data=att.data, file_size=len(att.data)))
        
        user_msg = Message.user_with_parts(parts)
        self._mount_message(user_msg)

        # Slash 命令
        if text.startswith("/"):
            await self._handle_slash(text)
            return

        # 运行流式
        await self._run_stream(text)

    async def _run_stream(self, user_input: str) -> None:
        self._streaming_in_progress = True
        self._sink = StreamingSink(self)
        try:
            await self._sink.run(user_input, self._agent.run_turn)
        except Exception as e:
            self._mount_message(Message.error(f"执行错误: {e}"))
        finally:
            self._streaming_in_progress = False
            self._sink = None

    async def _handle_slash(self, raw: str) -> None:
        parts = raw[1:].split(maxsplit=1)
        cmd_name = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        cmd = self._command_registry.get(cmd_name)
        if cmd is None:
            self._mount_message(Message.error(f"未知命令: `/{cmd_name}`\n输入 `/help` 查看所有命令"))
            return
        ctx = CommandContext(app=self, args=args, parts=args.split() if args else [], raw=raw)
        try:
            await cmd.execute(ctx)
        except Exception as e:
            self._mount_message(Message.error(f"命令执行错误: {e}"))

    # ----- Actions -----
    def action_quit_or_cancel(self) -> None:
        if self._streaming_in_progress and self._sink:
            self._sink.cancel()
            self._mount_message(Message.system("⏹ 已中断"))
        else:
            self.exit()

    def action_clear_screen(self) -> None:
        if self._message_list:
            self._message_list.clear_messages()
        self._mount_message(Message.system("✓ 屏幕已清除"))

    def action_cancel_streaming(self) -> None:
        if self._streaming_in_progress and self._sink:
            self._sink.cancel()
            self._mount_message(Message.system("⏹ 已中断"))

    def action_show_model_overlay(self) -> None:
        from .overlays import ModelOverlay
        current = getattr(self._agent, "_model_type", "deepseek")

        def on_select(model: str) -> None:
            if model and model != current:
                try:
                    self._agent._model_type = model
                    self._agent._init_model()
                    actual = self._agent._model_type
                    self._session.model_name = actual
                    if self._status_bar:
                        self._status_bar.model_name = actual
                    self._mount_message(Message.system(f"✓ 已切换到 **{actual}**"))
                except Exception as e:
                    self._mount_message(Message.error(f"切换模型失败: {e}"))

        self.push_screen(ModelOverlay(current), on_select)

    def action_show_help(self) -> None:
        from .overlays import HelpOverlay
        self.push_screen(HelpOverlay())

    def action_show_command_palette(self) -> None:
        """显示命令面板 (^p)."""
        from .overlays import CommandPalette
        self.push_screen(
            CommandPalette(self._command_registry),
            callback=self._on_palette_command
        )

    def _on_palette_command(self, cmd: str) -> None:
        """命令面板选择后的回调."""
        if cmd:
            self._mount_message(Message.system(f"执行命令: {cmd}"))
            asyncio.create_task(self._handle_slash(cmd))

    # ----- Status Bar Actions -----

    def on_status_bar_model_clicked(self, event: StatusBar.ModelClicked) -> None:
        """点击状态栏模型按钮 → 切换模型."""
        self.action_show_model_overlay()

    def on_status_bar_perm_clicked(self, event: StatusBar.PermClicked) -> None:
        """点击状态栏权限按钮 → 切换权限模式."""
        modes = ["bypass", "auto", "ask"]
        current = self._session.permission_mode
        try:
            idx = modes.index(current)
            next_mode = modes[(idx + 1) % len(modes)]
        except ValueError:
            next_mode = "bypass"
        self._session.permission_mode = next_mode
        if self._status_bar:
            self._status_bar.permission_mode = next_mode
        self._mount_message(Message.system(f"✓ 权限模式: **{next_mode}**"))


# 顶层入口
def run(agent: Any, voice_enabled: bool = False, session_id: Optional[str] = None) -> None:
    app = HakusApp(agent, voice_enabled=voice_enabled, session_id=session_id)
    app.run()