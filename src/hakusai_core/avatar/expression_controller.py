"""
表情和动作控制系统
结合 Open-LLM-VTuber 的情感映射和 ZerolanLiveRobot 的动画控制
"""

import asyncio
import time
import random
from typing import Optional, Callable, Dict, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger

from .base import BaseAvatar, Expression, Motion
from .model_manager import live2d_model_manager


class EmotionType(str, Enum):
    """情感类型枚举"""
    NEUTRAL = "neutral"
    JOY = "joy"
    ANGER = "anger"
    SADNESS = "sadness"
    FEAR = "fear"
    SURPRISE = "surprise"
    DISGUST = "disgust"
    SMIRK = "smirk"


@dataclass
class EmotionState:
    """情感状态"""
    emotion: EmotionType
    intensity: float = 1.0  # 0-1
    start_time: float = field(default_factory=time.time)
    duration: Optional[float] = None  # None 表示持续到下一个情感


@dataclass
class AnimationConfig:
    """动画配置"""
    auto_blink: bool = True
    blink_interval: Tuple[float, float] = (2.0, 5.0)  # 眨眼间隔（秒）
    blink_duration: float = 0.15  # 眨眼持续时间

    auto_breath: bool = True
    breath_intensity: float = 0.5  # 呼吸强度 0-1
    breath_speed: float = 1.0  # 呼吸速度

    idle_motion: bool = True
    idle_motion_interval: Tuple[float, float] = (10.0, 20.0)

    mouse_tracking: bool = True
    tracking_smoothing: float = 0.3  # 鼠标追踪平滑度


