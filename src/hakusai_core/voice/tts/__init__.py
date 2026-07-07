"""
HakusAI 2.0 TTS模块
"""

from .base import (
    BaseTTS,
    TTSResult,
    TTSProvider,
    tts_registry,
    register_tts,
)

# 导入具体引擎（自动注册）
try:
    from .edge import EdgeTTS
except ImportError:
    pass

__all__ = [
    "BaseTTS",
    "TTSResult",
    "TTSProvider",
    "tts_registry",
    "register_tts",
    # 引擎
    "EdgeTTS",
]
