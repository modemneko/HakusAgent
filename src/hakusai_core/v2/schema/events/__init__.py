"""
事件定义 - 借鉴 OpenCode 的事件驱动架构
用于模块间解耦通信
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class Event(BaseModel):
    """事件基类"""
    id: str
    type: str
    timestamp: datetime = Field(default_factory=datetime.now)
    source: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class AgentEvent(Event):
    """Agent 事件"""
    session_id: str
    agent_name: str


class ToolEvent(AgentEvent):
    """工具事件"""
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    tool_result: Optional[Any] = None


class MessageEvent(AgentEvent):
    """消息事件"""
    message_role: str
    message_content: str
    is_streaming: bool = False


class SessionEvent(Event):
    """会话事件"""
    session_id: str


class VoiceEvent(Event):
    """语音事件"""
    audio_data: Optional[bytes] = None
    text: Optional[str] = None


class PlatformEvent(BaseModel):
    """平台事件"""
    platform: str
    event_type: str
    user_id: str
    user_name: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventEmitter:
    """事件发射器"""
    
    def __init__(self):
        self._handlers: dict[str, list] = {}
    
    def on(self, event_type: str, handler):
        """注册事件处理器"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    def emit(self, event: Event):
        """触发事件"""
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            handler(event)
    
    async def emit_async(self, event: Event):
        """异步触发事件"""
        import asyncio
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)