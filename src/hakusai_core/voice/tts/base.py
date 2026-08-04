"""
HakusAI 2.0 TTS (文本转语音) 基类
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, BinaryIO, AsyncIterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import hashlib
import logging

logger = logging.getLogger(__name__)


class TTSProvider(str, Enum):
    """TTS提供商"""
    COSYVOICE = "cosyvoice"
    GPT_SOVITS = "gpt_sovits"
    ELEVENLABS = "elevenlabs"


@dataclass
class TTSResult:
    """TTS合成结果"""
    audio_data: bytes
    sample_rate: int = 16000
    format: str = "wav"  # wav, mp3, pcm
    duration: Optional[float] = None  # 音频时长（秒）
    cached: bool = False  # 是否来自缓存


class BaseTTS(ABC):
    """
    TTS基类
    
    所有语音合成引擎必须继承此类
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化TTS引擎
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.provider = config.get("provider", "cosyvoice")
        self.voice = config.get("voice", "")
        self.speed = config.get("speed", 1.0)
        self.volume = config.get("volume", 1.0)
        
        # 缓存配置
        self.cache_enabled = config.get("cache_enabled", True)
        self.cache_dir = Path(config.get("cache_dir", "data/cache/tts"))
        if self.cache_enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self._initialized = False
        
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """提供商名称"""
        pass
    
    @abstractmethod
    async def initialize(self):
        """初始化TTS引擎"""
        pass
    
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs
    ) -> TTSResult:
        """
        合成语音
        
        Args:
            text: 要合成的文本
            voice: 语音名称，默认使用配置中的值
            speed: 语速，默认使用配置中的值
            **kwargs: 其他参数
            
        Returns:
            合成结果
        """
        pass
    
    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs
    ) -> AsyncIterator[bytes]:
        """
        流式合成语音
        
        Args:
            text: 要合成的文本
            voice: 语音名称
            speed: 语速
            **kwargs: 其他参数
            
        Yields:
            音频数据块
        """
        # 默认实现：先完整合成再分块返回
        result = await self.synthesize(text, voice, speed, **kwargs)
        chunk_size = 4096
        for i in range(0, len(result.audio_data), chunk_size):
            yield result.audio_data[i:i + chunk_size]
    
    async def synthesize_to_file(
        self,
        text: str,
        file_path: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs
    ) -> str:
        """
        合成语音并保存到文件
        
        Args:
            text: 要合成的文本
            file_path: 输出文件路径
            voice: 语音名称
            speed: 语速
            **kwargs: 其他参数
            
        Returns:
            输出文件路径
        """
        result = await self.synthesize(text, voice, speed, **kwargs)
        
        with open(file_path, 'wb') as f:
            f.write(result.audio_data)
        
        return file_path
    
    def _get_cache_key(self, text: str, voice: str, speed: float) -> str:
        """
        生成缓存键
        
        Args:
            text: 文本
            voice: 语音
            speed: 语速
            
        Returns:
            缓存键
        """
        key = f"{self.provider}:{voice}:{speed}:{text}"
        return hashlib.md5(key.encode()).hexdigest()
    
    def _get_cache_path(self, cache_key: str, format: str = "wav") -> Path:
        """
        获取缓存文件路径
        
        Args:
            cache_key: 缓存键
            format: 音频格式
            
        Returns:
            缓存文件路径
        """
        return self.cache_dir / f"{cache_key}.{format}"
    
    def _check_cache(self, text: str, voice: str, speed: float) -> Optional[TTSResult]:
        """
        检查缓存
        
        Args:
            text: 文本
            voice: 语音
            speed: 语速
            
        Returns:
            缓存结果或None
        """
        if not self.cache_enabled:
            return None
        
        cache_key = self._get_cache_key(text, voice, speed)
        cache_path = self._get_cache_path(cache_key)
        
        if cache_path.exists():
            with open(cache_path, 'rb') as f:
                audio_data = f.read()
            
            return TTSResult(
                audio_data=audio_data,
                cached=True
            )
        
        return None
    
    def _save_cache(
        self,
        text: str,
        voice: str,
        speed: float,
        audio_data: bytes,
        format: str = "wav"
    ):
        """
        保存到缓存
        
        Args:
            text: 文本
            voice: 语音
            speed: 语速
            audio_data: 音频数据
            format: 音频格式
        """
        if not self.cache_enabled:
            return
        
        cache_key = self._get_cache_key(text, voice, speed)
        cache_path = self._get_cache_path(cache_key, format)
        
        try:
            with open(cache_path, 'wb') as f:
                f.write(audio_data)
            logger.debug(f"Saved TTS cache: {cache_path}")
        except Exception as e:
            logger.warning(f"Failed to save TTS cache: {e}")
    
    def _preprocess_text(self, text: str) -> str:
        """
        预处理文本
        
        Args:
            text: 原始文本
            
        Returns:
            处理后的文本
        """
        # 移除多余的空白字符
        text = ' '.join(text.split())
        
        # 限制长度（防止过长文本）
        max_length = self.config.get("max_text_length", 5000)
        if len(text) > max_length:
            text = text[:max_length]
            logger.warning(f"Text truncated to {max_length} characters")
        
        return text
    
    async def close(self):
        """关闭TTS引擎"""
        self._initialized = False
        logger.debug(f"TTS engine {self.provider_name} closed")


class TTSRegistry:
    """
    TTS引擎注册表 - 单例模式
    """
    _instance: Optional['TTSRegistry'] = None
    _engines: Dict[str, type] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def register(self, provider: str, engine_class: type):
        """
        注册TTS引擎
        
        Args:
            provider: 提供商名称
            engine_class: 引擎类
        """
        if not issubclass(engine_class, BaseTTS):
            raise ValueError(f"Engine class must inherit from BaseTTS")
        self._engines[provider] = engine_class
        logger.debug(f"Registered TTS engine: {provider}")
    
    def get_engine(self, provider: str) -> Optional[type]:
        """
        获取TTS引擎类
        
        Args:
            provider: 提供商名称
            
        Returns:
            引擎类或None
        """
        return self._engines.get(provider)
    
    def create_engine(self, provider: str, config: Dict[str, Any]) -> BaseTTS:
        """
        创建TTS引擎实例
        
        Args:
            provider: 提供商名称
            config: 配置字典
            
        Returns:
            引擎实例
        """
        engine_class = self.get_engine(provider)
        if engine_class is None:
            raise ValueError(f"Unknown TTS provider: {provider}")
        return engine_class(config)
    
    def list_providers(self) -> list:
        """列出所有已注册的提供商"""
        return list(self._engines.keys())


# 全局注册表实例
tts_registry = TTSRegistry()


def register_tts(provider: str):
    """
    TTS引擎注册装饰器
    
    用法:
        @register_tts("cosyvoice")
        class CosyVoiceTTS(BaseTTS):
            ...
    """
    def decorator(cls: type):
        tts_registry.register(provider, cls)
        return cls
    return decorator
