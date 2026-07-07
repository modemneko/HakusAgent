"""
HakusAI 2.0 Whisper ASR 实现
支持OpenAI API和本地faster-whisper
"""

import os
import numpy as np
import logging
from typing import Optional, Dict, Any, Literal
from pathlib import Path
import tempfile

from .base import BaseASR, ASRResult, register_asr

logger = logging.getLogger(__name__)


@register_asr("whisper")
class WhisperASR(BaseASR):
    """
    Whisper ASR引擎
    
    支持两种模式：
    - api: 使用OpenAI API (需要api_key)
    - local: 使用本地faster-whisper模型
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.mode = config.get("mode", "api")  # 'api' 或 'local'
        self.model_path = config.get("model_path")  # 本地模型路径或模型名称
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.model_size = config.get("model_size", "base")  # tiny, base, small, medium, large
        
        # 本地模型实例
        self._model = None
        self._client = None
        
    @property
    def provider_name(self) -> str:
        return "whisper"
    
    async def initialize(self):
        """初始化Whisper引擎"""
        if self.mode == "api":
            await self._init_api_mode()
        else:
            await self._init_local_mode()
        
        self._initialized = True
        logger.info(f"Whisper ASR initialized (mode: {self.mode})")
    
    async def _init_api_mode(self):
        """初始化API模式"""
        try:
            import openai
        except ImportError:
            logger.error("openai not installed. Please install: pip install openai")
            raise RuntimeError("openai not installed")
        
        if not self.api_key:
            raise ValueError("API key is required for API mode")
        
        self._client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    async def _init_local_mode(self):
        """初始化本地模式"""
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.error("faster-whisper not installed. Please install: pip install faster-whisper")
            raise RuntimeError("faster-whisper not installed")
        
        # 确定模型路径
        if self.model_path and os.path.exists(self.model_path):
            model_path = self.model_path
        else:
            # 使用预训练模型
            model_path = self.model_size
        
        logger.info(f"Loading Whisper model: {model_path}")
        
        # 加载模型
        device = "cuda" if self._check_cuda() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        
        self._model = WhisperModel(
            model_path,
            device=device,
            compute_type=compute_type,
            download_root="models/whisper"
        )
    
    def _check_cuda(self) -> bool:
        """检查是否可用CUDA"""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
    
    async def transcribe(
        self,
        audio_data: np.ndarray,
        sample_rate: Optional[int] = None
    ) -> ASRResult:
        """
        识别音频
        
        Args:
            audio_data: 音频数据 (numpy数组)
            sample_rate: 采样率
            
        Returns:
            识别结果
        """
        if not self._initialized:
            await self.initialize()
        
        if sample_rate is None:
            sample_rate = self.sample_rate
        
        # 归一化音频
        audio_data = self._normalize_audio(audio_data)
        
        # 重采样到16kHz (Whisper要求)
        if sample_rate != 16000:
            audio_data = self._resample(audio_data, sample_rate, 16000)
        
        if self.mode == "api":
            return await self._transcribe_api(audio_data)
        else:
            return await self._transcribe_local(audio_data)
    
    async def _transcribe_api(self, audio_data: np.ndarray) -> ASRResult:
        """使用API识别"""
        import io
        import wave
        
        # 转换为WAV格式
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            
            # 转换为int16
            audio_int16 = (audio_data * 32767).astype(np.int16)
            wav_file.writeframes(audio_int16.tobytes())
        
        wav_buffer.seek(0)
        
        # 调用API
        response = await self._client.audio.transcriptions.create(
            model="whisper-1",
            file=("audio.wav", wav_buffer),
            language=self.language if self.language != "zh" else "zh",
            response_format="json"
        )
        
        return ASRResult(
            text=response.text,
            confidence=0.95,
            language=self.language,
            duration=len(audio_data) / 16000
        )
    
    async def _transcribe_local(self, audio_data: np.ndarray) -> ASRResult:
        """使用本地模型识别"""
        # faster-whisper 需要文件路径，创建临时文件
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            import wave
            with wave.open(tmp_path, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                audio_int16 = (audio_data * 32767).astype(np.int16)
                wav_file.writeframes(audio_int16.tobytes())
        
        try:
            segments, info = self._model.transcribe(
                tmp_path,
                language=self.language if self.language != "zh" else "zh",
                beam_size=5
            )
            
            # 合并所有片段
            texts = []
            avg_confidence = 0.0
            count = 0
            
            for segment in segments:
                texts.append(segment.text)
                avg_confidence += segment.avg_logprob
                count += 1
            
            text = " ".join(texts).strip()
            confidence = np.exp(avg_confidence / count) if count > 0 else 0.0
            
            return ASRResult(
                text=text,
                confidence=confidence,
                language=info.language,
                duration=len(audio_data) / 16000
            )
        finally:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    async def transcribe_file(self, file_path: str) -> ASRResult:
        """
        识别音频文件
        
        Args:
            file_path: 音频文件路径
            
        Returns:
            识别结果
        """
        if not self._initialized:
            await self.initialize()
        
        if self.mode == "api":
            with open(file_path, 'rb') as f:
                response = await self._client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language=self.language if self.language != "zh" else "zh"
                )
            
            return ASRResult(
                text=response.text,
                confidence=0.95,
                language=self.language
            )
        else:
            segments, info = self._model.transcribe(
                file_path,
                language=self.language if self.language != "zh" else "zh",
                beam_size=5
            )
            
            texts = []
            avg_confidence = 0.0
            count = 0
            
            for segment in segments:
                texts.append(segment.text)
                avg_confidence += segment.avg_logprob
                count += 1
            
            text = " ".join(texts).strip()
            confidence = np.exp(avg_confidence / count) if count > 0 else 0.0
            
            return ASRResult(
                text=text,
                confidence=confidence,
                language=info.language
            )
    
    async def close(self):
        """关闭ASR引擎"""
        self._model = None
        self._client = None
        self._initialized = False
        logger.debug("Whisper ASR closed")
