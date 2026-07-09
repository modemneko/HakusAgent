"""
MessageList — 可滚动消息区

简化设计 (移除不稳定的虚拟化):
- 维护 self._messages (全部历史 dataclass)
- 所有 widget 直接 mount, 不做 eviction
- 滚动到底部自动跟随新消息
- 历史超过 MAX_MESSAGES 时裁剪最旧的
"""
from __future__ import annotations

from typing import List, Optional

from textual.containers import ScrollableContainer
from textual.widgets import Static

from ..messages import Message, Part, PartType
from .assistant_text import AssistantText
from .command_result import CommandResult
from .error_block import ErrorBlock
from .tool_result import ToolResult
from .user_bubble import UserBubble

MAX_MESSAGES = 500


class MessageList(ScrollableContainer):
    """消息列表容器.

    CSS: #message-list (在 theme.tcss中theme.tcss定义).
    """

    DEFAULT_CSS = """
    MessageList {
        padding: 1 2;
        background: #0a0a0a;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._messages: List[Message] = []
        self._streaming_widget: Optional[AssistantText] = None
        self._auto_scroll: bool = True

    def compose(self):
        return []

    def _check_auto_scroll(self) -> None:
        """检测是否在底部, 决定是否自动跟随."""
        try:
            if self.max_scroll_y > 0:
                self._auto_scroll = self.scroll_y >= self.max_scroll_y - 2
        except Exception:
            self._auto_scroll = True

    def _scroll_to_end_if_needed(self) -> None:
        """如果之前在底部, 滚动到最底部."""
        if self._auto_scroll:
            try:
                self.scroll_end(animate=False)
            except Exception:
                pass

    # ----- Data API -----

    def add_message(self, message: Message) -> None:
        self._check_auto_scroll()
        self._messages.append(message)
        widget = self._create_widget(message)
        self.mount(widget)
        self._trim_old()
        self._scroll_to_end_if_needed()

    def append_assistant_stream(self) -> AssistantText:
        self._check_auto_scroll()
        msg = Message(role="assistant", parts=[])
        self._messages.append(msg)
        widget = AssistantText(msg)
        self._streaming_widget = widget
        self.mount(widget)
        self._trim_old()
        self._scroll_to_end_if_needed()
        return widget

    def mount_tool(self, message: Message) -> None:
        self._check_auto_scroll()
        self._messages.append(message)
        widget = self._create_widget(message)
        self.mount(widget)
        self._trim_old()
        self._scroll_to_end_if_needed()

    def mount_command(self, message: Message) -> None:
        self._check_auto_scroll()
        self._messages.append(message)
        widget = self._create_widget(message)
        self.mount(widget)
        self._trim_old()
        self._scroll_to_end_if_needed()

    def mount_error(self, message: Message) -> None:
        self._check_auto_scroll()
        self._messages.append(message)
        widget = self._create_widget(message)
        self.mount(widget)
        self._trim_old()
        self._scroll_to_end_if_needed()

    def mount_widget(self, widget) -> None:
        self._check_auto_scroll()
        self.mount(widget)
        self._scroll_to_end_if_needed()

    def clear_messages(self) -> None:
        self._messages.clear()
        for child in list(self.children):
            child.remove()
        self._streaming_widget = None

    def all_messages(self) -> List[Message]:
        return list(self._messages)

    def replace_last_assistant(self, content: str) -> None:
        if not self._messages:
            return
        for i in range(len(self._messages) - 1, -1, -1):
            if self._messages[i].role == "assistant":
                # 保留 parts 结构，更新最后一个 text part
                msg = self._messages[i]
                text_parts = msg.get_text_parts()
                if text_parts:
                    text_parts[-1].text = content
                else:
                    msg.add_part(Part(type=PartType.TEXT, text=content))
                break

    def _trim_old(self) -> None:
        """裁剪最旧的消息, 保持 MAX_MESSAGES 上限."""
        if len(self._messages) <= MAX_MESSAGES:
            return
        excess = len(self._messages) - MAX_MESSAGES
        self._messages = self._messages[excess:]
        # 移除最旧的子 widget
        children = list(self.children)
        for child in children[:excess]:
            try:
                child.remove()
            except Exception:
                pass

    def _create_widget(self, msg: Message):
        if msg.role == "user":
            return UserBubble(msg)
        elif msg.role == "assistant":
            return AssistantText(msg)
        elif msg.role == "tool":
            return ToolResult(msg)
        elif msg.role in ("command", "system"):
            return CommandResult(msg)
        elif msg.role == "error" or msg.is_error:
            return ErrorBlock(msg)
        return Static(msg.content)
