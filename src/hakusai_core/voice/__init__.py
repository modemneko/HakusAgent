"""
HakusAI 2.0 语音系统模块
整合ASR、TTS、VAD三大组件
"""

# ASR
from .asr.base import (
    BaseASR,
    ASRResult,
    ASRProvider,
    asr_registry,
    register_asr,
)

# TTS
from .tts.base import (
    BaseTTS,
    TTSResult,
    TTSProvider,
    tts_registry,
    register_tts,
)

# VAD
from .vad.base import (
    BaseVAD,
    VADResult,
    VADState,
    VADConfig,
    vad_registry,
    register_vad,
)

# Pipeline
from .pipeline import (
    VoicePipeline,
    VoicePipelineConfig,
    VoicePipelineManager,
    PipelineState,
    PipelineResult,
    pipeline_manager,
)

__all__ = [
    # ASR
    "BaseASR",
    "ASRResult",
    "ASRProvider",
    "asr_registry",
    "register_asr",
    # TTS
    "BaseTTS",
    "TTSResult",
    "TTSProvider",
    "tts_registry",
    "register_tts",
    # VAD
    "BaseVAD",
    "VADResult",
    "VADState",
    "VADConfig",
    "vad_registry",
    "register_vad",
    # Pipeline
    "VoicePipeline",
    "VoicePipelineConfig",
    "VoicePipelineManager",
    "PipelineState",
    "PipelineResult",
    "pipeline_manager",
]
