import os
import threading
import asyncio
from typing import Optional, Dict, Any
import tempfile
import sounddevice as sd
import soundfile as sf
import numpy as np

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

# 全局sherpa-onnx TTS单例
_GLOBAL_SHERPA_ONNX_TTS = None
_SHERPA_ONNX_TTS_LOCK = threading.Lock()

class SherpaOnnxTTS:
    """sherpa-onnx本地TTS模型封装类（单例模式）"""
    
    def __new__(cls):
        global _GLOBAL_SHERPA_ONNX_TTS
        
        # 快速路径：如果模型已初始化，直接返回
        if _GLOBAL_SHERPA_ONNX_TTS is not None:
            return _GLOBAL_SHERPA_ONNX_TTS
        
        # 进入关键区域，确保线程安全
        with _SHERPA_ONNX_TTS_LOCK:
            # 双重检查锁定，防止在等待锁期间已经被其他线程初始化
            if _GLOBAL_SHERPA_ONNX_TTS is None:
                instance = super().__new__(cls)
                instance._initialize()
                _GLOBAL_SHERPA_ONNX_TTS = instance
        
        return _GLOBAL_SHERPA_ONNX_TTS
    
    def _initialize(self):
        """初始化sherpa-onnx TTS"""
        try:
            # 导入sherpa-onnx相关模块
            import sherpa_onnx
            import zipfile
            import requests
            
            # 获取配置
            model_dir = BASE_CONFIG["SHERPA_ONNX_MODEL_DIR"]
            voice = BASE_CONFIG["SHERPA_ONNX_VOICE"]
            
            # 验证模型目录是否存在
            if not os.path.exists(model_dir):
                logger.warning(f"TTS模型目录不存在: {model_dir}，将创建目录")
                os.makedirs(model_dir, exist_ok=True)
            
            # 检查必要的模型文件是否存在
            required_files = ["model.onnx", "lexicon.txt", "tokens.txt"]
            missing_files = [f for f in required_files if not os.path.exists(os.path.join(model_dir, f))]
            
            if missing_files:
                logger.info(f"缺少TTS模型文件: {missing_files}，将尝试自动下载")
                
                # 下载预训练模型（这里使用一个小型的中文TTS模型作为示例）
                model_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-zh-aishell3.tar.bz2"
                
                try:
                    import tempfile
                    import shutil
                    
                    # 下载模型压缩包
                    temp_file = tempfile.NamedTemporaryFile(suffix=".tar.bz2", delete=False)
                    temp_file_path = temp_file.name
                    temp_file.close()
                    
                    logger.info(f"正在下载TTS模型: {model_url}")
                    response = requests.get(model_url, stream=True)
                    response.raise_for_status()
                    
                    with open(temp_file_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    logger.info(f"模型下载完成，正在解压到: {model_dir}")
                    
                    # 解压模型文件
                    import tarfile
                    with tarfile.open(temp_file_path, "r:bz2") as tar:
                        # 提取所有文件到模型目录
                        tar.extractall(path=model_dir)
                    
                    # 清理临时文件
                    os.unlink(temp_file_path)
                    
                    logger.info("TTS模型下载和解压完成")
                    
                except Exception as download_error:
                    logger.error(f"下载TTS模型失败: {download_error}")
                    logger.warning("将使用sherpa-onnx的内置默认模型")
                    
            # 再次检查模型文件
            missing_files = [f for f in required_files if not os.path.exists(os.path.join(model_dir, f))]
            if missing_files:
                logger.warning(f"模型文件仍然缺少: {missing_files}，将尝试使用默认配置")
            
            try:
                # 创建VITS模型配置
                vits_config = sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=os.path.join(model_dir, "model.onnx"),
                    lexicon=os.path.join(model_dir, "lexicon.txt"),
                    tokens=os.path.join(model_dir, "tokens.txt"),
                    length_scale=1.0 / BASE_CONFIG["SHERPA_ONNX_SPEED"]  # speed与length_scale成反比
                )
                
                # 创建TTS模型配置
                model_config = sherpa_onnx.OfflineTtsModelConfig(
                    vits=vits_config,
                    provider=BASE_CONFIG["SHERPA_ONNX_DEVICE"],
                    num_threads=4
                )
                
                # 创建TTS配置
                tts_config = sherpa_onnx.OfflineTtsConfig(
                    model=model_config
                )
                
                # 初始化TTS生成器
                self.tts = sherpa_onnx.OfflineTts(config=tts_config)
                logger.info("✓ 使用完整配置初始化sherpa-onnx TTS成功")
                
            except Exception as init_error:
                logger.error(f"直接初始化TTS失败: {init_error}")
                logger.warning("将尝试使用简化配置")
                
                try:
                    # 尝试使用更简化的配置，只指定模型文件
                    vits_config = sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=os.path.join(model_dir, "model.onnx"),
                        tokens=os.path.join(model_dir, "tokens.txt") if os.path.exists(os.path.join(model_dir, "tokens.txt")) else "",
                        length_scale=1.0 / BASE_CONFIG["SHERPA_ONNX_SPEED"]
                    )
                    
                    model_config = sherpa_onnx.OfflineTtsModelConfig(
                        vits=vits_config,
                        provider=BASE_CONFIG["SHERPA_ONNX_DEVICE"]
                    )
                    
                    tts_config = sherpa_onnx.OfflineTtsConfig(
                        model=model_config
                    )
                    
                    self.tts = sherpa_onnx.OfflineTts(config=tts_config)
                    logger.info("✓ 使用简化配置初始化sherpa-onnx TTS成功")
                    
                except Exception as simplified_error:
                    logger.error(f"使用简化配置初始化TTS失败: {simplified_error}")
                    raise
            
            # 设置音频参数
            self.sample_rate = BASE_CONFIG.get("SHERPA_ONNX_SAMPLE_RATE", 22050)
            self.audio_format = BASE_CONFIG.get("SHERPA_ONNX_AUDIO_FORMAT", "WAV")
            
            logger.info("✓ sherpa-onnx本地TTS初始化完成")
            
        except ImportError as e:
            logger.error(f"导入sherpa-onnx失败: {e}")
            logger.info("请安装sherpa-onnx: pip install sherpa-onnx")
            # 不抛出异常，允许应用程序继续运行，但TTS功能不可用
        except Exception as e:
            logger.error(f"初始化sherpa-onnx TTS失败: {e}")
            logger.warning("TTS功能将不可用")
            # 不抛出异常，允许应用程序继续运行，但TTS功能不可用
    
    def generate_audio(self, text: str, speed: float = None, volume: float = None, pitch: float = None) -> any:
        """生成音频数据
        
        Args:
            text: 要转换为语音的文本
            speed: 语速，默认使用配置中的值
            volume: 音量，默认使用配置中的值
            pitch: 音调，默认使用配置中的值
            
        Returns:
            GeneratedAudio对象
        """
        try:
            # 使用默认值或传入的值
            speed = speed or BASE_CONFIG["SHERPA_ONNX_SPEED"]
            volume = volume or BASE_CONFIG["SHERPA_ONNX_VOLUME"]
            pitch = pitch or BASE_CONFIG["SHERPA_ONNX_PITCH"]
            
            logger.debug(f"生成TTS音频: 文本='{text[:20]}...' 语速={speed} 音量={volume} 音调={pitch}")
            
            # 生成音频 — pass speed to generate() as the 'speed' keyword
            # argument when supported by the sherpa-onnx version.  The
            # 'speed' parameter maps to length_scale internally (higher
            # speed → smaller length_scale).
            try:
                audio = self.tts.generate(text, speed=speed)
            except TypeError:
                # Older sherpa-onnx versions may not accept 'speed' kwarg;
                # fall back to text-only call.  Speed was already baked into
                # length_scale during _initialize(), so the init-time value
                # is used instead.
                logger.warning(
                    "sherpa-onnx generate() does not accept 'speed' kwarg; "
                    "using init-time length_scale. Per-call speed adjustment unavailable."
                )
                audio = self.tts.generate(text)
            
            logger.debug(f"生成的音频采样率: {audio.sample_rate}，音频长度: {len(audio.samples)} 样本")
            
            # Apply volume adjustment (not supported by sherpa-onnx API)
            if volume is not None and volume != 1.0:
                samples = np.array(audio.samples, dtype=np.float32) * volume
                # Reconstruct a GeneratedAudio-like object; sherpa-onnx returns
                # a named-tuple with .samples and .sample_rate
                audio = type(audio)(samples=samples, sample_rate=audio.sample_rate)
            
            # Pitch adjustment is not supported by the sherpa-onnx API at
            # either config or generate() level.  Log a warning so callers
            # are aware the parameter is silently ignored.
            if pitch is not None and pitch != 1.0:
                logger.warning(
                    "sherpa-onnx backend does not support pitch adjustment; "
                    "ignoring pitch=%.2f", pitch
                )
            
            return audio
            
        except Exception as e:
            logger.error(f"生成TTS音频失败: {e}")
            raise
    
    def _adjust_audio(self, audio: np.ndarray, speed: float, volume: float, pitch: float) -> np.ndarray:
        """调整音频参数
        
        Args:
            audio: 原始音频数据
            speed: 语速
            volume: 音量
            pitch: 音调
            
        Returns:
            调整后的音频数据
        """
        try:
            # 调整音量
            audio_adjusted = audio * volume
            
            # 调整语速（简单实现，实际可以使用更复杂的算法）
            if speed != 1.0:
                indices = np.arange(0, len(audio_adjusted), speed)
                audio_adjusted = np.interp(indices, np.arange(len(audio_adjusted)), audio_adjusted)
            
            # 调整音调（简单实现）
            if pitch != 1.0:
                import scipy.signal
                audio_adjusted = scipy.signal.resample(audio_adjusted, int(len(audio_adjusted) * (1.0 / pitch)))
            
            return audio_adjusted
            
        except Exception as e:
            logger.warning(f"调整音频参数失败，使用原始音频: {e}")
            return audio
    
    def save_to_file(self, audio: any, file_path: str) -> None:
        """保存音频到文件
        
        Args:
            audio: GeneratedAudio对象
            file_path: 输出文件路径
        """
        try:
            # 将音频样本转换为numpy数组
            audio_samples = np.array(audio.samples, dtype=np.float32)
            
            # 使用生成的音频的采样率
            sf.write(file_path, audio_samples, audio.sample_rate, format=self.audio_format)
            logger.debug(f"TTS音频已保存到: {file_path}")
            
        except Exception as e:
            logger.error(f"保存TTS音频失败: {e}")
            raise
    
    def play_audio(self, audio: any) -> None:
        """播放音频
        
        Args:
            audio: GeneratedAudio对象
        """
        try:
            if BASE_CONFIG["ENABLE_TTS_AUDIO_OUTPUT"]:
                # 将音频样本转换为numpy数组
                audio_samples = np.array(audio.samples, dtype=np.float32)
                
                logger.debug(f"播放TTS音频，时长: {len(audio_samples)/audio.sample_rate:.2f}秒")
                sd.play(audio_samples, audio.sample_rate)
                sd.wait()
                
        except Exception as e:
            logger.error(f"播放TTS音频失败: {e}")
            raise
    
    async def generate_and_play(self, text: str, speed: float = None, volume: float = None, pitch: float = None) -> Optional[str]:
        """异步生成并播放音频
        
        Args:
            text: 要转换为语音的文本
            speed: 语速
            volume: 音量
            pitch: 音调
            
        Returns:
            音频文件路径，如果生成失败则返回None
        """
        try:
            # 在后台线程中生成音频
            loop = asyncio.get_event_loop()
            audio = await loop.run_in_executor(
                None,
                self.generate_audio, text, speed, volume, pitch
            )
            
            # 保存到临时文件
            with tempfile.NamedTemporaryFile(suffix=f".{self.audio_format}", delete=False) as f:
                temp_file_path = f.name
            
            await loop.run_in_executor(None, self.save_to_file, audio, temp_file_path)
            
            # 播放音频
            await loop.run_in_executor(None, self.play_audio, audio)
            
            return temp_file_path
            
        except Exception as e:
            logger.error(f"生成并播放TTS音频失败: {e}")
            return None
