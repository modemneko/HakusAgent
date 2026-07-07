"""
语音系统 - 整合 ASR、TTS、VAD 三大组件
迁移自现有实现，适配 v2 架构
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, BinaryIO, AsyncIterator
from dataclasses import dataclass
from enum import Enum
import numpy as np
import logging

from ..schema.models import AudioData, Text
from ..schema.errors import HakusAIError

logger = logging.getLogger(__name__)


class VoiceError(HakusAIError):
    """语音系统错误"""
    pass


# ============ ASR (自动语音识别) ============

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
    duration: Optional[float] = None


class BaseASR(ABC):
    """ASR基类"""
    
    def __init__(self, config: Dict[str, Any]):
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
        """识别音频"""
        pass
    
    @abstractmethod
    async def transcribe_file(self, file_path: str) -> ASRResult:
        """识别音频文件"""
        pass
    
    async def transcribe_stream(
        self,
        audio_stream: BinaryIO,
        sample_rate: Optional[int] = None
    ) -> ASRResult:
        """识别音频流"""
        audio_bytes = audio_stream.read()
        audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
        return await self.transcribe(audio_data, sample_rate)
    
    async def close(self):
        """关闭ASR引擎"""
        self._initialized = False


class ASRRegistry:
    """ASR引擎注册表"""
    
    def __init__(self):
        self._engines: Dict[str, type] = {}
    
    def register(self, provider: str, engine_class: type):
        """注册ASR引擎"""
        if not issubclass(engine_class, BaseASR):
            raise ValueError("Engine class must inherit from BaseASR")
        self._engines[provider] = engine_class
    
    def get_engine(self, provider: str) -> Optional[type]:
        """获取ASR引擎类"""
        return self._engines.get(provider)
    
    def create_engine(self, provider: str, config: Dict[str, Any]) -> BaseASR:
        """创建ASR引擎实例"""
        engine_class = self.get_engine(provider)
        if engine_class is None:
            raise ValueError(f"Unknown ASR provider: {provider}")
        return engine_class(config)
    
    def list_providers(self) -> list:
        """列出所有已注册的提供商"""
        return list(self._engines.keys())


# ============ TTS (语音合成) ============

class TTSProvider(str, Enum):
    """TTS提供商"""
    COSYVOICE = "cosyvoice"
    GPT_SOVITS = "gpt_sovits"
    SHERPA_ONNX = "sherpa_onnx"
    EDGE_TTS = "edge_tts"
    BERT_VITS2 = "bert_vits2"


@dataclass
class TTSResult:
    """TTS合成结果"""
    audio_data: np.ndarray
    sample_rate: int
    duration: Optional[float] = None


class BaseTTS(ABC):
    """TTS基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider = config.get("provider", "edge_tts")
        self.voice = config.get("voice", "zh-CN-XiaoxiaoNeural")
        self.sample_rate = config.get("sample_rate", 24000)
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
        voice: Optional[str] = None
    ) -> TTSResult:
        """合成语音"""
        pass
    
    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None
    ) -> AsyncIterator[bytes]:
        """流式合成语音"""
        pass
    
    async def close(self):
        """关闭TTS引擎"""
        self._initialized = False


class TTSRegistry:
    """TTS引擎注册表"""
    
    def __init__(self):
        self._engines: Dict[str, type] = {}
    
    def register(self, provider: str, engine_class: type):
        """注册TTS引擎"""
        if not issubclass(engine_class, BaseTTS):
            raise ValueError("Engine class must inherit from BaseTTS")
        self._engines[provider] = engine_class
    
    def get_engine(self, provider: str) -> Optional[type]:
        """获取TTS引擎类"""
        return self._engines.get(provider)
    
    def create_engine(self, provider: str, config: Dict[str, Any]) -> BaseTTS:
        """创建TTS引擎实例"""
        engine_class = self.get_engine(provider)
        if engine_class is None:
            raise ValueError(f"Unknown TTS provider: {provider}")
        return engine_class(config)
    
    def list_providers(self) -> list:
        """列出所有已注册的提供商"""
        return list(self._engines.keys())


# ============ VAD (语音活动检测) ============

class VADState(str, Enum):
    """VAD状态"""
    IDLE = "idle"
    SPEECH = "speech"
    SILENCE = "silence"


@dataclass
class VADConfig:
    """VAD配置"""
    threshold: float = 0.5
    min_speech_duration: float = 0.1
    min_silence_duration: float = 0.3
    sample_rate: int = 16000


@dataclass
class VADResult:
    """VAD检测结果"""
    state: VADState
    confidence: float
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class BaseVAD(ABC):
    """VAD基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider = config.get("provider", "silero")
        self.vad_config = VADConfig(
            threshold=config.get("threshold", 0.5),
            min_speech_duration=config.get("min_speech_duration", 0.1),
            min_silence_duration=config.get("min_silence_duration", 0.3),
            sample_rate=config.get("sample_rate", 16000),
        )
        self._initialized = False
    
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
    async def detect(
        self,
        audio_data: np.ndarray,
        sample_rate: Optional[int] = None
    ) -> VADResult:
        """检测语音活动"""
        pass
    
    async def close(self):
        """关闭VAD引擎"""
        self._initialized = False


class VADRegistry:
    """VAD引擎注册表"""
    
    def __init__(self):
        self._engines: Dict[str, type] = {}
    
    def register(self, provider: str, engine_class: type):
        """注册VAD引擎"""
        if not issubclass(engine_class, BaseVAD):
            raise ValueError("Engine class must inherit from BaseVAD")
        self._engines[provider] = engine_class
    
    def get_engine(self, provider: str) -> Optional[type]:
        """获取VAD引擎类"""
        return self._engines.get(provider)
    
    def create_engine(self, provider: str, config: Dict[str, Any]) -> BaseVAD:
        """创建VAD引擎实例"""
        engine_class = self.get_engine(provider)
        if engine_class is None:
            raise ValueError(f"Unknown VAD provider: {provider}")
        return engine_class(config)
    
    def list_providers(self) -> list:
        """列出所有已注册的提供商"""
        return list(self._engines.keys())


# ============ 全局注册表实例 ============

asr_registry = ASRRegistry()
tts_registry = TTSRegistry()
vad_registry = VADRegistry()


def register_asr(provider: str):
    """ASR引擎注册装饰器"""
    def decorator(cls: type):
        asr_registry.register(provider, cls)
        return cls
    return decorator


def register_tts(provider: str):
    """TTS引擎注册装饰器"""
    def decorator(cls: type):
        tts_registry.register(provider, cls)
        return cls
    return decorator


def register_vad(provider: str):
    """VAD引擎注册装饰器"""
    def decorator(cls: type):
        vad_registry.register(provider, cls)
        return cls
    return decorator