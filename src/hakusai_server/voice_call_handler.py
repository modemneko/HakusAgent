"""
全双工语音通话 WebSocket 处理器
复用 vtuber_websocket.py 的架构，简化为语音通话场景

架构:
- 前端通过 WebSocket 持续发送 PCM 音频帧
- 后端 FunASR VAD 检测语音端点
- 语音结束后 ASR 识别
- 识别结果送 VoiceAgent（LLM 流式）
- LLM 流式输出 -> SentenceSplitter 按标点切分 -> 逐句 TTS -> 逐句音频推送
- 打断机制: VAD 检测到新语音开始时，取消当前 LLM+TTS 任务
"""

import asyncio
import json
import base64
import logging
import time
import re
import numpy as np
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# ========== 常量 ==========

_WS_RECEIVE_TIMEOUT = 300.0        # WebSocket 接收超时（秒）
_WS_TTS_WORKER_TIMEOUT = 60.0     # TTS 工作协程等待超时（秒）
_WS_TTS_TASK_SHUTDOWN_TIMEOUT = 30.0  # TTS 任务关闭等待超时（秒）
_VAD_CHUNK_SIZE = 512             # Silero VAD 每次处理的采样点数（16kHz 下 32ms）
_VAD_SILENCE_DURATION_MS = 600    # 语音结束后静音判定时长（毫秒）
_VAD_SPEECH_PAD_MS = 100          # 语音前后填充时长（毫秒）


# ========== 通话状态枚举 ==========

class CallState(Enum):
    """通话状态"""
    LISTENING = "listening"    # 监听中，等待用户语音
    THINKING = "thinking"     # 用户说完，ASR/LLM 处理中
    SPEAKING = "speaking"     # AI 正在回复语音


# ========== 配置 ==========

@dataclass
class VoiceCallConfig:
    """语音通话配置"""
    asr_provider: str = "funasr"
    asr_language: str = "zh"
    tts_provider: str = "cosyvoice"
    tts_voice: str = ""
    tts_model: str = "cosyvoice-v3-flash"
    vad_threshold: float = 0.5
    sample_rate: int = 16000
    dashscope_api_key: str = ""
    voice_mode: str = "balanced"           # 语音场景模式: companion/assistant/balanced
    enable_filler: bool = True             # 是否启用填充语
    enable_compressed_reasoning: bool = True  # 是否启用压缩推理
    filler_phrases: list = field(default_factory=lambda: ["让我想想…", "嗯…", "好的，我看看…"])
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model_name: str = "deepseek-chat"
    enable_context_asr: bool = True
    enable_coding_delegation: bool = True
    enable_progress_report: bool = True
    enable_emotion_aware: bool = True


# ========== 会话数据 ==========

@dataclass
class VoiceCallSession:
    """语音通话会话数据"""
    session_id: str
    user_id: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    state: CallState = CallState.LISTENING
    current_task: Optional[asyncio.Task] = None
    # 语音收集相关
    speech_buffer: List[np.ndarray] = field(default_factory=list)
    is_collecting_speech: bool = False
    silence_sample_count: int = 0
    # 空闲状态下的长停顿检测
    idle_silence_sample_count: int = 0
    silence_prompt_sent: bool = False
    # 当前回复文本
    current_text: str = ""
    filler_audio_cache: dict = field(default_factory=dict)


# ========== 标点切分器 ==========

class SentenceSplitter:
    """标点符号切分器 - 流式文本按句切分（复用自 vtuber_websocket.py）"""

    SENTENCE_ENDINGS = re.compile(r'[。！？!?\n]')
    CLAUSE_ENDINGS = re.compile(r'[，,；;：:、]')

    def __init__(self, min_length: int = 2, max_length: int = 80):
        self.buffer = ""
        self.min_length = min_length
        self.max_length = max_length

    def feed(self, text: str) -> List[str]:
        if not text:
            return []

        self.buffer += text
        sentences = []

        while self.buffer:
            sent_end = self.SENTENCE_ENDINGS.search(self.buffer)
            clause_end = self.CLAUSE_ENDINGS.search(self.buffer)

            cut_pos = None
            if sent_end:
                cut_pos = sent_end.end()
            elif len(self.buffer) >= self.max_length and clause_end:
                cut_pos = clause_end.end()

            if cut_pos is not None and cut_pos >= self.min_length:
                sentence = self.buffer[:cut_pos].strip()
                if sentence:
                    sentences.append(sentence)
                self.buffer = self.buffer[cut_pos:]
            elif len(self.buffer) >= self.max_length:
                sentence = self.buffer.strip()
                if sentence:
                    sentences.append(sentence)
                self.buffer = ""
            else:
                break

        return sentences

    def flush(self) -> Optional[str]:
        if self.buffer.strip():
            result = self.buffer.strip()
            self.buffer = ""
            return result
        return None

    def reset(self):
        self.buffer = ""


# ========== 语音通话处理器 ==========

