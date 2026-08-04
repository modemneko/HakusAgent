"""
HakusAI 2.0 ASR (自动语音识别) 模块

支持的引擎：
- FunASR: 阿里巴巴SenseVoice
- Whisper: OpenAI Whisper (API/本地)
"""

from .base import (
    BaseASR,
    ASRResult,
    ASRProvider,
    ASRRegistry,
    asr_registry,
    register_asr,
)

# 导入具体引擎（自动注册）
try:
    from .funasr import FunASR
except ImportError:
    pass

try:
    from .whisper import WhisperASR
except ImportError:
    pass

__all__ = [
    "BaseASR",
    "ASRResult",
    "ASRProvider",
    "ASRRegistry",
    "asr_registry",
    "register_asr",
    "FunASR",
    "WhisperASR",
]
