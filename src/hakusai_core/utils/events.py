"""
HakusAI 2.0 事件系统
提供统一的事件发布/订阅机制，支持异步事件处理
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum, auto
import logging

logger = logging.getLogger(__name__)


class EventType(Enum):
    """系统事件类型"""
    # 聊天相关
    CHAT_MESSAGE_RECEIVED = auto()
    CHAT_MESSAGE_SENT = auto()
    CHAT_STREAM_START = auto()
    CHAT_STREAM_TOKEN = auto()
    CHAT_STREAM_END = auto()
    
    # 语音相关
    VOICE_SPEECH_START = auto()
    VOICE_SPEECH_END = auto()
    VOICE_ASR_TEXT = auto()
    VOICE_TTS_START = auto()
    VOICE_TTS_END = auto()
    
    # 虚拟形象相关
    AVATAR_EXPRESSION_CHANGE = auto()
    AVATAR_LIPSYNC_UPDATE = auto()
    AVATAR_MOTION_TRIGGER = auto()
    
    # 平台相关
    PLATFORM_MESSAGE_RECEIVED = auto()
    PLATFORM_CONNECTED = auto()
    PLATFORM_DISCONNECTED = auto()
    
    # 系统相关
    SYSTEM_CONFIG_CHANGED = auto()
    SYSTEM_ERROR = auto()
    SYSTEM_SHUTDOWN = auto()


@dataclass
class Event:
    """事件对象"""
    type: EventType
    data: Any = None
    source: str = ""
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            import time
            self.timestamp = time.time()


class EventBus:
    """
    事件总线 - 单例模式
    管理所有事件的发布和订阅
    """
    _instance: Optional['EventBus'] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._once_subscribers: Dict[EventType, List[Callable]] = {}
        self._running = True
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        
    async def start(self):
        """启动事件处理循环"""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._process_events())
            logger.info("EventBus started")
    
    async def stop(self):
        """停止事件处理"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("EventBus stopped")
    
    async def _process_events(self):
        """事件处理循环"""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(), 
                    timeout=1.0
                )
                await self._dispatch(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error processing event: {e}")
    
    async def _dispatch(self, event: Event):
        """分发事件到订阅者"""
        # 处理普通订阅者
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(event))
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Error in event handler: {e}")
        
        # 处理一次性订阅者
        once_handlers = self._once_subscribers.get(event.type, [])
        for handler in once_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(event))
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Error in once event handler: {e}")
        # 清空一次性订阅者
        if once_handlers:
            self._once_subscribers[event.type] = []
    
    def subscribe(self, event_type: EventType, handler: Callable):
        """
        订阅事件
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed to {event_type.name}")
    
    def subscribe_once(self, event_type: EventType, handler: Callable):
        """
        订阅事件（只触发一次）
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        if event_type not in self._once_subscribers:
            self._once_subscribers[event_type] = []
        self._once_subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: EventType, handler: Callable):
        """
        取消订阅
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        if event_type in self._subscribers:
            if handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)
    
    async def emit(self, event_type: EventType, data: Any = None, source: str = ""):
        """
        发布事件（异步）
        
        Args:
            event_type: 事件类型
            data: 事件数据
            source: 事件来源
        """
        event = Event(type=event_type, data=data, source=source)
        await self._event_queue.put(event)
    
    def emit_sync(self, event_type: EventType, data: Any = None, source: str = ""):
        """
        发布事件（同步）
        
        Args:
            event_type: 事件类型
            data: 事件数据
            source: 事件来源
        """
        event = Event(type=event_type, data=data, source=source)
        # 尝试获取当前事件循环
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._event_queue.put(event))
        except RuntimeError:
            # 没有运行的事件循环，直接处理
            asyncio.run(self._event_queue.put(event))


# 全局事件总线实例
event_bus = EventBus()


# 装饰器形式的订阅
def on_event(event_type: EventType):
    """
    事件订阅装饰器
    
    用法:
        @on_event(EventType.CHAT_MESSAGE_RECEIVED)
        async def handle_message(event: Event):
            print(event.data)
    """
    def decorator(func: Callable):
        event_bus.subscribe(event_type, func)
        return func
    return decorator


# 便捷函数
async def emit(event_type: EventType, data: Any = None, source: str = ""):
    """发布事件"""
    await event_bus.emit(event_type, data, source)


def emit_sync(event_type: EventType, data: Any = None, source: str = ""):
    """同步发布事件"""
    event_bus.emit_sync(event_type, data, source)
