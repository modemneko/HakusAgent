"""
HakusAI 2.0 高级嘴型同步系统
融合 ZerolanLiveRobot 的 RMS 分析和 Open-LLM-VTuber 的音量切片算法

特性：
- 高精度 RMS 音量分析（借鉴 live2d-py WavHandler）
- 平滑滤波（指数移动平均 + 低通滤波）
- 自适应灵敏度调节
- 音素级别嘴型映射（可选）
- 实时音量可视化数据生成
"""

import asyncio
import numpy as np
from typing import Optional, Callable, Dict, List, Tuple
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
import logging
import struct
import wave
import io

from .base import LipSyncData, BaseAvatar
from ..utils.events import EventType, emit

logger = logging.getLogger(__name__)


class LipSyncMode(str, Enum):
    """嘴型同步模式"""
    VOLUME_ONLY = "volume_only"  # 仅基于音量
    PHONEME_BASIC = "phoneme_basic"  # 基础音素映射
    PHONEME_ADVANCED = "phoneme_advanced"  # 高级音素映射（需要TTS前端支持）


@dataclass
class LipSyncConfig:
    """嘴型同步配置"""
    # 基本参数
    sample_rate: int = 22050  # 采样率（与 TTS 输出匹配）
    frame_duration_ms: int = 20  # 每帧时长（ms），用于生成口型数据

    # 平滑参数
    smoothing_factor: float = 0.3  # 指数移动平均系数 (0-1)，越小越平滑
    lowpass_cutoff: float = 10.0  # 低通滤波截止频率 (Hz)
    smoothing_passes: int = 2  # 平滑遍数

    # 灵敏度
    sensitivity: float = 1.5  # 全局灵敏度倍率
    min_volume_threshold: float = 0.02  # 最小音量阈值（低于此值视为静音）
    max_volume_reference: float = 0.8  # 最大参考音量（用于归一化）

    # 嘴型参数
    mouth_open_max: float = 1.0  # 最大张嘴程度
    lip_sync_multiplier: float = 3.0  # 口型放大系数（借鉴 ZerolanLiveRobot）

    # 高级选项
    mode: LipSyncMode = LipSyncMode.VOLUME_ONLY
    adaptive_sensitivity: bool = True  # 自适应灵敏度
    silence_detection: bool = True  # 静音检测
    silence_threshold_db: float = -40.0  # 静音阈值 (dB)


class AudioAnalyzer:
    """
    音频分析器
    
    功能：
    - RMS 音量计算（均方根）
    - 分贝转换
    - 频谱分析（可选）
    - 静音检测
    """

    def __init__(self, config: LipSyncConfig):
        self.config = config

    def compute_rms(self, audio_data: np.ndarray) -> float:
        """
        计算 RMS（均方根）音量
        
        Args:
            audio_data: 音频样本数组
            
        Returns:
            RMS 值 (0.0-1.0)
        """
        if len(audio_data) == 0:
            return 0.0

        # 转换为 float32
        if audio_data.dtype in [np.int16, np.int32]:
            audio_float = audio_data.astype(np.float32) / np.iinfo(audio_data.dtype).max
        else:
            audio_float = audio_data.astype(np.float32)

        # 计算 RMS
        rms = np.sqrt(np.mean(audio_float ** 2))

        return float(rms)

    def compute_db(self, rms: float) -> float:
        """
        将 RMS 转换为分贝
        
        Args:
            rms: RMS 值
            
        Returns:
            分贝值
        """
        if rms <= 0:
            return -100.0

        return 20.0 * np.log10(rms)

    def is_silence(self, audio_data: np.ndarray) -> bool:
        """检测是否为静音"""
        if not self.config.silence_detection:
            return False

        rms = self.compute_rms(audio_data)
        db = self.compute_db(rms)

        return db < self.config.silence_threshold_db

    def extract_frames(
        self,
        audio_data: np.ndarray,
        sample_rate: int
    ) -> List[Tuple[np.ndarray, float]]:
        """
        将音频分割为帧
        
        Args:
            audio_data: 音频数据
            sample_rate: 采样率
            
        Returns:
            [(frame_data, timestamp), ...]
        """
        frame_size = int(sample_rate * self.config.frame_duration_ms / 1000)
        frames = []

        for i in range(0, len(audio_data), frame_size):
            frame = audio_data[i:i + frame_size]
            timestamp = i / sample_rate
            frames.append((frame, timestamp))

        return frames


