"""
阿里百炼 CosyVoice TTS 封装类
支持声音复刻、声音设计和语音合成

功能:
- 声音复刻: 从音频样本克隆声音
- 声音设计: 从文本描述生成音色
- 语音合成: 文本转语音（支持流式）
- 音色管理: 查询/更新/删除音色

支持的模型:
- cosyvoice-v3-flash: 快速版，支持多语种
- cosyvoice-v3-plus: 高质量版
- cosyvoice-v3.5-flash: 最新快速版（仅北京地域）
- cosyvoice-v3.5-plus: 最新高质量版（仅北京地域）
"""
import os
import threading
import asyncio
import tempfile
import queue
import time
import base64
import requests
from typing import Optional, Generator, AsyncGenerator, List, Dict, Any
from pathlib import Path

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

_GLOBAL_COSYVOICE_TTS = None
_COSYVOICE_TTS_LOCK = threading.Lock()

DEFAULT_VOICES = {
    "cosyvoice-v1": "longwan",
    "cosyvoice-v2": "longxiaochun_v2",
    "cosyvoice-v3-flash": "longanyang",
    "cosyvoice-v3-plus": "longanyang",
    "cosyvoice-v3.5-flash": None,
    "cosyvoice-v3.5-plus": None,
}

SUPPORTED_LANGUAGES = {
    "cosyvoice-v1": ["zh", "en"],
    "cosyvoice-v2": ["zh", "en"],
    "cosyvoice-v3-flash": ["zh", "en", "ja", "ko", "fr", "de", "ru", "pt", "th", "id", "vi"],
    "cosyvoice-v3-plus": ["zh", "en", "ja", "ko", "fr", "de", "ru"],
    "cosyvoice-v3.5-flash": ["zh", "en", "ja", "ko", "fr", "de", "ru", "pt", "th", "id", "vi"],
    "cosyvoice-v3.5-plus": ["zh", "en", "ja", "ko", "fr", "de", "ru", "pt", "th", "id", "vi"],
}

API_URLS = {
    "beijing": {
        "websocket": "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
        "http": "https://dashscope.aliyuncs.com/api/v1",
        "customization": "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
    },
    "singapore": {
        "websocket": "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference",
        "http": "https://dashscope-intl.aliyuncs.com/api/v1",
        "customization": "https://dashscope-intl.aliyuncs.com/api/v1/services/audio/tts/customization"
    }
}


