"""
TTS 引擎统一包
支持多种 TTS 后端:
- Edge TTS (微软在线)
- CosyVoice (阿里百炼)
- VoxCPM (本地模型)
- GPT-SoVITS (本地模型)
- Sherpa ONNX (本地模型)
"""

from .base import BaseTTSEngine, TTSResult
from .registry import tts_registry

__all__ = ["BaseTTSEngine", "TTSResult", "tts_registry"]
