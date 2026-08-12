"""
HakusAI 2.0 虚拟形象基类
定义统一的虚拟形象接口，支持Live2D和VRM
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


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
    """
    虚拟形象基类
    
    所有虚拟形象实现（Live2D/VRM）必须继承此类
    """
    
    def __init__(
        self,
        model_path: str,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化虚拟形象
        
        Args:
            model_path: 模型文件路径
            config: 配置字典
        """
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
        """初始化渲染引擎"""
        pass
    
    @abstractmethod
    async def load(self) -> bool:
        """
        加载模型
        
        Returns:
            是否加载成功
        """
        pass
    
    @abstractmethod
    async def unload(self):
        """卸载模型"""
        pass
    
    @abstractmethod
    async def update(self, delta_time: float):
        """
        更新渲染
        
        Args:
            delta_time: 时间增量（秒）
        """
        pass
    
    @abstractmethod
    def set_expression(self, expression: str, intensity: float = 1.0):
        """
        设置表情
        
        Args:
            expression: 表情名称
            intensity: 表情强度 (0-1)
        """
        pass
    
    @abstractmethod
    def set_motion(self, motion: str, loop: bool = False):
        """
        设置动作
        
        Args:
            motion: 动作名称
            loop: 是否循环
        """
        pass
    
    @abstractmethod
    def update_lipsync(self, data: LipSyncData):
        """
        更新嘴型同步
        
        Args:
            data: 嘴型同步数据
        """
        pass
    
    @abstractmethod
    def set_position(self, position: AvatarPosition):
        """
        设置位置
        
        Args:
            position: 位置信息
        """
        pass
    
    @abstractmethod
    def look_at(self, x: float, y: float):
        """
        注视某点
        
        Args:
            x: 屏幕X坐标 (0-1)
            y: 屏幕Y坐标 (0-1)
        """
        pass
    
    @abstractmethod
    def get_expressions(self) -> List[str]:
        """
        获取可用表情列表
        
        Returns:
            表情名称列表
        """
        pass
    
    @abstractmethod
    def get_motions(self) -> List[str]:
        """
        获取可用动作列表
        
        Returns:
            动作名称列表
        """
        pass
    
    async def speak(self, text: str = ""):
        """
        开始说话状态
        
        Args:
            text: 要说的文本（可选）
        """
        self.is_speaking = True
        logger.debug(f"Avatar started speaking: {text[:50] if text else ''}")
    
    async def stop_speaking(self):
        """停止说话状态"""
        self.is_speaking = False
        # 重置嘴型
        self.update_lipsync(LipSyncData())
        logger.debug("Avatar stopped speaking")
    
    def on_mouse_move(self, x: float, y: float):
        """
        鼠标移动事件
        
        Args:
            x: 屏幕X坐标 (0-1)
            y: 屏幕Y坐标 (0-1)
        """
        if self.look_at_mouse:
            self.look_at(x, y)
    
    def on_click(self, x: float, y: float):
        """
        点击事件
        
        Args:
            x: 屏幕X坐标 (0-1)
            y: 屏幕Y坐标 (0-1)
        """
        logger.debug(f"Avatar clicked at ({x}, {y})")
    
    @property
    def is_loaded(self) -> bool:
        """模型是否已加载"""
        return self._loaded
    
    async def close(self):
        """关闭并清理资源"""
        await self.unload()
        self._initialized = False
        logger.debug(f"Avatar {self.model_name} closed")


class AvatarManager:
    """
    虚拟形象管理器 - 单例模式
    
    统一管理Live2D和VRM形象
    """
    _instance: Optional['AvatarManager'] = None
    _current_avatar: Optional[BaseAvatar] = None
    _avatars: Dict[str, BaseAvatar] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def load_avatar(
        self,
        avatar_type: AvatarType,
        model_path: str,
        config: Optional[Dict[str, Any]] = None
    ) -> BaseAvatar:
        """
        加载虚拟形象
        
        Args:
            avatar_type: 形象类型
            model_path: 模型路径
            config: 配置
            
        Returns:
            形象实例
        """
        # 卸载当前形象
        if self._current_avatar:
            await self._current_avatar.unload()
        
        # 创建新形象
        if avatar_type == AvatarType.LIVE2D:
            from .live2d import Live2DAvatar
            avatar = Live2DAvatar(model_path, config)
        elif avatar_type == AvatarType.VRM:
            from .vrm import VRMAvatar
            avatar = VRMAvatar(model_path, config)
        else:
            raise ValueError(f"Unknown avatar type: {avatar_type}")
        
        # 初始化并加载
        await avatar.initialize()
        success = await avatar.load()
        
        if not success:
            raise RuntimeError(f"Failed to load avatar: {model_path}")
        
        self._current_avatar = avatar
        self._avatars[avatar.model_name] = avatar
        
        logger.info(f"Avatar loaded: {avatar.model_name} ({avatar_type.value})")
        return avatar
    
    def get_current_avatar(self) -> Optional[BaseAvatar]:
        """获取当前形象"""
        return self._current_avatar
    
    def get_avatar(self, name: str) -> Optional[BaseAvatar]:
        """获取指定形象"""
        return self._avatars.get(name)
    
    async def switch_avatar(self, name: str) -> Optional[BaseAvatar]:
        """
        切换形象
        
        Args:
            name: 形象名称
            
        Returns:
            形象实例或None
        """
        if name not in self._avatars:
            logger.warning(f"Avatar not found: {name}")
            return None
        
        # 卸载当前
        if self._current_avatar:
            await self._current_avatar.unload()
        
        # 加载新的
        self._current_avatar = self._avatars[name]
        await self._current_avatar.load()
        
        logger.info(f"Switched to avatar: {name}")
        return self._current_avatar
    
    async def close_all(self):
        """关闭所有形象"""
        for avatar in self._avatars.values():
            await avatar.close()
        self._avatars.clear()
        self._current_avatar = None
        logger.info("All avatars closed")


# 全局管理器实例
avatar_manager = AvatarManager()
