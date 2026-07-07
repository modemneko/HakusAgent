"""
Web 端 Live2D 虚拟形象实现
基于 Open-LLM-VTuber 的前端渲染架构 + 改进的控制算法

特点：
- 通过 WebSocket 与前端 Live2D 模型通信
- 集成高精度口型同步引擎 V2
- 完整的表情和动作控制系统
- 支持实时参数调整
"""

import asyncio
import json
import time
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from pathlib import Path
from loguru import logger

from .base import BaseAvatar, AvatarType, AvatarPosition, LipSyncData, Expression, Motion
from .model_manager import live2d_model_manager, ModelInfo
from .expression_controller import ExpressionController, EmotionType, AnimationConfig
from .lip_sync_v2 import LipSyncEngineV2, LipSyncConfig, get_lip_sync_engine


@dataclass
class Live2DConfig:
    """Live2D 特定配置"""
    model_name: str = "shizuku"
    lip_sync_enabled: bool = True
    expression_enabled: bool = True

    # 口型配置
    lip_sync_multiplier: float = 3.0  # 口型放大系数

    # 表情配置
    auto_blink: bool = True
    auto_breath: bool = True

    # 渲染配置
    opacity: float = 1.0
    scale: float = 1.0


class WebLive2DAvatar(BaseAvatar):
    """
    Web 端 Live2D 虚拟形象
    
    架构：
    - 后端：管理模型、表情、口型数据
    - 前端：实际渲染 Live2D 模型
    - 通信：WebSocket 实时双向通信
    
    使用方式：
    ```python
    avatar = WebLive2DAvatar(model_name="shizuku")
    await avatar.initialize()
    
    # 设置表情
    avatar.set_expression("joy", 0.8)
    
    # 更新嘴型（由 LipSyncEngine 自动调用）
    avatar.update_lipsync(LipSyncData(mouth_open=0.7))
    ```
    """

    def __init__(
        self,
        model_path: str = "",
        config: Optional[Dict[str, Any]] = None,
        websocket_send: Optional[Callable] = None
    ):
        """
        初始化 Web Live2D 形象
        
        Args:
            model_path: 模型路径（可选，也可通过 config.model_name 加载）
            config: 配置字典
            websocket_send: WebSocket 发送函数
        """
        super().__init__(model_path or "", config)

        # 解析特定配置
        self.live2d_config = Live2DConfig(**{
            k: v for k, v in (config or {}).items()
            if k in Live2DConfig.__dataclass_fields__
        })

        # WebSocket 通信接口
        self._websocket_send: Optional[Callable] = websocket_send

        # 子系统初始化
        self._expression_controller: Optional[ExpressionController] = None
        self._lip_sync_engine: Optional[LipSyncEngineV2] = None

        # 当前状态
        self._current_lip_data: LipSyncData = LipSyncData()
        self._last_update_time: float = 0.0

        # 缓存的模型信息
        self._model_info: Optional[ModelInfo] = None

    @property
    def avatar_type(self) -> AvatarType:
        return AvatarType.LIVE2D

    @property
    def model_name(self) -> str:
        return self.live2d_config.model_name

    async def initialize(self):
        """初始化所有子系统"""
        try:
            # 1. 初始化模型管理器
            if self.live2d_config.model_name:
                success = live2d_model_manager.set_model(self.live2d_config.model_name)
                if not success:
                    logger.warning(f"Failed to set model: {self.live2d_config.model_name}")

                self._model_info = live2d_model_manager.current_model

            # 2. 初始化表情控制器
            anim_config = AnimationConfig(
                auto_blink=self.live2d_config.auto_blink,
                auto_breath=self.live2d_config.auto_breath,
            )
            self._expression_controller = ExpressionController(self, anim_config)

            # 3. 初始化口型同步引擎
            if self.live2d_config.lip_sync_enabled:
                lip_config = LipSyncConfig(
                    lip_sync_multiplier=self.live2d_config.lip_sync_multiplier,
                )
                self._lip_sync_engine = await get_lip_sync_engine(
                    avatar=self,
                    config=lip_config
                )

            self._initialized = True
            logger.info(f"WebLive2DAvatar initialized: {self.live2d_config.model_name}")

        except Exception as e:
            logger.error(f"Failed to initialize WebLive2DAvatar: {e}")
            raise

    async def load(self) -> bool:
        """加载模型（发送配置到前端）"""
        if not self._initialized:
            await self.initialize()

        try:
            # 发送模型配置到前端
            model_config = live2d_model_manager.get_model_config()

            if model_config and self._websocket_send:
                await self._websocket_send(json.dumps({
                    "type": "set-model-and-conf",
                    "model_info": model_config,
                    "avatar_type": "live2d"
                }))

            self._loaded = True
            logger.info(f"Live2D model loaded: {self.live2d_config.model_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to load Live2D model: {e}")
            return False

    async def unload(self):
        """卸载模型"""
        # 停止子系统
        if self._expression_controller:
            await self._expression_controller.stop()

        if self._lip_sync_engine:
            from . import lip_sync_v2
            await lip_sync_v2.stop_lip_sync_engine()
            self._lip_sync_engine = None

        self._loaded = False
        logger.debug("Live2D model unloaded")

    async def update(self, delta_time: float):
        """更新状态（由主循环调用）"""
        pass  # Web 端不需要后端更新循环

    def set_expression(self, expression: str, intensity: float = 1.0):
        """
        设置表情
        
        Args:
            expression: 表情名称或索引
            intensity: 强度 0-1
        """
        self.current_expression = expression

        # 发送到前端
        if self._websocket_send:
            try:
                message = {
                    "type": "expression",
                    "expression": expression,
                    "intensity": intensity,
                    "timestamp": time.time()
                }
                # 使用 asyncio 确保异步安全
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._send(message))
                else:
                    loop.run_until_complete(self._send(message))
            except Exception as e:
                logger.error(f"Failed to send expression: {e}")

    async def _send(self, message: dict):
        """辅助方法：发送消息"""
        if self._websocket_send:
            await self._websocket_send(json.dumps(message))

    def set_motion(self, motion: str, loop: bool = False):
        """
        设置动作
        
        Args:
            motion: 动作名称
            loop: 是否循环
        """
        self.current_motion = motion

        if self._websocket_send:
            try:
                message = {
                    "type": "motion",
                    "motion": motion,
                    "loop": loop,
                    "timestamp": time.time()
                }
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._send(message))
                else:
                    loop.run_until_complete(self._send(message))
            except Exception as e:
                logger.error(f"Failed to send motion: {e}")

    def update_lipsync(self, data: LipSyncData):
        """
        更新嘴型同步（核心方法）
        
        由 LipSyncEngine 自动调用，也可以手动调用
        
        Args:
            data: 嘴型同步数据
        """
        self._current_lip_data = data

        # 发送到前端
        if self._websocket_send and data.mouth_open > 0.01:  # 只发送有效数据
            try:
                message = {
                    "type": "lip_sync",
                    "mouth_open": round(data.mouth_open, 3),
                    "mouth_form": round(data.mouth_form, 3),
                    "volume": round(data.volume, 3),
                    "timestamp": time.time()
                }
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._send(message))
            except Exception as e:
                logger.debug(f"Failed to send lip sync (non-critical): {e}")

    def set_position(self, position: AvatarPosition):
        """设置位置"""
        self.position = position

        if self._websocket_send:
            try:
                message = {
                    "type": "position",
                    "x": position.x,
                    "y": position.y,
                    "scale": position.scale,
                    "rotation": position.rotation
                }
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._send(message))
            except Exception as e:
                logger.error(f"Failed to send position: {e}")

    def look_at(self, x: float, y: float):
        """注视某点"""
        if self._websocket_send:
            try:
                message = {
                    "type": "look_at",
                    "x": x,
                    "y": y
                }
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._send(message))
            except Exception as e:
                logger.debug(f"Failed to send look_at: {e}")

    def get_expressions(self) -> List[str]:
        """获取可用表情列表"""
        return list(live2d_model_manager.emo_map.keys())

    def get_motions(self) -> List[str]:
        """获取可用动作列表"""
        # 从当前模型配置获取
        if self._model_info and self._model_info.tapMotions:
            motions = []
            for area, motion_dict in self._model_info.tapMotions.items():
                motions.extend(motion_dict.keys())
            return list(set(motions))
        return []

    async def speak(self, text: str = ""):
        """开始说话"""
        self.is_speaking = True

        # 从文本提取情感
        if text and self._expression_controller:
            self._expression_controller.set_emotion_from_text(text)

        if self._websocket_send:
            await self._send({
                "type": "speak_start",
                "text": text[:100] if text else ""
            })

    async def stop_speaking(self):
        """停止说话"""
        self.is_speaking = False
        self.update_lipsync(LipSyncData())  # 重置嘴型

        if self._websocket_send:
            await self._send({"type": "speak_end"})

    def on_mouse_move(self, x: float, y: float):
        """鼠标移动事件"""
        super().on_mouse_move(x, y)

        if self._expression_controller:
            self._expression_controller.update_mouse_position(x, y)

    def on_click(self, x: float, y: float):
        """点击事件"""
        super().on_click(x, y)

        # 可以触发点击动作
        if self._model_info and self._model_info.tapMotions:
            # 简单实现：播放第一个可用动作
            for area, motions in self._model_info.tapMotions.items():
                if motions:
                    motion_name = list(motions.keys())[0]
                    self.queue_motion(motion_name)
                    break

    def queue_motion(self, motion_name: str):
        """队列化动作"""
        if self._expression_controller:
            self._expression_controller.queue_motion(motion_name)

    def set_emotion(self, emotion: EmotionType, intensity: float = 1.0):
        """设置情感（高级接口）"""
        if self._expression_controller:
            self._expression_controller.set_emotion(emotion, intensity)

    def set_websocket_sender(self, send_func: Callable):
        """
        设置 WebSocket 发送函数
        
        Args:
            send_func: 异步发送函数 (message_str) -> None
        """
        self._websocket_send = send_func

    async def close(self):
        """关闭并清理资源"""
        await self.unload()
        self._initialized = False
        logger.debug(f"WebLive2DAvatar closed: {self.live2d_config.model_name}")

    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "type": "live2d",
            "model_name": self.live2d_config.model_name,
            "is_loaded": self._loaded,
            "is_initialized": self._initialized,
            "is_speaking": self.is_speaking,
            "current_expression": self.current_expression,
            "current_motion": self.current_motion,
            "lip_sync_enabled": self.live2d_config.lip_sync_enabled,
            "expression_enabled": self.live2d_config.expression_enabled,
            "available_expressions": self.get_expressions(),
            "available_motions": self.get_motions(),
        }


# ========== 工厂函数 ==========

async def create_web_live2d_avatar(
    model_name: str = "shizuku",
    config: Optional[Dict[str, Any]] = None,
    websocket_send: Optional[Callable] = None
) -> WebLive2DAvatar:
    """
    创建 Web Live2D 虚拟形象实例
    
    Args:
        model_name: 模型名称
        config: 配置
        websocket_send: WebSocket 发送函数
        
    Returns:
        初始化完成的形象实例
    """
    config = config or {}
    config["model_name"] = model_name

    avatar = WebLive2DAvatar(config=config, websocket_send=websocket_send)
    await avatar.initialize()
    await avatar.load()

    return avatar
