"""
HakusAI 2.0 Silero VAD 实现
高性能语音活动检测
"""

import os
import numpy as np
import logging
from typing import Optional, Dict, Any
from pathlib import Path
import torch
import torch.nn.functional as F

from .base import BaseVAD, VADResult, VADState, register_vad

logger = logging.getLogger(__name__)


@register_vad("silero")
class SileroVAD(BaseVAD):
    """
    Silero VAD引擎
    
    特点：
    - 轻量级，适合实时应用
    - 支持多种采样率 (8000, 16000 Hz)
    - 支持批处理
    """
    
    # Silero VAD模型URL
    MODEL_URL = "https://github.com/snakers4/silero-vad/raw/master/files/silero_vad.jit"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        self.model_path = config.get("model_path")
        self.force_on_cpu = config.get("force_on_cpu", False)
        
        # 模型实例
        self._model = None
        self._device = None
        
        # 状态变量
        self._last_sample_rate = 16000
        self._h = None  # 隐藏状态
        self._c = None  # 细胞状态
        
        # 音频累积缓冲区（用于语音段收集）
        self._speech_buffer: list = []
        self._is_collecting = False
        
    @property
    def provider_name(self) -> str:
        return "silero"
    
    async def initialize(self):
        """初始化Silero VAD引擎"""
        logger.info("Initializing Silero VAD...")
        
        # 确定设备
        if self.force_on_cpu:
            self._device = torch.device("cpu")
        else:
            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        logger.info(f"Using device: {self._device}")
        
        # 加载模型
        if self.model_path and os.path.exists(self.model_path):
            model_path = self.model_path
        else:
            # 下载或获取默认模型
            model_path = self._get_model_path()
        
        try:
            # 加载JIT模型
            self._model = torch.jit.load(model_path, map_location=self._device)
            self._model.eval()
        except Exception as e:
            logger.error(f"Failed to load Silero VAD model: {e}")
            # 尝试从torch hub加载
            self._model = self._load_from_torch_hub()
        
        # 重置状态
        self.reset_states()
        
        self._initialized = True
        logger.info("Silero VAD initialized successfully")
    
    def _get_model_path(self) -> str:
        """获取模型路径（如果不存在则下载）"""
        model_dir = Path("models/vad")
        model_dir.mkdir(parents=True, exist_ok=True)
        
        model_path = model_dir / "silero_vad.jit"
        
        if not model_path.exists():
            logger.info("Downloading Silero VAD model...")
            import urllib.request
            try:
                urllib.request.urlretrieve(self.MODEL_URL, model_path)
                logger.info(f"Model downloaded to {model_path}")
            except Exception as e:
                logger.error(f"Failed to download model: {e}")
                raise
        
        return str(model_path)
    
    def _load_from_torch_hub(self):
        """从torch hub加载模型"""
        logger.info("Loading Silero VAD from torch hub...")
        model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            onnx=False
        )
        return model.to(self._device)
    
    def reset_states(self):
        """重置模型状态"""
        self._h = torch.zeros(2, 1, 64).to(self._device)
        self._c = torch.zeros(2, 1, 64).to(self._device)
        self._speech_buffer = []
        self._is_collecting = False
    
    async def process(
        self,
        audio_data: np.ndarray,
        sample_rate: Optional[int] = None
    ) -> VADResult:
        """
        处理音频帧
        
        Args:
            audio_data: 音频数据 (numpy数组)
            sample_rate: 采样率 (必须是8000或16000)
            
        Returns:
            VAD检测结果
        """
        if not self._initialized:
            await self.initialize()
        
        if sample_rate is None:
            sample_rate = self.config.sample_rate
        
        # 验证采样率
        if sample_rate not in [8000, 16000]:
            # 重采样到16000
            audio_data = self._resample(audio_data, sample_rate, 16000)
            sample_rate = 16000
        
        self._last_sample_rate = sample_rate
        
        # 归一化音频
        audio_data = self._normalize_audio(audio_data)
        
        # 转换为tensor
        audio_tensor = torch.from_numpy(audio_data).to(self._device)
        
        # 确保正确的形状 [batch, samples]
        if audio_tensor.dim() == 1:
            audio_tensor = audio_tensor.unsqueeze(0)
        
        # 运行VAD
        with torch.no_grad():
            speech_prob, self._h, self._c = self._model(audio_tensor, self._last_sample_rate, self._h, self._c)
        
        # 获取概率值
        prob = speech_prob.item()
        
        # 判断是否语音
        is_speech = prob >= self.config.threshold
        
        # 收集语音段
        if is_speech:
            if not self._is_collecting:
                self._is_collecting = True
            self._speech_buffer.append(audio_data)
        else:
            if self._is_collecting:
                # 检查静音持续时间
                # 这里简化处理，实际应该跟踪时间
                pass
        
        # 准备返回的音频数据
        result_audio = None
        if is_speech and len(self._speech_buffer) > 0:
            result_audio = np.concatenate(self._speech_buffer)
            # 限制缓冲区大小
            if len(result_audio) > sample_rate * 10:  # 最多10秒
                self._speech_buffer = [result_audio[-sample_rate * 5:]]  # 保留最后5秒
        
        return VADResult(
            is_speech=is_speech,
            confidence=prob,
            audio_data=result_audio
        )
    
    async def process_batch(
        self,
        audio_batch: np.ndarray,
        sample_rate: Optional[int] = None
    ) -> list:
        """
        批量处理音频
        
        Args:
            audio_batch: 音频批次 [batch_size, samples]
            sample_rate: 采样率
            
        Returns:
            VAD结果列表
        """
        if not self._initialized:
            await self.initialize()
        
        if sample_rate is None:
            sample_rate = self.config.sample_rate
        
        if sample_rate not in [8000, 16000]:
            raise ValueError(f"Unsupported sample rate: {sample_rate}. Must be 8000 or 16000")
        
        # 归一化
        audio_batch = self._normalize_audio(audio_batch)
        
        # 转换为tensor
        audio_tensor = torch.from_numpy(audio_batch).to(self._device)
        
        # 确保正确的形状
        if audio_tensor.dim() == 1:
            audio_tensor = audio_tensor.unsqueeze(0)
        
        # 批量处理
        results = []
        h = self._h.clone()
        c = self._c.clone()
        
        with torch.no_grad():
            for i in range(audio_tensor.shape[0]):
                audio_chunk = audio_tensor[i:i+1]
                speech_prob, h, c = self._model(audio_chunk, sample_rate, h, c)
                
                prob = speech_prob.item()
                is_speech = prob >= self.config.threshold
                
                results.append(VADResult(
                    is_speech=is_speech,
                    confidence=prob
                ))
        
        return results
    
    def _resample(
        self,
        audio_data: np.ndarray,
        orig_sr: int,
        target_sr: int
    ) -> np.ndarray:
        """
        重采样音频
        
        Args:
            audio_data: 原始音频数据
            orig_sr: 原始采样率
            target_sr: 目标采样率
            
        Returns:
            重采样后的音频数据
        """
        if orig_sr == target_sr:
            return audio_data
        
        try:
            import librosa
            return librosa.resample(
                audio_data.astype(np.float32),
                orig_sr=orig_sr,
                target_sr=target_sr
            )
        except ImportError:
            # 简单线性插值
            from scipy import signal
            return signal.resample(
                audio_data,
                int(len(audio_data) * target_sr / orig_sr)
            )
    
    def get_speech_segment(self) -> Optional[np.ndarray]:
        """
        获取当前收集的语音段
        
        Returns:
            语音音频数据或None
        """
        if len(self._speech_buffer) == 0:
            return None
        
        segment = np.concatenate(self._speech_buffer)
        self._speech_buffer = []
        self._is_collecting = False
        return segment
    
    async def close(self):
        """关闭VAD引擎"""
        self._model = None
        self._h = None
        self._c = None
        self._speech_buffer = []
        torch.cuda.empty_cache() if torch.cuda.is_available() else None
        await super().close()


