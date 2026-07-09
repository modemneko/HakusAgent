"""
TTS 引擎基类
定义所有 TTS 后端的统一接口
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, AsyncIterator, List
from dataclasses import dataclass, field

__all__ = [
    "BaseTTSEngine",
    "TTSResult",
]


@dataclass
class TTSResult:
    """TTS 合成结果"""
    audio_data: bytes
    sample_rate: int = 22050
    format: str = "wav"  # wav, mp3, pcm
    cached: bool = False
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseTTSEngine(ABC):
    """TTS 引擎基类"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._initialized = False
        self._cache: Dict[str, TTSResult] = {}
        self._max_cache_size = 100
        
    @property
    @abstractmethod
    def engine_name(self) -> str:
        """引擎名称"""
        pass
    
    @abstractmethod
    async def initialize(self) -> bool:
        """初始化引擎"""
        pass
    
    @abstractmethod
    async def synthesize(self, text: str, **kwargs) -> Optional[TTSResult]:
        """合成语音"""
        pass
    
    async def synthesize_stream(self, text: str, **kwargs) -> AsyncIterator[bytes]:
        """流式合成语音（可选实现）"""
        raise NotImplementedError(f"{self.engine_name} does not support streaming")
    
    async def list_voices(self) -> List[Dict[str, str]]:
        """列出可用语音"""
        return []
    
    def _check_cache(self, text: str, **kwargs) -> Optional[TTSResult]:
        """检查缓存"""
        cache_key = f"{text}_{self.engine_name}_{hash(frozenset(kwargs.items()))}"
        return self._cache.get(cache_key)
    
    def _save_cache(self, text: str, result: TTSResult, **kwargs):
        """保存到缓存"""
        cache_key = f"{text}_{self.engine_name}_{hash(frozenset(kwargs.items()))}"
        if len(self._cache) >= self._max_cache_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        self._cache[cache_key] = result
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
    
    async def close(self):
        """关闭引擎"""
        self._initialized = False
