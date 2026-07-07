"""
Edge TTS 引擎
使用微软 Edge 在线 TTS 服务
"""

import edge_tts
from typing import Optional, Dict, Any, List, AsyncIterator
import logging

from ..base import BaseTTSEngine, TTSResult
from ..registry import register_tts

logger = logging.getLogger(__name__)


@register_tts("edge")
class EdgeTTSEngine(BaseTTSEngine):
    """Edge TTS 引擎"""
    
    CHINESE_VOICES = {
        "xiaoxiao": "zh-CN-XiaoxiaoNeural",
        "xiaoyi": "zh-CN-XiaoyiNeural",
        "yunjian": "zh-CN-YunjianNeural",
        "yunxi": "zh-CN-YunxiNeural",
        "yunxia": "zh-CN-YunxiaNeural",
        "yunyang": "zh-CN-YunyangNeural",
    }
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.voice = config.get("voice", "zh-CN-XiaoxiaoNeural") if config else "zh-CN-XiaoxiaoNeural"
        self.speed = config.get("speed", 1.0) if config else 1.0
        self.volume = config.get("volume", 1.0) if config else 1.0
        
        if self.voice in self.CHINESE_VOICES:
            self.voice = self.CHINESE_VOICES[self.voice]
    
    @property
    def engine_name(self) -> str:
        return "edge"
    
    async def initialize(self) -> bool:
        self._initialized = True
        logger.info(f"Edge TTS initialized: {self.voice}")
        return True
    
    async def synthesize(self, text: str, **kwargs) -> Optional[TTSResult]:
        if not self._initialized:
            await self.initialize()
        
        voice = kwargs.get("voice", self.voice)
        speed = kwargs.get("speed", self.speed)
        
        if voice in self.CHINESE_VOICES:
            voice = self.CHINESE_VOICES[voice]
        
        cached = self._check_cache(text, voice=voice, speed=speed)
        if cached:
            return cached
        
        try:
            communicate_kwargs = {"text": text, "voice": voice}
            if speed != 1.0:
                rate_percent = int((speed - 1) * 100)
                communicate_kwargs["rate"] = f"{rate_percent:+d}%"
            
            communicate = edge_tts.Communicate(**communicate_kwargs)
            audio_data = bytearray()
            
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])
            
            result = TTSResult(
                audio_data=bytes(audio_data),
                sample_rate=24000,
                format="mp3",
                text=text
            )
            
            self._save_cache(text, result, voice=voice, speed=speed)
            return result
            
        except Exception as e:
            logger.error(f"Edge TTS synthesis failed: {e}")
            return None
    
    async def synthesize_stream(self, text: str, **kwargs) -> AsyncIterator[bytes]:
        voice = kwargs.get("voice", self.voice)
        speed = kwargs.get("speed", self.speed)
        
        if voice in self.CHINESE_VOICES:
            voice = self.CHINESE_VOICES[voice]
        
        communicate_kwargs = {"text": text, "voice": voice}
        if speed != 1.0:
            rate_percent = int((speed - 1) * 100)
            communicate_kwargs["rate"] = f"{rate_percent:+d}%"
        
        communicate = edge_tts.Communicate(**communicate_kwargs)
        
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
    
    async def list_voices(self) -> List[Dict[str, str]]:
        return [
            {"id": k, "name": v, "language": "zh-CN"}
            for k, v in self.CHINESE_VOICES.items()
        ]
