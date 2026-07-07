"""
语音系统 - 整合 ASR、TTS、VAD 三大组件
"""

from .base import (
    BaseASR,
    ASRResult,
    ASRProvider,
    ASRRegistry,
    asr_registry,
    register_asr,
    
    BaseTTS,
    TTSResult,
    TTSProvider,
    TTSRegistry,
    tts_registry,
    register_tts,
    
    BaseVAD,
    VADResult,
    VADState,
    VADConfig,
    VADRegistry,
    vad_registry,
    register_vad,
    
    VoiceError,
)

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
    "ASRRegistry",
    "asr_registry",
    "register_asr",
    
    # TTS
    "BaseTTS",
    "TTSResult",
    "TTSProvider",
    "TTSRegistry",
    "tts_registry",
    "register_tts",
    
    # VAD
    "BaseVAD",
    "VADResult",
    "VADState",
    "VADConfig",
    "VADRegistry",
    "vad_registry",
    "register_vad",
    
    # Pipeline
    "VoicePipeline",
    "VoicePipelineConfig",
    "VoicePipelineManager",
    "PipelineState",
    "PipelineResult",
    "pipeline_manager",
    
    # Errors
    "VoiceError",
]