import threading
import asyncio
from typing import Optional, Dict, Any

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

# 全局TTS管理单例
_GLOBAL_TTS_MANAGER = None
_TTS_MANAGER_LOCK = threading.Lock()

class TTSManager:
    """TTS管理器，统一管理本地和API两种TTS模式"""
    
    def __new__(cls):
        global _GLOBAL_TTS_MANAGER
        
        # 快速路径：如果已初始化，直接返回
        if _GLOBAL_TTS_MANAGER is not None:
            return _GLOBAL_TTS_MANAGER
        
        # 进入关键区域，确保线程安全
        with _TTS_MANAGER_LOCK:
            # 双重检查锁定
            if _GLOBAL_TTS_MANAGER is None:
                instance = super().__new__(cls)
                instance._initialize()
                _GLOBAL_TTS_MANAGER = instance
        
        return _GLOBAL_TTS_MANAGER
    
    def _initialize(self):
        """初始化TTS管理器"""
        try:
            self.tts_type = BASE_CONFIG["TTS_TYPE"]
            self.tts_instance = None
            self.initialized = False
            
            # 根据TTS类型初始化对应的TTS实例
            if self.tts_type == "sherpa-onnx":
                from .sherpa_onnx_tts import SherpaOnnxTTS
                self.tts_instance = SherpaOnnxTTS()
            elif self.tts_type == "api":
                from .api_tts import ApiTTS
                self.tts_instance = ApiTTS()
            elif self.tts_type == "cosyvoice":
                from .cosyvoice_tts import CosyVoiceTTS
                self.tts_instance = CosyVoiceTTS()
            elif self.tts_type == "bert-vits2":
                from voice.bert_vits2_tts import BertVITS2TTS
                self.tts_instance = BertVITS2TTS()
            else:
                logger.error(f"不支持的TTS类型: {self.tts_type}")
                return
            
            self.initialized = True
            logger.info(f"✓ TTS管理器初始化完成，使用TTS类型: {self.tts_type}")
            
        except Exception as e:
            logger.error(f"初始化TTS管理器失败: {e}")
            self.initialized = False
    
    async def generate_and_play(self, text: str, speed: float = None, volume: float = None, pitch: float = None) -> Optional[str]:
        """生成并播放音频
        
        Args:
            text: 要转换为语音的文本
            speed: 语速（仅本地TTS支持）
            volume: 音量（仅本地TTS支持）
            pitch: 音调（仅本地TTS支持）
            
        Returns:
            音频文件路径，如果生成失败则返回None
        """
        try:
            if not self.initialized or not self.tts_instance:
                logger.error("TTS未初始化，无法生成音频")
                return None
            
            if not text or not text.strip():
                logger.warning("空文本，跳过TTS生成")
                return None
            
            logger.debug(f"生成TTS音频: {text[:20]}...")
            
            # 根据TTS类型调用不同的方法
            if self.tts_type == "sherpa-onnx":
                return await self.tts_instance.generate_and_play(text, speed, volume, pitch)
            elif self.tts_type == "api":
                return await self.tts_instance.generate_and_play(text)
            elif self.tts_type == "cosyvoice":
                return await self.tts_instance.generate_and_play(text, speed, volume, pitch)
            elif self.tts_type == "bert-vits2":
                return await self.tts_instance.generate_and_play(text, speed, volume, pitch)
            else:
                logger.error(f"不支持的TTS类型: {self.tts_type}")
                return None
                
        except Exception as e:
            logger.error(f"生成TTS音频失败: {e}")
            return None
    
    async def generate_audio(self, text: str, speed: float = None, volume: float = None, pitch: float = None) -> Optional[str]:
        """仅生成音频文件，不播放
        
        Args:
            text: 要转换为语音的文本
            speed: 语速（仅本地TTS支持）
            volume: 音量（仅本地TTS支持）
            pitch: 音调（仅本地TTS支持）
            
        Returns:
            音频文件路径，如果生成失败则返回None
        """
        try:
            if not self.initialized or not self.tts_instance:
                logger.error("TTS未初始化，无法生成音频")
                return None
            
            if not text or not text.strip():
                logger.warning("空文本，跳过TTS生成")
                return None
            
            logger.debug(f"生成TTS音频文件: {text[:20]}...")
            
            # 根据TTS类型调用不同的方法
            if self.tts_type == "sherpa-onnx":
                # 生成音频数据
                audio = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.tts_instance.generate_audio, text, speed, volume, pitch
                )
                
                # 保存到临时文件
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=f".{self.tts_instance.audio_format}", delete=False) as f:
                    temp_file_path = f.name
                
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.tts_instance.save_to_file, audio, temp_file_path
                )
                
                return temp_file_path
            elif self.tts_type == "api":
                return await self.tts_instance.generate_audio(text)
            elif self.tts_type == "cosyvoice":
                # 生成音频数据
                audio_data = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.tts_instance.generate_audio, text
                )

                if not audio_data:
                    return None

                # 保存到临时文件
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    temp_file_path = f.name

                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.tts_instance.save_to_file, audio_data, temp_file_path
                )

                return temp_file_path
            elif self.tts_type == "bert-vits2":
                return await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.tts_instance.generate, text
                )
            else:
                logger.error(f"不支持的TTS类型: {self.tts_type}")
                return None
                
        except Exception as e:
            logger.error(f"生成TTS音频文件失败: {e}")
            return None
    
    def is_initialized(self) -> bool:
        """检查TTS是否已初始化
        
        Returns:
            True如果TTS已初始化，否则False
        """
        return self.initialized
    
    def get_tts_type(self) -> str:
        """获取当前使用的TTS类型
        
        Returns:
            TTS类型字符串
        """
        return self.tts_type


# 创建TTS管理器实例的便捷函数
def get_tts_manager() -> TTSManager:
    """获取TTS管理器实例
    
    Returns:
        TTS管理器实例
    """
    return TTSManager()
