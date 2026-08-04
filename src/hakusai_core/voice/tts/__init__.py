"""
HakusAI 2.0 TTS模块

支持的引擎：
- CosyVoice: 阿里云DashScope语音合成/语音复刻
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
    from .cosyvoice import CosyVoiceTTS
except ImportError:
    pass

__all__ = [
    "BaseTTS",
    "TTSResult",
    "TTSProvider",
    "tts_registry",
    "register_tts",
    "CosyVoiceTTS",
]
