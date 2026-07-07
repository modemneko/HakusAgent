"""
HakusAI 2.0 VAD (语音活动检测) 模块

支持的引擎：
- Silero: 轻量级高性能VAD
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

# 导入并注册所有VAD引擎
try:
    from .silero import SileroVAD, SileroVADIterator
except ImportError as e:
    import logging
    logging.getLogger(__name__).debug(f"Silero VAD not available: {e}")


__all__ = [
    "BaseVAD",
    "VADResult",
    "VADState",
    "VADConfig",
    "VADRegistry",
    "vad_registry",
    "register_vad",
    "SileroVAD",
    "SileroVADIterator",
]
