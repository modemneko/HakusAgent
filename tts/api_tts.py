import asyncio
import threading
import os
import tempfile
from typing import Optional, Dict, Any

from hakus.models import GeminiModel, QwenModel
from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

# 全局API TTS单例
_GLOBAL_API_TTS = None
_API_TTS_LOCK = threading.Lock()

class ApiTTS:
    """API模式TTS封装类（单例模式）"""
    
    def __new__(cls):
        global _GLOBAL_API_TTS
        
        # 快速路径：如果已初始化，直接返回
        if _GLOBAL_API_TTS is not None:
            return _GLOBAL_API_TTS
        
        # 进入关键区域，确保线程安全
        with _API_TTS_LOCK:
            # 双重检查锁定
            if _GLOBAL_API_TTS is None:
                instance = super().__new__(cls)
                instance._initialize()
                _GLOBAL_API_TTS = instance
        
        return _GLOBAL_API_TTS
    
    def _initialize(self):
        """初始化API TTS"""
        try:
            # 获取API类型
            self.api_type = BASE_CONFIG.get("TTS_API_TYPE", "gemini")
            
            # 根据API类型初始化对应的模型
            if self.api_type == "qwen":
                self.model = QwenModel()
            else:
                # 默认使用Gemini模型
                self.api_type = "gemini"
                self.model = GeminiModel()
            
            logger.info(f"API TTS初始化完成，使用模型: {self.api_type}")
            
        except Exception as e:
            logger.error(f"初始化API TTS失败: {e}")
            raise
    
    async def generate_audio(self, text: str) -> Optional[str]:
        """生成音频文件
        
        Args:
            text: 要转换为语音的文本
            
        Returns:
            音频文件路径，如果生成失败则返回None
        """
        try:
            logger.debug(f"使用{self.api_type} API生成TTS音频: {text[:20]}...")
            
            # 根据不同的API类型生成音频
            if self.api_type == "qwen":
                return await self._generate_with_qwen(text)
            elif self.api_type == "gemini":
                return await self._generate_with_gemini(text)
            else:
                logger.error(f"不支持的TTS API类型: {self.api_type}")
                return None
                
        except Exception as e:
            logger.error(f"生成API TTS音频失败: {e}")
            return None
    
    async def _generate_with_qwen(self, text: str) -> Optional[str]:
        """使用Qwen API生成音频"""
        try:
            logger.info(f"使用Qwen API生成TTS音频: {text[:20]}...")
            
            import dashscope
            from dashscope.audio.tts_v2 import SpeechSynthesizer
            
            # 使用 DashScope CosyVoice API
            synthesizer = SpeechSynthesizer(
                model=BASE_CONFIG.get("COSYVOICE_MODEL", "cosyvoice-v2"),
                voice=BASE_CONFIG.get("TTS_VOICE_ID", "longxiaochun"),
            )
            
            audio = synthesizer.call(text)
            
            if audio is None:
                logger.error("Qwen TTS API 返回空音频")
                return None
            
            # 写入临时文件
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio)
                temp_file_path = f.name
            
            return temp_file_path
            
        except ImportError:
            logger.warning("dashscope 未安装，Qwen TTS 不可用，请安装: pip install dashscope")
            return None
        except Exception as e:
            logger.error(f"使用Qwen API生成音频失败: {e}")
            return None
    
    async def _generate_with_gemini(self, text: str) -> Optional[str]:
        """使用Gemini API生成音频"""
        try:
            logger.info(f"使用Gemini API生成TTS音频: {text[:20]}...")
            
            import google.generativeai as genai
            
            api_key = BASE_CONFIG.get("GEMINI_API_KEY", "")
            if not api_key:
                logger.error("GEMINI_API_KEY 未配置")
                return None
            
            genai.configure(api_key=api_key)
            
            # 使用 Gemini 的 TTS 能力（通过 generate_content）
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(
                f"请将以下文本转为语音音素描述: {text}",
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="audio/wav",
                ),
            )
            
            if not response or not hasattr(response, "candidates"):
                logger.error("Gemini TTS API 返回空响应")
                return None
            
            # 提取音频数据
            audio_data = None
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, "inline_data") and part.inline_data:
                            audio_data = part.inline_data.data
                            break
            
            if audio_data is None:
                logger.error("Gemini TTS 响应中未找到音频数据")
                return None
            
            # 写入临时文件
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_data)
                temp_file_path = f.name
            
            return temp_file_path
            
        except ImportError:
            logger.warning("google-generativeai 未安装，Gemini TTS 不可用")
            return None
        except Exception as e:
            logger.error(f"使用Gemini API生成音频失败: {e}")
            return None
    
    async def generate_and_play(self, text: str) -> Optional[str]:
        """生成并播放音频
        
        Args:
            text: 要转换为语音的文本
            
        Returns:
            音频文件路径，如果生成失败则返回None
        """
        try:
            audio_path = await self.generate_audio(text)
            
            if audio_path and BASE_CONFIG.get("ENABLE_TTS_AUDIO_OUTPUT", True):
                # 播放音频文件
                import sounddevice as sd
                import soundfile as sf
                
                try:
                    data, samplerate = sf.read(audio_path)
                    logger.debug(f"播放TTS音频，时长: {len(data)/samplerate:.2f}秒")
                    sd.play(data, samplerate)
                    sd.wait()
                except Exception as e:
                    logger.error(f"播放TTS音频失败: {e}")
            
            return audio_path
            
        except Exception as e:
            logger.error(f"生成并播放API TTS音频失败: {e}")
            return None