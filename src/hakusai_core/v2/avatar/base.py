"""
虚拟形象系统 - 支持 Live2D 和 VRM
迁移自现有实现，适配 v2 架构
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import logging
import asyncio

from ..schema.models import AvatarState
from ..schema.errors import HakusAIError

logger = logging.getLogger(__name__)


class AvatarError(HakusAIError):
    """虚拟形象错误"""
    pass


class AvatarType(str, Enum):
    """虚拟形象类型"""
    LIVE2D = "live2d"
    VRM = "vrm"
    NONE = "none"


@dataclass
class AvatarPosition:
    """形象位置"""
    x: float = 0.5  # 0-1，屏幕宽度百分比
    y: float = 0.5  # 0-1，屏幕高度百分比
    scale: float = 1.0
    rotation: float = 0.0


@dataclass
class LipSyncData:
    """嘴型同步数据"""
    mouth_open: float = 0.0  # 0-1，嘴巴张开程度
    mouth_form: float = 0.0  # 0-1，嘴型
    volume: float = 0.0  # 音量级别


@dataclass
class Expression:
    """表情数据"""
    name: str
    intensity: float = 1.0  # 0-1，表情强度
    duration: Optional[float] = None  # 持续时间（秒），None表示永久


@dataclass
class Motion:
    """动作数据"""
    name: str
    loop: bool = False
    priority: int = 1


class BaseAvatar(ABC):
    """虚拟形象基类"""
    
    def __init__(
        self,
        model_path: str,
        config: Optional[Dict[str, Any]] = None
    ):
        self.model_path = Path(model_path)
        self.config = config or {}
        self._initialized = False
        self._loaded = False
        
        # 状态
        self.position = AvatarPosition()
        self.current_expression: Optional[str] = None
        self.current_motion: Optional[str] = None
        self.is_speaking = False
        
        # 自动行为
        self.auto_blink = self.config.get("auto_blink", True)
        self.auto_breath = self.config.get("auto_breath", True)
        self.look_at_mouse = self.config.get("look_at_mouse", True)
    
    @property
    @abstractmethod
    def avatar_type(self) -> AvatarType:
        """形象类型"""
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """模型名称"""
        pass
    
    @abstractmethod
    async def initialize(self):
        """初始化虚拟形象"""
        pass
    
    @abstractmethod
    async def load_model(self):
        """加载模型"""
        pass
    
    @abstractmethod
    def set_expression(self, expression: str, intensity: float = 1.0):
        """设置表情"""
        pass
    
    @abstractmethod
    def set_motion(self, motion: str, loop: bool = False):
        """设置动作"""
        pass
    
    @abstractmethod
    def update_lip_sync(self, data: LipSyncData):
        """更新嘴型同步"""
        pass
    
    def set_position(self, position: AvatarPosition):
        """设置位置"""
        self.position = position
    
    def get_state(self) -> AvatarState:
        """获取当前状态"""
        return AvatarState(
            expression=self.current_expression,
            motion=self.current_motion,
            mouth_open=self._mouth_open if hasattr(self, '_mouth_open') else 0.0,
        )
    
    async def close(self):
        """关闭虚拟形象"""
        self._initialized = False
        self._loaded = False


class AvatarManager:
    """虚拟形象管理器"""
    
    _instance: Optional['AvatarManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._avatars: Dict[str, BaseAvatar] = {}
        return cls._instance
    
    def register(self, name: str, avatar: BaseAvatar):
        """注册虚拟形象"""
        self._avatars[name] = avatar
    
    def get(self, name: str) -> Optional[BaseAvatar]:
        """获取虚拟形象"""
        return self._avatars.get(name)
    
    def list_avatars(self) -> List[str]:
        """列出所有虚拟形象"""
        return list(self._avatars.keys())
    
    async def close_all(self):
        """关闭所有虚拟形象"""
        for avatar in self._avatars.values():
            await avatar.close()
        self._avatars.clear()


# 全局管理器实例
avatar_manager = AvatarManager()