"""
平台集成系统 - 支持 Bilibili、Discord、YouTube 等平台
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import asyncio
import logging

from ..schema.models import PlatformEvent
from ..schema.errors import HakusAIError

logger = logging.getLogger(__name__)


class PlatformError(HakusAIError):
    """平台集成错误"""
    pass


class PlatformType(str, Enum):
    """平台类型"""
    BILIBILI = "bilibili"
    DISCORD = "discord"
    WECHAT = "wechat"
    YOUTUBE = "youtube"
    TWITCH = "twitch"
    CUSTOM = "custom"


@dataclass
class PlatformConfig:
    """平台配置"""
    platform_type: PlatformType
    enabled: bool = True
    credentials: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlatformMessage:
    """平台消息"""
    id: str
    content: str
    author_id: str
    author_name: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SendMessage:
    """发送消息"""
    content: str
    reply_to: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BasePlatform(ABC):
    """平台适配器基类"""
    
    def __init__(self, config: PlatformConfig):
        self.config = config
        self._connected = False
        self._message_handlers = []
        self._event_handlers = []
    
    @property
    @abstractmethod
    def platform_type(self) -> PlatformType:
        """平台类型"""
        pass
    
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台名称"""
        pass
    
    @abstractmethod
    async def connect(self):
        """连接平台"""
        pass
    
    @abstractmethod
    async def disconnect(self):
        """断开连接"""
        pass
    
    @abstractmethod
    async def send_message(self, message: SendMessage) -> bool:
        """发送消息"""
        pass
    
    @abstractmethod
    async def receive_messages(self) -> AsyncIterator[PlatformMessage]:
        """接收消息"""
        pass
    
    def on_message(self, handler):
        """注册消息处理器"""
        self._message_handlers.append(handler)
    
    def on_event(self, handler):
        """注册事件处理器"""
        self._event_handlers.append(handler)
    
    async def _handle_message(self, message: PlatformMessage):
        """处理接收到的消息"""
        for handler in self._message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.error(f"Message handler error: {e}")
    
    async def _emit_event(self, event: PlatformEvent):
        """触发事件"""
        for handler in self._event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected


class PlatformManager:
    """平台管理器"""
    
    _instance: Optional['PlatformManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._platforms: Dict[str, BasePlatform] = {}
        return cls._instance
    
    def register(self, name: str, platform: BasePlatform):
        """注册平台"""
        self._platforms[name] = platform
    
    def get(self, name: str) -> Optional[BasePlatform]:
        """获取平台"""
        return self._platforms.get(name)
    
    def list_platforms(self) -> list:
        """列出所有平台"""
        return list(self._platforms.keys())
    
    async def connect_all(self):
        """连接所有平台"""
        for platform in self._platforms.values():
            if platform.config.enabled:
                try:
                    await platform.connect()
                except Exception as e:
                    logger.error(f"Failed to connect {platform.platform_name}: {e}")
    
    async def disconnect_all(self):
        """断开所有平台"""
        for platform in self._platforms.values():
            try:
                await platform.disconnect()
            except Exception as e:
                logger.error(f"Failed to disconnect {platform.platform_name}: {e}")
    
    async def broadcast(self, message: SendMessage, exclude: Optional[str] = None):
        """广播消息到所有平台"""
        for name, platform in self._platforms.items():
            if name != exclude and platform.is_connected:
                try:
                    await platform.send_message(message)
                except Exception as e:
                    logger.error(f"Failed to broadcast to {platform.platform_name}: {e}")


# 全局管理器实例
platform_manager = PlatformManager()