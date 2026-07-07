"""
HakusAI 2.0 语音Agent
整合语音管道和AI对话能力
"""

import asyncio
from typing import Optional, Dict, Any, Callable, AsyncIterator
from dataclasses import dataclass
import numpy as np
import logging

from .base_agent import BaseAgent, AgentContext, AgentResponse, AgentState
from ..voice.pipeline import VoicePipeline, VoicePipelineConfig, PipelineState
from ..memory.manager import MemoryManager, MemoryStorage
from ..utils.events import EventType, emit, on_event

logger = logging.getLogger(__name__)


@dataclass
class VoiceAgentConfig:
    """语音Agent配置"""
    # 语音管道配置
    voice_config: VoicePipelineConfig = None
    
    # 记忆配置
    memory_config: MemoryStorage = None
    
    # 行为配置
    enable_voice: bool = True
    enable_memory: bool = True
    auto_speak: bool = True  # 自动语音回复
    interrupt_enabled: bool = True  # 支持语音打断
    
    # 对话配置
    max_context_messages: int = 20


class VoiceAgent:
    """
    语音Agent
    
    整合能力：
    - AI对话 (BaseAgent)
    - 语音识别/合成 (VoicePipeline)
    - 记忆系统 (MemoryManager)
    - 虚拟形象控制
    """
    
    def __init__(
        self,
        agent: BaseAgent,
        config: Optional[VoiceAgentConfig] = None
    ):
        """
        初始化语音Agent
        
        Args:
            agent: 基础Agent实例
            config: 语音Agent配置
        """
        self.agent = agent
        self.config = config or VoiceAgentConfig()
        
        # 语音管道
        self.voice_pipeline: Optional[VoicePipeline] = None
        
        # 记忆系统
        self.memory: Optional[MemoryManager] = None
        
        # 状态
        self._initialized = False
        self._listening = False
        self._current_response_task: Optional[asyncio.Task] = None
        
        # 回调
        self._on_user_speech: Optional[Callable] = None
        self._on_agent_speech: Optional[Callable] = None
        self._on_avatar_expression: Optional[Callable] = None
        
    async def initialize(self):
        """初始化语音Agent"""
        logger.info("Initializing VoiceAgent...")
        
        # 初始化语音管道
        if self.config.enable_voice:
            self.voice_pipeline = VoicePipeline(self.config.voice_config)
            self.voice_pipeline.set_callbacks(
                on_text=self._on_asr_text,
                on_audio=self._on_tts_audio,
                on_state_change=self._on_voice_state_change
            )
            await self.voice_pipeline.initialize()
            logger.info("Voice pipeline initialized")
        
        # 初始化记忆系统
        if self.config.enable_memory:
            memory_config = self.config.memory_config or MemoryStorage()
            self.memory = MemoryManager(memory_config)
            await self.memory.initialize()
            logger.info("Memory system initialized")
        
        # 设置Agent记忆钩子
        if self.memory:
            self.agent.add_hook("before_chat", self._before_chat_hook)
            self.agent.add_hook("after_chat", self._after_chat_hook)
        
        self._initialized = True
        logger.info("VoiceAgent initialized successfully")
    
    def set_callbacks(
        self,
        on_user_speech: Optional[Callable] = None,
        on_agent_speech: Optional[Callable] = None,
        on_avatar_expression: Optional[Callable] = None
    ):
        """
        设置回调函数
        
        Args:
            on_user_speech: 用户语音输入回调
            on_agent_speech: Agent语音输出回调
            on_avatar_expression: 虚拟形象表情回调
        """
        self._on_user_speech = on_user_speech
        self._on_agent_speech = on_agent_speech
        self._on_avatar_expression = on_avatar_expression
    
    async def start_listening(self):
        """开始监听语音输入"""
        if not self._initialized:
            raise RuntimeError("VoiceAgent not initialized")
        
        if not self.voice_pipeline:
            logger.warning("Voice pipeline not enabled")
            return
        
        self._listening = True
        await self.voice_pipeline.start()
        logger.info("Started listening for voice input")
    
    async def stop_listening(self):
        """停止监听语音输入"""
        self._listening = False
        
        if self.voice_pipeline:
            await self.voice_pipeline.stop()
        
        logger.info("Stopped listening")
    
    async def feed_audio(self, audio_data: np.ndarray):
        """
        输入音频数据（用于外部音频源）
        
        Args:
            audio_data: 音频数据
        """
        if self.voice_pipeline and self._listening:
            await self.voice_pipeline.feed_audio(audio_data)
    
    async def chat(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
        stream: bool = True
    ) -> AsyncIterator[AgentResponse]:
        """
        文本对话
        
        Args:
            user_input: 用户输入
            context: 对话上下文
            stream: 是否流式输出
            
        Yields:
            Agent响应
        """
        # 保存用户输入到记忆
        if self.memory:
            await self.memory.add_message("user", user_input)
        
        # 调用Agent对话
        async for response in self.agent.chat(user_input, context, stream):
            yield response
        
        # 保存Agent回复到记忆
        if self.memory and not stream:
            await self.memory.add_message("assistant", response.content)
    
    async def chat_with_voice(
        self,
        user_input: str,
        context: Optional[AgentContext] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        语音对话（文本+语音输出）
        
        Args:
            user_input: 用户输入
            context: 对话上下文
            
        Yields:
            包含文本和/或音频的数据
        """
        if not self.voice_pipeline:
            logger.warning("Voice pipeline not available")
            async for response in self.chat(user_input, context, stream=True):
                yield {"type": "text", "content": response.content}
            return
        
        # 收集完整回复
        full_text = ""
        
        async for response in self.agent.chat(user_input, context, stream=True):
            full_text += response.content
            
            # 发送文本
            yield {
                "type": "text",
                "content": response.content,
                "emotion": response.emotion,
                "actions": response.actions
            }
            
            # 触发虚拟形象表情
            if self._on_avatar_expression and response.emotion:
                await self._trigger_avatar_expression(response.emotion)
        
        # 保存到记忆
        if self.memory:
            await self.memory.add_message("assistant", full_text)
        
        # 合成语音
        if self.config.auto_speak and full_text:
            yield {"type": "tts_start", "text": full_text}
            
            async for audio_chunk in self.voice_pipeline.speak(full_text):
                yield {"type": "audio", "data": audio_chunk}
            
            yield {"type": "tts_end"}
    
    async def speak(self, text: str) -> AsyncIterator[bytes]:
        """
        合成语音
        
        Args:
            text: 要合成的文本
            
        Yields:
            音频数据
        """
        if not self.voice_pipeline:
            logger.error("Voice pipeline not available")
            return
        
        async for chunk in self.voice_pipeline.speak(text):
            yield chunk
    
    async def interrupt(self):
        """打断当前语音输出"""
        if self._current_response_task and not self._current_response_task.done():
            self._current_response_task.cancel()
            try:
                await self._current_response_task
            except asyncio.CancelledError:
                pass
        
        if self.voice_pipeline:
            # 停止当前TTS
            pass  # TTS是流式的，自然结束
        
        logger.info("Speech interrupted")
        await emit(EventType.VOICE_INTERRUPTED)
    
    # ========== 回调处理 ==========
    
    async def _on_asr_text(self, text: str):
        """
        ASR识别到文本的回调
        
        Args:
            text: 识别的文本
        """
        logger.info(f"User said: {text}")
        
        # 触发事件
        await emit(EventType.VOICE_USER_SPEECH, {"text": text})
        
        # 调用用户回调
        if self._on_user_speech:
            if asyncio.iscoroutinefunction(self._on_user_speech):
                await self._on_user_speech(text)
            else:
                self._on_user_speech(text)
        
        # 如果启用了自动回复，开始对话
        if self.config.auto_speak:
            # 打断当前回复
            if self.config.interrupt_enabled:
                await self.interrupt()
            
            # 开始新的回复
            self._current_response_task = asyncio.create_task(
                self._handle_voice_response(text)
            )
    
    async def _handle_voice_response(self, user_text: str):
        """
        处理语音回复
        
        Args:
            user_text: 用户输入文本
        """
        try:
            async for chunk in self.chat_with_voice(user_text):
                if chunk["type"] == "text":
                    # 可以在这里发送到前端
                    pass
                elif chunk["type"] == "audio":
                    # 调用Agent语音回调
                    if self._on_agent_speech:
                        if asyncio.iscoroutinefunction(self._on_agent_speech):
                            await self._on_agent_speech(chunk["data"])
                        else:
                            self._on_agent_speech(chunk["data"])
        except asyncio.CancelledError:
            logger.debug("Voice response cancelled")
        except Exception as e:
            logger.error(f"Error in voice response: {e}")
    
    async def _on_tts_audio(self, audio_data: bytes):
        """
        TTS生成音频的回调
        
        Args:
            audio_data: 音频数据
        """
        # 可以在这里处理音频输出
        pass
    
    async def _on_voice_state_change(self, state: PipelineState):
        """
        语音状态变化的回调
        
        Args:
            state: 新的状态
        """
        logger.debug(f"Voice pipeline state: {state.name}")
        
        # 可以在这里更新UI状态
        await emit(EventType.VOICE_STATE_CHANGE, {"state": state.name})
    
    # ========== 记忆钩子 ==========
    
    async def _before_chat_hook(self, user_input: str, context: AgentContext):
        """对话前的钩子 - 加载记忆上下文"""
        if not self.memory:
            return
        
        # 获取相关记忆作为上下文
        memory_context = await self.memory.get_context_for_model(
            max_short_term=self.config.max_context_messages,
            max_long_term=3,
            query=user_input
        )
        
        # 将记忆添加到Agent的系统提示词中
        if memory_context:
            memory_text = "\n".join([
                f"{msg['role']}: {msg['content']}"
                for msg in memory_context
            ])
            
            # 更新系统提示词
            original_prompt = self.agent.system_prompt
            enhanced_prompt = f"""{original_prompt}

相关记忆：
{memory_text}
"""
            self.agent.system_prompt = enhanced_prompt
    
    async def _after_chat_hook(self, user_input: str, context: AgentContext):
        """对话后的钩子 - 恢复系统提示词"""
        # 恢复原始系统提示词（在before_chat中可能被修改）
        # 这里可以添加记忆更新逻辑
        pass
    
    # ========== 虚拟形象控制 ==========
    
    async def _trigger_avatar_expression(self, emotion: str):
        """
        触发虚拟形象表情
        
        Args:
            emotion: 表情名称
        """
        emotion_to_expression = {
            "joy": "happy",
            "sadness": "sad",
            "anger": "angry",
            "surprise": "surprised",
            "fear": "scared",
            "neutral": "normal",
        }
        
        expression = emotion_to_expression.get(emotion, "normal")
        
        await emit(EventType.AVATAR_EXPRESSION, {"expression": expression})
        
        if self._on_avatar_expression:
            if asyncio.iscoroutinefunction(self._on_avatar_expression):
                await self._on_avatar_expression(expression)
            else:
                self._on_avatar_expression(expression)
    
    async def set_avatar_expression(self, expression: str):
        """
        设置虚拟形象表情
        
        Args:
            expression: 表情名称
        """
        await self._trigger_avatar_expression(expression)
    
    async def set_avatar_motion(self, motion: str):
        """
        设置虚拟形象动作
        
        Args:
            motion: 动作名称
        """
        await emit(EventType.AVATAR_MOTION, {"motion": motion})
    
    # ========== 生命周期 ==========
    
    async def close(self):
        """关闭语音Agent"""
        logger.info("Closing VoiceAgent...")
        
        # 停止监听
        await self.stop_listening()
        
        # 关闭语音管道
        if self.voice_pipeline:
            await self.voice_pipeline.stop()
        
        # 关闭记忆系统
        if self.memory:
            await self.memory.close()
        
        self._initialized = False
        logger.info("VoiceAgent closed")
    
    @property
    def is_listening(self) -> bool:
        """是否正在监听"""
        return self._listening
    
    @property
    def is_speaking(self) -> bool:
        """是否正在说话"""
        return (
            self.voice_pipeline is not None and
            self.voice_pipeline.is_speaking
        )
    
    @property
    def state(self) -> AgentState:
        """Agent状态"""
        return self.agent.state