class Smoother:
    """
    平滑器
    
    实现：
    - 指数移动平均 (EMA)
    - 多遍平滑
    """

    def __init__(self, config: LipSyncConfig):
        self.config = config
        self._ema_value: float = 0.0
        self._history: deque = deque(maxlen=10)

    def smooth(self, raw_value: float) -> float:
        """
        应用平滑处理
        
        Args:
            raw_value: 原始值
            
        Returns:
            平滑后的值
        """
        # 第一遍：EMA
        ema_result = (
            self.config.smoothing_factor * raw_value +
            (1 - self.config.smoothing_factor) * self._ema_value
        )
        self._ema_value = ema_result

        # 保存历史
        self._history.append(ema_result)

        # 第二遍：移动平均（如果配置了多遍平滑）
        if self.config.smoothing_passes > 1 and len(self._history) >= 3:
            result = np.mean(list(self._history)[-3:])
        else:
            result = ema_result

        return float(result)

    def reset(self):
        """重置状态"""
        self._ema_value = 0.0
        self._history.clear()


class AdaptiveSensitivity:
    """
    自适应灵敏度调节器
    
    根据音频动态范围自动调整灵敏度
    """

    def __init__(self, config: LipSyncConfig):
        self.config = config
        self._peak_tracker: deque = deque(maxlen=100)
        self._current_sensitivity: float = config.sensitivity
        self._adaptation_rate: float = 0.05  # 适应速度

    def update(self, volume: float) -> float:
        """
        更新并返回调整后的灵敏度
        
        Args:
            volume: 当前音量
            
        Returns:
            调整后的音量
        """
        if not self.config.adaptive_sensitivity:
            return volume * self.config.sensitivity

        # 追踪峰值
        self._peak_tracker.append(volume)

        if len(self._peak_tracker) < 10:
            return volume * self._current_sensitivity

        # 计算动态范围
        recent_peak = max(list(self._peak_tracker)[-20:])
        recent_avg = np.mean(list(self._peak_tracker)[-20:])

        # 动态范围比率
        if recent_avg > 0:
            dynamic_ratio = recent_peak / recent_avg
        else:
            dynamic_ratio = 1.0

        # 目标灵敏度：使峰值接近 max_volume_reference
        target_sensitivity = self.config.max_volume_reference / (recent_peak + 1e-6)

        # 限制灵敏度范围
        target_sensitivity = np.clip(target_sensitivity, 0.5, 3.0)

        # 平滑过渡
        self._current_sensitivity += (target_sensitivity - self._current_sensitivity) * self._adaptation_rate

        return volume * self._current_sensitivity

    def reset(self):
        """重置"""
        self._peak_tracker.clear()
        self._current_sensitivity = self.config.sensitivity


