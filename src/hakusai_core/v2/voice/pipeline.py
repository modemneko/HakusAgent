"""
语音管线 - 统一语音处理流程
"""

from typing import Optional, Dict, Any, AsyncIterator
from dataclasses import dataclass
from enum import Enum
import numpy as np
import asyncio
import logging

from .base import (
    BaseASR,
    BaseTTS,
    BaseVAD,
    ASRResult,
    TTSResult,
    VADResult,
    VADState,
    asr_registry,
    tts_registry,
    vad_registry,
)
from ..schema.models import AudioData, Text
from ..schema.errors import HakusAIError

logger = logging.getLogger(__name__)


class PipelineState(str, Enum):
    """管线状态"""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


@dataclass
class VoicePipelineConfig:
    """语音管线配置"""
    # ASR 配置
    asr_provider: str = "funasr"
    asr_config: Dict[str, Any] = None
    
    # TTS 配置
    tts_provider: str = "edge_tts"
    tts_config: Dict[str, Any] = None
    
    # VAD 配置
    vad_provider: str = "silero"
    vad_config: Dict[str, Any] = None
    
    # 管线配置
    auto_vad: bool = True
    sample_rate: int = 16000
    
    def __post_init__(self):
        if self.asr_config is None:
            self.asr_config = {"provider": self.asr_provider}
        if self.tts_config is None:
            self.tts_config = {"provider": self.tts_provider}
        if self.vad_config is None:
            self.vad_config = {"provider": self.vad_provider}


@dataclass
class PipelineResult:
    """管线处理结果"""
    success: bool
    text: Optional[str] = None
    audio: Optional[AudioData] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class VoicePipeline:
    """语音管线"""
    
    def __init__(self, config: VoicePipelineConfig):
        self.config = config
        self.state = PipelineState.IDLE
        
        # 引擎实例
        self.asr: Optional[BaseASR] = None
        self.tts: Optional[BaseTTS] = None
        self.vad: Optional[BaseVAD] = None
        
        self._initialized = False
    
    async def initialize(self):
        """初始化语音管线"""
        if self._initialized:
            return
        
        try:
            # 创建 ASR 引擎
            self.asr = asr_registry.create_engine(
                self.config.asr_provider,
                self.config.asr_config
            )
            await self.asr.initialize()
            
            # 创建 TTS 引擎
            self.tts = tts_registry.create_engine(
                self.config.tts_provider,
                self.config.tts_config
            )
            await self.tts.initialize()
            
            # 创建 VAD 引擎
            if self.config.auto_vad:
                self.vad = vad_registry.create_engine(
                    self.config.vad_provider,
                    self.config.vad_config
                )
                await self.vad.initialize()
            
            self._initialized = True
            logger.info("Voice pipeline initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize voice pipeline: {e}")
            raise HakusAIError(f"Voice pipeline initialization failed: {e}")
    
    async def process_audio(self, audio: AudioData) -> PipelineResult:
        """处理音频输入"""
        if not self._initialized:
            await self.initialize()
        
        self.state = PipelineState.PROCESSING
        
        try:
            # VAD 检测
            if self.vad:
                vad_result = await self.vad.detect(
                    np.frombuffer(audio.data, dtype=np.int16),
                    audio.sample_rate
                )
                if vad_result.state == VADState.SILENCE:
                    return PipelineResult(
                        success=True,
                        text="",
                        metadata={"vad": "silence"}
                    )
            
            # ASR 识别
            audio_array = np.frombuffer(audio.data, dtype=np.int16)
            asr_result = await self.asr.transcribe(audio_array, audio.sample_rate)
            
            self.state = PipelineState.IDLE
            
            return PipelineResult(
                success=True,
                text=asr_result.text,
                metadata={
                    "confidence": asr_result.confidence,
                    "language": asr_result.language,
                }
            )
            
        except Exception as e:
            self.state = PipelineState.IDLE
            logger.error(f"Audio processing failed: {e}")
            return PipelineResult(
                success=False,
                error=str(e)
            )
    
    async def synthesize_speech(self, text: str) -> PipelineResult:
        """合成语音"""
        if not self._initialized:
            await self.initialize()
        
        self.state = PipelineState.SPEAKING
        
        try:
            # TTS 合成
            tts_result = await self.tts.synthesize(text)

            if tts_result is None:
                raise RuntimeError("TTS synthesize returned None")

            self.state = PipelineState.IDLE

            # 转换为 AudioData
            audio_bytes = tts_result.audio_data.tobytes()
            audio = AudioData(
                data=audio_bytes,
                sample_rate=tts_result.sample_rate,
            )
            
            return PipelineResult(
                success=True,
                text=text,
                audio=audio,
                metadata={
                    "duration": tts_result.duration,
                }
            )
            
        except Exception as e:
            self.state = PipelineState.IDLE
            logger.error(f"Speech synthesis failed: {e}")
            return PipelineResult(
                success=False,
                error=str(e)
            )
    
    async def voice_to_voice(self, audio: AudioData) -> PipelineResult:
        """语音到语音处理"""
        # 1. 识别语音
        asr_result = await self.process_audio(audio)
        if not asr_result.success or not asr_result.text:
            return asr_result
        
        # 2. 生成回复（需要外部 LLM）
        # 这里只是示例，实际应该调用 LLM
        response_text = f"你说的是：{asr_result.text}"
        
        # 3. 合成语音
        tts_result = await self.synthesize_speech(response_text)
        
        return PipelineResult(
            success=True,
            text=response_text,
            audio=tts_result.audio,
            metadata={
                "input_text": asr_result.text,
                "output_text": response_text,
            }
        )
    
    async def close(self):
        """关闭语音管线"""
        if self.asr:
            await self.asr.close()
        if self.tts:
            await self.tts.close()
        if self.vad:
            await self.vad.close()
        
        self._initialized = False
        self.state = PipelineState.IDLE
        logger.info("Voice pipeline closed")


class VoicePipelineManager:
    """语音管线管理器"""
    
    _instance: Optional['VoicePipelineManager'] = None
    _pipelines: Dict[str, VoicePipeline] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_pipeline(
        self,
        name: str = "default",
        config: Optional[VoicePipelineConfig] = None
    ) -> VoicePipeline:
        """获取或创建语音管线"""
        if name not in self._pipelines:
            if config is None:
                config = VoicePipelineConfig()
            self._pipelines[name] = VoicePipeline(config)
        return self._pipelines[name]
    
    async def close_all(self):
        """关闭所有管线"""
        for pipeline in self._pipelines.values():
            await pipeline.close()
        self._pipelines.clear()


# 全局管线管理器实例
pipeline_manager = VoicePipelineManager()