"""
HakusAI 2.0 嘴型同步系统
分析音频并驱动虚拟形象嘴型动画
"""

import asyncio
import numpy as np
from typing import Optional, Callable, Dict, Tuple
from dataclasses import dataclass
from collections import deque
import logging

from .base import LipSyncData, BaseAvatar
from ..utils.events import EventType, emit

logger = logging.getLogger(__name__)


@dataclass
class LipSyncConfig:
    """嘴型同步配置"""
    sample_rate: int = 16000
    frame_size: int = 512  # 每帧样本数
    smoothing: float = 0.3  # 平滑系数 (0-1)
    sensitivity: float = 1.0  # 灵敏度
    min_volume: float = 0.01  # 最小音量阈值
    max_volume: float = 0.5   # 最大音量参考值


class LipSyncAnalyzer:
    """
    嘴型同步分析器
    
    分析音频音量，转换为嘴型开合程度
    """
    
    def __init__(self, config: Optional[LipSyncConfig] = None):
        """
        初始化分析器
        
        Args:
            config: 配置
        """
        self.config = config or LipSyncConfig()
        self._smoothed_value: float = 0.0
        self._history: deque = deque(maxlen=10)
        
    def analyze(self, audio_data: np.ndarray) -> LipSyncData:
        """
        分析音频数据
        
        Args:
            audio_data: 音频数据 (numpy数组)
            
        Returns:
            嘴型同步数据
        """
        # 归一化音频数据
        if audio_data.dtype == np.int16:
            audio_float = audio_data.astype(np.float32) / 32768.0
        elif audio_data.dtype == np.int32:
            audio_float = audio_data.astype(np.float32) / 2147483648.0
        else:
            audio_float = audio_data.astype(np.float32)
        
        # 计算音量 (RMS)
        volume = np.sqrt(np.mean(audio_float ** 2))
        
        # 应用灵敏度
        volume *= self.config.sensitivity
        
        # 限制范围
        volume = np.clip(volume, self.config.min_volume, self.config.max_volume)
        
        # 归一化到 0-1
        normalized_volume = (volume - self.config.min_volume) / (self.config.max_volume - self.config.min_volume)
        
        # 平滑处理
        self._smoothed_value = (
            self.config.smoothing * self._smoothed_value +
            (1 - self.config.smoothing) * normalized_volume
        )
        
        # 保存历史
        self._history.append(self._smoothed_value)
        
        return LipSyncData(
            mouth_open=self._smoothed_value,
            mouth_form=0.5,  # 默认嘴型
            volume=self._smoothed_value
        )
    
    def reset(self):
        """重置状态"""
        self._smoothed_value = 0.0
        self._history.clear()


