"""
UserBubble — 用户消息气泡 (OpenCode 风格 Part-based)

特点:
- 支持文本、文件、图片、工具结果引用
- 背景色 + 左侧粗边框 (无外框 Panel — 解决 Panel 边框过长)
- 与 OpenCode UserPromptMessage 一致: 消息**只**出现在 MessageList, 不在 stdout echo
"""
from __future__ import annotations

from textual.containers import Container, Vertical
from textual.widgets import Static

from ..messages import Message, Part, PartType


class UserBubble(Container):
    """用户消息气泡 - Part-based 渲染.

    CSS 类: UserBubble (在 theme.tcss 中定义).
    """

    DEFAULT_CSS = """
    UserBubble {
        background: transparent;
        margin: 0;
        padding: 0 1;
        height: auto;
        border-left: tall #3c3c3c;
    }

    UserBubble .bubble-prefix {
        color: #5c9cf5;
        text-style: bold;
        width: 100%;
        height: 1;
    }

    UserBubble .bubble-text {
        color: #eeeeee;
        width: 100%;
        height: auto;
    }

    UserBubble .bubble-file {
        color: #56b6c2;
        margin: 0 0 0 2;
    }

    UserBubble .bubble-image {
        margin: 0 0 0 2;
    }
    """

    def __init__(self, message: Message, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._message = message

    def compose(self):
        yield Static("用户:", classes="bubble-prefix")

        # 支持 Part-based 渲染 (直接 yield, 避免中间容器被拉伸)
        if self._message.parts:
            for part in self._message.parts:
                yield from self._render_part(part)
        else:
            # 向后兼容: 纯文本
            text = self._message.content
            MAX = 10_000
            if len(text) > MAX:
                head = text[:2500]
                tail = text[-2500:]
                text = f"{head}\n… [已截断] …\n{tail}"
            yield Static(text, classes="bubble-text", markup=False)

    def _render_part(self, part: Part):
        """根据 part 类型渲染"""
        if part.type == PartType.TEXT:
            text = part.text
            MAX = 10_000
            if len(text) > MAX:
                head = text[:2500]
                tail = text[-2500:]
                text = f"{head}\n… [已截断] …\n{tail}"
            yield Static(text, classes="bubble-text", markup=False)
        
        elif part.type == PartType.FILE:
            # 文件引用
            filename = part.file_path or "未知文件"
            size_kb = part.file_size / 1024 if part.file_size > 0 else 0
            yield Static(
                f"📄 {filename} ({size_kb:.1f} KB, {part.file_mime})",
                classes="bubble-file",
            )
        
        elif part.type == PartType.IMAGE:
            # 图片引用
            filename = part.file_path or "image"
            yield Static(
                f"🖼️ {filename}",
                classes="bubble-image",
            )
        
        elif part.type == PartType.TOOL:
            # 用户消息中的工具引用 (如用户触发的工具)
            yield Static(
                f"🔧 {part.tool_name}",
                classes="bubble-text",
            )
