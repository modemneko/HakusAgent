"""
VRM 虚拟形象 - VRM 模型渲染和控制
"""

from typing import Optional, Dict, Any
import asyncio
import logging

from .base import (
    BaseAvatar,
    AvatarType,
    AvatarPosition,
    LipSyncData,
    Expression,
    Motion,
)
from ..schema.models import AvatarState

logger = logging.getLogger(__name__)


class VRMAvatar(BaseAvatar):
    """VRM 虚拟形象"""
    
    def __init__(
        self,
        model_path: str,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(model_path, config)
        self._model = None
        self._blend_shape_proxy = None
        self._spring_bone_manager = None
        self._mouth_open = 0.0
    
    @property
    def avatar_type(self) -> AvatarType:
        return AvatarType.VRM
    
    @property
    def model_name(self) -> str:
        return self.model_path.stem
    
    async def initialize(self):
        """初始化 VRM 引擎"""
        if self._initialized:
            return
        
        try:
            # 这里应该初始化 Three.js VRM SDK
            # 暂时使用占位符
            logger.info(f"Initializing VRM avatar: {self.model_name}")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize VRM avatar: {e}")
            raise
    
    async def load_model(self):
        """加载 VRM 模型"""
        if self._loaded:
            return
        
        try:
            # 这里应该加载 .vrm 模型文件
            # 暂时使用占位符
            logger.info(f"Loading VRM model: {self.model_path}")
            self._loaded = True
        except Exception as e:
            logger.error(f"Failed to load VRM model: {e}")
            raise
    
    def set_expression(self, expression: str, intensity: float = 1.0):
        """设置表情"""
        if not self._loaded:
            logger.warning("Model not loaded")
            return
        
        self.current_expression = expression
        # 这里应该调用 VRM BlendShape API
        logger.debug(f"Setting expression: {expression} (intensity: {intensity})")
    
    def set_motion(self, motion: str, loop: bool = False):
        """设置动作"""
        if not self._loaded:
            logger.warning("Model not loaded")
            return
        
        self.current_motion = motion
        # 这里应该调用 VRM 动画 API
        logger.debug(f"Setting motion: {motion} (loop: {loop})")
    
    def update_lip_sync(self, data: LipSyncData):
        """更新嘴型同步"""
        if not self._loaded:
            return
        
        self._mouth_open = data.mouth_open
        # 这里应该更新 VRM BlendShape
        logger.debug(f"Updating lip sync: mouth_open={data.mouth_open:.2f}")
    
    def set_position(self, position: AvatarPosition):
        """设置位置"""
        super().set_position(position)
        # 这里应该更新 Three.js 位置
        logger.debug(f"Setting position: x={position.x}, y={position.y}")
    
    async def render(self) -> Optional[Dict[str, Any]]:
        """渲染当前帧"""
        if not self._loaded:
            return None
        
        # 返回渲染数据（供前端使用）
        return {
            "model": self.model_name,
            "type": "vrm",
            "expression": self.current_expression,
            "motion": self.current_motion,
            "mouth_open": self._mouth_open,
            "position": {
                "x": self.position.x,
                "y": self.position.y,
                "scale": self.position.scale,
            }
        }
    
    async def close(self):
        """关闭 VRM 形象"""
        # 这里应该释放 Three.js 资源
        await super().close()
        logger.info(f"VRM avatar closed: {self.model_name}")


class WebVRMAvatar(VRMAvatar):
    """Web 端 VRM 形象（通过 WebSocket 通信）"""
    
    def __init__(
        self,
        model_path: str,
        config: Optional[Dict[str, Any]] = None,
        websocket_send=None,
    ):
        super().__init__(model_path, config)
        self.websocket_send = websocket_send
        self._client_id = None
    
    async def initialize(self):
        """初始化 Web VRM"""
        await super().initialize()
        # 生成客户端 ID
        self._client_id = f"vrm_{self.model_name}_{id(self)}"
        logger.info(f"Web VRM initialized: {self._client_id}")
    
    async def send_command(self, command: str, data: Dict[str, Any]):
        """发送命令到前端"""
        if self.websocket_send:
            message = {
                "type": "vrm",
                "client_id": self._client_id,
                "command": command,
                "data": data,
            }
            await self.websocket_send(message)
    
    def set_expression(self, expression: str, intensity: float = 1.0):
        """设置表情（通过 WebSocket）"""
        super().set_expression(expression, intensity)
        asyncio.create_task(
            self.send_command("set_expression", {
                "name": expression,
                "intensity": intensity,
            })
        )
    
    def set_motion(self, motion: str, loop: bool = False):
        """设置动作（通过 WebSocket）"""
        super().set_motion(motion, loop)
        asyncio.create_task(
            self.send_command("set_motion", {
                "name": motion,
                "loop": loop,
            })
        )
    
    def update_lip_sync(self, data: LipSyncData):
        """更新嘴型同步（通过 WebSocket）"""
        super().update_lip_sync(data)
        asyncio.create_task(
            self.send_command("lip_sync", {
                "mouth_open": data.mouth_open,
                "mouth_form": data.mouth_form,
                "volume": data.volume,
            })
        )
    
    async def close(self):
        """关闭 Web VRM"""
        if self.websocket_send:
            await self.send_command("close", {})
        await super().close()


async def create_web_vrm_avatar(
    model_name: str,
    config: Optional[Dict[str, Any]] = None,
    websocket_send=None,
) -> WebVRMAvatar:
    """创建 Web VRM 形象"""
    from .model_manager import vrm_model_manager
    
    # 获取模型路径
    model_info = vrm_model_manager.get_model(model_name)
    if model_info is None:
        raise ValueError(f"Model not found: {model_name}")
    
    # 创建形象
    avatar = WebVRMAvatar(
        model_path=str(model_info.path),
        config=config,
        websocket_send=websocket_send,
    )
    
    # 初始化
    await avatar.initialize()
    await avatar.load_model()
    
    return avatar