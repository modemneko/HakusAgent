"""
HakusAI 2.0 VAD (语音活动检测) 模块

支持的引擎：
- FunASR: 阿里达摩院 FSMN VAD 流式检测
"""

from .base import (
    BaseVAD,
    VADResult,
    VADState,
    VADConfig,
    VADRegistry,
    vad_registry,
    register_vad,
)

# 导入具体引擎（自动注册）
try:
    from .funasr_vad import FunASRVAD, FunASRVADIterator
except ImportError:
    pass

__all__ = [
    "BaseVAD",
    "VADResult",
    "VADState",
    "VADConfig",
    "VADRegistry",
    "vad_registry",
    "register_vad",
    "FunASRVAD",
    "FunASRVADIterator",
]
