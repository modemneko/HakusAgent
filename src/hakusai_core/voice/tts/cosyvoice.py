"""
HakusAI 2.0 CosyVoice TTS 引擎
基于阿里云 DashScope CosyVoice API，支持语音合成与语音复刻
"""

import asyncio
import json
import os
import ssl
import threading
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import aiohttp

from .base import BaseTTS, TTSResult, register_tts

import logging

logger = logging.getLogger(__name__)

# DashScope API 地址
_DASHSCOPE_BASE_URL = "dashscope.aliyuncs.com"
_DASHSCOPE_HTTP_TTS_URL = f"https://{_DASHSCOPE_BASE_URL}/api/v1/services/audio/tts/SpeechSynthesizer"
_DASHSCOPE_WS_TTS_URL = f"wss://{_DASHSCOPE_BASE_URL}/api-ws/v1/inference"
_DASHSCOPE_CUSTOMIZATION_URL = f"https://{_DASHSCOPE_BASE_URL}/api/v1/services/audio/tts/customization"
_DASHSCOPE_FILES_URL = f"https://{_DASHSCOPE_BASE_URL}/api/v1/files"

# 支持的模型列表
SUPPORTED_MODELS = [
    "cosyvoice-v2",
    "cosyvoice-v3-flash",
    "cosyvoice-v3-plus",
    "cosyvoice-v3.5-plus",
    "cosyvoice-v3.5-flash",
]

# 需要复刻音色的模型（不支持系统默认音色）
_MODELS_REQUIRING_CLONE = {"cosyvoice-v3.5-plus", "cosyvoice-v3.5-flash"}

# 默认系统音色（用于 v2/v3 系列）
_DEFAULT_SYSTEM_VOICE = "longanhuan"

# 语音复刻本地路径
def _voice_data_dir() -> str:
    configured = os.environ.get("HAKUSAI_DATA_DIR")
    if configured:
        return os.path.abspath(os.path.join(configured, "voice"))
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    return os.path.join(project_root, "hakusai_data", "voice")


_VOICE_DATA_DIR = _voice_data_dir()
_REF_AUDIO_PATH = os.path.join(_VOICE_DATA_DIR, "ref_audio.wav")
_VOICE_ID_CACHE_PATH = os.path.join(_VOICE_DATA_DIR, "voice_id.txt")
_VOICE_STATUS_PATH = os.path.join(_VOICE_DATA_DIR, "voice_status.txt")
_VOICE_ERROR_PATH = os.path.join(_VOICE_DATA_DIR, "voice_error.txt")