class LipSyncAnalyzerV2:
    """
    嘴型同步分析器 V2
    
    融合多种算法的高级版本
    """

    def __init__(self, config: Optional[LipSyncConfig] = None):
        self.config = config or LipSyncConfig()
        self.analyzer = AudioAnalyzer(self.config)
        self.smoother = Smoother(self.config)
        self.adaptive = AdaptiveSensitivity(self.config)

    def analyze_frame(self, audio_frame: np.ndarray) -> LipSyncData:
        """
        分析单个音频帧
        
        Args:
            audio_frame: 音频帧数据
            
        Returns:
            嘴型同步数据
        """
        # 1. 计算 RMS
        raw_rms = self.analyzer.compute_rms(audio_frame)

        # 2. 自适应灵敏度调节
        adjusted_volume = self.adaptive.update(raw_rms)

        # 3. 应用阈值
        if adjusted_volume < self.config.min_volume_threshold:
            adjusted_volume = 0.0

        # 4. 归一化到 0-1
        normalized = min(1.0, adjusted_volume / self.config.max_volume_reference)

        # 5. 平滑处理
        smoothed = self.smoother.smooth(normalized)

        # 6. 应用口型放大系数（借鉴 ZerolanLiveRobot）
        mouth_open = smoothed * self.config.lip_sync_multiplier
        mouth_open = min(1.0, mouth_open)  # 限制最大值

        return LipSyncData(
            mouth_open=mouth_open,
            mouth_form=0.5,  # 默认嘴型（可扩展）
            volume=smoothed
        )

    def analyze_audio_stream(
        self,
        audio_data: np.ndarray,
        sample_rate: int
    ) -> List[Dict]:
        """
        分析完整音频流，生成时间序列数据
        
        Args:
            audio_data: 完整音频数据
            sample_rate: 采样率
            
        Returns:
            口型时间序列 [{"time": t, "mouth_open": v, "amplitude": a}, ...]
        """
        frames = self.analyzer.extract_frames(audio_data, sample_rate)
        lip_sync_data = []

        for frame, timestamp in frames:
            lip_data = self.analyze_frame(frame)
            lip_sync_data.append({
                "time": timestamp,
                "mouth_open": lip_data.mouth_open,
                "amplitude": lip_data.volume
            })

        return lip_sync_data

    def reset(self):
        """重置所有状态"""
        self.smoother.reset()
        self.adaptive.reset()