class CosyVoiceTTS:
    """阿里百炼CosyVoice TTS封装类（支持声音复刻、声音设计和流式输出）"""

    def __new__(cls):
        global _GLOBAL_COSYVOICE_TTS

        if _GLOBAL_COSYVOICE_TTS is not None:
            return _GLOBAL_COSYVOICE_TTS

        with _COSYVOICE_TTS_LOCK:
            if _GLOBAL_COSYVOICE_TTS is None:
                instance = super().__new__(cls)
                instance._initialize()
                _GLOBAL_COSYVOICE_TTS = instance

        return _GLOBAL_COSYVOICE_TTS

    def _initialize(self):
        """初始化CosyVoice TTS"""
        try:
            self.api_key = BASE_CONFIG.get("DASHSCOPE_API_KEY", "")
            if not self.api_key:
                logger.warning("未配置DASHSCOPE_API_KEY，CosyVoice TTS功能将受限")

            self.model = BASE_CONFIG.get("COSYVOICE_MODEL", "cosyvoice-v3-flash")
            self.voice_id = BASE_CONFIG.get("COSYVOICE_VOICE_ID", "")
            self.ref_audio_url = BASE_CONFIG.get("COSYVOICE_REF_AUDIO_URL", "")
            self.language_hints = BASE_CONFIG.get("COSYVOICE_LANGUAGE_HINTS", "zh")
            self.streaming_enabled = BASE_CONFIG.get("COSYVOICE_STREAMING", True)
            self.format = BASE_CONFIG.get("COSYVOICE_FORMAT", "wav")
            self.sample_rate = BASE_CONFIG.get("COSYVOICE_SAMPLE_RATE", 22050)
            self.voice_prefix = BASE_CONFIG.get("COSYVOICE_VOICE_PREFIX", "custom")

            self._dashscope = None
            self._region = "beijing"

            if self.api_key:
                try:
                    import dashscope
                    dashscope.api_key = self.api_key
                    dashscope.base_websocket_api_url = API_URLS["beijing"]["websocket"]
                    dashscope.base_http_api_url = API_URLS["beijing"]["http"]
                    self._dashscope = dashscope
                    logger.info("✓ 百炼SDK初始化成功")
                except ImportError:
                    logger.warning("未安装dashscope SDK，请运行: pip install dashscope")

            if not self.voice_id:
                default_voice = DEFAULT_VOICES.get(self.model)
                if default_voice:
                    self.voice_id = default_voice
                    logger.info(f"使用默认音色: {self.voice_id}")
                else:
                    logger.info(f"模型 {self.model} 无预设音色，需要配置复刻音色ID")

            supported = SUPPORTED_LANGUAGES.get(self.model, ["zh", "en"])
            logger.info(f"✓ CosyVoice TTS初始化完成")
            logger.info(f"  模型: {self.model}")
            logger.info(f"  音色: {self.voice_id or '未配置'}")
            logger.info(f"  支持语种: {', '.join(supported)}")
            logger.info(f"  流式输出: {'启用' if self.streaming_enabled else '禁用'}")

        except Exception as e:
            logger.error(f"初始化CosyVoice TTS失败: {e}")

    def _get_audio_format(self):
        """获取音频格式枚举"""
        try:
            from dashscope.audio.tts_v2 import AudioFormat
            
            format_map = {
                "wav_8000": AudioFormat.WAV_8000HZ_MONO_16BIT,
                "wav_16000": AudioFormat.WAV_16000HZ_MONO_16BIT,
                "wav_22050": AudioFormat.WAV_22050HZ_MONO_16BIT,
                "wav_24000": AudioFormat.WAV_24000HZ_MONO_16BIT,
                "wav_44100": AudioFormat.WAV_44100HZ_MONO_16BIT,
                "wav_48000": AudioFormat.WAV_48000HZ_MONO_16BIT,
                "mp3_8000": AudioFormat.MP3_8000HZ_MONO_128KBPS,
                "mp3_16000": AudioFormat.MP3_16000HZ_MONO_128KBPS,
                "mp3_22050": AudioFormat.MP3_22050HZ_MONO_256KBPS,
                "mp3_24000": AudioFormat.MP3_24000HZ_MONO_256KBPS,
                "pcm_8000": AudioFormat.PCM_8000HZ_MONO_16BIT,
                "pcm_16000": AudioFormat.PCM_16000HZ_MONO_16BIT,
                "pcm_22050": AudioFormat.PCM_22050HZ_MONO_16BIT,
                "pcm_24000": AudioFormat.PCM_24000HZ_MONO_16BIT,
            }
            
            key = f"{self.format.lower()}_{self.sample_rate}"
            return format_map.get(key, AudioFormat.WAV_22050HZ_MONO_16BIT)
        except Exception:
            return None

    # ==================== 声音复刻 API ====================

    def create_voice_from_url(
        self, 
        audio_url: str, 
        prefix: str = None,
        language_hints: str = None,
        max_prompt_audio_length: float = 10.0,
        enable_preprocess: bool = False
    ) -> Optional[str]:
        """从公网URL创建复刻音色
        
        Args:
            audio_url: 公网可访问的音频文件URL（10-20秒）
            prefix: 音色ID前缀（仅允许数字和小写字母，不超过10个字符）
            language_hints: 语种提示 (zh/ja/en/ko/fr/de/ru/pt/th/id/vi)
            max_prompt_audio_length: 参考音频最大时长（秒），范围3.0-30.0
            enable_preprocess: 是否开启音频预处理（降噪、增强等）
            
        Returns:
            音色ID，失败返回None
        """
        try:
            if not self._dashscope:
                logger.error("dashscope SDK未初始化")
                return None

            from dashscope.audio.tts_v2 import VoiceEnrollmentService

            service = VoiceEnrollmentService()
            
            prefix = prefix or self.voice_prefix
            lang_hints = [language_hints or self.language_hints]
            
            logger.info(f"创建复刻音色...")
            logger.info(f"  模型: {self.model}")
            logger.info(f"  前缀: {prefix}")
            logger.info(f"  语种: {lang_hints[0]}")
            logger.info(f"  音频URL: {audio_url[:50]}...")
            
            voice_id = service.create_voice(
                target_model=self.model,
                prefix=prefix,
                url=audio_url,
                language_hints=lang_hints,
                max_prompt_audio_length=max_prompt_audio_length,
                enable_preprocess=enable_preprocess
            )
            
            logger.info(f"音色创建请求已提交: {voice_id}")
            logger.info("等待音色处理完成...")
            
            max_attempts = 30
            for attempt in range(max_attempts):
                voice_info = service.query_voice(voice_id=voice_id)
                status = voice_info.get("status")
                logger.info(f"  状态查询 ({attempt+1}/{max_attempts}): {status}")
                
                if status == "OK":
                    logger.info(f"✓ 音色创建成功: {voice_id}")
                    self.voice_id = voice_id
                    return voice_id
                elif status == "UNDEPLOYED":
                    logger.error("音色创建失败，请检查音频质量")
                    return None
                
                time.sleep(2)
            
            logger.warning("音色创建超时，请稍后查询状态")
            return voice_id

        except Exception as e:
            logger.error(f"创建音色失败: {e}")
            return None

    def create_voice_from_file(self, audio_path: str, prefix: str = None) -> Optional[str]:
        """从本地文件创建复刻音色（需要上传到公网）
        
        注意：此方法需要先将文件上传到公网可访问的位置
        建议使用阿里云OSS或其他云存储服务
        
        Args:
            audio_path: 本地音频文件路径
            prefix: 音色ID前缀
            
        Returns:
            音色ID，失败返回None
        """
        logger.warning("本地文件需要先上传到公网可访问的URL")
        logger.warning("建议使用阿里云OSS或其他云存储服务")
        logger.info(f"参考音频路径: {audio_path}")
        
        if not os.path.exists(audio_path):
            logger.error(f"音频文件不存在: {audio_path}")
            return None
            
        logger.info("请将音频上传到OSS后使用 create_voice_from_url() 方法")
        return None

    # ==================== 声音设计 API ====================

    def design_voice(
        self,
        voice_prompt: str,
        preview_text: str = "大家好，欢迎收听。",
        prefix: str = None,
        language_hints: str = "zh",
        sample_rate: int = 24000,
        response_format: str = "wav"
    ) -> tuple[Optional[str], Optional[bytes]]:
        """通过文本描述设计音色
        
        Args:
            voice_prompt: 声音描述（如："沉稳的中年男性播音员，音色低沉浑厚，富有磁性"）
            preview_text: 试听文本
            prefix: 音色ID前缀
            language_hints: 语种提示 (zh/en)
            sample_rate: 采样率 (16000/24000/48000)
            response_format: 音频格式 (pcm/wav/mp3)
            
        Returns:
            (音色ID, 预览音频数据)，失败返回 (None, None)
        """
        try:
            if not self.api_key:
                logger.error("未配置API Key")
                return None, None

            prefix = prefix or self.voice_prefix
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "voice-enrollment",
                "input": {
                    "action": "create_voice",
                    "target_model": self.model,
                    "voice_prompt": voice_prompt,
                    "preview_text": preview_text,
                    "prefix": prefix,
                    "language_hints": [language_hints]
                },
                "parameters": {
                    "sample_rate": sample_rate,
                    "response_format": response_format
                }
            }
            
            url = API_URLS[self._region]["customization"]
            
            logger.info(f"设计音色...")
            logger.info(f"  描述: {voice_prompt[:50]}...")
            logger.info(f"  试听文本: {preview_text}")
            
            response = requests.post(url, headers=headers, json=data, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                output = result.get("output") or {}
                voice_id = output.get("voice_id")
                preview_audio = output.get("preview_audio") or {}
                base64_audio = preview_audio.get("data")

                if not voice_id or not base64_audio:
                    logger.error(f"音色设计返回数据不完整: output={output}")
                    return None, None

                audio_bytes = base64.b64decode(base64_audio)
                
                logger.info(f"✓ 音色设计成功: {voice_id}")
                self.voice_id = voice_id
                return voice_id, audio_bytes
            else:
                logger.error(f"音色设计失败: {response.status_code} - {response.text}")
                return None, None
                
        except Exception as e:
            logger.error(f"设计音色失败: {e}")
            return None, None

    # ==================== 音色管理 API ====================

    def list_voices(self, prefix: str = None, page_index: int = 0, page_size: int = 10) -> List[dict]:
        """查询已创建的音色列表
        
        Args:
            prefix: 音色前缀筛选
            page_index: 页码索引
            page_size: 每页数量
            
        Returns:
            音色列表
        """
        try:
            if not self._dashscope:
                logger.error("dashscope SDK未初始化")
                return []

            from dashscope.audio.tts_v2 import VoiceEnrollmentService

            service = VoiceEnrollmentService()
            voices = service.list_voices(prefix=prefix, page_index=page_index, page_size=page_size)
            
            return voices

        except Exception as e:
            logger.error(f"查询音色列表失败: {e}")
            return []

    def query_voice(self, voice_id: str) -> Optional[dict]:
        """查询特定音色详情
        
        Args:
            voice_id: 音色ID
            
        Returns:
            音色详情
        """
        try:
            if not self._dashscope:
                logger.error("dashscope SDK未初始化")
                return None

            from dashscope.audio.tts_v2 import VoiceEnrollmentService

            service = VoiceEnrollmentService()
            voice_info = service.query_voice(voice_id=voice_id)
            
            return voice_info

        except Exception as e:
            logger.error(f"查询音色失败: {e}")
            return None

    def update_voice(self, voice_id: str, audio_url: str) -> bool:
        """更新音色（仅限声音复刻）
        
        Args:
            voice_id: 音色ID
            audio_url: 新的音频文件URL
            
        Returns:
            是否成功
        """
        try:
            if not self._dashscope:
                logger.error("dashscope SDK未初始化")
                return False

            from dashscope.audio.tts_v2 import VoiceEnrollmentService

            service = VoiceEnrollmentService()
            service.update_voice(voice_id=voice_id, url=audio_url)
            
            logger.info(f"音色更新请求已提交: {voice_id}")
            return True

        except Exception as e:
            logger.error(f"更新音色失败: {e}")
            return False

    def delete_voice(self, voice_id: str) -> bool:
        """删除音色
        
        Args:
            voice_id: 音色ID
            
        Returns:
            是否成功
        """
        try:
            if not self._dashscope:
                logger.error("dashscope SDK未初始化")
                return False

            from dashscope.audio.tts_v2 import VoiceEnrollmentService

            service = VoiceEnrollmentService()
            service.delete_voice(voice_id=voice_id)
            
            logger.info(f"音色删除请求已提交: {voice_id}")
            return True

        except Exception as e:
            logger.error(f"删除音色失败: {e}")
            return False

    # ==================== 语音合成 API ====================

    def generate_audio(self, text: str, voice_id: str = None) -> Optional[bytes]:
        """生成音频数据（非流式）

        Args:
            text: 要合成的文本
            voice_id: 音色ID（可选，默认使用已配置的音色）

        Returns:
            音频字节数据
        """
        try:
            if not self._dashscope:
                logger.error("dashscope SDK未初始化")
                return None

            if not text or not text.strip():
                logger.warning("空文本，跳过TTS生成")
                return None

            from dashscope.audio.tts_v2 import SpeechSynthesizer

            target_voice = voice_id or self.voice_id
            if not target_voice:
                logger.error("未配置音色ID，请先创建音色或配置COSYVOICE_VOICE_ID")
                return None

            audio_format = self._get_audio_format()

            logger.debug(f"生成CosyVoice音频: 文本='{text[:20]}...', 音色={target_voice}")

            if audio_format:
                synthesizer = SpeechSynthesizer(
                    model=self.model,
                    voice=target_voice,
                    format=audio_format
                )
            else:
                synthesizer = SpeechSynthesizer(
                    model=self.model,
                    voice=target_voice
                )

            audio_data = synthesizer.call(text)

            if audio_data:
                logger.debug(f"CosyVoice音频生成成功，大小: {len(audio_data)} 字节")
                return audio_data
            else:
                logger.error("CosyVoice音频生成失败")
                return None

        except Exception as e:
            logger.error(f"生成CosyVoice音频失败: {e}")
            return None

    def generate_audio_stream(self, text: str, voice_id: str = None) -> Generator[bytes, None, None]:
        """流式生成音频数据

        Args:
            text: 要合成的文本
            voice_id: 音色ID（可选）

        Yields:
            音频数据块
        """
        try:
            if not self._dashscope:
                logger.error("dashscope SDK未初始化")
                return

            if not text or not text.strip():
                logger.warning("空文本，跳过TTS生成")
                return

            from dashscope.audio.tts_v2 import SpeechSynthesizer, ResultCallback

            target_voice = voice_id or self.voice_id
            if not target_voice:
                logger.error("未配置音色ID")
                return

            audio_format = self._get_audio_format()
            audio_queue = queue.Queue()
            completed = threading.Event()

            class StreamCallback(ResultCallback):
                def on_open(self):
                    pass

                def on_data(self, data: bytes):
                    audio_queue.put(data)

                def on_complete(self):
                    completed.set()

                def on_error(self, message: str):
                    logger.error(f"流式合成错误: {message}")
                    completed.set()

                def on_close(self):
                    pass

            callback = StreamCallback()

            if audio_format:
                synthesizer = SpeechSynthesizer(
                    model=self.model,
                    voice=target_voice,
                    format=audio_format,
                    callback=callback
                )
            else:
                synthesizer = SpeechSynthesizer(
                    model=self.model,
                    voice=target_voice,
                    callback=callback
                )

            logger.debug(f"流式生成CosyVoice音频: 文本='{text[:20]}...'")

            synthesizer.call(text)

            while not completed.is_set() or not audio_queue.empty():
                try:
                    chunk = audio_queue.get(timeout=0.1)
                    if chunk:
                        yield chunk
                except queue.Empty:
                    continue

        except Exception as e:
            logger.error(f"流式生成CosyVoice音频失败: {e}")

    async def generate_audio_async(self, text: str, voice_id: str = None) -> Optional[bytes]:
        """异步生成音频数据"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.generate_audio,
            text, voice_id
        )

    async def generate_audio_stream_async(self, text: str, voice_id: str = None) -> AsyncGenerator[bytes, None]:
        """异步流式生成音频数据"""
        loop = asyncio.get_event_loop()
        q = queue.Queue()

        def producer():
            try:
                for chunk in self.generate_audio_stream(text, voice_id):
                    q.put(chunk)
            finally:
                q.put(None)

        await loop.run_in_executor(None, producer)

        while True:
            chunk = await loop.run_in_executor(None, q.get)
            if chunk is None:
                break
            yield chunk

    # ==================== 工具方法 ====================

    def save_to_file(self, audio_data: bytes, file_path: str) -> bool:
        """保存音频到文件"""
        try:
            with open(file_path, "wb") as f:
                f.write(audio_data)
            logger.debug(f"CosyVoice音频已保存到: {file_path}")
            return True
        except Exception as e:
            logger.error(f"保存CosyVoice音频失败: {e}")
            return False

    def play_audio(self, audio_data: bytes) -> bool:
        """播放音频"""
        try:
            if not BASE_CONFIG.get("ENABLE_TTS_AUDIO_OUTPUT", True):
                return True

            import sounddevice as sd
            import soundfile as sf

            ext = "mp3" if self.format.lower() == "mp3" else "wav"
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_file_path = temp_file.name

            try:
                data, samplerate = sf.read(temp_file_path)
                logger.debug(f"播放CosyVoice音频，时长: {len(data)/samplerate:.2f}秒")
                sd.play(data, samplerate)
                sd.wait()
                return True
            finally:
                os.unlink(temp_file_path)

        except Exception as e:
            logger.error(f"播放CosyVoice音频失败: {e}")
            return False

    async def generate_and_play(self, text: str, speed: float = None, volume: float = None, pitch: float = None) -> Optional[str]:
        """异步生成并播放音频"""
        try:
            if self.streaming_enabled:
                return await self._stream_and_play(text)
            else:
                return await self._generate_and_play_normal(text)

        except Exception as e:
            logger.error(f"生成并播放CosyVoice音频失败: {e}")
            return None

    async def _generate_and_play_normal(self, text: str) -> Optional[str]:
        """非流式生成并播放"""
        audio_data = await self.generate_audio_async(text)

        if not audio_data:
            return None

        ext = "mp3" if self.format.lower() == "mp3" else "wav"
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
            temp_file_path = f.name

        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                self.save_to_file,
                audio_data, temp_file_path
            )

            await asyncio.get_event_loop().run_in_executor(
                None,
                self.play_audio,
                audio_data
            )

            return temp_file_path
        finally:
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass

    async def _stream_and_play(self, text: str) -> Optional[str]:
        """流式生成并播放"""
        temp_file_path = None
        try:
            audio_chunks = []

            async for chunk in self.generate_audio_stream_async(text):
                if chunk:
                    audio_chunks.append(chunk)

            if not audio_chunks:
                return None

            ext = "mp3" if self.format.lower() == "mp3" else "wav"
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                temp_file_path = f.name

            with open(temp_file_path, "wb") as f:
                for chunk in audio_chunks:
                    f.write(chunk)

            if BASE_CONFIG.get("ENABLE_TTS_AUDIO_OUTPUT", True):
                import soundfile as sf
                import sounddevice as sd
                data, sr = sf.read(temp_file_path)
                logger.debug(f"播放流式CosyVoice音频，时长: {len(data)/sr:.2f}秒")

                # Run blocking sd.play/sd.wait in a daemon thread to avoid
                # blocking the asyncio event loop
                def _play_in_thread(audio_data, sample_rate):
                    sd.play(audio_data, sample_rate)
                    sd.wait()

                thread = threading.Thread(
                    target=_play_in_thread, args=(data, sr), daemon=True
                )
                thread.start()

            return temp_file_path

        except Exception as e:
            logger.error(f"流式播放失败: {e}")
            return None
        finally:
            if temp_file_path:
                try:
                    os.unlink(temp_file_path)
                except OSError:
                    pass

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._dashscope is not None

    def get_voice_id(self) -> str:
        """获取当前音色ID"""
        return self.voice_id

    def set_voice_id(self, voice_id: str):
        """设置音色ID"""
        self.voice_id = voice_id
        logger.info(f"音色ID已更新为: {voice_id}")

    def get_supported_languages(self) -> List[str]:
        """获取当前模型支持的语种"""
        return SUPPORTED_LANGUAGES.get(self.model, ["zh", "en"])
