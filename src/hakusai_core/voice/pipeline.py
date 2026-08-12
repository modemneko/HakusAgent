"""
HakusAI 2.0 语音管道整合模块
将ASR、VAD、TTS串联起来，实现完整的语音交互流程
"""

import asyncio
from typing import Optional, Dict, Any, Callable, AsyncIterator
from dataclasses import dataclass
from enum import Enum, auto
import numpy as np
import logging

from .asr.base import BaseASR, ASRResult, asr_registry
from .tts.base import BaseTTS, TTSResult, tts_registry
from .vad.base import BaseVAD, VADResult, vad_registry
from ..utils.events import EventType, emit
from ..config import config_manager

logger = logging.getLogger(__name__)


class PipelineState(Enum):
    """管道状态"""
    IDLE = auto()
    LISTENING = auto()
    RECOGNIZING = auto()
    THINKING = auto()
    SPEAKING = auto()


@dataclass
class VoicePipelineConfig:
    """语音管道配置"""
    # ASR配置
    asr_provider: str = "funasr"
    asr_config: Dict[str, Any] = None
    
    # TTS配置
    tts_provider: str = "cosyvoice"
    tts_config: Dict[str, Any] = None
    
    # VAD配置
    vad_provider: str = "funasr"
    vad_config: Dict[str, Any] = None
    
    # 行为配置
    auto_play: bool = True
    interrupt_enabled: bool = True


@dataclass
class PipelineResult:
    """管道处理结果"""
    text: str
    audio_data: Optional[bytes] = None
    is_final: bool = True


