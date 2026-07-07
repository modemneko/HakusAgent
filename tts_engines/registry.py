"""
TTS 引擎注册表
"""

from typing import Dict, Type
from .base import BaseTTSEngine

_tts_registry: Dict[str, Type[BaseTTSEngine]] = {}


def register_tts(name: str):
    """注册 TTS 引擎"""
    def decorator(cls: Type[BaseTTSEngine]) -> Type[BaseTTSEngine]:
        _tts_registry[name] = cls
        return cls
    return decorator


class TTSRegistry:
    """TTS 注册表管理器"""
    
    def __init__(self):
        self._registry = _tts_registry
    
    def register(self, name: str, engine_class: Type[BaseTTSEngine]):
        """注册引擎类"""
        self._registry[name] = engine_class
    
    def create_engine(self, name: str, config: dict = None) -> BaseTTSEngine:
        """创建引擎实例"""
        if name not in self._registry:
            raise ValueError(f"Unknown TTS engine: {name}. Available: {list(self._registry.keys())}")
        return self._registry[name](config=config)
    
    def list_engines(self) -> list:
        """列出已注册的引擎"""
        return list(self._registry.keys())
    
    def has_engine(self, name: str) -> bool:
        """检查引擎是否已注册"""
        return name in self._registry


tts_registry = TTSRegistry()
