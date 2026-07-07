"""
HakusAI 2.0 Sherpa-ONNX ASR 实现
支持流式语音识别
"""

import os
import numpy as np
import logging
from typing import Optional, Dict, Any
from pathlib import Path

from .base import BaseASR, ASRResult, register_asr

logger = logging.getLogger(__name__)


@register_asr("sherpa_onnx")
class SherpaONNXASR(BaseASR):
    """
    Sherpa-ONNX ASR引擎
    
    支持多种模型格式：
    - Zipformer 模型
    - Paraformer 模型
    - Whisper 模型
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model_path = config.get("sherpa_onnx_model") or config.get("model_path")
        self.tokens_path = config.get("tokens_path")
        self.provider = "sherpa_onnx"
        
        # Sherpa-ONNX 识别器
        self.recognizer = None
        self.sample_rate = config.get("sample_rate", 16000)
        
        # 流式识别状态
        self._stream = None
        
    @property
    def provider_name(self) -> str:
        return "sherpa_onnx"
    
    async def initialize(self):
        """初始化Sherpa-ONNX识别器"""
        try:
            import sherpa_onnx
        except ImportError:
            logger.error("sherpa_onnx not installed. Please install: pip install sherpa-onnx")
            raise RuntimeError("sherpa_onnx not installed")
        
        if not self.model_path:
            # 尝试自动查找模型
            self.model_path = self._find_default_model()
        
        if not self.model_path or not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model not found: {self.model_path}")
        
        # 查找tokens文件
        if not self.tokens_path:
            self.tokens_path = self._find_tokens_file()
        
        logger.info(f"Initializing Sherpa-ONNX ASR with model: {self.model_path}")
        
        # 根据模型类型创建识别器
        model_path = Path(self.model_path)
        
        if model_path.suffix == '.onnx':
            # 检查是否是Paraformer模型
            if 'paraformer' in model_path.name.lower():
                self.recognizer = self._create_paraformer_recognizer(sherpa_onnx)
            else:
                # 默认使用Zipformer
                self.recognizer = self._create_zipformer_recognizer(sherpa_onnx)
        else:
            raise ValueError(f"Unsupported model format: {model_path.suffix}")
        
        self._initialized = True
        logger.info("Sherpa-ONNX ASR initialized successfully")
    
    def _create_zipformer_recognizer(self, sherpa_onnx):
        """创建Zipformer识别器"""
        model_config = sherpa_onnx.OnlineModelConfig(
            transducer=sherpa_onnx.OnlineTransducerModelConfig(
                encoder=self.model_path,
                decoder=self.model_path.replace("encoder", "decoder").replace("-encoder-", "-decoder-"),
                joiner=self.model_path.replace("encoder", "joiner").replace("-encoder-", "-joiner-"),
            ),
            tokens=self.tokens_path,
            num_threads=4,
            provider="cpu",
            debug=False,
        )
        
        config = sherpa_onnx.OnlineRecognizerConfig(
            feat_config=sherpa_onnx.FeatureExtractorConfig(
                sampling_rate=self.sample_rate,
                feature_dim=80,
            ),
            model_config=model_config,
            decoding_method="greedy_search",
            max_active_paths=4,
        )
        
        return sherpa_onnx.OnlineRecognizer(config)
    
    def _create_paraformer_recognizer(self, sherpa_onnx):
        """创建Paraformer识别器"""
        model_config = sherpa_onnx.OnlineModelConfig(
            paraformer=sherpa_onnx.OnlineParaformerModelConfig(
                encoder=self.model_path,
                decoder=self.model_path.replace("encoder", "decoder"),
            ),
            tokens=self.tokens_path,
            num_threads=4,
            provider="cpu",
            debug=False,
        )
        
        config = sherpa_onnx.OnlineRecognizerConfig(
            feat_config=sherpa_onnx.FeatureExtractorConfig(
                sampling_rate=self.sample_rate,
                feature_dim=80,
            ),
            model_config=model_config,
            decoding_method="greedy_search",
        )
        
        return sherpa_onnx.OnlineRecognizer(config)
    
    def _find_default_model(self) -> Optional[str]:
        """查找默认模型"""
        model_dirs = [
            "models/asr",
            "data/models/asr",
            "resources/models/asr",
        ]
        
        for model_dir in model_dirs:
            if os.path.exists(model_dir):
                # 查找.onnx文件
                for file in os.listdir(model_dir):
                    if file.endswith('.onnx') and 'encoder' in file.lower():
                        return os.path.join(model_dir, file)
        
        return None
    
    def _find_tokens_file(self) -> Optional[str]:
        """查找tokens文件"""
        if not self.model_path:
            return None
        
        model_dir = os.path.dirname(self.model_path)
        
        # 常见tokens文件名
        tokens_names = ['tokens.txt', 'tokens', 'vocab.txt', 'vocab']
        
        for name in tokens_names:
            path = os.path.join(model_dir, name)
            if os.path.exists(path):
                return path
        
        return None
    
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
        
        # 重采样到目标采样率
        if sample_rate != self.sample_rate:
            audio_data = self._resample(audio_data, sample_rate, self.sample_rate)
        
        # 创建识别流
        stream = self.recognizer.create_stream()
        
        # 接受音频数据
        stream.accept_waveform(self.sample_rate, audio_data)
        
        # 识别
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)
        
        # 获取结果
        result = self.recognizer.get_result(stream)
        
        return ASRResult(
            text=result.text,
            confidence=getattr(result, 'confidence', 0.0) or 0.9,
            language=self.language,
            duration=len(audio_data) / self.sample_rate
        )
    
    async def transcribe_file(self, file_path: str) -> ASRResult:
        """
        识别音频文件
        
        Args:
            file_path: 音频文件路径
            
        Returns:
            识别结果
        """
        import soundfile as sf
        
        audio_data, sample_rate = sf.read(file_path, dtype=np.float32)
        
        # 如果是立体声，转换为单声道
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)
        
        return await self.transcribe(audio_data, sample_rate)
    
    def create_stream(self):
        """创建流式识别流"""
        if not self._initialized:
            raise RuntimeError("ASR not initialized")
        self._stream = self.recognizer.create_stream()
        return self._stream
    
    def accept_waveform(self, audio_data: np.ndarray, sample_rate: Optional[int] = None):
        """
        向流中输入音频数据
        
        Args:
            audio_data: 音频数据
            sample_rate: 采样率
        """
        if self._stream is None:
            self.create_stream()
        
        if sample_rate is None:
            sample_rate = self.sample_rate
        
        # 归一化
        audio_data = self._normalize_audio(audio_data)
        
        # 重采样
        if sample_rate != self.sample_rate:
            audio_data = self._resample(audio_data, sample_rate, self.sample_rate)
        
        self._stream.accept_waveform(self.sample_rate, audio_data)
    
    def decode_stream(self) -> bool:
        """
        解码流中的数据
        
        Returns:
            是否还有更多数据需要解码
        """
        if self._stream is None:
            return False
        
        if self.recognizer.is_ready(self._stream):
            self.recognizer.decode_stream(self._stream)
            return True
        return False
    
    def get_stream_result(self) -> ASRResult:
        """获取流式识别结果"""
        if self._stream is None:
            return ASRResult(text="", confidence=0.0)
        
        result = self.recognizer.get_result(self._stream)
        
        return ASRResult(
            text=result.text,
            confidence=getattr(result, 'confidence', 0.0) or 0.9,
            language=self.language,
        )
    
    def reset_stream(self):
        """重置流式识别状态"""
        self._stream = None
    
    async def close(self):
        """关闭ASR引擎"""
        self._stream = None
        self.recognizer = None
        self._initialized = False
        logger.debug("Sherpa-ONNX ASR closed")
