"""
HakusAI 2.0 FunASR VAD 实现
使用阿里巴巴达摩院 FSMN VAD 流式检测
"""

import os
import logging
from typing import Optional, Dict, Any, List
import numpy as np
import torch

from .base import BaseVAD, VADResult, register_vad

logger = logging.getLogger(__name__)


@register_vad("funasr")
class FunASRVAD(BaseVAD):
    """
    FunASR FSMN VAD 引擎
    
    特点：
    - 支持流式处理，无需固定帧长
    - 动态静音阈值，适合实时长自动调整
    - 内置语音段切分和合并
    - 与 FunASR ASR 完美配合
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        self.model_name = config.get("model_name", "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch")
        self.model_path = config.get("model_path")
        self.device = config.get("device", "auto")  # auto, cpu, cuda
        
        # 模型实例
        self._model = None
        self._dynamic_vad = None
        
        # 流式处理状态
        self._initialized = False
        
        # 采样率
        self._sample_rate = config.get("sample_rate", 16000)
        
        # 语音段收集
        self._speech_buffer: List[np.ndarray] = []
        self._is_collecting = False

    @property
    def provider_name(self) -> str:
        return "funasr"

    async def initialize(self):
        """初始化 FunASR VAD 引擎"""
        try:
            from funasr import AutoModel
            from funasr.models.fsmn_vad_streaming.dynamic_vad import DynamicStreamingVAD
        except ImportError:
            logger.error("funasr not installed. Please install: pip install funasr")
            raise RuntimeError("funasr not installed")

        logger.info(f"Loading FunASR VAD model: {self.model_name}")

        # 确定设备
        if self.device == "auto":
            try:
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"

        logger.info(f"Using device: {self.device}")

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

        # 创建动态流式 VAD
        self._dynamic_vad = DynamicStreamingVAD(
            vad_model=self._model,
            chunk_size_ms=60,  # 60ms per chunk
            speech_noise_thres=0.5,
            speech_to_sil_thres_ms=150,
            sample_rate=self._sample_rate,
        )

        self._initialized = True
        logger.info("FunASR VAD initialized successfully")

    def reset_states(self):
        """重置 VAD 状态"""
        if self._dynamic_vad:
            self._dynamic_vad.reset()
        self._speech_buffer = []
        self._is_collecting = False

    async def process(
        self,
        audio_data: np.ndarray,
        sample_rate: Optional[int] = None
    ) -> VADResult:
        """
        处理音频帧（流式）
        
        Args:
            audio_data: 音频数据 (numpy数组)
            sample_rate: 采样率
            
        Returns:
            VAD检测结果
        """
        if not self._initialized:
            await self.initialize()

        if sample_rate is None:
            sample_rate = self.config.sample_rate

        # 重采样到 16kHz（如果需要）
        if sample_rate != self._sample_rate:
            audio_data = self._resample(audio_data, sample_rate, self._sample_rate)
            sample_rate = self._sample_rate

        # 归一化音频
        audio_data = self._normalize_audio(audio_data)

        # 转换为 tensor
        audio_tensor = torch.from_numpy(audio_data).float()

        # 运行 VAD
        segments = self._dynamic_vad.feed(audio_tensor, is_final=False)
        
        is_speech = self._dynamic_vad.is_speaking
        confidence = 1.0 if is_speech else 0.0

        # 收集语音段
        if is_speech:
            if not self._is_collecting:
                self._is_collecting = True
            self._speech_buffer.append(audio_data)
        else:
            if self._is_collecting and segments:
                # 检测到语音结束
                pass

        # 准备返回的音频数据
        result_audio = None
        if self._speech_buffer:
            result_audio = np.concatenate(self._speech_buffer)
            # 限制缓冲区大小
            max_samples = self._sample_rate * 10  # 最多10秒
            if len(result_audio) > max_samples:
                self._speech_buffer = [result_audio[-self._sample_rate * 5:]]  # 保留最后5秒

        return VADResult(
            is_speech=is_speech,
            confidence=confidence,
            audio_data=result_audio
        )

    async def process_batch(
        self,
        audio_batch: np.ndarray,
        sample_rate: Optional[int] = None
    ) -> List[VADResult]:
        """
        批量处理音频（非流式）
        
        Args:
            audio_batch: 音频批次
            sample_rate: 采样率
            
        Returns:
            VAD结果列表
        """
        if not self._initialized:
            await self.initialize()

        if sample_rate is None:
            sample_rate = self.config.sample_rate

        if sample_rate != self._sample_rate:
            audio_batch = self._resample(audio_batch, sample_rate, self._sample_rate)

        # 归一化
        audio_batch = self._normalize_audio(audio_batch)
        audio_tensor = torch.from_numpy(audio_batch).float()

        # 重置状态
        self._dynamic_vad.reset()

        # 非流式处理
        segments = self._dynamic_vad.process(audio_tensor)

        results = []
        for seg in segments:
            start_ms, end_ms = seg
            results.append(VADResult(
                is_speech=True,
                confidence=1.0,
            ))

        return results

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

    def _resample(
        self,
        audio_data: np.ndarray,
        orig_sr: int,
        target_sr: int
    ) -> np.ndarray:
        """
        重采样音频
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
            from scipy import signal
            return signal.resample(
                audio_data,
                int(len(audio_data) * target_sr / orig_sr)
            )

    def _normalize_audio(self, audio_data: np.ndarray) -> np.ndarray:
        """
        归一化音频数据
        """
        if audio_data.dtype == np.int16:
            return audio_data.astype(np.float32) / 32768.0
        elif audio_data.dtype == np.int32:
            return audio_data.astype(np.float32) / 2147483648.0
        return audio_data.astype(np.float32)

    async def close(self):
        """关闭 VAD 引擎"""
        self._model = None
        self._dynamic_vad = None
        self._speech_buffer = []
        self._initialized = False
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        await super().close()


class FunASRVADIterator:
    """
    FunASR VAD 迭代器
    
    用于流式音频处理，自动检测语音段
    """

    def __init__(
        self,
        vad: FunASRVAD,
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