@register_tts("cosyvoice")
class CosyVoiceTTS(BaseTTS):
    """
    CosyVoice TTS 引擎

    基于阿里云 DashScope CosyVoice API，支持：
    - HTTP 模式：完整合成后返回音频
    - WebSocket 流式模式：实时流式输入文本、流式输出音频
    - 语音复刻：上传参考音频 → 创建克隆音色 → 缓存 voice_id

    配置项（通过 config 字典传入）：
        - api_key: DashScope API Key（必需）
        - model: 模型名称（默认 cosyvoice-v3-flash）
        - voice_id: 已克隆的音色 ID（可选）
        - ref_audio: 参考音频路径（可选，用于语音复刻）
        - format: 音频格式（默认 mp3）
        - sample_rate: 采样率（默认 22050）
        - instruction: 默认语气指令（可选）
        - proxy: HTTP 代理地址（可选）
        - auto_clone: 是否自动执行语音复刻（默认 True）
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 CosyVoice TTS

        Args:
            config: 配置字典
        """
        super().__init__(config)

        # 核心配置
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "cosyvoice-v3-flash")
        self.voice_id = config.get("voice_id", "")
        self.ref_audio = config.get("ref_audio", _REF_AUDIO_PATH)
        self.audio_format = config.get("format", "pcm")
        self.sample_rate = config.get("sample_rate", 22050)
        self.default_instruction = config.get("instruction", "")
        self.proxy = config.get("proxy", "")
        self.auto_clone = config.get("auto_clone", True)

        # 验证模型
        if self.model not in SUPPORTED_MODELS:
            logger.warning(
                f"模型 {self.model} 不在已知支持列表中，可能无法正常工作。"
                f"支持的模型: {SUPPORTED_MODELS}"
            )

        # 语音复刻状态
        self._clone_task: Optional[threading.Thread] = None
        self._clone_complete = False
        self._clone_status = "pending"
        self._clone_error = ""

        # 尝试从本地缓存加载 voice_id
        cached_voice_id = self._load_cached_voice_id()
        if cached_voice_id:
            self.voice_id = cached_voice_id
            self._clone_status = "completed"
            logger.info(f"从本地缓存加载 CosyVoice voice_id: {self.voice_id}")

    @property
    def provider_name(self) -> str:
        """提供商名称"""
        return "cosyvoice"

    async def initialize(self):
        """初始化 TTS 引擎"""
        if not self.api_key:
            logger.warning("api_key 未配置，CosyVoice TTS 功能将不可用")
            self._initialized = True
            return

        # 判断是否需要声音克隆
        is_cloned_voice = self.voice_id and "hakusai" in self.voice_id
        need_clone = self.auto_clone and self.ref_audio and not is_cloned_voice

        if need_clone:
            # 异步克隆：先用当前 voice_id 工作，克隆完成后自动切换
            self._start_clone_background()

        self._initialized = True
        logger.info(
            f"CosyVoice TTS 初始化完成，模型: {self.model}，"
            f"voice_id: {self.voice_id or '(使用默认音色)'}"
        )

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs,
    ) -> TTSResult:
        """
        合成语音（HTTP 模式，非实时）

        Args:
            text: 要合成的文本
            voice: 语音名称/voice_id，默认使用配置中的值
            speed: 语速（CosyVoice 不直接支持，通过 instruction 控制）
            **kwargs:
                - instruction: 语气指令
                - format: 音频格式
                - sample_rate: 采样率

        Returns:
            TTSResult 合成结果
        """
        if not self._initialized:
            await self.initialize()

        text = self._preprocess_text(text)
        if not text:
            return TTSResult(audio_data=b"", sample_rate=self.sample_rate, format=self.audio_format)

        if not self.api_key:
            raise RuntimeError("api_key 未配置，无法调用 CosyVoice TTS")

        # 确定使用的 voice_id
        use_voice = self._resolve_voice(voice)
        if not use_voice:
            raise RuntimeError(
                f"模型 {self.model} 需要复刻音色，请配置 voice_id 或 ref_audio 进行语音复刻"
            )

        # 合成参数
        instruction = kwargs.get("instruction") or self.default_instruction or None
        audio_format = kwargs.get("format") or self.audio_format
        sample_rate = kwargs.get("sample_rate") or self.sample_rate

        # 检查缓存
        use_speed = speed or self.speed
        cached_result = self._check_cache(text, use_voice, use_speed)
        if cached_result:
            logger.debug(f"TTS cache hit: {text[:30]}...")
            return cached_result

        # 构建请求体
        input_obj = {
            "text": text,
            "voice": use_voice,
            "format": audio_format,
            "sample_rate": sample_rate,
        }
        if instruction:
            input_obj["instruction"] = instruction

        body = {"model": self.model, "input": input_obj}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.debug(f"调用 CosyVoice HTTP TTS: 文本='{text[:30]}...' voice={use_voice}")

        # 发起 HTTP 请求 — 单个 session 完成合成 + 下载
        connector = self._build_connector()
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=60)) as session:
                # 1. 请求合成
                async with session.post(
                    _DASHSCOPE_HTTP_TTS_URL,
                    headers=headers,
                    json=body,
                    proxy=self.proxy or None,
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise RuntimeError(f"CosyVoice TTS 请求失败: {resp.status} {error_text}")

                    result = await resp.json()

                # 从响应中获取音频 URL
                audio_url = result.get("output", {}).get("audio", {}).get("url")
                if not audio_url:
                    raise RuntimeError(f"CosyVoice TTS 响应中无音频 URL: {result}")

                # 2. 下载音频（复用同一个 session）
                logger.debug(f"下载音频: {audio_url}")
                async with session.get(audio_url, proxy=self.proxy or None) as audio_resp:
                    if audio_resp.status != 200:
                        raise RuntimeError(f"下载音频失败: {audio_resp.status}")
                    audio_data = await audio_resp.read()

            # 保存缓存
            self._save_cache(text, use_voice, use_speed, audio_data, audio_format)

            logger.info(f"CosyVoice TTS 合成完成: {text[:50]}...")
            return TTSResult(
                audio_data=audio_data,
                sample_rate=sample_rate,
                format=audio_format,
                cached=False,
            )

        except Exception as e:
            logger.error(f"CosyVoice TTS 合成失败: {e}")
            raise

    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs,
    ) -> AsyncIterator[bytes]:
        """
        流式合成语音（WebSocket 模式，实时流式）

        通过 DashScope WebSocket API 流式输入文本、流式输出音频。

        Args:
            text: 要合成的文本
            voice: 语音名称/voice_id
            speed: 语速
            **kwargs:
                - instruction: 语气指令
                - format: 音频格式
                - sample_rate: 采样率

        Yields:
            音频数据块（bytes）
        """
        if not self._initialized:
            await self.initialize()

        text = self._preprocess_text(text)
        if not text:
            return

        if not self.api_key:
            raise RuntimeError("api_key 未配置，无法调用 CosyVoice TTS")

        # 确定使用的 voice_id
        use_voice = self._resolve_voice(voice)
        if not use_voice:
            raise RuntimeError(
                f"模型 {self.model} 需要复刻音色，请配置 voice_id 或 ref_audio 进行语音复刻"
            )

        # 合成参数
        instruction = kwargs.get("instruction") or self.default_instruction or None
        audio_format = kwargs.get("format") or self.audio_format
        sample_rate = kwargs.get("sample_rate") or self.sample_rate

        logger.debug(f"调用 CosyVoice WebSocket TTS: 文本='{text[:30]}...' voice={use_voice}")

        try:
            async for chunk in self._ws_synthesize(
                text=text,
                voice=use_voice,
                instruction=instruction,
                audio_format=audio_format,
                sample_rate=sample_rate,
            ):
                yield chunk
        except Exception as e:
            logger.error(f"CosyVoice WebSocket TTS 流式合成失败: {e}")
            raise

    # ==================== WebSocket 流式 TTS ====================

    async def _ws_synthesize(
        self,
        text: str,
        voice: str,
        instruction: Optional[str] = None,
        audio_format: str = "mp3",
        sample_rate: int = 22050,
    ) -> AsyncIterator[bytes]:
        """
        通过 DashScope WebSocket API 进行流式语音合成

        协议流程：
        1. 建立 WebSocket 连接
        2. 发送 run-task 消息，包含模型和参数
        3. 发送 text-input 消息，包含待合成文本
        4. 发送 run-task 完成（空文本标记结束）
        5. 持续接收 audio-output 消息，获取音频数据
        6. 收到 task-finished 消息，关闭连接

        Args:
            text: 待合成文本
            voice: 音色 ID
            instruction: 语气指令
            audio_format: 音频格式
            sample_rate: 采样率

        Yields:
            音频数据块
        """
        task_id = uuid.uuid4().hex

        # 构建 WebSocket 请求头
        ws_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-DashScope-DataInspection": "enable",
        }

        # 构建 run-task 参数
        parameters = {
            "voice": voice,
            "format": audio_format,
            "sample_rate": sample_rate,
            "rate": 1,
            "pitch": 1,
        }
        if instruction:
            parameters["instruction"] = instruction

        # WebSocket 连接配置
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(ssl=ssl_ctx)

        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.ws_connect(
                _DASHSCOPE_WS_TTS_URL,
                headers=ws_headers,
                proxy=self.proxy or None,
            ) as ws:
                # 1. 发送 run-task
                run_task_msg = {
                    "header": {
                        "task_id": task_id,
                        "action": "run-task",
                        "streaming": "duplex",
                    },
                    "payload": {
                        "task_group": "audio",
                        "task": "tts",
                        "function": "SpeechSynthesizer",
                        "model": self.model,
                        "parameters": parameters,
                        "input": {},
                    },
                }
                await ws.send_json(run_task_msg)

                # 2. 发送文本输入
                text_input_msg = {
                    "header": {
                        "task_id": task_id,
                        "action": "feed-text",
                        "sequence_id": 1,
                    },
                    "payload": {
                        "text": text,
                    },
                }
                await ws.send_json(text_input_msg)

                # 3. 标记文本输入结束
                finish_msg = {
                    "header": {
                        "task_id": task_id,
                        "action": "finish-task",
                        "sequence_id": -1,
                    },
                    "payload": {
                        "text": "",
                    },
                }
                await ws.send_json(finish_msg)

                # 4. 接收音频数据
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        header = data.get("header", {})
                        action = header.get("action", "")
                        code = header.get("code", "")

                        # 检查错误
                        if code and code != "200" and code != 0:
                            error_msg = data.get("header", {}).get("message", "unknown error")
                            raise RuntimeError(
                                f"CosyVoice WebSocket TTS 错误: code={code}, message={error_msg}"
                            )

                        # 处理音频输出
                        if action == "result":
                            payload = data.get("payload", {})
                            audio_b64 = payload.get("audio")
                            if audio_b64:
                                import base64
                                audio_chunk = base64.b64decode(audio_b64)
                                yield audio_chunk

                        # 任务完成
                        elif action == "task-finished":
                            break

                        # 任务失败
                        elif action == "task-failed":
                            error_msg = data.get("header", {}).get("message", "task failed")
                            raise RuntimeError(f"CosyVoice WebSocket TTS 任务失败: {error_msg}")

                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        # DashScope 二进制音频帧：前4字节小端序表示帧长度，后面是音频数据
                        if len(msg.data) > 4:
                            audio_chunk = msg.data[4:]
                            if audio_chunk:
                                yield audio_chunk

                    elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break

    # ==================== 语音复刻 ====================

    def _start_clone_background(self):
        """后台启动声音克隆（非阻塞），先用当前 voice_id 工作"""

        def _run():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._clone_voice_async())
                loop.close()
            except Exception as e:
                logger.error(f"声音克隆过程出错: {e}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self._clone_task = t
        logger.info("声音克隆已在后台启动，当前使用系统音色工作")

    async def _clone_voice_async(self):
        """
        通过参考音频进行声音克隆（异步完整流程）

        流程：
        1. 上传参考音频文件到 DashScope (POST /api/v1/files)
        2. 获取文件下载 URL (GET /api/v1/files/{file_id})
        3. 创建克隆声音 (POST /api/v1/services/audio/tts/customization, action=create_voice)
        4. 轮询声音状态 (POST /api/v1/services/audio/tts/customization, action=query_voice)
        5. 缓存 voice_id 到本地文件
        """
        self._clone_status = "cloning"
        self._clone_error = ""
        self._save_clone_status("cloning")

        if not self.api_key:
            self._set_clone_failed("声音克隆需要 DashScope API Key")
            return

        if not os.path.exists(self.ref_audio):
            self._set_clone_failed(f"参考音频文件不存在: {self.ref_audio}")
            return

        connector = self._build_connector()
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with aiohttp.ClientSession(
            connector=connector, timeout=aiohttp.ClientTimeout(total=600)
        ) as session:
            # 步骤 1：上传音频文件
            file_id = await self._upload_ref_audio(session, headers)
            if not file_id:
                self._set_clone_failed("上传参考音频失败，请检查网络或 API Key 是否有效")
                return

            # 步骤 2：获取文件下载 URL
            oss_url = await self._get_file_url(session, headers, file_id)
            if not oss_url:
                self._set_clone_failed("获取文件下载 URL 失败")
                return

            # 步骤 3：创建克隆声音
            voice_id = await self._create_voice(session, headers, oss_url)
            if not voice_id:
                self._set_clone_failed("创建克隆声音失败")
                return

            # 步骤 4：轮询声音状态
            success = await self._poll_voice_status(session, headers, voice_id)
            if success:
                self.voice_id = voice_id
                self._clone_complete = True
                self._clone_status = "completed"
                self._clone_error = ""
                self._save_voice_id(voice_id)
                self._save_clone_status("completed")
                logger.info(f"声音克隆成功，voice_id: {voice_id}")
            else:
                self._set_clone_failed("声音克隆失败或超时，请稍后重试")

    async def _upload_ref_audio(
        self, session: aiohttp.ClientSession, headers: Dict[str, str]
    ) -> Optional[str]:
        """
        上传参考音频文件到 DashScope

        Args:
            session: aiohttp 会话
            headers: 请求头

        Returns:
            file_id 或 None
        """
        logger.info(f"正在上传参考音频: {self.ref_audio}")
        try:
            data = aiohttp.FormData()
            data.add_field("purpose", "file-extract")
            data.add_field(
                "files",
                open(self.ref_audio, "rb"),
                filename=os.path.basename(self.ref_audio),
                content_type="audio/wav",
            )

            async with session.post(_DASHSCOPE_FILES_URL, headers=headers, data=data) as resp:
                response_text = await resp.text()
                if resp.status != 200:
                    err = f"上传参考音频失败: HTTP {resp.status} - {response_text[:500]}"
                    logger.error(err)
                    self._set_clone_failed(err)
                    return None
                try:
                    upload_result = json.loads(response_text)
                except json.JSONDecodeError:
                    err = f"上传参考音频返回非 JSON: {response_text[:500]}"
                    logger.error(err)
                    self._set_clone_failed(err)
                    return None

            uploaded_files = upload_result.get("data", {}).get("uploaded_files", [])
            if not uploaded_files:
                err = f"上传参考音频返回数据异常: {response_text[:500]}"
                logger.error(err)
                self._set_clone_failed(err)
                return None

            file_id = uploaded_files[0].get("file_id", "")
            logger.info(f"参考音频上传成功，file_id: {file_id}")
            return file_id

        except Exception as e:
            logger.error(f"上传参考音频异常: {e}")
            return None

    async def _get_file_url(
        self, session: aiohttp.ClientSession, headers: Dict[str, str], file_id: str
    ) -> Optional[str]:
        """
        获取已上传文件的下载 URL

        Args:
            session: aiohttp 会话
            headers: 请求头
            file_id: 文件 ID

        Returns:
            下载 URL 或 None
        """
        max_retries = 5
        for attempt in range(max_retries):
            try:
                async with session.get(
                    f"{_DASHSCOPE_FILES_URL}/{file_id}", headers=headers
                ) as resp:
                    response_text = await resp.text()
                    if resp.status == 429:
                        wait = 2 ** attempt
                        err = f"获取文件 URL 被限流 (429)，{wait}s 后重试..."
                        logger.warning(err)
                        if attempt == max_retries - 1:
                            self._set_clone_failed(f"获取文件下载 URL 失败: 请求过于频繁，请稍后重试。{response_text[:300]}")
                            return None
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        err = f"获取文件 URL 失败: HTTP {resp.status} - {response_text[:500]}"
                        logger.error(err)
                        self._set_clone_failed(err)
                        return None
                    try:
                        file_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        err = f"获取文件 URL 返回非 JSON: {response_text[:500]}"
                        logger.error(err)
                        self._set_clone_failed(err)
                        return None

                oss_url = file_data.get("data", {}).get("url", "")
                if not oss_url:
                    err = f"获取文件 URL 返回数据异常: {response_text[:500]}"
                    logger.error(err)
                    self._set_clone_failed(err)
                    return None

                logger.info("获取到文件下载 URL")
                return oss_url

            except Exception as e:
                logger.error(f"获取文件 URL 异常: {e}")
                if attempt == max_retries - 1:
                    self._set_clone_failed(f"获取文件下载 URL 失败: {str(e)}")
                    return None
                await asyncio.sleep(2 ** attempt)
        return None

    async def _create_voice(
        self, session: aiohttp.ClientSession, headers: Dict[str, str], oss_url: str
    ) -> Optional[str]:
        """
        创建克隆声音

        Args:
            session: aiohttp 会话
            headers: 请求头
            oss_url: 参考音频下载 URL

        Returns:
            voice_id 或 None
        """
        logger.info("正在创建克隆声音...")
        max_retries = 5
        create_body = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": self.model,
                "prefix": "hakusai",
                "url": oss_url,
                "language_hints": ["zh"],
            },
        }
        create_headers = {**headers, "Content-Type": "application/json"}

        for attempt in range(max_retries):
            try:
                async with session.post(
                    _DASHSCOPE_CUSTOMIZATION_URL, headers=create_headers, json=create_body
                ) as resp:
                    response_text = await resp.text()
                    if resp.status == 429:
                        wait = 2 ** attempt
                        logger.warning(f"创建克隆声音被限流 (429)，{wait}s 后重试...")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(wait)
                            continue
                        self._set_clone_failed(f"创建克隆声音失败: 请求过于频繁，请稍后重试。{response_text[:300]}")
                        return None
                    if resp.status != 200:
                        err = f"创建克隆声音失败: HTTP {resp.status} - {response_text[:500]}"
                        logger.error(err)
                        self._set_clone_failed(err)
                        return None
                    try:
                        create_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        err = f"创建克隆声音返回非 JSON: {response_text[:500]}"
                        logger.error(err)
                        self._set_clone_failed(err)
                        return None

                voice_id = create_data.get("output", {}).get("voice_id", "")
                if not voice_id:
                    err = f"创建克隆声音返回数据异常: {response_text[:500]}"
                    logger.error(err)
                    self._set_clone_failed(err)
                    return None

                logger.info(f"克隆声音创建中，voice_id: {voice_id}")
                return voice_id

            except Exception as e:
                logger.error(f"创建克隆声音异常: {e}")
                if attempt == max_retries - 1:
                    self._set_clone_failed(f"创建克隆声音失败: {str(e)}")
                    return None
                await asyncio.sleep(2 ** attempt)
        return None

    async def _poll_voice_status(
        self, session: aiohttp.ClientSession, headers: Dict[str, str], voice_id: str
    ) -> bool:
        """
        轮询声音克隆状态，直到成功或失败

        Args:
            session: aiohttp 会话
            headers: 请求头
            voice_id: 音色 ID

        Returns:
            是否克隆成功
        """
        max_retries = 60
        poll_interval = 5
        query_body = {
            "model": "voice-enrollment",
            "input": {
                "action": "query_voice",
                "voice_id": voice_id,
            },
        }
        query_headers = {**headers, "Content-Type": "application/json"}

        for i in range(max_retries):
            await asyncio.sleep(poll_interval)
            try:
                async with session.post(
                    _DASHSCOPE_CUSTOMIZATION_URL, headers=query_headers, json=query_body
                ) as poll_resp:
                    response_text = await poll_resp.text()
                    if poll_resp.status == 429:
                        wait = min(2 ** (i % 6), 30)
                        logger.warning(f"查询声音状态被限流 (429)，{wait}s 后重试...")
                        continue
                    if poll_resp.status != 200:
                        logger.warning(f"查询声音状态失败: {poll_resp.status} {response_text[:300]}")
                        continue

                    try:
                        poll_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        logger.warning(f"查询声音状态返回非 JSON: {response_text[:300]}")
                        continue

                    status = poll_data.get("output", {}).get("status", "")
                    logger.info(f"声音克隆状态 ({i + 1}/{max_retries}): {status}")

                    if status == "OK":
                        return True
                    elif status in ("FAILED", "ERROR", "UNDEPLOYED"):
                        err = f"声音克隆失败，状态: {status} - {response_text[:500]}"
                        logger.error(err)
                        self._set_clone_failed(err)
                        return False

            except Exception as e:
                logger.warning(f"查询声音状态异常: {e}")
                continue

        logger.error("声音克隆超时")
        self._set_clone_failed("声音克隆失败或超时，请稍后重试")
        return False

    # ==================== 语音复刻公共接口 ====================

    async def clone_voice(self, ref_audio: Optional[str] = None) -> Optional[str]:
        """
        执行语音复刻（公共异步接口）

        Args:
            ref_audio: 参考音频路径，默认使用配置中的路径

        Returns:
            克隆成功返回 voice_id，失败返回 None
        """
        if ref_audio:
            self.ref_audio = ref_audio

        if not self.api_key:
            self._set_clone_failed("语音复刻需要 DashScope API Key")
            return None

        if not os.path.exists(self.ref_audio):
            self._set_clone_failed(f"参考音频文件不存在: {self.ref_audio}")
            return None

        # 直接在当前事件循环中执行
        connector = self._build_connector()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        self._clone_status = "cloning"
        self._clone_error = ""
        self._save_clone_status("cloning")

        async with aiohttp.ClientSession(
            connector=connector, timeout=aiohttp.ClientTimeout(total=600)
        ) as session:
            file_id = await self._upload_ref_audio(session, headers)
            if not file_id:
                self._set_clone_failed("上传参考音频失败，请检查网络或 API Key 是否有效")
                return None

            oss_url = await self._get_file_url(session, headers, file_id)
            if not oss_url:
                self._set_clone_failed("获取文件下载 URL 失败")
                return None

            voice_id = await self._create_voice(session, headers, oss_url)
            if not voice_id:
                self._set_clone_failed("创建克隆声音失败")
                return None

            success = await self._poll_voice_status(session, headers, voice_id)
            if success:
                self.voice_id = voice_id
                self._clone_complete = True
                self._clone_status = "completed"
                self._clone_error = ""
                self._save_voice_id(voice_id)
                self._save_clone_status("completed")
                return voice_id
            else:
                self._set_clone_failed("声音克隆失败或超时，请稍后重试")

        return None

    # ==================== 辅助方法 ====================

    def _resolve_voice(self, voice: Optional[str] = None) -> Optional[str]:
        """
        解析实际使用的 voice_id

        优先级：传入的 voice > 配置的 voice_id > 默认系统音色

        Args:
            voice: 调用时传入的语音标识

        Returns:
            实际使用的 voice_id，如果无法确定则返回 None
        """
        # 优先使用调用时传入的 voice
        if voice:
            return voice

        # 使用配置中的 voice_id
        if self.voice_id:
            return self.voice_id

        # 检查模型是否支持系统默认音色
        if self.model not in _MODELS_REQUIRING_CLONE:
            logger.debug(f"未配置 voice_id，使用默认系统音色: {_DEFAULT_SYSTEM_VOICE}")
            return _DEFAULT_SYSTEM_VOICE

        # v3.5 系列模型必须使用复刻音色
        return None

    def _build_connector(self) -> Optional[aiohttp.TCPConnector]:
        """
        构建 aiohttp 连接器（处理 SSL 问题）

        Returns:
            TCPConnector 实例
        """
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        return aiohttp.TCPConnector(ssl=ssl_ctx)

    def _load_cached_voice_id(self) -> str:
        """
        从本地缓存加载已克隆的 voice_id

        Returns:
            缓存的 voice_id 或空字符串
        """
        if not os.path.exists(_VOICE_ID_CACHE_PATH):
            return ""
        try:
            with open(_VOICE_ID_CACHE_PATH, "r", encoding="utf-8") as f:
                cached_id = f.read().strip()
            if cached_id and "hakusai" in cached_id:
                return cached_id
        except Exception as e:
            logger.warning(f"读取 voice_id 缓存文件失败: {e}")
        return ""

    def _save_voice_id(self, voice_id: str):
        """
        保存 voice_id 到本地缓存文件

        Args:
            voice_id: 要缓存的 voice_id
        """
        try:
            os.makedirs(os.path.dirname(_VOICE_ID_CACHE_PATH), exist_ok=True)
            with open(_VOICE_ID_CACHE_PATH, "w", encoding="utf-8") as f:
                f.write(voice_id)
            logger.info(f"voice_id 已缓存到: {_VOICE_ID_CACHE_PATH}")
        except Exception as e:
            logger.warning(f"保存 voice_id 缓存失败: {e}")

    def _save_clone_status(self, status: str, error: str = ""):
        """
        保存语音复刻状态到本地文件
        """
        try:
            os.makedirs(os.path.dirname(_VOICE_STATUS_PATH), exist_ok=True)
            with open(_VOICE_STATUS_PATH, "w", encoding="utf-8") as f:
                f.write(status)
            if error:
                with open(_VOICE_ERROR_PATH, "w", encoding="utf-8") as f:
                    f.write(error)
            elif os.path.exists(_VOICE_ERROR_PATH):
                os.remove(_VOICE_ERROR_PATH)
            logger.info(f"语音复刻状态: {status}")
        except Exception as e:
            logger.warning(f"保存语音复刻状态失败: {e}")

    def _set_clone_failed(self, error: str):
        """设置复刻失败状态"""
        self._clone_status = "failed"
        self._clone_error = error
        self._save_clone_status("failed", error)
        logger.error(f"语音复刻失败: {error}")

    def get_clone_status(self) -> Dict[str, Any]:
        """
        获取语音复刻状态

        Returns:
            {status, voice_id?, error?}
        """
        # 优先从内存返回
        result = {"status": self._clone_status}
        if self._clone_status == "completed":
            result["voice_id"] = self.voice_id
        elif self._clone_status == "failed":
            result["error"] = self._clone_error
        return result

    @staticmethod
    def get_instruction_for_emotion(emotion) -> Optional[str]:
        """
        根据情绪类型获取对应的语气指令

        Args:
            emotion: EmotionType 枚举值

        Returns:
            语气指令字符串，如果无匹配则返回 None
        """
        # 支持的情感值：neutral, fearful, angry, sad, surprised, happy, disgusted
        emotion_instruction_map = {
            "HAPPY": "你正在进行闲聊对话，你说话的情感是happy。",
            "EXCITED": "你正在进行闲聊对话，你说话的情感是happy。",
            "SAD": "你正在进行闲聊对话，你说话的情感是sad。",
            "TSUNDERE": "你正在进行闲聊对话，你说话的情感是angry。",
            "TENDER": "你正在进行闲聊对话，你说话的情感是neutral。",
            "ANGRY": "你正在进行闲聊对话，你说话的情感是angry。",
            "CONFUSED": "你正在进行闲聊对话，你说话的情感是surprised。",
            "BORED": "你正在进行闲聊对话，你说话的情感是neutral。",
        }

        # 支持枚举类型和字符串类型
        emotion_name = emotion.name if hasattr(emotion, "name") else str(emotion)
        return emotion_instruction_map.get(emotion_name)

    @classmethod
    def list_supported_models(cls) -> List[str]:
        """
        列出支持的模型

        Returns:
            模型名称列表
        """
        return SUPPORTED_MODELS.copy()

    async def close(self):
        """关闭 TTS 引擎"""
        self._initialized = False
        logger.debug("CosyVoice TTS closed")
