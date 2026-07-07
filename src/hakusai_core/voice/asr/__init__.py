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

# 导入并注册所有ASR引擎
# 这些导入会自动注册引擎到注册表

try:
    from .sherpa_onnx import SherpaONNXASR
except ImportError as e:
    import logging
    logging.getLogger(__name__).debug(f"Sherpa-ONNX ASR not available: {e}")

try:
    from .whisper import WhisperASR
except ImportError as e:
    import logging
    logging.getLogger(__name__).debug(f"Whisper ASR not available: {e}")

try:
    from .funasr import FunASR
except ImportError as e:
    import logging
    logging.getLogger(__name__).debug(f"FunASR not available: {e}")


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