class VoiceCallHandler:
    """
    全双工语音通话 WebSocket 处理器

    流程:
    1. 前端持续发送 PCM 音频帧
    2. Silero VAD 检测语音端点（开始/结束）
    3. 语音段结束后 ASR 识别
    4. 识别文本送入 VoiceAgent（LLM 流式推理）
    5. LLM 流式输出 -> SentenceSplitter 切句 -> 逐句 TTS -> 音频推送
    6. 打断: VAD 检测到新语音 或 收到 interrupt 消息 -> 取消当前任务
    """

    def __init__(self, config: Optional[VoiceCallConfig] = None, agent_bridge: Any = None):
        """
        初始化语音通话处理器

        Args:
            config: 语音通话配置
            agent_bridge: AgentBridge 实例，用于创建 VoiceAgent 的 LLM 会话
        """
        self.config = config or VoiceCallConfig()
        self.agent_bridge = agent_bridge

        # 会话表
        self.sessions: Dict[str, VoiceCallSession] = {}

        # 打断事件
        self._interrupt_events: Dict[str, asyncio.Event] = {}

        # 语音引擎（延迟初始化）
        self._vad = None           # Silero VAD 引擎
        self._asr = None           # ASR 引擎
        self._tts = None           # TTS 引擎
        self._tts_provider: str = ""  # 实际使用的 TTS provider

        # VoiceAgent 实例
        self._voice_agent = None

        self._initialized = False

    # ========== 引擎初始化 ==========

    async def initialize(self):
        """初始化所有语音引擎"""
        logger.info("VoiceCallHandler: 开始初始化语音引擎...")

        # 1. 初始化 VAD (Silero)
        await self._init_vad()

        # 2. 初始化 ASR
        await self._init_asr()

        # 3. 初始化 TTS
        await self._init_tts()

        # 4. 初始化 VoiceAgent
        await self._init_voice_agent()

        self._initialized = True
        logger.info(
            f"VoiceCallHandler: 初始化完成 "
            f"(VAD={'✓' if self._vad else '✗'}, "
            f"ASR={'✓' if self._asr else '✗'}, "
            f"TTS={self._tts_provider or '✗'}, "
            f"Agent={'✓' if self._voice_agent else '✗'})"
        )

    async def _init_vad(self):
        """初始化 FunASR VAD 引擎"""
        try:
            from hakusai_core.voice.vad import vad_registry
            self._vad = vad_registry.create_engine("funasr", {
                "threshold": self.config.vad_threshold,
                "sample_rate": self.config.sample_rate,
            })
            await self._vad.initialize()
            logger.info("VoiceCallHandler: FunASR VAD 初始化成功")
        except Exception as e:
            logger.error(f"VoiceCallHandler: FunASR VAD 初始化失败: {e}")
            self._vad = None

    async def _init_asr(self):
        """初始化 ASR 引擎，失败时尝试其他可用引擎"""
        from hakusai_core.voice.asr import asr_registry
        providers_to_try = [self.config.asr_provider]
        # 添加所有其他可用引擎作为 fallback
        for p in asr_registry.list_providers():
            if p not in providers_to_try:
                providers_to_try.append(p)

        for provider in providers_to_try:
            try:
                self._asr = asr_registry.create_engine(provider, {
                    "provider": provider,
                    "language": self.config.asr_language,
                    "sample_rate": self.config.sample_rate,
                })
                await self._asr.initialize()
                self._asr_provider = provider
                logger.info(f"VoiceCallHandler: ASR ({provider}) 初始化成功")
                return
            except Exception as e:
                logger.warning(f"VoiceCallHandler: ASR ({provider}) 初始化失败: {e}")
                continue

        logger.error("VoiceCallHandler: 所有 ASR 引擎初始化失败")
        self._asr = None

    async def _init_tts(self):
        """初始化 TTS 引擎，使用 CosyVoice"""
        try:
            from hakusai_core.voice.tts import tts_registry
            tts_config = {
                "provider": self.config.tts_provider,
                "voice": self.config.tts_voice,
                "model": self.config.tts_model,
            }
            # 前端设置的 API Key 优先
            if self.config.dashscope_api_key:
                tts_config["api_key"] = self.config.dashscope_api_key
            self._tts = tts_registry.create_engine(self.config.tts_provider, tts_config)
            await self._tts.initialize()
            self._tts_provider = self.config.tts_provider
            logger.info(f"VoiceCallHandler: TTS ({self.config.tts_provider}) 初始化成功")
        except Exception as e:
            logger.error(f"VoiceCallHandler: TTS ({self.config.tts_provider}) 初始化失败: {e}")
            self._tts = None

    async def _init_voice_agent(self):
        """初始化 VoiceAgent（独立 LLM 调用，不依赖 agent_bridge）"""
        try:
            from hakusai_core.agent.voice_agent import VoiceAgent
            if self.config.llm_api_key:
                self._voice_agent = VoiceAgent(
                    api_key=self.config.llm_api_key,
                    base_url=self.config.llm_base_url,
                    model_name=self.config.llm_model_name or "deepseek-chat",
                )
                if self.agent_bridge:
                    self._voice_agent.set_agent_bridge(self.agent_bridge)
                logger.info(f"VoiceCallHandler: VoiceAgent 初始化成功 (model={self.config.llm_model_name})")
            else:
                logger.warning("VoiceCallHandler: llm_api_key 未设置，VoiceAgent 不可用")
                self._voice_agent = None
        except Exception as e:
            logger.error(f"VoiceCallHandler: VoiceAgent 初始化失败: {e}")
            self._voice_agent = None

    # ========== 填充语预缓存 ==========

    async def _precache_fillers(self, session: VoiceCallSession):
        """预生成填充语音频并缓存为 base64 PCM"""
        if not self._tts or not self.config.enable_filler:
            return

        import base64
        for phrase in self.config.filler_phrases:
            try:
                result = await self._tts.synthesize(phrase)
                if result and result.audio_data:
                    audio_b64 = base64.b64encode(result.audio_data).decode('utf-8')
                    session.filler_audio_cache[phrase] = {
                        "data": audio_b64,
                        "format": getattr(result, "format", "pcm"),
                        "sample_rate": getattr(result, "sample_rate", 22050),
                    }
                    logger.info(f"填充语预缓存成功: {phrase}")
            except Exception as e:
                logger.warning(f"填充语预缓存失败 '{phrase}': {e}")

    def _get_random_filler(self, session: VoiceCallSession) -> Optional[dict]:
        """从缓存中随机获取一个填充语音频"""
        import random
        if not session.filler_audio_cache:
            return None
        phrase = random.choice(list(session.filler_audio_cache.keys()))
        return session.filler_audio_cache[phrase]

    # ========== 语音场景模式 ==========

    def _apply_voice_mode_settings(self):
        """根据语音场景模式动态调整参数"""
        mode = self.config.voice_mode

        # VAD 静音阈值 (毫秒)
        global _VAD_SILENCE_DURATION_MS
        if mode == "companion":
            _VAD_SILENCE_DURATION_MS = 800
        elif mode == "assistant":
            _VAD_SILENCE_DURATION_MS = 400
        else:  # balanced
            _VAD_SILENCE_DURATION_MS = 600

        # assistant 模式禁用填充语，其他模式恢复
        self.config.enable_filler = (mode != "assistant")

        logger.info(f"语音场景模式已设置: {mode}, VAD静音={_VAD_SILENCE_DURATION_MS}ms, 填充语={self.config.enable_filler}")

    # ========== WebSocket 主入口 ==========

    async def handle_connection(self, websocket: WebSocket, session_id: str = "default"):
        """
        处理 WebSocket 连接 — 主入口

        Args:
            websocket: FastAPI WebSocket 实例
            session_id: 会话 ID
        """
        await websocket.accept()

        # 首次连接时初始化引擎
        if not self._initialized:
            await self.initialize()

        session = VoiceCallSession(
            session_id=session_id,
            user_id=f"voice_call_user_{id(websocket)}"
        )
        self.sessions[session_id] = session
        self._interrupt_events[session_id] = asyncio.Event()

        # 根据语音场景模式动态调整参数
        self._apply_voice_mode_settings()

        # 预缓存填充语音频（per-session）
        await self._precache_fillers(session)

        logger.info(f"VoiceCall WebSocket 已连接: {session_id}")

        # 发送连接确认
        await self._send(websocket, {
            "type": "state",
            "state": CallState.LISTENING.value,
        })

        try:
            while True:
                try:
                    raw_data = await asyncio.wait_for(
                        websocket.receive(),
                        timeout=_WS_RECEIVE_TIMEOUT
                    )

                    if raw_data.get("type") == "websocket.disconnect":
                        break

                    session.last_activity = time.time()

                    if "text" in raw_data:
                        await self._handle_text_message(websocket, session, raw_data["text"])
                    elif "bytes" in raw_data:
                        # 二进制帧直接作为 PCM 音频处理
                        await self._handle_audio_frame(websocket, session, raw_data["bytes"])

                except asyncio.TimeoutError:
                    # 心跳检测
                    await self._send(websocket, {"type": "pong"})

        except WebSocketDisconnect:
            logger.info(f"VoiceCall WebSocket 已断开: {session_id}")
        except Exception as e:
            logger.error(f"VoiceCall WebSocket 错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # 清理 VoiceAgent 的对话历史
            if self._voice_agent:
                self._voice_agent.clear_session(session.session_id)
            await self._cleanup_session(session, session_id)

    # ========== 消息处理 ==========

    async def _handle_text_message(self, websocket: WebSocket, session: VoiceCallSession, text: str):
        """
        处理文本消息

        协议:
        - {type: "audio", data: base64_pcm_16k}  // 音频帧
        - {type: "interrupt"}                    // 手动打断
        - {type: "ping"}                         // 心跳
        """
        try:
            data = json.loads(text)
            msg_type = data.get("type", "")

            if msg_type == "audio":
                # base64 编码的 PCM 音频帧
                audio_b64 = data.get("data", "")
                if audio_b64:
                    pcm_bytes = base64.b64decode(audio_b64)
                    await self._handle_audio_frame(websocket, session, pcm_bytes)

            elif msg_type == "interrupt":
                await self._handle_interrupt(websocket, session)

            elif msg_type == "ping":
                await self._send(websocket, {"type": "pong"})

            else:
                logger.warning(f"未知消息类型: {msg_type}")

        except json.JSONDecodeError:
            logger.warning(f"无法解析的文本消息: {text[:100]}")
        except Exception as e:
            logger.error(f"处理文本消息错误: {e}")
            await self._send_error(websocket, str(e))

    async def _handle_audio_frame(self, websocket: WebSocket, session: VoiceCallSession, pcm_bytes: bytes):
        """
        处理音频帧

        将 PCM 字节转为 numpy 数组，送入 VAD 检测端点。
        检测到语音结束后，触发 ASR + LLM + TTS 管线。
        检测到新语音开始且当前正在说话，触发打断。
        """
        # PCM16 字节 → numpy int16 数组
        try:
            audio_np = np.frombuffer(pcm_bytes, dtype=np.int16)
        except Exception as e:
            logger.debug(f"音频帧解析失败: {e}")
            return

        if len(audio_np) == 0:
            return

        # VAD 检测：优先 Silero，回退到简单能量检测
        is_speech = False
        if self._vad and self._vad._initialized:
            try:
                vad_result = await self._vad.process(audio_np, self.config.sample_rate)
                is_speech = vad_result.is_speech
            except Exception as e:
                logger.debug(f"VAD 处理失败，回退到能量检测: {e}")
                is_speech = self._energy_vad(audio_np)
        else:
            # 无 VAD 引擎时使用简单能量检测
            is_speech = self._energy_vad(audio_np)

        if is_speech:
            # ---- 检测到语音 ----
            if not session.is_collecting_speech:
                # 语音开始
                session.is_collecting_speech = True
                session.speech_buffer = []
                session.silence_sample_count = 0
                session.idle_silence_sample_count = 0
                session.silence_prompt_sent = False
                logger.debug(f"[{session.session_id}] VAD: 语音开始")

                # 打断机制: 如果 AI 正在说话，立即打断
                if session.state == CallState.SPEAKING:
                    logger.info(f"[{session.session_id}] VAD 检测到新语音，打断当前回复")
                    await self._handle_interrupt(websocket, session)

            # 收集语音帧
            session.speech_buffer.append(audio_np)
            session.silence_sample_count = 0

        else:
            # ---- 检测到静音 ----
            if session.is_collecting_speech:
                # 仍在语音段内，但出现了静音
                session.speech_buffer.append(audio_np)
                session.silence_sample_count += len(audio_np)

                # 检查静音时长是否超过阈值
                silence_samples_threshold = int(
                    _VAD_SILENCE_DURATION_MS * self.config.sample_rate / 1000
                )
                if session.silence_sample_count >= silence_samples_threshold:
                    # 语音端点确认 — 触发识别 + 回复
                    logger.info(f"[{session.session_id}] VAD: 语音结束（静音 {_VAD_SILENCE_DURATION_MS}ms）")
                    speech_audio = np.concatenate(session.speech_buffer)

                    # 重置收集状态
                    session.is_collecting_speech = False
                    session.speech_buffer = []
                    session.silence_sample_count = 0

                    # 启动识别 + 回复管线
                    await self._start_reply_pipeline(websocket, session, speech_audio)
            else:
                # ---- 空闲状态下的长停顿检测（companion 模式） ----
                if session.state == CallState.LISTENING:
                    session.idle_silence_sample_count += len(audio_np)
                    # 长停顿阈值 1.5s
                    idle_silence_threshold = int(1500 * self.config.sample_rate / 1000)
                    if (session.idle_silence_sample_count >= idle_silence_threshold
                            and not session.silence_prompt_sent):
                        await self._check_silence_prompt(session, websocket)
                        session.silence_prompt_sent = True

    # ========== Task 7: 长停顿主动接话 ==========

    async def _check_silence_prompt(self, session: VoiceCallSession, websocket):
        """
        检测长停顿，在 companion 模式下触发主动接话。
        仅在 AI 空闲（非 SPEAKING 状态）时检测。
        """
        if self.config.voice_mode != "companion":
            return
        if session.state == CallState.SPEAKING:
            return  # AI 正在说话时不触发

        # 发送 silence_prompt 消息给前端
        await self._send(websocket, {
            "type": "silence_prompt",
            "message": "嗯？继续说"
        })
        logger.debug(f"[{session.session_id}] 发送长停顿接话提示")

    # ========== 识别 + 回复管线 ==========

    async def _start_reply_pipeline(self, websocket: WebSocket, session: VoiceCallSession, speech_audio: np.ndarray):
        """
        启动 识别 → LLM → TTS 完整管线

        Args:
            websocket: WebSocket 连接
            session: 通话会话
            speech_audio: 用户语音的 numpy 数组
        """
        # 取消之前的任务
        await self._cancel_current_task(session)

        # 重置打断事件
        self._interrupt_events[session.session_id] = asyncio.Event()

        # 创建管线任务
        task = asyncio.create_task(
            self._reply_pipeline(websocket, session, speech_audio)
        )
        session.current_task = task

        try:
            await task
        except asyncio.CancelledError:
            logger.info(f"[{session.session_id}] 回复管线被取消")
        except Exception as e:
            logger.error(f"[{session.session_id}] 回复管线错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            session.current_task = None
            if session.state != CallState.LISTENING:
                session.state = CallState.LISTENING

    def _classify_intent(self, text: str) -> str:
        """
        意图分类：判断用户输入是简单还是复杂意图。

        基于规则（关键词匹配 + 输入长度），不依赖额外 LLM 调用。

        Returns:
            "simple" — 问候、确认/否定、简单事实、短指令
            "complex" — 推理、计算、长文生成、多步骤操作
        """
        text = text.strip()
        text_len = len(text)

        # 复杂意图关键词
        complex_keywords = [
            "计算", "算一下", "乘以", "除以", "加", "减", "等于",
            "为什么", "怎么", "如何", "分析", "比较", "区别",
            "写一篇", "写一个", "生成", "翻译", "总结",
            "帮我", "帮助我", "解释", "说明",
            "计划", "方案", "设计", "实现",
            "步骤", "流程", "过程",
        ]

        # 简单意图模式
        simple_patterns = [
            "你好", "嗨", "哈喽", "早上好", "晚上好", "中午好",
            "谢谢", "感谢", "多谢",
            "好的", "嗯", "哦", "是的", "不是", "对", "不对",
            "再见", "拜拜", "晚安",
            "在吗", "听到了", "明白",
        ]

        # 1. 检查简单模式
        for pattern in simple_patterns:
            if pattern in text and text_len <= 10:
                return "simple"

        # 2. 检查复杂关键词
        for keyword in complex_keywords:
            if keyword in text:
                return "complex"

        # 3. 基于长度判断
        if text_len <= 8:
            return "simple"
        if text_len > 30:
            return "complex"

        # 4. 默认中等长度视为复杂
        return "complex"

    def _get_voice_system_prompt(self) -> str:
        """根据语音场景模式生成系统提示"""
        mode = self.config.voice_mode

        # 压缩推理基础提示
        compressed_base = (
            "你正在语音对话模式中。回答必须简洁直接，避免冗长推理过程。"
            "保留关键计算步骤，但不要输出过渡语句和重复解释。"
            "回答要自然口语化，适合语音播放。"
        )

        if mode == "companion":
            return compressed_base + (
                "你的语气温暖、耐心、有亲和力。"
                "关注用户情绪，适时表达理解和共情。"
                "回答长度适中，不要过于简短冷漠。"
            )
        elif mode == "assistant":
            return compressed_base + (
                "你的语气简洁、精确、高效。"
                "直接给出答案，不要寒暄和客套话。"
                "回答尽量短，一句话能说清的不用两句。"
            )
        else:  # balanced
            return compressed_base + (
                "你的语气自然、友好。"
                "回答简洁但不失温度，像一个有礼貌的朋友。"
            )

    async def _reply_pipeline(self, websocket: WebSocket, session: VoiceCallSession, speech_audio: np.ndarray):
        """
        完整回复管线: ASR → LLM流式 → 标点切分 → 逐句TTS → 音频推送
        """
        interrupt_event = self._interrupt_events.get(session.session_id)

        # ====== 阶段1: ASR 识别 ======
        session.state = CallState.THINKING
        await self._send(websocket, {"type": "state", "state": CallState.THINKING.value})

        if not self._asr:
            await self._send_error(websocket, "ASR 引擎不可用")
            return

        try:
            asr_result = await self._asr.transcribe(speech_audio, self.config.sample_rate)
            user_text = asr_result.text.strip()
        except Exception as e:
            logger.error(f"ASR 识别失败: {e}")
            await self._send_error(websocket, f"语音识别失败: {str(e)}")
            return

        if not user_text:
            logger.info(f"[{session.session_id}] ASR 返回空文本，跳过回复")
            session.state = CallState.LISTENING
            await self._send(websocket, {"type": "state", "state": CallState.LISTENING.value})
            return

        logger.info(f"[{session.session_id}] ASR 识别结果: {user_text}")

        # Context ASR 后纠正
        if self.config.enable_context_asr and self._voice_agent:
            try:
                user_text = await self._voice_agent._post_correct_asr(user_text, session.session_id)
            except Exception as e:
                logger.warning(f"ASR 后纠正失败: {e}")

        # 情感感知
        if self.config.enable_emotion_aware and self._voice_agent:
            emotion = getattr(asr_result, 'emotion', None)
            if emotion and emotion != "NEUTRAL":
                emotion_prompts = {
                    "SAD": "用户似乎有点难过，请适当共情。",
                    "ANGRY": "用户似乎有些生气，请保持冷静和理解。",
                    "HAPPY": "用户心情不错，可以轻松一点。",
                    "FEAR": "用户似乎有些担心，请给予安慰。",
                }
                emotion_hint = emotion_prompts.get(emotion)
                if emotion_hint:
                    base_prompt = self._get_voice_system_prompt()
                    self._voice_agent.set_system_prompt(session.session_id, base_prompt + "\n" + emotion_hint)
                    logger.info(f"[{session.session_id}] 检测到情感: {emotion}")

        # 发送识别文本给前端
        await self._send(websocket, {"type": "asr_text", "text": user_text})

        # 将用户消息写入 AgentBridge 的 session（如果可用）
        # await self._write_user_message_to_bridge(session.session_id, user_text)

        # 检查打断
        if interrupt_event and interrupt_event.is_set():
            return

        # ====== 阶段1.5: 意图分类 + 填充语 ======
        intent = self._classify_intent(user_text)
        logger.info(f"[{session.session_id}] 意图分类: {intent}")

        filler_sent = False
        if (intent == "complex" and self.config.enable_filler):
            filler = self._get_random_filler(session)
            if filler:
                # 立即发送填充语音频，前端同步播放
                await self._send(websocket, {
                    "type": "filler",
                    "data": filler["data"],
                    "format": filler["format"],
                    "sample_rate": filler["sample_rate"],
                })
                filler_sent = True
                logger.debug(f"[{session.session_id}] 已发送填充语")

        # ====== 阶段1.6: 编程任务委派检查 ======
        is_coding_task = False
        if self.config.enable_coding_delegation and self._voice_agent:
            is_coding_task = self._voice_agent._detect_coding_intent(user_text)
            if is_coding_task:
                logger.info(f"[{session.session_id}] 检测到编程任务，委派给 Coding Agent")

                # 先说"好的，我来处理"
                ack_text = "好的，我来处理"
                if self._tts:
                    try:
                        tts_result = await self._tts.synthesize(ack_text)
                        if tts_result and tts_result.audio_data:
                            import base64
                            audio_b64 = base64.b64encode(tts_result.audio_data).decode('utf-8')
                            await self._send(websocket, {
                                "type": "audio",
                                "data": audio_b64,
                                "format": getattr(tts_result, "format", "pcm"),
                                "sample_rate": getattr(tts_result, "sample_rate", 22050),
                            })
                    except Exception as e:
                        logger.warning(f"委派确认语 TTS 失败: {e}")

                # 委派给 Coding Agent
                if hasattr(self._voice_agent, '_agent_bridge') and self._voice_agent._agent_bridge:
                    full_response = ""
                    async for chunk in self._voice_agent.delegate_to_coding_agent(user_text, session.session_id):
                        # 检查打断
                        if interrupt_event and interrupt_event.is_set():
                            break

                        if chunk.startswith("[PROGRESS]"):
                            # Task 5: 进度播报
                            progress_text = chunk[len("[PROGRESS]"):]
                            if self.config.enable_progress_report and progress_text and self._tts:
                                try:
                                    tts_result = await self._tts.synthesize(progress_text)
                                    if tts_result and tts_result.audio_data:
                                        import base64
                                        audio_b64 = base64.b64encode(tts_result.audio_data).decode('utf-8')
                                        await self._send(websocket, {
                                            "type": "audio",
                                            "data": audio_b64,
                                            "format": getattr(tts_result, "format", "pcm"),
                                            "sample_rate": getattr(tts_result, "sample_rate", 22050),
                                        })
                                except Exception as e:
                                    logger.warning(f"进度播报 TTS 失败: {e}")
                        else:
                            # 正常文本，送入 splitter 队列
                            full_response += chunk
                            # 这里简化处理：直接流式 TTS
                            # 复用现有的 splitter + tts_worker 逻辑
                            # 将 chunk 送入 sentence_queue
                            pass

                    # 委派完成，发送最终文本到前端
                    if full_response:
                        await self._send(websocket, {"type": "llm_token", "content": full_response})
                        # 用 TTS 播报最终结果
                        if self._tts:
                            try:
                                tts_result = await self._tts.synthesize(full_response)
                                if tts_result and tts_result.audio_data:
                                    import base64
                                    audio_b64 = base64.b64encode(tts_result.audio_data).decode('utf-8')
                                    await self._send(websocket, {
                                        "type": "audio",
                                        "data": audio_b64,
                                        "format": getattr(tts_result, "format", "pcm"),
                                        "sample_rate": getattr(tts_result, "sample_rate", 22050),
                                    })
                            except Exception as e:
                                logger.warning(f"委派结果 TTS 失败: {e}")

                    # 委派完成后返回，不走正常 LLM 流程
                    # 恢复监听状态
                    if not (interrupt_event and interrupt_event.is_set()):
                        session.state = CallState.LISTENING
                        await self._send(websocket, {"type": "state", "state": CallState.LISTENING.value})
                    return
                else:
                    logger.warning("agent_bridge 未注入，无法委派，走正常对话")
                    is_coding_task = False

        # ====== 阶段2: LLM 流式 + 标点切分 → TTS ======
        session.state = CallState.SPEAKING
        await self._send(websocket, {"type": "state", "state": CallState.SPEAKING.value})

        splitter = SentenceSplitter()

        # TTS 队列和工作者
        tts_queue: asyncio.Queue = asyncio.Queue()
        tts_semaphore = asyncio.Semaphore(1)
        tts_task = asyncio.create_task(
            self._tts_worker(websocket, session, tts_queue, interrupt_event, tts_semaphore)
        )

        full_response = ""

        try:
            # 注入压缩推理系统提示
            system_prompt = self._get_voice_system_prompt()
            if system_prompt and self._voice_agent:
                try:
                    self._voice_agent.set_system_prompt(session.session_id, system_prompt)
                except Exception:
                    pass  # 如果 VoiceAgent 不支持 set_system_prompt，静默跳过
            elif system_prompt and self.agent_bridge:
                try:
                    if hasattr(self.agent_bridge, 'set_system_prompt'):
                        self.agent_bridge.set_system_prompt(session.session_id, system_prompt)
                except Exception:
                    pass

            # 获取 LLM 流式响应
            async for token_text in self._stream_llm(user_text, session):
                if interrupt_event and interrupt_event.is_set():
                    logger.info(f"[{session.session_id}] LLM 流式被打断")
                    break

                if token_text:
                    full_response += token_text
                    session.current_text = full_response

                    # 推送 LLM token 给前端
                    await self._send(websocket, {"type": "llm_token", "text": token_text})

                    # 标点切分
                    sentences = splitter.feed(token_text)
                    for sentence in sentences:
                        if interrupt_event and interrupt_event.is_set():
                            break
                        await tts_queue.put(sentence)

            # flush 切分器中剩余文本
            remaining = splitter.flush()
            if remaining and not (interrupt_event and interrupt_event.is_set()):
                await tts_queue.put(remaining)

        finally:
            # 通知 TTS 工作者结束
            await tts_queue.put(None)
            try:
                await asyncio.wait_for(tts_task, timeout=_WS_TTS_TASK_SHUTDOWN_TIMEOUT)
            except asyncio.TimeoutError:
                tts_task.cancel()
                try:
                    await tts_task
                except asyncio.CancelledError:
                    pass

        # 将 AI 回复写入 AgentBridge 的 session
        if full_response:
            # await self._write_assistant_message_to_bridge(session.session_id, full_response)
            pass

        # 恢复监听状态
        if not (interrupt_event and interrupt_event.is_set()):
            session.state = CallState.LISTENING
            await self._send(websocket, {"type": "state", "state": CallState.LISTENING.value})

    # ========== LLM 流式 ==========

    async def _stream_llm(self, user_text: str, session: VoiceCallSession):
        """
        调用 VoiceAgent / AgentBridge 的 LLM 流式接口

        Yields:
            逐个 token 字符串
        """
        if self._voice_agent:
            try:
                async for token in self._voice_agent.chat_stream(user_text, session.session_id):
                    yield token
                return
            except Exception as e:
                logger.error(f"VoiceAgent 流式调用失败: {e}")
                yield f"抱歉，处理时出现错误: {str(e)}"
                return

        # 回退: 通过 agent_bridge 直接调用
        if self.agent_bridge is not None:
            try:
                if hasattr(self.agent_bridge, 'chat_stream'):
                    async for token in self.agent_bridge.chat_stream(user_text, session.session_id):
                        yield token
                    return
                elif hasattr(self.agent_bridge, 'chat'):
                    result = await self.agent_bridge.chat(user_text, session.session_id)
                    if isinstance(result, str):
                        yield result
                    elif hasattr(result, 'content'):
                        yield result.content
                    return
            except Exception as e:
                logger.error(f"AgentBridge 调用失败: {e}")
                yield f"抱歉，处理时出现错误: {str(e)}"
                return

        # 最终回退: 返回固定文本
        yield f"收到: {user_text}"

    # ========== TTS 工作者 ==========

    async def _tts_worker(
        self,
        websocket: WebSocket,
        session: VoiceCallSession,
        queue: asyncio.Queue,
        interrupt_event: Optional[asyncio.Event],
        semaphore: asyncio.Semaphore
    ):
        """
        TTS 工作协程 — 从队列取句子，合成音频，推送

        流程:
        1. 从 tts_queue 取出一个句子
        2. 调用 TTS 引擎合成音频
        3. base64 编码后通过 WebSocket 推送
        """
        while True:
            try:
                sentence = await asyncio.wait_for(queue.get(), timeout=_WS_TTS_WORKER_TIMEOUT)

                # None 是结束信号
                if sentence is None:
                    break

                if interrupt_event and interrupt_event.is_set():
                    break

                async with semaphore:
                    if interrupt_event and interrupt_event.is_set():
                        break
                    await self._synthesize_and_send(websocket, session, sentence, interrupt_event)

            except asyncio.TimeoutError:
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TTS 工作者错误: {e}")

    async def _synthesize_and_send(
        self,
        websocket: WebSocket,
        session: VoiceCallSession,
        text: str,
        interrupt_event: Optional[asyncio.Event] = None
    ):
        """
        合成 TTS 音频并发送

        Args:
            websocket: WebSocket 连接
            session: 通话会话
            text: 要合成的文本
            interrupt_event: 打断事件
        """
        if not text or not text.strip():
            return

        if interrupt_event and interrupt_event.is_set():
            return

        if not self._tts:
            # TTS 不可用，仅发送文本
            logger.debug("TTS 引擎不可用，仅发送文本")
            return

        try:
            logger.debug(f"开始 TTS 合成: {text[:50]}")

            # 调用 TTS 引擎
            tts_speed = 1.0
            if self.config.voice_mode == "companion":
                tts_speed = 0.9
            elif self.config.voice_mode == "assistant":
                tts_speed = 1.1

            tts_result = await self._tts.synthesize(
                text,
                voice=self.config.tts_voice or None,
                speed=tts_speed,
            )

            if interrupt_event and interrupt_event.is_set():
                return

            if tts_result and tts_result.audio_data:
                # base64 编码音频数据
                audio_base64 = base64.b64encode(tts_result.audio_data).decode('utf-8')
                logger.info(
                    f"[TTS] 发送音频块: {len(audio_base64)} chars base64, "
                    f"文本: {text[:30]}..."
                )

                # 发送音频给前端
                await self._send(websocket, {
                    "type": "audio",
                    "data": audio_base64,
                    "format": getattr(tts_result, "format", "wav") or "wav",
                    "sample_rate": int(getattr(tts_result, "sample_rate", 24000) or 24000),
                    "text": text,
                })
            else:
                logger.debug(f"TTS 返回空音频: {text[:30]}")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"TTS 合成错误: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    # ========== 打断处理 ==========

    async def _handle_interrupt(self, websocket: WebSocket, session: VoiceCallSession):
        """
        处理打断请求

        - 设置打断事件
        - 取消当前 LLM+TTS 任务
        - 通知前端
        """
        logger.info(f"[{session.session_id}] 收到打断请求")

        # 设置打断事件
        interrupt_event = self._interrupt_events.get(session.session_id)
        if interrupt_event:
            interrupt_event.set()

        # 取消当前任务
        await self._cancel_current_task(session)

        # 重置状态
        session.state = CallState.LISTENING
        session.current_text = ""

        # 通知前端打断确认
        await self._send(websocket, {"type": "interrupted"})

    async def _cancel_current_task(self, session: VoiceCallSession):
        """取消当前正在执行的管线任务"""
        if session.current_task and not session.current_task.done():
            session.current_task.cancel()
            try:
                await asyncio.wait_for(session.current_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            session.current_task = None

    # ========== AgentBridge 集成 ==========

    async def _write_user_message_to_bridge(self, session_id: str, text: str):
        """将用户消息写入 AgentBridge 的 session"""
        if self.agent_bridge is None:
            return
        try:
            if hasattr(self.agent_bridge, 'add_user_message'):
                await self.agent_bridge.add_user_message(session_id, text)
            elif hasattr(self.agent_bridge, 'add_message'):
                await self.agent_bridge.add_message(session_id, "user", text)
        except Exception as e:
            logger.debug(f"写入用户消息到 bridge 失败: {e}")

    async def _write_assistant_message_to_bridge(self, session_id: str, text: str):
        """将 AI 回复写入 AgentBridge 的 session"""
        if self.agent_bridge is None:
            return
        try:
            if hasattr(self.agent_bridge, 'add_assistant_message'):
                await self.agent_bridge.add_assistant_message(session_id, text)
            elif hasattr(self.agent_bridge, 'add_message'):
                await self.agent_bridge.add_message(session_id, "assistant", text)
        except Exception as e:
            logger.debug(f"写入助手消息到 bridge 失败: {e}")

    # ========== 资源清理 ==========

    async def _cleanup_session(self, session: VoiceCallSession, session_id: str):
        """清理会话资源"""
        await self._cancel_current_task(session)

        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self._interrupt_events:
            del self._interrupt_events[session_id]

        logger.info(f"VoiceCall 会话已清理: {session_id}")

    async def close(self):
        """关闭处理器，释放所有引擎资源"""
        logger.info("VoiceCallHandler: 关闭中...")

        # 取消所有进行中的任务
        for session_id, session in list(self.sessions.items()):
            await self._cancel_current_task(session)
        self.sessions.clear()
        self._interrupt_events.clear()

        # 关闭引擎
        if self._vad:
            try:
                await self._vad.close()
            except Exception as e:
                logger.debug(f"VAD 关闭失败: {e}")
            self._vad = None

        if self._asr:
            try:
                await self._asr.close()
            except Exception as e:
                logger.debug(f"ASR 关闭失败: {e}")
            self._asr = None

        if self._tts:
            try:
                await self._tts.close()
            except Exception as e:
                logger.debug(f"TTS 关闭失败: {e}")
            self._tts = None

        # VoiceAgent 是轻量级，无需 close
        self._voice_agent = None

        self._initialized = False
        logger.info("VoiceCallHandler: 已关闭")

    # ========== 通用发送 ==========

    async def _send(self, websocket: WebSocket, message: dict):
        """安全发送 JSON 消息"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.debug(f"发送消息失败（连接可能已关闭）: {e}")

    async def _send_error(self, websocket: WebSocket, error_msg: str):
        """发送错误消息"""
        await self._send(websocket, {
            "type": "error",
            "message": error_msg,
        })

    # ========== 能量 VAD 降级 ==========

    def _energy_vad(self, audio_np: np.ndarray, threshold: float = 0.01) -> bool:
        """
        简单能量检测作为 VAD 降级方案

        当 Silero VAD 不可用时使用。计算音频 RMS 能量，
        超过阈值则判定为语音。

        Args:
            audio_np: PCM int16 音频数据
            threshold: 能量阈值（归一化后）

        Returns:
            是否检测到语音
        """
        # 归一化到 [-1, 1] 范围
        audio_float = audio_np.astype(np.float32) / 32768.0
        # 计算 RMS 能量
        energy = np.sqrt(np.mean(audio_float ** 2))
        return energy > threshold

    # ========== 状态查询 ==========

    def get_session(self, session_id: str) -> Optional[VoiceCallSession]:
        """获取指定会话"""
        return self.sessions.get(session_id)

    def get_active_sessions(self) -> int:
        """获取活跃会话数"""
        return len(self.sessions)

    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized
