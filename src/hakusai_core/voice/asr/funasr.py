"""
HakusAI 2.0 FunASR (SenseVoice) 实现
阿里巴巴达摩院语音识别
"""

import os
import numpy as np
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
import tempfile

from .base import BaseASR, ASRResult, register_asr

logger = logging.getLogger(__name__)


@register_asr("funasr")
class FunASR(BaseASR):
    """
    FunASR引擎 - 支持SenseVoice模型
    
    特点：
    - 支持多语言（中、英、日、粤等）
    - 支持情感识别
    - 支持歌声识别
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model_path = config.get("model_path")
        self.model_name = config.get("model_name", "iic/SenseVoiceSmall")
        self.device = config.get("device", "auto")  # auto, cpu, cuda
        
        # 模型实例
        self._model = None
        self._inference_pipeline = None
        
    @property
    def provider_name(self) -> str:
        return "funasr"
    
    async def initialize(self):
        """初始化FunASR引擎"""
        try:
            from funasr import AutoModel
        except ImportError:
            logger.error("funasr not installed. Please install: pip install funasr")
            raise RuntimeError("funasr not installed")
        
        logger.info(f"Loading FunASR model: {self.model_name}")
        
        # 确定设备
        if self.device == "auto":
            try:
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"
        
        # 加载模型
        if self.model_path and os.path.exists(self.model_path):
            model_path = self.model_path
        else:
            model_path = self.model_name
        
        self._model = AutoModel(
            model=model_path,
            device=self.device,
            disable_pbar=True,
        )
        
        self._initialized = True
        logger.info("FunASR initialized successfully")
    
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
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            import wave
            with wave.open(tmp_path, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                audio_int16 = (audio_data * 32767).astype(np.int16)
                wav_file.writeframes(audio_int16.tobytes())
        
        try:
            return await self.transcribe_file(tmp_path)
        finally:
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
        
        # 执行识别
        result = self._model.generate(
            input=file_path,
            language=self._map_language(self.language),
            use_itn=True,  # 使用逆文本归一化
        )
        
        if not result or len(result) == 0:
            return ASRResult(text="", confidence=0.0)
        
        # 解析结果
        text = result[0].get("text", "")
        
        # 提取情感标签（如果有）
        # SenseVoice格式: <|zh|><|NEUTRAL|><|Speech|><|woitn|>文本内容
        emotion = None
        if text.startswith("<"):
            # 解析标签
            tags = []
            while text.startswith("<"):
                end = text.find("|>")
                if end == -1:
                    break
                tag = text[2:end]
                tags.append(tag)
                text = text[end+2:].strip()
            
            # 提取情感
            for tag in tags:
                if tag in ["NEUTRAL", "HAPPY", "SAD", "ANGRY", "FEAR"]:
                    emotion = tag
        
        # 获取置信度（如果有）
        confidence = result[0].get("confidence", 0.9)
        
        return ASRResult(
            text=text,
            confidence=confidence,
            language=self.language,
        )
    
    def _map_language(self, lang: str) -> str:
        """
        映射语言代码到FunASR格式
        
        Args:
            lang: 语言代码
            
        Returns:
            FunASR语言代码
        """
        mapping = {
            "zh": "zh",
            "en": "en",
            "ja": "ja",
            "yue": "yue",  # 粤语
            "ko": "ko",
            "auto": "auto",
        }
        return mapping.get(lang, "auto")
    
    async def transcribe_batch(
        self,
        audio_files: List[str]
    ) -> List[ASRResult]:
        """
        批量识别音频文件
        
        Args:
            audio_files: 音频文件路径列表
            
        Returns:
            识别结果列表
        """
        if not self._initialized:
            await self.initialize()
        
        results = self._model.generate(
            input=audio_files,
            language=self._map_language(self.language),
            use_itn=True,
            batch_size=len(audio_files),
        )
        
        asr_results = []
        for result in results:
            text = result.get("text", "")
            
            # 移除标签
            if text.startswith("<"):
                while text.startswith("<"):
                    end = text.find("|>")
                    if end == -1:
                        break
                    text = text[end+2:].strip()
            
            asr_results.append(ASRResult(
                text=text,
                confidence=result.get("confidence", 0.9),
                language=self.language,
            ))
        
        return asr_results
    
    async def close(self):
        """关闭ASR引擎"""
        self._model = None
        self._inference_pipeline = None
        self._initialized = False
        logger.debug("FunASR closed")
