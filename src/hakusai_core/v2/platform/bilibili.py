"""
Bilibili 平台适配器 - 支持 Bilibili 直播间互动
"""

from typing import Optional, Dict, Any, AsyncIterator
from dataclasses import dataclass
import asyncio
import logging
import json
from datetime import datetime

from .base import (
    BasePlatform,
    PlatformType,
    PlatformConfig,
    PlatformMessage,
    SendMessage,
    PlatformError,
)

logger = logging.getLogger(__name__)


@dataclass
class BilibiliConfig(PlatformConfig):
    """Bilibili 配置"""
    room_id: Optional[str] = None
    uid: Optional[str] = None
    session_id: Optional[str] = None
    
    def __post_init__(self):
        self.platform_type = PlatformType.BILIBILI


@dataclass
class Gift:
    """礼物"""
    user_id: str
    user_name: str
    gift_id: str
    gift_name: str
    count: int
    price: float
    timestamp: datetime


@dataclass
class Danmaku:
    """弹幕"""
    user_id: str
    user_name: str
    content: str
    timestamp: datetime


class BilibiliPlatform(BasePlatform):
    """Bilibili 平台适配器"""
    
    def __init__(self, config: BilibiliConfig):
        super().__init__(config)
        self.config: BilibiliConfig = config
        self._ws = None
        self._heartbeat_task = None
        self._gift_handlers = []
        self._danmaku_handlers = []
    
    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.BILIBILI
    
    @property
    def platform_name(self) -> str:
        return "Bilibili"
    
    async def connect(self):
        """连接 Bilibili 直播间"""
        if self._connected:
            return
        
        try:
            # 这里应该实现 Bilibili WebSocket 连接
            # 暂时使用占位符
            logger.info(f"Connecting to Bilibili room: {self.config.room_id}")
            
            # 模拟连接成功
            self._connected = True
            
            # 启动心跳
            self._heartbeat_task = asyncio.create_task(self._heartbeat())
            
            logger.info("Connected to Bilibili")
            
        except Exception as e:
            logger.error(f"Failed to connect to Bilibili: {e}")
            raise PlatformError(f"Bilibili connection failed: {e}")
    
    async def disconnect(self):
        """断开连接"""
        if not self._connected:
            return
        
        try:
            # 取消心跳
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            
            # 关闭 WebSocket
            if self._ws:
                await self._ws.close()
            
            self._connected = False
            logger.info("Disconnected from Bilibili")
            
        except Exception as e:
            logger.error(f"Failed to disconnect from Bilibili: {e}")
    
    async def send_message(self, message: SendMessage) -> bool:
        """发送弹幕"""
        if not self._connected:
            logger.warning("Not connected to Bilibili")
            return False
        
        try:
            # 这里应该实现发送弹幕
            # 暂时使用占位符
            logger.info(f"Sending danmaku: {message.content}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send danmaku: {e}")
            return False
    
    async def receive_messages(self) -> AsyncIterator[PlatformMessage]:
        """接收消息"""
        # 这里应该实现接收 WebSocket 消息
        # 暂时使用占位符
        while self._connected:
            await asyncio.sleep(1)
            # yield PlatformMessage(...)
    
    async def _heartbeat(self):
        """心跳保活"""
        while self._connected:
            try:
                # 发送心跳包
                logger.debug("Sending heartbeat")
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                break
    
    def on_gift(self, handler):
        """注册礼物处理器"""
        self._gift_handlers.append(handler)
    
    def on_danmaku(self, handler):
        """注册弹幕处理器"""
        self._danmaku_handlers.append(handler)
    
    async def _handle_gift(self, gift: Gift):
        """处理礼物"""
        for handler in self._gift_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(gift)
                else:
                    handler(gift)
            except Exception as e:
                logger.error(f"Gift handler error: {e}")
    
    async def _handle_danmaku(self, danmaku: Danmaku):
        """处理弹幕"""
        for handler in self._danmaku_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(danmaku)
                else:
                    handler(danmaku)
            except Exception as e:
                logger.error(f"Danmaku handler error: {e}")