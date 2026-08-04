"""
HakusAI 2.0 VAD (语音活动检测) 基类
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass
from enum import Enum
from collections import deque
import numpy as np
import asyncio
import logging

logger = logging.getLogger(__name__)


class VADState(Enum):
    """VAD状态"""
    SILENCE = "silence"
    SPEECH = "speech"


@dataclass
class VADConfig:
    """VAD配置"""
    threshold: float = 0.5
    min_speech_duration_ms: int = 250
    min_silence_duration_ms: int = 500
    speech_pad_ms: int = 100
    sample_rate: int = 16000


@dataclass
class VADResult:
    """VAD检测结果"""
    is_speech: bool
    confidence: float
    audio_data: Optional[np.ndarray] = None


class BaseVAD(ABC):
    """
    VAD基类
    
    所有语音活动检测引擎必须继承此类
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化VAD引擎
        
        Args:
            config: 配置字典
        """
        self.config = VADConfig(
            threshold=config.get("threshold", 0.5),
            min_speech_duration_ms=config.get("min_speech_duration_ms", 250),
            min_silence_duration_ms=config.get("min_silence_duration_ms", 500),
            speech_pad_ms=config.get("speech_pad_ms", 100),
            sample_rate=config.get("sample_rate", 16000)
        )
        
        self._initialized = False
        self._state = VADState.SILENCE
        self._speech_start_time: Optional[float] = None
        self._silence_start_time: Optional[float] = None
        
        # 回调函数
        self._on_speech_start: Optional[Callable] = None
        self._on_speech_end: Optional[Callable] = None
        self._on_vad_update: Optional[Callable] = None
        
        # 音频缓冲区
        self._audio_buffer: deque = deque(maxlen=int(
            self.config.sample_rate * self.config.speech_pad_ms / 1000
        ))
        
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """提供商名称"""
        pass
    
    @abstractmethod
    async def initialize(self):
        """初始化VAD引擎"""
        pass
    
    @abstractmethod
    async def process(
        self,
        audio_data: np.ndarray,
        sample_rate: Optional[int] = None
    ) -> VADResult:
        """
        处理音频帧
        
        Args:
            audio_data: 音频数据 (numpy数组)
            sample_rate: 采样率
            
        Returns:
            VAD检测结果
        """
        pass
    
    def set_callbacks(
        self,
        on_speech_start: Optional[Callable] = None,
        on_speech_end: Optional[Callable] = None,
        on_vad_update: Optional[Callable] = None
    ):
        """
        设置回调函数
        
        Args:
            on_speech_start: 语音开始回调
            on_speech_end: 语音结束回调
            on_vad_update: VAD更新回调
        """
        self._on_speech_start = on_speech_start
        self._on_speech_end = on_speech_end
        self._on_vad_update = on_vad_update
    
    async def process_stream(
        self,
        audio_stream,
        sample_rate: Optional[int] = None
    ):
        """
        处理音频流
        
        Args:
            audio_stream: 音频流（异步生成器）
            sample_rate: 采样率
        """
        async for audio_chunk in audio_stream:
            result = await self.process(audio_chunk, sample_rate)
            
            # 状态机处理
            await self._handle_state(result)
            
            # 调用更新回调
            if self._on_vad_update:
                if asyncio.iscoroutinefunction(self._on_vad_update):
                    await self._on_vad_update(result)
                else:
                    self._on_vad_update(result)
    
    async def _handle_state(self, result: VADResult):
        """
        处理VAD状态机
        
        Args:
            result: VAD检测结果
        """
        import time
        current_time = time.time()
        
        if result.is_speech:
            # 检测到语音
            if self._state == VADState.SILENCE:
                # 从静音切换到语音
                self._state = VADState.SPEECH
                self._speech_start_time = current_time
                
                # 触发语音开始回调
                if self._on_speech_start:
                    audio_with_pad = self._get_audio_with_pad(result.audio_data)
                    if asyncio.iscoroutinefunction(self._on_speech_start):
                        asyncio.create_task(self._on_speech_start(audio_with_pad))
                    else:
                        self._on_speech_start(audio_with_pad)
                
                logger.debug("VAD: Speech started")
            
            # 重置静音计时器
            self._silence_start_time = None
            
        else:
            # 检测到静音
            if self._state == VADState.SPEECH:
                # 从语音切换到静音
                if self._silence_start_time is None:
                    self._silence_start_time = current_time
                
                # 检查静音持续时间
                silence_duration = (current_time - self._silence_start_time) * 1000
                if silence_duration >= self.config.min_silence_duration_ms:
                    # 静音持续时间超过阈值，认为语音结束
                    self._state = VADState.SILENCE
                    
                    # 触发语音结束回调
                    if self._on_speech_end:
                        if asyncio.iscoroutinefunction(self._on_speech_end):
                            asyncio.create_task(self._on_speech_end())
                        else:
                            self._on_speech_end()
                    
                    logger.debug(f"VAD: Speech ended (silence: {silence_duration:.0f}ms)")
    
    def _get_audio_with_pad(self, audio_data: Optional[np.ndarray]) -> np.ndarray:
        """
        获取带前后填充的音频
        
        Args:
            audio_data: 当前音频数据
            
        Returns:
            带填充的音频数据
        """
        if audio_data is None:
            return np.array([])
        
        # 将缓冲区数据添加到开头
        if len(self._audio_buffer) > 0:
            pad_audio = np.array(list(self._audio_buffer))
            audio_data = np.concatenate([pad_audio, audio_data])
        
        return audio_data
    
    def _update_buffer(self, audio_data: np.ndarray):
        """
        更新音频缓冲区
        
        Args:
            audio_data: 音频数据
        """
        # 只保留最后 speech_pad_ms 的音频
        pad_samples = int(self.config.sample_rate * self.config.speech_pad_ms / 1000)
        
        if len(audio_data) > pad_samples:
            # 只保留最后部分
            audio_data = audio_data[-pad_samples:]
        
        # 添加到缓冲区
        for sample in audio_data:
            self._audio_buffer.append(sample)
    
    def _normalize_audio(self, audio_data: np.ndarray) -> np.ndarray:
        """
        归一化音频数据
        
        Args:
            audio_data: 原始音频数据
            
        Returns:
            归一化后的音频数据
        """
        if audio_data.dtype == np.int16:
            return audio_data.astype(np.float32) / 32768.0
        elif audio_data.dtype == np.int32:
            return audio_data.astype(np.float32) / 2147483648.0
        return audio_data.astype(np.float32)
    
    @property
    def state(self) -> VADState:
        """当前VAD状态"""
        return self._state
    
    @property
    def is_speaking(self) -> bool:
        """是否正在说话"""
        return self._state == VADState.SPEECH
    
    async def close(self):
        """关闭VAD引擎"""
        self._initialized = False
        self._audio_buffer.clear()
        logger.debug(f"VAD engine {self.provider_name} closed")


class VADRegistry:
    """
    VAD引擎注册表 - 单例模式
    """
    _instance: Optional['VADRegistry'] = None
    _engines: Dict[str, type] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def register(self, provider: str, engine_class: type):
        """
        注册VAD引擎
        
        Args:
            provider: 提供商名称
            engine_class: 引擎类
        """
        if not issubclass(engine_class, BaseVAD):
            raise ValueError(f"Engine class must inherit from BaseVAD")
        self._engines[provider] = engine_class
        logger.debug(f"Registered VAD engine: {provider}")
    
    def get_engine(self, provider: str) -> Optional[type]:
        """
        获取VAD引擎类
        
        Args:
            provider: 提供商名称
            
        Returns:
            引擎类或None
        """
        return self._engines.get(provider)
    
    def create_engine(self, provider: str, config: Dict[str, Any]) -> BaseVAD:
        """
        创建VAD引擎实例
        
        Args:
            provider: 提供商名称
            config: 配置字典
            
        Returns:
            引擎实例
        """
        engine_class = self.get_engine(provider)
        if engine_class is None:
            raise ValueError(f"Unknown VAD provider: {provider}")
        return engine_class(config)
    
    def list_providers(self) -> List[str]:
        """列出所有已注册的提供商"""
        return list(self._engines.keys())


# 全局注册表实例
vad_registry = VADRegistry()


def register_vad(provider: str):
    """
    VAD引擎注册装饰器
    
    用法:
        @register_vad("funasr")
        class FunASRVAD(BaseVAD):
            ...
    """
    def decorator(cls: type):
        vad_registry.register(provider, cls)
        return cls
    return decorator