class LipSyncEngineV2:
    """
    嘴型同步引擎 V2
    
    改进版引擎，支持实时流式和批量处理
    """

    def __init__(
        self,
        avatar: Optional[BaseAvatar] = None,
        config: Optional[LipSyncConfig] = None
    ):
        self.avatar = avatar
        self.config = config or LipSyncConfig()
        self.analyzer = LipSyncAnalyzerV2(self.config)

        self._running = False
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None

        # 回调
        self._on_lipsync_update: Optional[Callable] = None
        self._on_lipsync_complete: Optional[Callable] = None

    def set_avatar(self, avatar: BaseAvatar):
        """设置目标形象"""
        self.avatar = avatar

    def set_callback(
        self,
        on_update: Optional[Callable] = None,
        on_complete: Optional[Callable] = None
    ):
        """设置回调"""
        self._on_lipsync_update = on_update
        self._on_lipsync_complete = on_complete

    async def start(self):
        """启动引擎"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("LipSyncEngine V2 started")

    async def stop(self):
        """停止引擎"""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self.analyzer.reset()

        if self.avatar:
            self.avatar.update_lipsync(LipSyncData())

        logger.debug("LipSyncEngine V2 stopped")

    async def feed_audio(self, audio_data: np.ndarray):
        """
        输入音频数据（实时流）
        
        Args:
            audio_data: 音频数据
        """
        await self._audio_queue.put(audio_data)

    async def process_audio_file(self, audio_bytes: bytes) -> List[Dict]:
        """
        处理音频文件（批量模式）
        
        Args:
            audio_bytes: 音频字节数据 (WAV/MP3)
            
        Returns:
            口型时间序列
        """
        try:
            # 解析 WAV
            audio_data, sample_rate = self._parse_wav(audio_bytes)
            if audio_data is None:
                return []

            # 分析
            lip_sync_data = self.analyzer.analyze_audio_stream(audio_data, sample_rate)

            # 触发完成回调
            if self._on_lipsync_complete:
                if asyncio.iscoroutinefunction(self._on_lipsync_complete):
                    await self._on_lipsync_complete(lip_sync_data)
                else:
                    self._on_lipsync_complete(lip_sync_data)

            return lip_sync_data

        except Exception as e:
            logger.error(f"Error processing audio file: {e}")
            return []

    def _parse_wav(self, audio_bytes: bytes) -> Tuple[Optional[np.ndarray], int]:
        """解析 WAV 音频"""
        try:
            # 使用 io.BytesIO 包装
            buf = io.BytesIO(audio_bytes)

            # 尝试使用 wave 模块
            with wave.open(buf, 'rb') as wav_file:
                n_channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                n_frames = wav_file.getnframes()

                # 读取原始数据
                raw_data = wav_file.readframes(n_frames)

                # 转换为 numpy 数组
                if sample_width == 1:
                    audio_np = np.frombuffer(raw_data, dtype=np.uint8)
                elif sample_width == 2:
                    audio_np = np.frombuffer(raw_data, dtype=np.int16)
                elif sample_width == 4:
                    audio_np = np.frombuffer(raw_data, dtype=np.int32)
                else:
                    logger.error(f"Unsupported sample width: {sample_width}")
                    return None, 0

                # 如果是立体声，转换为单声道
                if n_channels > 1:
                    audio_np = audio_np.reshape(-1, n_channels)
                    audio_np = np.mean(audio_np, axis=1)

                return audio_np, sample_rate

        except Exception as e:
            logger.error(f"Error parsing WAV: {e}")
            # 尝试备用方法：直接解析原始字节
            return self._parse_raw_audio(audio_bytes)

    def _parse_raw_audio(self, audio_bytes: bytes) -> Tuple[Optional[np.ndarray], int]:
        """备用：解析原始音频数据"""
        try:
            # 检查 RIFF header
            if audio_bytes[:4] == b'RIFF':
                sample_rate = int.from_bytes(audio_bytes[24:28], 'little')
                sample_width = int.from_bytes(audio_bytes[34:36], 'little')
                audio_samples = audio_bytes[44:]
            else:
                # 假设默认格式
                sample_rate = 22050
                sample_width = 2
                audio_samples = audio_bytes

            # 转换为样本数组
            samples = []
            for i in range(0, len(audio_samples), sample_width):
                if i + sample_width <= len(audio_samples):
                    sample = int.from_bytes(audio_samples[i:i+sample_width], 'little', signed=True)
                    samples.append(sample)

            if not samples:
                return None, 0

            return np.array(samples, dtype=np.int16), sample_rate

        except Exception as e:
            logger.error(f"Error parsing raw audio: {e}")
            return None, 0

    async def _process_loop(self):
        """处理循环（实时模式）"""
        while self._running:
            try:
                audio_data = await asyncio.wait_for(
                    self._audio_queue.get(),
                    timeout=0.1
                )

                # 分析音频
                lip_data = self.analyzer.analyze_frame(audio_data)

                # 更新形象
                if self.avatar:
                    self.avatar.update_lipsync(lip_data)

                # 触发事件
                await emit(EventType.AVATAR_LIPSYNC_UPDATE, {
                    "mouth_open": lip_data.mouth_open,
                    "volume": lip_data.volume
                })

                # 调用回调
                if self._on_lipsync_update:
                    if asyncio.iscoroutinefunction(self._on_lipsync_update):
                        await self._on_lipsync_update(lip_data)
                    else:
                        self._on_lipsync_update(lip_data)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in lip sync loop: {e}")

    def update_config(self, config: LipSyncConfig):
        """更新配置"""
        self.config = config
        self.analyzer = LipSyncAnalyzerV2(config)


# ========== 全局实例 ==========

_lip_sync_engine_v2: Optional[LipSyncEngineV2] = None


async def get_lip_sync_engine(
    avatar: Optional[BaseAvatar] = None,
    config: Optional[LipSyncConfig] = None
) -> LipSyncEngineV2:
    """
    获取嘴型同步引擎 V2 实例（单例）
    
    Args:
        avatar: 虚拟形象
        config: 配置
        
    Returns:
        引擎实例
    """
    global _lip_sync_engine_v2

    if _lip_sync_engine_v2 is None:
        _lip_sync_engine_v2 = LipSyncEngineV2(avatar, config)
        await _lip_sync_engine_v2.start()
    elif avatar:
        _lip_sync_engine_v2.set_avatar(avatar)

    return _lip_sync_engine_v2


async def stop_lip_sync_engine():
    """停止嘴型同步引擎"""
    global _lip_sync_engine_v2

    if _lip_sync_engine_v2:
        await _lip_sync_engine_v2.stop()
        _lip_sync_engine_v2 = None