class VoicePipeline:
    """
    语音管道
    
    整合ASR、VAD、TTS，实现完整的语音交互流程：
    
    麦克风 → VAD → ASR → LLM → TTS → 播放器
    
    功能：
    - 实时语音监听和识别
    - 语音打断支持
    - 流式TTS播放
    - 事件驱动架构
    """
    
    def __init__(
        self,
        config: Optional[VoicePipelineConfig] = None,
        asr: Optional[BaseASR] = None,
        tts: Optional[BaseTTS] = None,
        vad: Optional[BaseVAD] = None
    ):
        """
        初始化语音管道
        
        Args:
            config: 管道配置
            asr: ASR引擎实例（可选）
            tts: TTS引擎实例（可选）
            vad: VAD引擎实例（可选）
        """
        self.config = config or VoicePipelineConfig()
        self.state = PipelineState.IDLE
        
        # 引擎实例
        self._asr = asr
        self._tts = tts
        self._vad = vad
        
        # 音频流
        self._audio_input_queue: asyncio.Queue = asyncio.Queue()
        self._audio_output_queue: asyncio.Queue = asyncio.Queue()
        
        # 任务
        self._tasks: list = []
        self._running = False
        
        # 回调
        self._on_text: Optional[Callable] = None
        self._on_audio: Optional[Callable] = None
        self._on_state_change: Optional[Callable] = None
        
    async def initialize(self):
        """初始化所有引擎"""
        # 初始化ASR
        if self._asr is None:
            asr_config = self.config.asr_config or config_manager.config.voice.asr.model_dump()
            self._asr = asr_registry.create_engine(
                self.config.asr_provider,
                asr_config
            )
        await self._asr.initialize()
        logger.info(f"ASR initialized: {self._asr.provider_name}")
        
        # 初始化TTS
        if self._tts is None:
            tts_config = self.config.tts_config or config_manager.config.voice.tts.model_dump()
            self._tts = tts_registry.create_engine(
                self.config.tts_provider,
                tts_config
            )
        await self._tts.initialize()
        logger.info(f"TTS initialized: {self._tts.provider_name}")
        
        # 初始化VAD
        if self._vad is None:
            vad_config = self.config.vad_config or config_manager.config.voice.vad.model_dump()
            self._vad = vad_registry.create_engine(
                self.config.vad_provider,
                vad_config
            )
            # 设置VAD回调
            self._vad.set_callbacks(
                on_speech_start=self._on_vad_speech_start,
                on_speech_end=self._on_vad_speech_end
            )
        await self._vad.initialize()
        logger.info(f"VAD initialized: {self._vad.provider_name}")
        
    def set_callbacks(
        self,
        on_text: Optional[Callable] = None,
        on_audio: Optional[Callable] = None,
        on_state_change: Optional[Callable] = None
    ):
        """
        设置回调函数
        
        Args:
            on_text: 文本识别回调
            on_audio: 音频输出回调
            on_state_change: 状态变化回调
        """
        self._on_text = on_text
        self._on_audio = on_audio
        self._on_state_change = on_state_change
        
    def _set_state(self, state: PipelineState):
        """设置状态并触发回调"""
        if self.state != state:
            old_state = self.state
            self.state = state
            logger.debug(f"Pipeline state: {old_state.name} -> {state.name}")
            
            if self._on_state_change:
                if asyncio.iscoroutinefunction(self._on_state_change):
                    asyncio.create_task(self._on_state_change(state))
                else:
                    self._on_state_change(state)
                    
            # 触发事件
            asyncio.create_task(emit(EventType.VOICE_SPEECH_START if state == PipelineState.LISTENING else EventType.VOICE_SPEECH_END))
    
    async def start(self):
        """启动语音管道"""
        if self._running:
            return
        
        self._running = True
        logger.info("Starting voice pipeline...")
        
        # 启动处理任务
        self._tasks = [
            asyncio.create_task(self._vad_loop()),
            asyncio.create_task(self._asr_loop()),
        ]
        
        self._set_state(PipelineState.IDLE)
        
    async def stop(self):
        """停止语音管道"""
        if not self._running:
            return
        
        self._running = False
        logger.info("Stopping voice pipeline...")
        
        # 取消所有任务
        for task in self._tasks:
            task.cancel()
        
        # 等待任务完成
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        
        # 关闭引擎
        if self._asr:
            await self._asr.close()
        if self._tts:
            await self._tts.close()
        if self._vad:
            await self._vad.close()
            
        self._set_state(PipelineState.IDLE)
        
    async def feed_audio(self, audio_data: np.ndarray):
        """
        输入音频数据
        
        Args:
            audio_data: 音频数据 (numpy数组)
        """
        await self._audio_input_queue.put(audio_data)
        
    async def speak(self, text: str) -> AsyncIterator[bytes]:
        """
        合成语音并播放
        
        Args:
            text: 要合成的文本
            
        Yields:
            音频数据块
        """
        if not self._tts:
            logger.error("TTS not initialized")
            return
        
        self._set_state(PipelineState.SPEAKING)
        
        try:
            # 触发TTS开始事件
            await emit(EventType.VOICE_TTS_START, {"text": text})
            
            # 流式合成
            async for chunk in self._tts.synthesize_stream(text):
                yield chunk
                
                # 调用音频回调
                if self._on_audio:
                    if asyncio.iscoroutinefunction(self._on_audio):
                        await self._on_audio(chunk)
                    else:
                        self._on_audio(chunk)
            
            # 触发TTS结束事件
            await emit(EventType.VOICE_TTS_END, {"text": text})
            
        except Exception as e:
            logger.error(f"Error in speak: {e}")
        finally:
            self._set_state(PipelineState.IDLE)
            
    async def speak_to_file(self, text: str, file_path: str) -> str:
        """
        合成语音并保存到文件
        
        Args:
            text: 要合成的文本
            file_path: 输出文件路径
            
        Returns:
            输出文件路径
        """
        if not self._tts:
            logger.error("TTS not initialized")
            return ""
        
        return await self._tts.synthesize_to_file(text, file_path)
        
    async def _vad_loop(self):
        """VAD处理循环"""
        logger.debug("VAD loop started")
        
        while self._running:
            try:
                # 获取音频数据
                audio_data = await asyncio.wait_for(
                    self._audio_input_queue.get(),
                    timeout=0.1
                )
                
                # 处理VAD
                if self._vad:
                    result = await self._vad.process(audio_data)
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in VAD loop: {e}")
                
        logger.debug("VAD loop stopped")
        
    async def _asr_loop(self):
        """ASR处理循环"""
        logger.debug("ASR loop started")
        
        speech_buffer: list = []
        is_recording = False
        
        while self._running:
            try:
                # 等待VAD检测到语音
                if self._vad and self._vad.is_speaking:
                    if not is_recording:
                        is_recording = True
                        speech_buffer.clear()
                        self._set_state(PipelineState.LISTENING)
                    
                    # 收集音频数据
                    try:
                        audio_data = await asyncio.wait_for(
                            self._audio_input_queue.get(),
                            timeout=0.05
                        )
                        speech_buffer.append(audio_data)
                    except asyncio.TimeoutError:
                        pass
                        
                else:
                    # 语音结束，进行识别
                    if is_recording and speech_buffer:
                        is_recording = False
                        self._set_state(PipelineState.RECOGNIZING)
                        
                        # 合并音频数据
                        full_audio = np.concatenate(speech_buffer)
                        speech_buffer.clear()
                        
                        # 识别
                        if self._asr:
                            result = await self._asr.transcribe(full_audio)
                            
                            if result.text.strip():
                                logger.info(f"ASR result: {result.text}")
                                
                                # 触发事件
                                await emit(EventType.VOICE_ASR_TEXT, {
                                    "text": result.text,
                                    "confidence": result.confidence
                                })
                                
                                # 调用文本回调
                                if self._on_text:
                                    if asyncio.iscoroutinefunction(self._on_text):
                                        await self._on_text(result.text)
                                    else:
                                        self._on_text(result.text)
                        
                        self._set_state(PipelineState.IDLE)
                        
                await asyncio.sleep(0.01)
                
            except Exception as e:
                logger.error(f"Error in ASR loop: {e}")
                is_recording = False
                speech_buffer.clear()
                
        logger.debug("ASR loop stopped")
        
    async def _on_vad_speech_start(self, audio_data: np.ndarray):
        """VAD语音开始回调"""
        logger.debug("VAD: Speech started")
        self._set_state(PipelineState.LISTENING)
        
    async def _on_vad_speech_end(self):
        """VAD语音结束回调"""
        logger.debug("VAD: Speech ended")
        
    @property
    def is_listening(self) -> bool:
        """是否正在监听"""
        return self.state in [PipelineState.LISTENING, PipelineState.RECOGNIZING]
        
    @property
    def is_speaking(self) -> bool:
        """是否正在播放语音"""
        return self.state == PipelineState.SPEAKING


class VoicePipelineManager:
    """
    语音管道管理器 - 单例模式
    """
    _instance: Optional['VoicePipelineManager'] = None
    _pipeline: Optional[VoicePipeline] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def create_pipeline(
        self,
        config: Optional[VoicePipelineConfig] = None
    ) -> VoicePipeline:
        """
        创建语音管道
        
        Args:
            config: 管道配置
            
        Returns:
            语音管道实例
        """
        if self._pipeline is None:
            self._pipeline = VoicePipeline(config)
            await self._pipeline.initialize()
        return self._pipeline
    
    def get_pipeline(self) -> Optional[VoicePipeline]:
        """获取当前管道实例"""
        return self._pipeline
    
    async def close(self):
        """关闭管道"""
        if self._pipeline:
            await self._pipeline.stop()
            self._pipeline = None


# 全局管理器实例
pipeline_manager = VoicePipelineManager()