class LipSyncEngine:
    """
    嘴型同步引擎
    
    将音频流转换为嘴型动画，驱动虚拟形象
    """
    
    def __init__(
        self,
        avatar: Optional[BaseAvatar] = None,
        config: Optional[LipSyncConfig] = None
    ):
        """
        初始化引擎
        
        Args:
            avatar: 虚拟形象实例
            config: 配置
        """
        self.avatar = avatar
        self.config = config or LipSyncConfig()
        self.analyzer = LipSyncAnalyzer(self.config)
        
        self._running = False
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        
        # 回调
        self._on_lipsync: Optional[Callable] = None
        
    def set_avatar(self, avatar: BaseAvatar):
        """
        设置目标形象
        
        Args:
            avatar: 虚拟形象实例
        """
        self.avatar = avatar
        
    def set_callback(self, callback: Callable):
        """
        设置嘴型同步回调
        
        Args:
            callback: 回调函数，接收LipSyncData
        """
        self._on_lipsync = callback
        
    async def start(self):
        """启动引擎"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.debug("LipSync engine started")
        
    async def stop(self):
        """停止引擎"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        self.analyzer.reset()
        
        # 重置形象嘴型
        if self.avatar:
            self.avatar.update_lipsync(LipSyncData())
        
        logger.debug("LipSync engine stopped")
        
    async def feed_audio(self, audio_data: np.ndarray):
        """
        输入音频数据
        
        Args:
            audio_data: 音频数据
        """
        await self._audio_queue.put(audio_data)
        
    async def _process_loop(self):
        """处理循环"""
        while self._running:
            try:
                # 获取音频数据
                audio_data = await asyncio.wait_for(
                    self._audio_queue.get(),
                    timeout=0.1
                )
                
                # 分析音频
                lip_data = self.analyzer.analyze(audio_data)
                
                # 更新形象
                if self.avatar:
                    self.avatar.update_lipsync(lip_data)
                
                # 触发事件
                await emit(EventType.AVATAR_LIPSYNC_UPDATE, {
                    "mouth_open": lip_data.mouth_open,
                    "volume": lip_data.volume
                })
                
                # 调用回调
                if self._on_lipsync:
                    if asyncio.iscoroutinefunction(self._on_lipsync):
                        await self._on_lipsync(lip_data)
                    else:
                        self._on_lipsync(lip_data)
                        
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in lip sync loop: {e}")
                
    def update_config(self, config: LipSyncConfig):
        """
        更新配置
        
        Args:
            config: 新配置
        """
        self.config = config
        self.analyzer.config = config


class PhonemeMapper:
    """
    音素映射器
    
    将音素映射到嘴型参数（用于更精确的嘴型同步）
    """
    
    # 简化的音素到嘴型映射
    PHONEME_MAP = {
        # 元音 - 嘴巴张开
        'a': (0.8, 0.5),  # 啊
        'e': (0.5, 0.8),  # 呃
        'i': (0.2, 0.9),  # 衣
        'o': (0.6, 0.2),  # 哦
        'u': (0.3, 0.1),  # 乌
        
        # 辅音 - 嘴巴闭合或半开
        'b': (0.0, 0.5),  # 波
        'p': (0.0, 0.5),  # 坡
        'm': (0.0, 0.5),  # 摸
        'f': (0.2, 0.3),  # 佛
        'v': (0.2, 0.3),  # 微
        
        # 默认
        'default': (0.3, 0.5),
    }
    
    @classmethod
    def get_mouth_shape(cls, phoneme: str) -> Tuple[float, float]:
        """
        获取音素对应的嘴型
        
        Args:
            phoneme: 音素
            
        Returns:
            (mouth_open, mouth_form) 元组
        """
        phoneme_lower = phoneme.lower()
        return cls.PHONEME_MAP.get(phoneme_lower, cls.PHONEME_MAP['default'])
    
    @classmethod
    def text_to_phonemes(cls, text: str) -> list:
        """
        将文本转换为音素序列（简化版）
        
        Args:
            text: 文本
            
        Returns:
            音素列表
        """
        # 这里应该使用真正的TTS前端或拼音转换
        # 简化实现：直接返回字符
        return list(text.lower())


# 全局引擎实例
_lip_sync_engine: Optional[LipSyncEngine] = None


async def get_lip_sync_engine(
    avatar: Optional[BaseAvatar] = None,
    config: Optional[LipSyncConfig] = None
) -> LipSyncEngine:
    """
    获取嘴型同步引擎实例（单例）
    
    Args:
        avatar: 虚拟形象
        config: 配置
        
    Returns:
        引擎实例
    """
    global _lip_sync_engine
    
    if _lip_sync_engine is None:
        _lip_sync_engine = LipSyncEngine(avatar, config)
        await _lip_sync_engine.start()
    elif avatar:
        _lip_sync_engine.set_avatar(avatar)
    
    return _lip_sync_engine


async def stop_lip_sync_engine():
    """停止嘴型同步引擎"""
    global _lip_sync_engine
    
    if _lip_sync_engine:
        await _lip_sync_engine.stop()
        _lip_sync_engine = None
