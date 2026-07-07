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
            self.api_type = BASE_CONFIG["TTS_API_TYPE"]
            
            # 根据API类型初始化对应的模型
            if self.api_type == "qwen":
                self.model = QwenModel()
            else:
                # 默认使用Gemini模型
                self.api_type = "gemini"
                self.model = GeminiModel()
            
            logger.info(f"✓ API TTS初始化完成，使用模型: {self.api_type}")
            
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
            # 使用Qwen的TTS API
            # 注意：这里需要根据实际的Qwen API进行调整
            # 目前Qwen API可能通过调用DashScope的TTS服务来实现
            logger.info(f"使用Qwen API生成TTS音频: {text[:20]}...")
            
            # 这里是一个简化的实现，实际应该调用Qwen的TTS API
            # 例如：使用阿里云DashScope的TTS服务
            # import dashscope
            # response = dashscope.audio.tts.SpeechSynthesis.call(
            #     model='sambert-zhichu-v1',
            #     text=text,
            #     voice='zhichu-emo',
            #     format='wav'
            # )
            
            # 创建临时文件作为占位符
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_file_path = f.name
            
            return temp_file_path
            
        except Exception as e:
            logger.error(f"使用Qwen API生成音频失败: {e}")
            return None
    
    async def _generate_with_gemini(self, text: str) -> Optional[str]:
        """使用Gemini API生成音频"""
        try:
            # 使用Gemini的TTS API
            # 注意：这里需要根据实际的Gemini API进行调整
            logger.info(f"使用Gemini API生成TTS音频: {text[:20]}...")
            
            # 这里是一个简化的实现，实际应该调用Gemini的TTS API
            # 例如：使用Google Cloud Text-to-Speech API
            # from google.cloud import texttospeech_v1beta1 as texttospeech
            # client = texttospeech.TextToSpeechClient()
            # input_text = texttospeech.SynthesisInput(text=text)
            # voice = texttospeech.VoiceSelectionParams(
            #     language_code="zh-CN",
            #     ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
            # )
            # audio_config = texttospeech.AudioConfig(
            #     audio_encoding=texttospeech.AudioEncoding.LINEAR16
            # )
            # response = client.synthesize_speech(
            #     input=input_text, voice=voice, audio_config=audio_config
            # )
            
            # 创建临时文件作为占位符
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_file_path = f.name
            
            return temp_file_path
            
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
            
            if audio_path and BASE_CONFIG["ENABLE_TTS_AUDIO_OUTPUT"]:
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
