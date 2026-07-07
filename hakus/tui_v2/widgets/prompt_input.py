"""
PromptInput — 底部多行输入条 (OpenCode 风格)

特点:
- 多行输入 (TextArea) — Shift+Enter 换行, Enter 发送
- 高度自动扩展 (3-12 行)
- 历史导航 (上/下箭头)
- Slash 命令补全弹出框
- 文件/代理引用 (@mentions, 文件路径)
- Shell 模式 (! 前缀)
- 附件支持 (图片/文件粘贴)
- 编辑器上下文显示
- 智能占位符
"""
from __future__ import annotations

import os
import base64
import mimetypes
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from textual.containers import Container, Horizontal, Vertical
from textual.widgets import TextArea, Static, ListView, ListItem, Label, Button
from textual.message import Message
from textual import events
from textual.reactive import reactive
from textual.geometry import Size

# 尝试导入 PIL 用于图片处理
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# 尝试导入 magic 用于文件类型检测
try:
    import magic
    MAGIC_AVAILABLE = True
except ImportError:
    MAGIC_AVAILABLE = False


class _PromptTextArea(TextArea):
    """TextArea 子类: 拦截 Enter 键用于发送, 仅 Shift+Enter 换行."""

    class TextChanged(Message):
        """输入文本变化消息 (冒泡到 PromptInput 用于触发斜杠补全)."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def _on_key(self, event: events.Key) -> None:
        # "enter" = 发送, "shift+enter" = 换行 (交给 TextArea 默认处理)
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            try:
                parent = self.parent
                while parent is not None:
                    if isinstance(parent, PromptInput):
                        # 斜杠弹窗可见时 → 补全命令而不是提交
                        if parent._slash_visible and parent._slash_matches:
                            parent._complete_slash()
                        else:
                            parent._submit()
                        break
                    parent = parent.parent
            except Exception:
                pass
            return

        # Tab = 斜杠补全 (TextArea 焦点下必须在这里拦截, 不会冒泡到父)
        if event.key == "tab":
            try:
                parent = self.parent
                while parent is not None:
                    if isinstance(parent, PromptInput):
                        if parent._slash_visible and parent._slash_matches:
                            event.prevent_default()
                            event.stop()
                            parent._complete_slash()
                        break
                    parent = parent.parent
            except Exception:
                pass
            return

        # Escape = 关闭斜杠弹窗
        if event.key == "escape":
            try:
                parent = self.parent
                while parent is not None:
                    if isinstance(parent, PromptInput):
                        if parent._slash_visible:
                            event.prevent_default()
                            event.stop()
                            parent._hide_slash_popup()
                        break
                    parent = parent.parent
            except Exception:
                pass
            return

        # Ctrl+P 命令面板 — 直接触发 App action, 不依赖 binding 冒泡
        if event.key == "ctrl+p":
            event.prevent_default()
            event.stop()
            try:
                from textual.app import get_app
                app = get_app()
                if hasattr(app, "action_show_command_palette"):
                    app.action_show_command_palette()
            except Exception:
                pass
            return

        # 其他 Ctrl+ 组合键让事件冒泡到 App
        if event.key.startswith("ctrl+"):
            return

        # Up/Down 导航历史 (仅在光标在首/末行时)
        # 但 popup 可见时优先用 ↑↓ 切换 popup 选中项
        if event.key == "up":
            try:
                parent = self.parent
                while parent is not None:
                    if isinstance(parent, PromptInput):
                        if parent._slash_visible:
                            event.prevent_default()
                            event.stop()
                            parent._move_slash_selection(-1)
                        elif self.cursor_location[0] == 0:
                            event.prevent_default()
                            event.stop()
                            parent._history_prev()
                        break
                    parent = parent.parent
            except Exception:
                pass
            return

        if event.key == "down":
            try:
                parent = self.parent
                while parent is not None:
                    if isinstance(parent, PromptInput):
                        if parent._slash_visible:
                            event.prevent_default()
                            event.stop()
                            parent._move_slash_selection(+1)
                        elif self.cursor_location[0] == self.document.line_count - 1:
                            event.prevent_default()
                            event.stop()
                            parent._history_next()
                        break
                    parent = parent.parent
            except Exception:
                pass
            return

        # 其他键: 交给 TextArea 默认处理
        super()._on_key(event)
        # 处理完后再发一个变化消息 (让父组件可以做补全/字符统计等)
        try:
            self.post_message(self.TextChanged(self.text))
        except Exception:
            pass


HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".hakus")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history")

# Slash commands for auto-completion
# 格式: (命令名, 简短描述)
SLASH_COMMANDS = [
    ("/help", "Show available commands"),
    ("/model", "Switch AI model"),
    ("/clear", "Clear conversation history"),
    ("/compact", "Compact context to save tokens"),
    ("/permission", "Manage tool permissions"),
    ("/cost", "Show token usage and cost"),
    ("/context", "Show current context info"),
    ("/tools", "List available tools"),
    ("/diff", "Show pending file changes"),
    ("/status", "Show system status"),
    ("/exit", "Exit HakusAI"),
    ("/verify", "Run verification checks"),
    ("/btw", "Ask a side question"),
    ("/checkpoint", "Save current state"),
    ("/rollback", "Rollback to checkpoint"),
    ("/task", "Manage background tasks"),
    ("/init", "Initialize project context"),
    ("/memory", "Manage persistent memory"),
    ("/plan", "Show current plan"),
    ("/todos", "Show todo list"),
    ("/tree", "Show project tree"),
    ("/git", "Git operations"),
    ("/voice", "Toggle voice input"),
    ("/spec", "Spec-driven development"),
    ("/orchestrate", "Multi-agent orchestration"),
    ("/debug", "Toggle debug logging"),
    ("/harness", "Toggle agent harness guard"),
]

# Agent references (@mentions)
AGENT_REFERENCES = [
    ("@build", "Build agent - implements features"),
    ("@plan", "Plan agent - creates implementation plans"),
    ("@debug", "Debug agent - investigates issues"),
    ("@test", "Test agent - writes and runs tests"),
    ("@review", "Review agent - code review"),
    ("@doc", "Documentation agent - writes docs"),
]

# File path completion helpers
def _matches_prefix(cmd_tuple, prefix: str) -> bool:
    """检查命令名是否以 prefix 开头 (大小写不敏感)."""
    return cmd_tuple[0].lower().startswith(prefix.lower())


class Attachment:
    """附件数据结构"""
    def __init__(self, name: str, mime: str, data: bytes, filepath: str = ""):
        self.name = name
        self.mime = mime
        self.data = data
        self.filepath = filepath
        self.id = f"att_{id(self)}"
    
    @property
    def is_image(self) -> bool:
        return self.mime.startswith("image/")
    
    @property
    def is_pdf(self) -> bool:
        return self.mime == "application/pdf"
    
    @property
    def is_text(self) -> bool:
        return self.mime.startswith("text/") or self.mime in (
            "application/json", "application/xml", "application/yaml"
        )
    
    @property
    def virtual_text(self) -> str:
        """显示在输入框中的虚拟文本"""
        if self.is_image:
            return f"[Image: {self.name}]"
        elif self.is_pdf:
            return f"[PDF: {self.name}]"
        elif self.is_text:
            return f"[File: {self.name}]"
        else:
            return f"[Attachment: {self.name}]"
    
    def to_base64(self) -> str:
        return base64.b64encode(self.data).decode("utf-8")
    
    def to_data_url(self) -> str:
        return f"data:{self.mime};base64,{self.to_base64()}"


class PromptInput(Container):
    """底部多行输入条 (OpenCode 风格)."""

    DEFAULT_CSS = """
    PromptInput {
        background: #141414;
        border-top: solid #3c3c3c;
        height: auto;
        min-height: 3;
        max-height: 24;
        padding: 0 1;
    }

    PromptInput .prompt-row {
        width: 100%;
        height: auto;
    }

    PromptInput .prompt-prefix {
        color: #56b6c2;
        text-style: bold;
        width: auto;
    }

    PromptInput .agent-badge {
        color: #fab283;
        text-style: bold;
        width: auto;
        padding: 0 1;
    }

    PromptInput .model-badge {
        color: #9d7cd8;
        width: auto;
        padding: 0 1;
    }

    PromptInput .mode-badge {
        color: #56b6c2;
        width: auto;
        padding: 0 1;
    }

    PromptInput TextArea {
        background: #141414;
        color: #eeeeee;
        border: none;
        width: 1fr;
        height: auto;
        min-height: 1;
        max-height: 8;
        padding: 0;
        margin: 0;
        scrollbar-size: 0 0;
    }

    PromptInput TextArea:focus {
        border: none;
    }

    PromptInput TextArea .cursor {
        background: #9d7cd8;
        color: #141414;
    }

    PromptInput .hint {
        color: #606060;
        height: 1;
        width: 100%;
    }

    /* 附件预览区 */
    PromptInput .attachments-bar {
        height: auto;
        min-height: 0;
        padding: 0 1;
        margin: 0;
    }

    PromptInput .attachment-item {
        height: 1;
        padding: 0 1;
        margin: 0 1 0 0;
        background: #1e1e1e;
        border: solid #3c3c3c;
        color: #eeeeee;
    }

    PromptInput .attachment-item:hover {
        background: #3c3c3c;
    }

    PromptInput .attachment-remove {
        color: #e06c75;
        margin-left: 1;
    }

    PromptInput .attachment-remove:hover {
        color: #ff6b6b;
        background: #3c3c3c;
    }

    /* 编辑器上下文显示 */
    PromptInput .editor-context {
        height: 1;
        padding: 0 1;
        margin: 0 1 0 0;
        background: #1e1e1e;
        border: solid #5c9cf5;
        color: #56b6c2;
    }

    PromptInput .editor-context.dismiss {
        color: #808080;
    }

    /* 占位符提示 */
    PromptInput .placeholder-hints {
        height: 1;
        color: #606060;
        padding: 0 1;
    }

    /* Shell 模式指示器 */
    PromptInput .shell-indicator {
        color: #e5c07b;
        text-style: bold;
        width: auto;
        padding: 0 1;
    }

    /* Claude Code 风格：popup 在输入框上方，无标题无边框 */
    PromptInput .slash-popup {
        display: none;
        background: #141414;
        height: auto;
        max-height: 12;
        width: 100%;
        padding: 0;
        margin: 0;
        border: none;
        dock: top;
    }

    PromptInput .slash-popup.visible {
        display: block;
    }

    PromptInput .slash-popup > ListView {
        background: transparent;
        height: auto;
        max-height: 12;
        width: 100%;
        padding: 0;
        margin: 0;
        border: none;
    }

    PromptInput .slash-popup > ListView > ListItem {
        background: transparent;
        color: #eeeeee;
        height: 1;
        width: 100%;
        padding: 0 1;
    }

    PromptInput .slash-popup > ListView > ListItem.-highlight {
        background: #1e1e1e;
        color: #eeeeee;
    }

    PromptInput .slash-cmd {
        color: #56b6c2;
        text-style: bold;
    }

    PromptInput .slash-popup > ListView > ListItem.-highlight .slash-cmd {
        color: #56b6c2;
    }

    PromptInput .slash-desc {
        color: #606060;
    }

    PromptInput .slash-popup > ListView > ListItem.-highlight .slash-desc {
        color: #808080;
    }

    /* 补全分类标题 */
    PromptInput .completion-category {
        color: #808080;
        text-style: bold;
        padding: 0 1;
        background: #1e1e1e;
    }
    """

    class Submitted(Message):
        """用户提交了消息."""
        def __init__(self, value: str, attachments: List[Attachment] = None, editor_context: str = "") -> None:
            self.value = value
            self.attachments = attachments or []
            self.editor_context = editor_context
            super().__init__()

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._history: List[str] = []
        self._history_index: int = -1
        self._temp_buffer: str = ""  # 保存当前输入当翻历史时恢复
        self._slash_index: int = 0
        self._slash_matches: List[tuple] = []
        self._slash_visible: bool = False
        self._slash_category: str = "commands"  # commands, agents, files
        self._attachments: List[Attachment] = []
        self._editor_context: str = ""
        self._editor_context_path: str = ""
        self._mode: str = "normal"  # normal, shell
        self._completion_type: str = "slash"  # slash, agent, file
        self._load_history()

    def compose(self):
        # 编辑器上下文栏 (如果有)
        yield Static("", classes="editor-context", id="editor-context-bar")
        
        # 附件预览栏
        yield Horizontal(classes="attachments-bar", id="attachments-bar")
        
        # 提示行 (Shell 模式指示器 / 占位符提示)
        yield Static("", classes="placeholder-hints", id="placeholder-hints")
        
        # 主输入行
        yield Horizontal(
            Static("> ", classes="prompt-prefix", id="prompt-prefix"),
            Static("", classes="shell-indicator", id="shell-indicator"),
            Static("", classes="agent-badge", id="agent-badge"),
            Static("", classes="model-badge", id="model-badge"),
            Static("", classes="mode-badge", id="mode-badge"),
            _PromptTextArea("", id="prompt-area"),
            classes="prompt-row",
        )
        
        yield Static(
            "Enter 发送 · Shift+Enter 换行 · Esc 中断 · Ctrl+C 退出 · ! Shell · @Agent · /Command",
            classes="hint",
        )
        
        # 斜杠命令补全 — Claude Code 风格纯净下拉
        with Vertical(classes="slash-popup"):
            yield ListView(id="slash-list")

    def on_mount(self) -> None:
        try:
            area = self.query_one("#prompt-area", TextArea)
            area.focus()
        except Exception:
            pass
        
        self._update_ui_state()

    def _update_ui_state(self) -> None:
        """更新 UI 状态显示"""
        try:
            # Shell 模式指示器
            shell_indicator = self.query_one("#shell-indicator", Static)
            if self._mode == "shell":
                shell_indicator.update("$ ")
                shell_indicator.add_class("shell-indicator")
            else:
                shell_indicator.update("")
            
            # Agent badge
            agent_badge = self.query_one("#agent-badge", Static)
            # 从 app 获取当前 agent
            try:
                app = self.app
                if hasattr(app, '_agent') and hasattr(app._agent, '_agent'):
                    agent_name = app._agent._agent.current() if hasattr(app._agent._agent, 'current') else None
                    if agent_name:
                        agent_badge.update(f"@{agent_name} ")
                    else:
                        agent_badge.update("")
                else:
                    agent_badge.update("")
            except Exception:
                agent_badge.update("")
            
            # Model badge
            model_badge = self.query_one("#model-badge", Static)
            try:
                app = self.app
                if hasattr(app, '_session') and hasattr(app._session, 'model_name'):
                    model_badge.update(f"[{app._session.model_name}] ")
                else:
                    model_badge.update("")
            except Exception:
                model_badge.update("")
            
            # 附件预览
            self._update_attachments_bar()
            
            # 编辑器上下文
            self._update_editor_context_bar()
            
            # 占位符提示
            self._update_placeholder_hints()
            
        except Exception:
            pass

    def _update_attachments_bar(self) -> None:
        """更新附件预览栏"""
        try:
            bar = self.query_one("#attachments-bar", Horizontal)
            bar.remove_children()
            for att in self._attachments:
                remove_btn = Button("✕", classes="attachment-remove", id=f"att-remove-{att.id}")
                remove_btn.data_attachment_id = att.id
                bar.mount(
                    Horizontal(
                        Static(att.virtual_text),
                        remove_btn,
                        classes="attachment-item",
                    )
                )
        except Exception:
            pass

    def _update_editor_context_bar(self) -> None:
        """更新编辑器上下文栏"""
        try:
            bar = self.query_one("#editor-context-bar", Static)
            if self._editor_context:
                bar.update(f"📝 {self._editor_context_path} (按 Ctrl+E 移除)")
                bar.remove_class("dismiss")
            else:
                bar.update("")
                bar.add_class("dismiss")
        except Exception:
            pass

    def _update_placeholder_hints(self) -> None:
        """更新占位符提示"""
        try:
            hints = self.query_one("#placeholder-hints", Static)
            area = self.query_one("#prompt-area", _PromptTextArea)
            if not area.text and not self._attachments and not self._editor_context:
                if self._mode == "shell":
                    hints.update('Shell 模式 · 输入命令 · "exit" 退出')
                else:
                    hints.update('输入提问 · ! 进入 Shell · @ 引用 Agent · / 命令 · Ctrl+V 粘贴文件')
            else:
                hints.update("")
        except Exception:
            pass

    # ----- Text change handling -----

    async def on__prompt_text_area_text_changed(self, event: _PromptTextArea.TextChanged) -> None:
        """监听 TextArea 内容变化, 触发斜杠补全."""
        await self._check_completion()
        self._update_ui_state()

    def on_key(self, event: events.Key) -> None:
        """Container 层级兜底 — 拦截弹窗关闭 (Escape), 焦点回到 TextArea."""
        if event.key == "escape" and self._slash_visible:
            event.prevent_default()
            event.stop()
            self._hide_slash_popup()
            try:
                self.query_one("#prompt-area", TextArea).focus()
            except Exception:
                pass
            return

        # Ctrl+E = 移除编辑器上下文
        if event.key == "ctrl+e":
            if self._editor_context:
                event.prevent_default()
                event.stop()
                self._clear_editor_context()
            return

        # Ctrl+P 等 Ctrl 组合键: 不拦截, 让 Textual 绑定系统处理

    def _submit(self) -> None:
        """Submit the current input."""
        try:
            area = self.query_one("#prompt-area", TextArea)
            text = area.text.strip()
            if not text and not self._attachments and not self._editor_context:
                return
            
            # 保存历史
            if text:
                self.push_history(text)
            
            # 准备提交数据
            attachments = self._attachments.copy()
            editor_context = self._editor_context
            
            # 清空输入
            area.clear()
            self._attachments.clear()
            self._editor_context = ""
            self._editor_context_path = ""
            self._mode = "normal"
            
            self.post_message(self.Submitted(text, attachments, editor_context))
            self._update_ui_state()
        except Exception:
            pass

    # ----- History -----

    def _load_history(self) -> None:
        if not os.path.exists(HISTORY_FILE):
            return
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                self._history = [line.rstrip("\n") for line in f if line.strip()]
        except Exception:
            self._history = []

    def _save_history(self) -> None:
        try:
            os.makedirs(HISTORY_DIR, exist_ok=True)
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                for line in self._history[-1000:]:
                    f.write(line + "\n")
        except Exception:
            pass

    def push_history(self, text: str) -> None:
        if not text:
            return
        if self._history and self._history[-1] == text:
            return
        self._history.append(text)
        self._save_history()
        self._history_index = -1
        self._temp_buffer = ""

    def _history_prev(self) -> None:
        if not self._history:
            return
        try:
            area = self.query_one("#prompt-area", TextArea)
        except Exception:
            return
        if self._history_index == -1:
            self._temp_buffer = area.text
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        area.load_text(self._history[self._history_index])

    def _history_next(self) -> None:
        if not self._history or self._history_index == -1:
            return
        try:
            area = self.query_one("#prompt-area", TextArea)
        except Exception:
            return
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            area.load_text(self._history[self._history_index])
        else:
            self._history_index = -1
            area.load_text(self._temp_buffer)

    # ----- Completion System -----

    async def _check_completion(self) -> None:
        """统一补全检查: /命令, @Agent, 文件路径"""
        try:
            area = self.query_one("#prompt-area", TextArea)
            text = area.text
            cursor_pos = area.cursor_location[1]  # 列位置
        except Exception:
            return

        # 获取光标前的词
        line = text.split("\n")[-1] if "\n" in text else text
        before_cursor = line[:cursor_pos]

        # Shell 模式下不显示补全
        if self._mode == "shell":
            self._hide_slash_popup()
            return

        # 检查 / 命令
        if before_cursor.startswith("/") and " " not in before_cursor and "\n" not in before_cursor:
            prefix = before_cursor.lower()
            self._slash_matches = [
                cmd for cmd in SLASH_COMMANDS
                if _matches_prefix(cmd, prefix)
            ]
            self._completion_type = "slash"
            if self._slash_matches:
                self._slash_index = 0
                await self._show_completion_popup()
                return

        # 检查 @ Agent 引用
        if "@" in before_cursor:
            at_pos = before_cursor.rfind("@")
            prefix = before_cursor[at_pos:].lower()
            if " " not in prefix and "\n" not in prefix:
                self._slash_matches = [
                    cmd for cmd in AGENT_REFERENCES
                    if _matches_prefix(cmd, prefix)
                ]
                self._completion_type = "agent"
                if self._slash_matches:
                    self._slash_index = 0
                    await self._show_completion_popup()
                    return

        # 检查文件路径 (以 ./ 或 ../ 或 ~/ 开头)
        if before_cursor.startswith(("./", "../", "~/")) and " " not in before_cursor:
            self._slash_matches = self._complete_file_paths(before_cursor)
            self._completion_type = "file"
            if self._slash_matches:
                self._slash_index = 0
                await self._show_completion_popup()
                return

        self._hide_slash_popup()

    def _complete_file_paths(self, prefix: str) -> List[tuple]:
        """文件路径补全"""
        try:
            base_dir = os.getcwd()
            if prefix.startswith("~/"):
                prefix = os.path.expanduser(prefix)
            elif prefix.startswith("./"):
                prefix = prefix[2:]
            elif prefix.startswith("../"):
                pass  # 保持相对路径

            dir_part = os.path.dirname(prefix) or "."
            file_part = os.path.basename(prefix)

            full_dir = os.path.join(base_dir, dir_part) if not os.path.isabs(dir_part) else dir_part
            if not os.path.exists(full_dir):
                return []

            matches = []
            for entry in os.listdir(full_dir):
                if entry.startswith(file_part):
                    full_path = os.path.join(dir_part, entry)
                    if os.path.isdir(os.path.join(full_dir, entry)):
                        full_path += "/"
                    matches.append((full_path, f"File: {entry}"))
            return matches[:20]
        except Exception:
            return []

    async def _show_completion_popup(self) -> None:
        """显示补全弹出框"""
        self._slash_visible = True
        try:
            popup = self.query_one(".slash-popup", Vertical)
            popup.add_class("visible")
            list_view = self.query_one("#slash-list", ListView)
            await list_view.clear()
            
            category_labels = {
                "slash": "Commands",
                "agent": "Agents",
                "file": "Files",
            }
            category = category_labels.get(self._completion_type, "Completions")
            
            # 添加分类标题
            title_item = ListItem(Static(category, classes="completion-category"))
            await list_view.append(title_item)
            
            for cmd, desc in self._slash_matches:
                label_text = f"[b cyan]{cmd}[/]  [dim #8a8ab8]{desc}[/]"
                item = ListItem(Label(label_text, markup=True))
                await list_view.append(item)
            
            if len(list_view.children) > 1:
                list_view.index = 1  # 跳过标题
            # 不 focus list_view — 焦点保留在 TextArea
        except Exception:
            pass

    def _hide_slash_popup(self) -> None:
        """隐藏补全弹出框"""
        self._slash_visible = False
        try:
            popup = self.query_one(".slash-popup", Vertical)
            popup.remove_class("visible")
            try:
                self.query_one("#prompt-area", TextArea).focus()
            except Exception:
                pass
        except Exception:
            pass

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """ListView 选中项变化时同步 _slash_index"""
        if not self._slash_visible:
            return
        try:
            list_view = self.query_one("#slash-list", ListView)
            if list_view.index is not None and list_view.index > 0:  # 跳过标题
                self._slash_index = list_view.index - 1
        except Exception:
            pass

    def _move_slash_selection(self, delta: int) -> None:
        """移动 popup 中选中项"""
        if not self._slash_matches:
            return
        try:
            list_view = self.query_one("#slash-list", ListView)
            count = len(self._slash_matches)
            if count == 0:
                return
            self._slash_index = (self._slash_index + delta) % count
            list_view.index = self._slash_index + 1  # +1 跳过标题
        except Exception:
            pass

    def _complete_slash(self) -> None:
        """Complete the current completion."""
        if not self._slash_matches:
            return
        try:
            if self._slash_index >= len(self._slash_matches):
                self._slash_index = 0
            area = self.query_one("#prompt-area", TextArea)
            cmd, _ = self._slash_matches[self._slash_index]
            
            if self._completion_type == "agent":
                # @agent 引用: 插入 @agent 并在后面加空格
                area.insert_text(cmd[1:] + " ")  # 去掉 @ 前缀再加
            elif self._completion_type == "file":
                # 文件路径: 替换当前词
                text = area.text
                cursor_col = area.cursor_location[1]
                line = text.split("\n")[-1]
                before = line[:cursor_col]
                # 找到最后一个分隔符
                for sep in ["/", "\\", " "]:
                    pos = before.rfind(sep)
                    if pos >= 0:
                        before = before[:pos+1]
                        break
                area.load_text(text[:-(len(line) - cursor_col)] + before + cmd + " ")
            else:
                area.load_text(cmd + " ")
            
            area.cursor_location = (0, len(area.text))
            area.focus()
        except Exception:
            pass
        self._hide_slash_popup()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """处理弹窗中点击/回车选中命令的事件."""
        if not self._slash_visible:
            return
        try:
            list_view = self.query_one("#slash-list", ListView)
            if list_view.index is not None and list_view.index > 0:
                self._slash_index = list_view.index - 1
            self._complete_slash()
        except Exception:
            pass

    # ----- Attachment Handling -----

    def on_paste(self, event: events.Paste) -> None:
        """处理粘贴事件 - 支持文件/图片粘贴"""
        if not event.data:
            return
        
        # 检查是否有文件路径
        for fmt in event.data.formats:
            if fmt.mime == "text/uri-list":
                uris = event.data.get(fmt).decode("utf-8").strip().split("\n")
                for uri in uris:
                    uri = uri.strip()
                    if uri.startswith("file://"):
                        path = uri[7:]  # 移除 file://
                        self._add_file_attachment(path)
                event.prevent_default()
                return
            
            # Windows 可能发送文本路径
            if fmt.mime == "text/plain":
                text = event.data.get(fmt).decode("utf-8").strip()
                if os.path.exists(text) and not text.startswith(("http://", "https://")):
                    self._add_file_attachment(text)
                    event.prevent_default()
                    return

    def _add_file_attachment(self, filepath: str) -> None:
        """添加文件附件"""
        try:
            path = Path(filepath).expanduser().resolve()
            if not path.exists():
                return
            
            # 检测 MIME 类型
            mime, _ = mimetypes.guess_type(str(path))
            if not mime:
                if MAGIC_AVAILABLE:
                    mime = magic.from_file(str(path), mime=True)
                else:
                    mime = "application/octet-stream"
            
            # 读取文件数据
            data = path.read_bytes()
            
            # 大小限制 (10MB)
            if len(data) > 10 * 1024 * 1024:
                self._notify(f"文件过大: {path.name} (>10MB)")
                return
            
            attachment = Attachment(path.name, mime, data, str(path))
            self._attachments.append(attachment)
            self._update_ui_state()
            self._notify(f"已添加附件: {attachment.virtual_text}")
        except Exception as e:
            self._notify(f"添加附件失败: {e}")

    def _notify(self, message: str) -> None:
        """显示通知"""
        try:
            if hasattr(self.app, '_notification_bar'):
                self.app._notification_bar.show(message)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """处理附件移除按钮"""
        if event.button.id and event.button.id.startswith("att-remove-"):
            att_id = event.button.id[len("att-remove-"):]
            self._attachments = [a for a in self._attachments if a.id != att_id]
            self._update_ui_state()
            event.stop()

    # ----- Editor Context -----

    def set_editor_context(self, filepath: str, selection: str = "") -> None:
        """设置编辑器上下文"""
        self._editor_context_path = filepath
        filename = os.path.basename(filepath)
        if selection:
            self._editor_context = f"用户选中了 {filename} 的内容"
        else:
            self._editor_context = f"用户打开了文件 {filename}"
        self._update_ui_state()

    def _clear_editor_context(self) -> None:
        """清除编辑器上下文"""
        self._editor_context = ""
        self._editor_context_path = ""
        self._update_ui_state()

    # ----- Shell Mode -----

    def action_toggle_shell(self) -> None:
        """切换 Shell 模式"""
        try:
            area = self.query_one("#prompt-area", TextArea)
            if area.text.strip() == "!":
                self._mode = "shell" if self._mode == "normal" else "normal"
                area.clear()
                self._update_ui_state()
        except Exception:
            pass

    def focus_input(self) -> None:
        try:
            self.query_one("#prompt-area", TextArea).focus()
        except Exception:
            pass