class ExpressionController:
    """
    表情控制器
    
    功能：
    - 管理情感状态转换
    - 自动行为（眨眼、呼吸、待机动作）
    - 动作队列管理
    - 平滑过渡
    """

    def __init__(self, avatar: BaseAvatar, config: Optional[AnimationConfig] = None):
        """
        初始化表情控制器
        
        Args:
            avatar: 虚拟形象实例
            config: 动画配置
        """
        self.avatar = avatar
        self.config = config or AnimationConfig()

        # 当前状态
        self._current_emotion: EmotionState = EmotionState(EmotionType.NEUTRAL)
        self._previous_expression: Optional[int] = None
        self._target_expression: Optional[int] = None
        self._expression_blend: float = 0.0  # 表情混合进度 0-1

        # 动作队列
        self._motion_queue: asyncio.Queue = asyncio.Queue()
        self._current_motion: Optional[str] = None

        # 自动行为状态
        self._last_blink_time: float = 0.0
        self._is_blinking: bool = False
        self._blink_start_time: float = 0.0
        self._breath_phase: float = 0.0  # 呼吸相位 0-2π

        # 鼠标追踪
        self._mouse_pos: Tuple[float, float] = (0.5, 0.5)
        self._current_look_at: Tuple[float, float] = (0.5, 0.5)

        # 运行状态
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

        # 回调
        self._on_emotion_change: Optional[Callable] = None

    async def start(self):
        """启动控制器"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._update_loop())
        logger.debug("ExpressionController started")

    async def stop(self):
        """停止控制器"""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.debug("ExpressionController stopped")

    def set_emotion(self, emotion: EmotionType, intensity: float = 1.0, duration: Optional[float] = None):
        """
        设置情感
        
        Args:
            emotion: 情感类型
            intensity: 强度 0-1
            duration: 持续时间（秒）
        """
        old_emotion = self._current_emotion.emotion
        self._current_emotion = EmotionState(emotion, intensity, time.time(), duration)

        # 获取表情索引
        expression_idx = live2d_model_manager.emo_map.get(emotion.value)
        if expression_idx is not None:
            self._previous_expression = self._target_expression
            self._target_expression = expression_idx
            self._expression_blend = 0.0

            # 应用表情
            if self.avatar:
                self.avatar.set_expression(str(expression_idx), intensity)

        logger.debug(f"Emotion changed: {old_emotion} -> {emotion} (intensity={intensity})")

        # 触发回调
        if self._on_emotion_change:
            if asyncio.iscoroutinefunction(self._on_emotion_change):
                asyncio.create_task(self._on_emotion_change(emotion, intensity))
            else:
                self._on_emotion_change(emotion, intensity)

    def set_emotion_from_text(self, text: str):
        """
        从文本中提取并设置情感
        
        Args:
            text: 包含 [emotion] 标签的文本
        """
        emotions = live2d_model_manager.extract_emotions(text)
        if emotions:
            # 使用第一个匹配的情感
            expr_idx = emotions[0]
            # 反向查找情感名称
            for name, idx in live2d_model_manager.emo_map.items():
                if idx == expr_idx:
                    try:
                        emotion = EmotionType(name)
                        self.set_emotion(emotion)
                        break
                    except ValueError:
                        continue

    def queue_motion(self, motion_name: str, loop: bool = False, priority: int = 1):
        """
        添加动作到队列
        
        Args:
            motion_name: 动作名称
            loop: 是否循环
            priority: 优先级（数字越小越优先）
        """
        self._motion_queue.put_nowait(Motion(motion_name, loop, priority))
        logger.debug(f"Motion queued: {motion_name}")

    def play_motion(self, motion_name: str, loop: bool = False):
        """
        立即播放动作
        
        Args:
            motion_name: 动作名称
            loop: 是否循环
        """
        if self.avatar:
            self.avatar.set_motion(motion_name, loop)
            self._current_motion = motion_name
            logger.debug(f"Motion playing: {motion_name}")

    def update_mouse_position(self, x: float, y: float):
        """
        更新鼠标位置（用于视线追踪）
        
        Args:
            x: 屏幕X坐标 0-1
            y: 屏幕Y坐标 0-1
        """
        self._mouse_pos = (x, y)

    def set_callback(self, callback: Callable):
        """
        设置情感变化回调
        
        Args:
            callback: 回调函数 (emotion, intensity) -> None
        """
        self._on_emotion_change = callback

    async def _update_loop(self):
        """主更新循环"""
        while self._running:
            try:
                current_time = time.time()
                delta_time = 0.033  # ~30fps

                # 更新自动行为
                await self._update_auto_behaviors(current_time)

                # 更新表情混合
                self._update_expression_blend(delta_time)

                # 处理动作队列
                await self._process_motion_queue()

                # 更新鼠标追踪
                self._update_mouse_tracking(delta_time)

                await asyncio.sleep(delta_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in expression update loop: {e}")
                await asyncio.sleep(0.1)

    async def _update_auto_behaviors(self, current_time: float):
        """更新自动行为"""
        # 自动眨眼
        if self.config.auto_blink and not self._is_blinking:
            time_since_blink = current_time - self._last_blink_time
            blink_interval = random.uniform(*self.config.blink_interval)

            if time_since_blink >= blink_interval:
                self._start_blink(current_time)

        # 更新眨眼状态
        if self._is_blinking:
            blink_elapsed = current_time - self._blink_start_time
            if blink_elapsed >= self.config.blink_duration:
                self._end_blink()
                self._last_blink_time = current_time

        # 自动呼吸
        if self.config.auto_breath:
            self._breath_phase += 0.05 * self.config.breath_speed
            if self._breath_phase > 2 * 3.14159:
                self._breath_phase -= 2 * 3.14159

            # 呼吸效果可以通过参数传递给模型（如果支持）
            breath_value = math.sin(self._breath_phase) * self.config.breath_intensity

    def _start_blink(self, current_time: float):
        """开始眨眼"""
        self._is_blinking = True
        self._blink_start_time = current_time
        # 可以在这里触发眨眼表情或参数变化

    def _end_blink(self):
        """结束眨眼"""
        self._is_blinking = False

    def _update_expression_blend(self, delta_time: float):
        """更新表情混合（平滑过渡）"""
        if self._target_expression is not None and self._expression_blend < 1.0:
            # 混合速度：每秒完成 80%
            blend_speed = 8.0
            self._expression_blend = min(1.0, self._expression_blend + blend_speed * delta_time)

            if self._expression_blend >= 1.0:
                self._previous_expression = self._target_expression

    async def _process_motion_queue(self):
        """处理动作队列"""
        if self._motion_queue.empty() or self._current_motion:
            return

        try:
            motion = self._motion_queue.get_nowait()
            self.play_motion(motion.name, motion.loop)
        except asyncio.QueueEmpty:
            pass

    def _update_mouse_tracking(self, delta_time: float):
        """更新鼠标追踪（平滑跟随）"""
        if not self.config.mouse_tracking:
            return

        smoothing = self.config.tracking_smoothing

        # 线性插值
        self._current_look_at = (
            self._current_look_at[0] + (self._mouse_pos[0] - self._current_look_at[0]) * smoothing,
            self._current_look_at[1] + (self._mouse_pos[1] - self._current_look_at[1]) * smoothing,
        )

        # 应用到形象
        if self.avatar:
            self.avatar.look_at(*self._current_look_at)

    @property
    def current_emotion(self) -> EmotionType:
        """获取当前情感"""
        return self._current_emotion.emotion

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running


import math
