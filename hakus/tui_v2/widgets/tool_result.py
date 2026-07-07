"""
ToolResult — 工具结果 (Part-based 渲染, 兼容旧版 Message)

设计:
- 使用新的 PartType.TOOL 渲染
- 兼容旧版 Message.tool_* 字段
- 默认折叠 (>800 字符)
- 标题: `✓ ToolName · 0.5s` (OpenCode 风格)
"""

from __future__ import annotations

from textual.containers import Container
from textual import events
from textual.widgets import Collapsible, Markdown, Static

from ..messages import Message, Part, PartType, ToolState


class ToolResult(Container):
    """工具结果 — Part-based 渲染, 兼容旧版"""

    DEFAULT_CSS = """
    ToolResult {
        margin: 1 0;
        border-left: thick #e5c07b;
        height: auto;
    }

    ToolResult.error {
        border-left: thick #e06c75;
    }

    ToolResult Collapsible {
        background: #0a0a0a;
    }

    ToolResult CollapsibleTitle {
        background: #0a0a0a;
        color: #e5c07b;
        padding: 0 1;
    }

    ToolResult.error CollapsibleTitle {
        color: #e06c75;
    }

    ToolResult .tool-summary {
        color: #e5c07b;
        width: 100%;
        height: 1;
    }

    ToolResult .tool-meta {
        color: #606060;
    }

    ToolResult .collapsible-content {
        background: #141414;
        padding: 0 1;
    }

    ToolResult .diff-link {
        color: #56b6c2;
        height: 1;
        padding: 0 1;
        text-style: bold;
    }
    """

    def __init__(self, message: Message, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._message = message
        
        # 检查是否为错误 (兼容旧版 + 新版)
        is_error = False
        if message.is_error or (hasattr(message, 'tool_success') and not message.tool_success):
            is_error = True
        elif message.parts:
            for part in message.parts:
                if part.type == PartType.TOOL and part.tool_state == ToolState.ERROR:
                    is_error = True
                    break
        
        if is_error:
            self.add_class("error")

    def compose(self):
        # 支持新版 Part-based 和旧版字段
        tool_parts = self._message.get_parts(PartType.TOOL)
        
        if tool_parts:
            # 新版: 遍历所有 tool part
            for part in tool_parts:
                yield from self._render_tool_part(part)
        else:
            # 旧版兼容
            yield from self._render_legacy()

    def _render_tool_part(self, part: Part):
        """渲染单个 tool part"""
        name = part.tool_name or "Tool"
        is_error = part.tool_state == ToolState == ToolState.ERROR
        
        if is_error:
            icon = "✗"
        else:
            icon = "✓"
        
        duration = ""
        if part.tool_duration is not None:
            duration = f" · {part.tool_duration:.1f}s"
        
        result_str = part.tool_result or ""
        size_hint = ""
        if len(result_str) > 800:
            size_hint = f" · {len(result_str):,} chars"
        
        title = f"{icon} {name}{duration}{size_hint}"
        
        with Collapsible(title=title, collapsed=len(result_str) > 800):
            yield Markdown(part.tool_result or "(无输出)")

        # Add "查看 Diff" button for file write/edit tools
        name_lower = name.lower()
        if name_lower in ("write_file", "write", "edit_file", "edit") and not is_error:
            yield Static(
                "[#56b6c2]📄 查看变更[/]",
                classes="diff-link",
                markup=True,
            )

    def _render_legacy(self):
        """旧版 Message 渲染兼容"""
        name = getattr(self._message, 'tool_name', 'Tool') or "Tool"
        success = getattr(self._message, 'tool_success', True)
        duration = getattr(self._message, 'tool_duration', None)
        result_str = getattr(self._message, 'tool_result', '') or ""
        
        if success:
            icon = "✓"
        else:
            icon = "✗"
        
        duration_str = ""
        if duration is not None:
            duration_str = f" · {duration:.1f}s"
        
        size_hint = ""
        if len(result_str) > 800:
            size_hint = f" · {len(result_str):,} chars"
        
        title = f"{icon} {name}{duration_str}{size_hint}"
        
        with Collapsible(title=title, collapsed=len(result_str) > 800):
            yield Markdown(self._message.content or result_str or "(无输出)")

        name_lower = name.lower()
        if name_lower in ("write_file", "write", "edit_file", "edit") and success:
            yield Static(
                "[#56b6c2]📄 查看变更[/]",
                classes="diff-link",
                markup=True,
            )

    def on_click(self, event: events.Click) -> None:
        """Handle click — only trigger diff overlay when clicking .diff-link."""
        try:
            target = getattr(event, 'widget', None) or getattr(event, 'node', None)
            if target is None:
                return
            node = target
            found = False
            while node is not None:
                if hasattr(node, 'has_class') and node.has_class("diff-link"):
                    found = True
                    break
                if node is self:
                    break
                node = getattr(node, 'parent', None)
            if not found:
                return
        except Exception:
            return
        try:
            app = self.app
            patches = getattr(app, '_recent_patches', [])
            if patches:
                last_patch = patches[-1]
                app.show_diff_overlay(last_patch['path'], last_patch['diff'])
        except Exception:
            pass
