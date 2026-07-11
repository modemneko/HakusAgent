"""
AssistantText — 助手消息 (OpenCode 风格 Part-based 渲染)

特点:
- 按 Part 类型渲染: text, reasoning, tool, file, compaction
- Reasoning 可折叠 (思维块)
- Tool 调用显示输入/输出
- 文件引用显示
- 无 Panel 边框 (解决 Panel 边框过长)
- 流式渲染支持
"""
from __future__ import annotations

import time
from typing import Optional, List

from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Markdown, Static, Collapsible
from textual import events

from ..messages import Message, Part, PartType, ToolState

# Throttle: minimum interval between Markdown re-renders (seconds)
_THROTTLE_INTERVAL = 0.1  # 100ms


class ReasoningBlock(Container):
    """思维块 - 可折叠的推理内容"""

    DEFAULT_CSS = """
    ReasoningBlock {
        margin: 1 0;
        padding: 0 1;
        background: #141414;
        border-left: thick #9d7cd8;
        height: auto;
    }

    ReasoningBlock.collapsed {
        background: #0a0a0a;
    }

    ReasoningBlock .reasoning-summary {
        color: #808080;
        text-style: italic;
        padding: 0 1;
    }

    ReasoningBlock .reasoning-content {
        color: #eeeeee;
        padding-left: 2;
    }

    ReasoningBlock CollapsibleTitle {
        background: #0a0a0a;
        color: #9d7cd8;
        padding: 0 1;
    }
    """

    def __init__(self, part: Part, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._part = part

    def compose(self):
        collapsed = self._part.metadata.get("collapsed", False)
        summary = self._part.metadata.get("summary", "Thinking...")
        with Collapsible(title=f"💭 {summary}", collapsed=collapsed):
            yield Markdown(self._part.text or "", classes="reasoning-content")


class ToolCallBlock(Container):
    """工具调用块 - 显示工具输入/输出"""

    DEFAULT_CSS = """
    ToolCallBlock {
        margin: 1 0;
        padding: 0 1;
        background: #141414;
        border-left: thick #e5c07b;
        height: auto;
    }

    ToolCallBlock.error {
        border-left: thick #e06c75;
    }

    ToolCallBlock .tool-header {
        height: 1;
        color: #e5c07b;
        text-style: bold;
    }

    ToolCallBlock.error .tool-header {
        color: #e06c75;
    }

    ToolCallBlock .tool-args {
        color: #606060;
        padding-left: 2;
    }

    ToolCallBlock .tool-result {
        color: #eeeeee;
        padding-left: 2;
    }

    ToolCallBlock .tool-duration {
        color: #808080;
        text-style: italic;
    }
    """

    def __init__(self, part: Part, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._part = part
        if part.tool_state == ToolState.ERROR:
            self.add_class("error")

    def compose(self):
        # Header
        duration = ""
        if self._part.tool_duration is not None:
            duration = f" · {self._part.tool_duration:.1f}s"
        status = "✓" if self._part.tool_state == ToolState.COMPLETED else "✗"
        yield Static(f"{status} {self._part.tool_name}{duration}", classes="tool-header")

        # Args (collapsible if long)
        args_text = str(self._part.tool_args)
        if args_text and args_text != "{}":
            with Collapsible(title="📥 参数", collapsed=len(args_text) > 200):
                yield Static(f"```json\n{args_text}\n```", classes="tool-args", markup=True)

        # Result
        result = self._part.tool_result
        if result:
            with Collapsible(title="📤 结果", collapsed=len(result) > 800):
                yield Markdown(result or "(无输出)", classes="tool-result")

        # Error
        if self._part.tool_error:
            with Collapsible(title="⚠ 错误", collapsed=False):
                yield Static(self._part.tool_error, classes="tool-result", markup=True)


class FileBlock(Container):
    """文件引用块"""

    DEFAULT_CSS = """
    FileBlock {
        margin: 1 0;
        padding: 0 1;
        background: #141414;
        border-left: thick #5c9cf5;
        height: auto;
    }

    FileBlock .file-header {
        color: #56b6c2;
        text-style: bold;
    }

    FileBlock .file-path {
        color: #808080;
    }
    """

    def __init__(self, part: Part, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._part = part

    def compose(self):
        yield Static(f"📄 {self._part.file_path}", classes="file-header")
        if self._part.file_size > 0:
            size_kb = self._part.file_size / 1024
            yield Static(f"{size_kb:.1f} KB · {self._part.file_mime}", classes="file-path")


class CompactionBlock(Container):
    """压缩/摘要块"""

    DEFAULT_CSS = """
    CompactionBlock {
        margin: 1 0;
        border: thick #9d7cd8;
        height: auto;
    }

    CompactionBlock .compaction-title {
        background: #9d7cd8;
        color: #0a0a0a;
        text-style: bold;
        text-align: center;
        padding: 0 1;
    }

    CompactionBlock .compaction-content {
        padding: 1;
        background: #141414;
    }
    """

    def __init__(self, part: Part, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._part = part

    def compose(self):
        yield Static("📝 上下文已压缩", classes="compaction-title")
        yield Markdown(self._part.text or "", classes="compaction-content")


class ActivityBlock(Static):
    """AI 执行状态滚动块 — 嵌在 AssistantText 顶部.

    视觉风格 (参照 OpenCode inline activity):
    - 高度固定 3 行, 新活动从底部进入, 旧活动向上滚动
    - 上下边框极暗, 仿佛融入黑色背景 (渐变感)
    - 3 行文字亮度从上到下递减: 旧活动暗, 当前活动最亮
    - Turn 结束后自动收起
    """

    DEFAULT_CSS = """
    ActivityBlock {
        dock: top;
        height: 0;
        min-height: 0;
        max-height: 3;
        background: #0a0a0a;
        color: #808080;
        border-top: none;
        border-bottom: none;
        margin: 0 0 0 0;
        padding: 0 1;
        overflow: hidden;
    }

    ActivityBlock.active {
        height: 3;
        min-height: 3;
        border-top: solid #0f0f0f;
        border-bottom: solid #0f0f0f;
        margin: 0 0 1 0;
    }
    """

    VISIBLE_LINES = 3

    # 亮度梯度: 最旧 -> 最新 (Rich markup 颜色)
    _LINE_TONES = ["#303030", "#707070", "#eeeeee"]

    def __init__(self, **kwargs: object) -> None:
        super().__init__("", markup=True, **kwargs)
        self._lines: List[str] = []

    def show(self) -> None:
        self.add_class("active")
        self.styles.height = "3"
        self.styles.min_height = "3"
        self.refresh(layout=True)

    def hide(self) -> None:
        self.remove_class("active")
        self.styles.height = "0"
        self.styles.min_height = "0"
        self._lines.clear()
        self.update("")
        self.refresh(layout=True)

    def add_activity(self, text: str) -> None:
        self._lines.append(text)
        self.show()
        # 取最后 VISIBLE_LINES 行, 最新的在最下面
        visible = self._lines[-self.VISIBLE_LINES:]
        # 补齐空行以保持 3 行固定高度
        while len(visible) < self.VISIBLE_LINES:
            visible.insert(0, "")
        # 应用亮度渐变: 越新越亮
        rendered: List[str] = []
        for i, line in enumerate(visible):
            tone = self._LINE_TONES[i]
            safe = (line or "").replace("[", "[[").replace("]", "]]")
            rendered.append(f"[{tone}]{safe}[/{tone}]")
        self.update("\n".join(rendered))



class AssistantText(Container):
    """助手消息 — Part-based 渲染

    CSS 类: AssistantText (在 theme.tcss 中定义).
    """

    DEFAULT_CSS = """
    AssistantText {
        margin: 1 0;
        padding: 0 1;
        height: auto;
    }

    AssistantText .assistant-dot {
        color: #9d7cd8;
        text-style: bold;
        width: 100%;
        height: 1;
    }

    AssistantText .assistant-content {
        width: 100%;
        height: auto;
        background: transparent;
    }

    AssistantText .part-container {
        margin: 0 0 1 0;
    }
    """

    def __init__(self, message: Optional[Message] = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._message = message
        self._streaming_buffer: str = ""
        self._md_view: Optional[Markdown] = None
        self._activity_block: Optional[ActivityBlock] = None
        self._last_render_ts: float = 0.0
        self._pending_render: bool = False
        self._finalized: bool = False

    def compose(self):
        yield Static("● HakusAI", classes="assistant-dot")
        self._activity_block = ActivityBlock(id="assistant-activity")
        yield self._activity_block
        if self._message and self._message.parts:
            # Part-based 渲染
            with Vertical(classes="part-container"):
                for part in self._message.parts:
                    yield self._create_part_widget(part)
            self._finalized = True
            if self._activity_block is not None:
                self._activity_block.hide()
        elif self._message and self._message.content:
            # 向后兼容: 纯文本内容
            yield Markdown(self._message.content, classes="assistant-content")
            self._finalized = True
            if self._activity_block is not None:
                self._activity_block.hide()
        else:
            # 流式开始
            md = Markdown("", classes="assistant-content")
            yield md

    def _create_part_widget(self, part: Part):
        """根据 part 类型创建对应的 widget"""
        if part.type == PartType.TEXT:
            if part.text:
                return Markdown(part.text, classes="assistant-content")
        elif part.type == PartType.REASONING:
            return ReasoningBlock(part)
        elif part.type == PartType.TOOL:
            return ToolCallBlock(part)
        elif part.type == PartType.FILE:
            return FileBlock(part)
        elif part.type == PartType.COMPACTION:
            return CompactionBlock(part)
        return Static("")

    def on_mount(self) -> None:
        if not self._finalized:
            try:
                self._md_view = self.query_one(".assistant-content", Markdown)
            except Exception:
                self._md_view = None

    def update_activity(self, text: str) -> None:
        if self._activity_block is not None:
            self._activity_block.add_activity(text)

    def hide_activity(self) -> None:
        if self._activity_block is not None:
            self._activity_block.hide()

    def append_delta(self, token: str) -> None:
        """流式追加文本 — 实时渲染 Markdown (节流 100ms)."""
        if self._finalized:
            return
        self._streaming_buffer += token
        now = time.monotonic()
        # Throttle: only re-render every 100ms
        if now - self._last_render_ts >= _THROTTLE_INTERVAL:
            self._render_markdown()
            self._last_render_ts = now
            self._pending_render = False
        else:
            self._pending_render = True

    def finalize(self, content: Optional[str] = None) -> None:
        """流式结束后做最终 canonical 渲染."""
        if self._finalized:
            return
        self._finalized = True
        final_content = content or self._streaming_buffer
        if not final_content:
            return
        # Remove old Markdown widget and mount a fresh one
        try:
            old_md = self.query_one(".assistant-content", Markdown)
            old_md.remove()
        except Exception:
            pass
        md = Markdown(final_content, classes="assistant-content")
        self.mount(md)
        self._md_view = md

    def _render_markdown(self) -> None:
        """Re-render the current streaming buffer as Markdown."""
        if self._md_view is None:
            return
        try:
            self._md_view.update(self._streaming_buffer)
        except Exception:
            pass

    @property
    def content(self) -> str:
        return self._streaming_buffer or (self._message.content if self._message else "")

    # Backward compatibility aliases
    def append_text(self, token: str) -> None:
        """Backward compat alias for append_delta."""
        self.append_delta(token)

    def set_markdown(self, content: str) -> None:
        """Backward compat alias for finalize."""
        self.finalize(content)
