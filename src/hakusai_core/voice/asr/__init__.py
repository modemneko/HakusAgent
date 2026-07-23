"""
HakusAI 2.0 ASR (自动语音识别) 模块

支持的引擎：
- Sherpa-ONNX: 本地高性能识别
- Whisper: OpenAI Whisper (API/本地)
- FunASR: 阿里巴巴SenseVoice
"""

from .base import (
    BaseASR,
    ASRResult,
    ASRProvider,
    ASRRegistry,
    asr_registry,
    register_asr,
)




__all__ = [
    "BaseASR",
    "ASRResult",
    "ASRProvider",
    "ASRRegistry",
    "asr_registry",
    "register_asr",
    "SherpaONNXASR",
    "WhisperASR",
    "FunASR",
]
