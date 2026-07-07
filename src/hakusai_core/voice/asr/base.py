"""
HakusAI 2.0 ASR (自动语音识别) 基类
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, BinaryIO
from dataclasses import dataclass
from enum import Enum
import numpy as np
import logging

logger = logging.getLogger(__name__)


class ASRProvider(str, Enum):
    """ASR提供商"""
    SHERPA_ONNX = "sherpa_onnx"
    WHISPER = "whisper"
    FUNASR = "funasr"
    AZURE = "azure"


@dataclass
class ASRResult:
    """ASR识别结果"""
    text: str
    confidence: float = 0.0
    language: Optional[str] = None
    duration: Optional[float] = None  # 音频时长（秒）
    

class BaseASR(ABC):
    """
    ASR基类
    
    所有语音识别引擎必须继承此类
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化ASR引擎
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.provider = config.get("provider", "sherpa_onnx")
        self.language = config.get("language", "zh")
        self.sample_rate = config.get("sample_rate", 16000)
        self._initialized = False
        
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """提供商名称"""
        pass
    
    @abstractmethod
    async def initialize(self):
        """初始化ASR引擎"""
        pass
    
    @abstractmethod
    async def transcribe(
        self,
        audio_data: np.ndarray,
        sample_rate: Optional[int] = None
    ) -> ASRResult:
        """
        识别音频
        
        Args:
            audio_data: 音频数据 (numpy数组)
            sample_rate: 采样率，默认使用配置中的值
            
        Returns:
            识别结果
        """
        pass
    
    @abstractmethod
    async def transcribe_file(self, file_path: str) -> ASRResult:
        """
        识别音频文件
        
        Args:
            file_path: 音频文件路径
            
        Returns:
            识别结果
        """
        pass
    
    async def transcribe_stream(
        self,
        audio_stream: BinaryIO,
        sample_rate: Optional[int] = None
    ) -> ASRResult:
        """
        识别音频流
        
        Args:
            audio_stream: 音频流
            sample_rate: 采样率
            
        Returns:
            识别结果
        """
        # 默认实现：读取全部数据后识别
        audio_bytes = audio_stream.read()
        audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
        return await self.transcribe(audio_data, sample_rate)
    
    def _resample(
        self,
        audio_data: np.ndarray,
        orig_sr: int,
        target_sr: int
    ) -> np.ndarray:
        """
        重采样音频
        
        Args:
            audio_data: 原始音频数据
            orig_sr: 原始采样率
            target_sr: 目标采样率
            
        Returns:
            重采样后的音频数据
        """
        if orig_sr == target_sr:
            return audio_data
        
        # 简单的线性插值重采样
        try:
            import librosa
            return librosa.resample(
                audio_data.astype(np.float32),
                orig_sr=orig_sr,
                target_sr=target_sr
            )
        except ImportError:
            # 如果没有librosa，使用简单的numpy重采样
            from scipy import signal
            return signal.resample(
                audio_data,
                int(len(audio_data) * target_sr / orig_sr)
            )
    
    def _normalize_audio(self, audio_data: np.ndarray) -> np.ndarray:
        """
        归一化音频数据
        
        Args:
            audio_data: 原始音频数据
            
        Returns:
            归一化后的音频数据
        """
        # 转换为float32并归一化到[-1, 1]
        if audio_data.dtype == np.int16:
            audio_data = audio_data.astype(np.float32) / 32768.0
        elif audio_data.dtype == np.int32:
            audio_data = audio_data.astype(np.float32) / 2147483648.0
        
        return audio_data
    
    async def close(self):
        """关闭ASR引擎"""
        self._initialized = False
        logger.debug(f"ASR engine {self.provider_name} closed")


class ASRRegistry:
    """
    ASR引擎注册表 - 单例模式
    """
    _instance: Optional['ASRRegistry'] = None
    _engines: Dict[str, type] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def register(self, provider: str, engine_class: type):
        """
        注册ASR引擎
        
        Args:
            provider: 提供商名称
            engine_class: 引擎类
        """
        if not issubclass(engine_class, BaseASR):
            raise ValueError(f"Engine class must inherit from BaseASR")
        self._engines[provider] = engine_class
        logger.debug(f"Registered ASR engine: {provider}")
    
    def get_engine(self, provider: str) -> Optional[type]:
        """
        获取ASR引擎类
        
        Args:
            provider: 提供商名称
            
        Returns:
            引擎类或None
        """
        return self._engines.get(provider)
    
    def create_engine(self, provider: str, config: Dict[str, Any]) -> BaseASR:
        """
        创建ASR引擎实例
        
        Args:
            provider: 提供商名称
            config: 配置字典
            
        Returns:
            引擎实例
        """
        engine_class = self.get_engine(provider)
        if engine_class is None:
            raise ValueError(f"Unknown ASR provider: {provider}")
        return engine_class(config)
    
    def list_providers(self) -> list:
        """列出所有已注册的提供商"""
        return list(self._engines.keys())


# 全局注册表实例
asr_registry = ASRRegistry()


def register_asr(provider: str):
    """
    ASR引擎注册装饰器
    
    用法:
        @register_asr("sherpa_onnx")
        class SherpaONNXASR(BaseASR):
            ...
    """
    def decorator(cls: type):
        asr_registry.register(provider, cls)
        return cls
    return decorator
