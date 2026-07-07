"""
HakusAI 2.0 Edge TTS 引擎
使用微软Edge浏览器的在线TTS服务（免费）
"""

import edge_tts
import asyncio
from typing import Optional, Dict, Any, AsyncIterator
import logging

from .base import BaseTTS, TTSResult, register_tts

logger = logging.getLogger(__name__)


@register_tts("edge")
class EdgeTTS(BaseTTS):
    """
    Edge TTS 引擎
    
    使用微软Edge浏览器的在线TTS服务，特点：
    - 免费使用
    - 支持多种中文语音
    - 质量较好
    - 需要网络连接
    """
    
    # 可用的中文语音列表
    CHINESE_VOICES = {
        "xiaoxiao": "zh-CN-XiaoxiaoNeural",      # 晓晓 - 年轻女性
        "xiaoyi": "zh-CN-XiaoyiNeural",          # 晓伊 - 年轻女性
        "yunjian": "zh-CN-YunjianNeural",        # 云健 - 男性新闻
        "yunxi": "zh-CN-YunxiNeural",            # 云希 - 年轻男性
        "yunxia": "zh-CN-YunxiaNeural",          # 云夏 - 年轻男性
        "yunyang": "zh-CN-YunyangNeural",        # 云扬 - 男性新闻
        "liaoning": "zh-CN-liaoning-XiaobeiNeural",  # 辽宁 - 东北话女性
        "shaanxi": "zh-CN-shaanxi-XiaoniNeural",     # 陕西 - 陕西话女性
    }
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化Edge TTS
        
        Args:
            config: 配置字典
                - voice: 语音名称（默认 zh-CN-XiaoxiaoNeural）
                - speed: 语速（默认 1.0）
                - volume: 音量（默认 1.0）
        """
        super().__init__(config)
        
        # 获取语音
        voice = config.get("voice", "zh-CN-XiaoxiaoNeural")
        # 如果传入的是简称，转换为完整名称
        if voice in self.CHINESE_VOICES:
            voice = self.CHINESE_VOICES[voice]
        self.voice = voice
        
        self._communicate: Optional[edge_tts.Communicate] = None
        
    @property
    def provider_name(self) -> str:
        """提供商名称"""
        return "edge"
    
    async def initialize(self):
        """初始化TTS引擎"""
        # Edge TTS 不需要预初始化
        self._initialized = True
        logger.info(f"Edge TTS initialized with voice: {self.voice}")
    
    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs
    ) -> TTSResult:
        """
        合成语音
        
        Args:
            text: 要合成的文本
            voice: 语音名称（可选）
            speed: 语速（可选）
            **kwargs: 其他参数
            
        Returns:
            合成结果
        """
        if not self._initialized:
            await self.initialize()
        
        # 预处理文本
        text = self._preprocess_text(text)
        
        if not text:
            return TTSResult(audio_data=b"", sample_rate=24000)
        
        # 使用指定的语音或默认语音
        use_voice = voice or self.voice
        if use_voice in self.CHINESE_VOICES:
            use_voice = self.CHINESE_VOICES[use_voice]
        
        # 检查缓存
        use_speed = speed or self.speed
        cached_result = self._check_cache(text, use_voice, use_speed)
        if cached_result:
            logger.debug(f"TTS cache hit: {text[:30]}...")
            return cached_result
        
        try:
            # 创建Communicate对象
            # 语速格式: "+50%" 或 "-50%"
            communicate_kwargs = {
                "text": text,
                "voice": use_voice,
            }
            
            if use_speed != 1.0:
                rate_percent = int((use_speed - 1) * 100)
                communicate_kwargs["rate"] = f"{rate_percent:+d}%"
            
            if self.volume != 1.0:
                volume_percent = int((self.volume - 1) * 100)
                communicate_kwargs["volume"] = f"{volume_percent:+d}%"
            
            communicate = edge_tts.Communicate(**communicate_kwargs)
            
            # 收集音频数据
            audio_data = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])
            
            # 转换为bytes
            audio_bytes = bytes(audio_data)
            
            # 保存缓存
            self._save_cache(text, use_voice, use_speed, audio_bytes, "mp3")
            
            logger.info(f"Edge TTS synthesized: {text[:50]}...")
            
            return TTSResult(
                audio_data=audio_bytes,
                sample_rate=24000,  # Edge TTS 输出 24kHz
                format="mp3",
                cached=False
            )
            
        except Exception as e:
            logger.error(f"Edge TTS synthesis failed: {e}")
            raise
    
    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs
    ) -> AsyncIterator[bytes]:
        """
        流式合成语音
        
        Args:
            text: 要合成的文本
            voice: 语音名称
            speed: 语速
            **kwargs: 其他参数
            
        Yields:
            音频数据块
        """
        if not self._initialized:
            await self.initialize()
        
        text = self._preprocess_text(text)
        
        if not text:
            return
        
        use_voice = voice or self.voice
        if use_voice in self.CHINESE_VOICES:
            use_voice = self.CHINESE_VOICES[use_voice]
        
        use_speed = speed or self.speed
        
        try:
            # 语速和音量格式
            communicate_kwargs = {
                "text": text,
                "voice": use_voice,
            }
            
            if use_speed != 1.0:
                rate_percent = int((use_speed - 1) * 100)
                communicate_kwargs["rate"] = f"{rate_percent:+d}%"
            
            if self.volume != 1.0:
                volume_percent = int((self.volume - 1) * 100)
                communicate_kwargs["volume"] = f"{volume_percent:+d}%"
            
            communicate = edge_tts.Communicate(**communicate_kwargs)
            
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
                    
        except Exception as e:
            logger.error(f"Edge TTS stream synthesis failed: {e}")
            raise
    
    @classmethod
    def list_voices(cls) -> Dict[str, str]:
        """
        列出可用的中文语音
        
        Returns:
            语音名称映射
        """
        return cls.CHINESE_VOICES.copy()
    
    async def close(self):
        """关闭TTS引擎"""
        self._initialized = False
        logger.debug("Edge TTS closed")


# 便捷函数
async def list_edge_voices() -> Dict[str, str]:
    """
    列出所有可用的Edge语音
    
    Returns:
        语音列表
    """
    try:
        voices = await edge_tts.list_voices()
        # 只返回中文语音
        chinese_voices = {
            v["ShortName"]: v["FriendlyName"]
            for v in voices
            if v["Locale"].startswith("zh")
        }
        return chinese_voices
    except Exception as e:
        logger.error(f"Failed to list voices: {e}")
        return EdgeTTS.CHINESE_VOICES
