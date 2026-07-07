"""
HakusAI TUI v2 — 消息数据模型与 dispatcher

设计原则 (来自 OpenCode Messages.tsx):
- 每个消息由多个 Part 组成 (text, tool, reasoning, file, compaction)
- 每个 Part 是不可变的 dataclass, 唯一 id
- dispatcher 按 part type 分发到对应 widget
- 解决"用户输入回显重复": UI 层只通过 mount_message 添加, 永远不直接 stdout.echo
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

MessageRole = Literal["user", "assistant", "tool", "command", "error", "system", "compact", "welcome"]


class PartType(Enum):
    """消息部分类型 (对应 OpenCode PartType)"""
    TEXT = "text"
    TOOL = "tool"
    REASONING = "reasoning"
    FILE = "file"
    COMPACTION = "compaction"
    IMAGE = "image"
    PATCH = "patch"


class ToolState(Enum):
    """工具执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class Part:
    """消息的基本组成单元"""
    type: PartType
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    # 通用字段
    text: str = ""  # 文本内容 (text, reasoning, compaction)
    # Tool 相关
    tool_name: str = ""
    tool_args: Dict[str, Any] = field(default_factory=dict)
    tool_result: str = ""
    tool_state: ToolState = ToolState.PENDING
    tool_duration: Optional[float] = None
    tool_error: str = ""
    # File 相关
    file_path: str = ""
    file_mime: str = ""
    file_data: bytes = b""
    file_size: int = 0
    # Patch 相关
    patch_path: str = ""
    patch_diff: str = ""
    # Metadata
    synthetic: bool = False  # 是否是合成的 (如摘要)
    ignored: bool = False    # 是否忽略 (如已折叠)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """单条消息 - 由多个 Part 组成

    Attributes:
        id: 唯一 id (用于去重 + 虚拟化 widget key).
        role: 消息角色 (见 MessageRole).
        parts: 消息部分列表.
        timestamp: 创建时间.
        agent: Agent 名称 (assistant 消息).
        model: 模型名称 (assistant 消息).
        finish: 结束原因 (assistant 消息).
        tokens: Token 使用统计.
        metadata: 扩展元数据.
        
    向后兼容属性 (旧版 API):
        content: 文本内容 (getter/setter)
        tool_name: 工具名
        tool_args: 工具参数
        tool_result: 工具结果
        tool_success: 工具是否成功
        tool_duration: 工具耗时
        is_error: 是否错误
        collapsed: 是否折叠
    """

    role: MessageRole
    parts: List[Part] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    agent: Optional[str] = None
    model: Optional[str] = None
    finish: Optional[str] = None
    tokens: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 向后兼容字段 (内部存储)
    _content: str = field(default="", repr=False)
    _tool_name: Optional[str] = field(default=None, repr=False)
    _tool_args: Optional[Dict[str, Any]] = field(default=None, repr=False)
    _tool_result: Optional[str] = field(default=None, repr=False)
    _tool_success: bool = field(default=True, repr=False)
    _tool_duration: Optional[float] = field(default=None, repr=False)
    _is_error: bool = field(default=False, repr=False)
    _collapsed: bool = field(default=False, repr=False)

    @property
    def content(self) -> str:
        """获取所有文本部分的拼接内容 (向后兼容)"""
        if self._content:
            return self._content
        return "\n".join(p.text for p in self.parts if p.type == PartType.TEXT and p.text)

    @content.setter
    def content(self, value: str) -> None:
        """设置内容 (向后兼容)"""
        self._content = value
        # 更新 parts 中的 text part
        text_parts = [p for p in self.parts if p.type == PartType.TEXT]
        if text_parts:
            text_parts[-1].text = value
        else:
            self.parts.append(Part(type=PartType.TEXT, text=value))

    @property
    def tool_name(self) -> Optional[str]:
        if self._tool_name:
            return self._tool_name
        tool_parts = self.get_parts(PartType.TOOL)
        return tool_parts[0].tool_name if tool_parts else None

    @tool_name.setter
    def tool_name(self, value: str) -> None:
        self._tool_name = value

    @property
    def tool_args(self) -> Optional[Dict[str, Any]]:
        if self._tool_args:
            return self._tool_args
        tool_parts = self.get_parts(PartType.TOOL)
        return tool_parts[0].tool_args if tool_parts else None

    @tool_args.setter
    def tool_args(self, value: Dict[str, Any]) -> None:
        self._tool_args = value

    @property
    def tool_result(self) -> Optional[str]:
        if self._tool_result:
            return self._tool_result
        tool_parts = self.get_parts(PartType.TOOL)
        return tool_parts[0].tool_result if tool_parts else None

    @tool_result.setter
    def tool_result(self, value: str) -> None:
        self._tool_result = value

    @property
    def tool_success(self) -> bool:
        if self._tool_success is not None:
            return self._tool_success
        tool_parts = self.get_parts(PartType.TOOL)
        return tool_parts[0].tool_state == ToolState.COMPLETED if tool_parts else True

    @tool_success.setter
    def tool_success(self, value: bool) -> None:
        self._tool_success = value

    @property
    def tool_duration(self) -> Optional[float]:
        if self._tool_duration:
            return self._tool_duration
        tool_parts = self.get_parts(PartType.TOOL)
        return tool_parts[0].tool_duration if tool_parts else None

    @tool_duration.setter
    def tool_duration(self, value: float) -> None:
        self._tool_duration = value

    @property
    def is_error(self) -> bool:
        return self._is_error or self.role == "error"

    @is_error.setter
    def is_error(self, value: bool) -> None:
        self._is_error = value

    @property
    def collapsed(self) -> bool:
        if self._collapsed:
            return self._collapsed
        return any(p.type == PartType.TOOL and len(p.tool_result) > 800 for p in self.parts)

    @collapsed.setter
    def collapsed(self, value: bool) -> None:
        self._collapsed = value

    # 工厂方法 (向后兼容 + 新增 part-based)
    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role="user", parts=[Part(type=PartType.TEXT, text=content)], _content=content)

    @classmethod
    def assistant(cls, content: str) -> "Message":
        return cls(role="assistant", parts=[Part(type=PartType.TEXT, text=content)], _content=content)

    @classmethod
    def tool(
        cls,
        name: str,
        args: Dict[str, Any],
        result: str,
        *,
        success: bool = True,
        duration: Optional[float] = None,
        error: str = "",
    ) -> "Message":
        tool_state = ToolState.COMPLETED if success else ToolState.ERROR
        part = Part(
            type=PartType.TOOL,
            tool_name=name,
            tool_args=args,
            tool_result=result,
            tool_state=tool_state,
            tool_duration=duration,
            tool_error=error,
        )
        return cls(role="tool", parts=[part])

    @classmethod
    def command(cls, name: str, output: str) -> "Message":
        return cls(
            role="command",
            parts=[Part(type=PartType.TEXT, text=output)],
            metadata={"cmd": name},
        )

    @classmethod
    def error(cls, content: str) -> "Message":
        return cls(role="error", parts=[Part(type=PartType.TEXT, text=content)])

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role="system", parts=[Part(type=PartType.TEXT, text=content)])

    @classmethod
    def assistant_with_parts(cls, parts: List[Part], agent: str = None, model: str = None) -> "Message":
        """创建包含多个 part 的 assistant 消息"""
        return cls(role="assistant", parts=parts, agent=agent, model=model)

    @classmethod
    def user_with_parts(cls, parts: List[Part]) -> "Message":
        """创建包含多个 part 的 user 消息"""
        return cls(role="user", parts=parts)

    def add_part(self, part: Part) -> None:
        """添加 part"""
        self.parts.append(part)

    def get_parts(self, part_type: PartType) -> List[Part]:
        """获取指定类型的所有 part"""
        return [p for p in self.parts if p.type == part_type]

    def get_text_parts(self) -> List[Part]:
        return self.get_parts(PartType.TEXT)

    def get_tool_parts(self) -> List[Part]:
        return self.get_parts(PartType.TOOL)

    def get_reasoning_parts(self) -> List[Part]:
        return self.get_parts(PartType.REASONING)

    def get_file_parts(self) -> List[Part]:
        return self.get_parts(PartType.FILE)

    def get_compaction_parts(self) -> List[Part]:
        return self.get_parts(PartType.COMPACTION)


@dataclass
class CollapsedReadGroup:
    """用于合并多条 read/search 工具结果 (Claude Code CollapsedReadSearchContent)."""
    items: List[Message] = field(default_factory=list)
    collapsed: bool = True