class SileroVADIterator:
    """
    Silero VAD迭代器
    
    用于流式音频处理，自动检测语音段
    """
    
    def __init__(
        self,
        vad: SileroVAD,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_silence_duration_ms: int = 500,
        speech_pad_ms: int = 100
    ):
        self.vad = vad
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms
        
        self.reset_states()
    
    def reset_states(self):
        """重置状态"""
        self.triggered = False
        self.buffer = []
        self.silence_counter = 0
    
    async def __call__(self, audio_chunk: np.ndarray) -> Optional[np.ndarray]:
        """
        处理音频块
        
        Args:
            audio_chunk: 音频数据
            
        Returns:
            如果检测到完整语音段则返回音频数据，否则返回None
        """
        result = await self.vad.process(audio_chunk, self.sampling_rate)
        
        if not self.triggered:
            # 等待语音开始
            if result.is_speech:
                self.triggered = True
                self.buffer.append(audio_chunk)
                self.silence_counter = 0
            return None
        
        else:
            # 正在收集语音
            self.buffer.append(audio_chunk)
            
            if result.is_speech:
                # 重置静音计数器
                self.silence_counter = 0
            else:
                # 增加静音计数
                self.silence_counter += len(audio_chunk)
                
                # 检查是否达到静音阈值
                silence_samples = int(self.min_silence_duration_ms * self.sampling_rate / 1000)
                if self.silence_counter > silence_samples:
                    # 语音结束
                    speech = np.concatenate(self.buffer)
                    self.reset_states()
                    return speech
            
            return None
