"""
VoxCPM TTS 引擎
本地模型，支持 XPU 加速
"""

import sys
import os
import asyncio
from typing import Optional, Dict, Any
import logging

from ..base import BaseTTSEngine, TTSResult
from ..registry import register_tts

logger = logging.getLogger(__name__)


@register_tts("voxcpm")
class VoxCPMEngine(BaseTTSEngine):
    """VoxCPM TTS 引擎"""
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.config = config or {}
        self._engine = None
        self.voxcpm_path = self.config.get("voxcpm_path", r"D:\项目\HakusAI_chat\voxcpm")
        self.model_path = self.config.get("model_path", "./VoxCPM1.5/OpenBMB/VoxCPM1___5")
    
    @property
    def engine_name(self) -> str:
        return "voxcpm"
    
    async def initialize(self) -> bool:
        try:
            import torch
            
            original_cwd = os.getcwd()
            os.chdir(self.voxcpm_path)
            sys.path.insert(0, os.path.join(self.voxcpm_path, "VoxCPM", "src"))
            
            from voxcpm import VoxCPM
            self._engine = VoxCPM.from_pretrained(
                self.model_path,
                load_denoiser=False,
                optimize=False
            )
            
            tts_model = self._engine.tts_model
            device = self.config.get("device", "xpu")
            
            if device == "xpu" and hasattr(torch, 'xpu') and torch.xpu.is_available():
                device_name = f"xpu:{torch.xpu.current_device()}"
                self._engine.tts_model = tts_model.to(device_name)
                logger.info(f"VoxCPM moved to XPU: {device_name}")
            elif not torch.cuda.is_available():
                if torch.backends.mps.is_available():
                    self._engine.tts_model = tts_model.to("mps")
                else:
                    self._engine.tts_model = tts_model.to("cpu")
            
            os.chdir(original_cwd)
            self._initialized = True
            logger.info(f"VoxCPM initialized on {self._engine.tts_model.device}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize VoxCPM: {e}")
            return False
    
    async def synthesize(self, text: str, **kwargs) -> Optional[TTSResult]:
        if not self._initialized:
            success = await self.initialize()
            if not success:
                return None
        
        try:
            import numpy as np
            import soundfile as sf
            import io
            
            loop = asyncio.get_event_loop()
            
            def _generate():
                wav = self._engine.generate(
                    target_text=text,
                    cfg_value=kwargs.get("cfg_value", 1.8),
                    inference_timesteps=kwargs.get("inference_timesteps", 5),
                )
                return wav
            
            wav = await loop.run_in_executor(None, _generate)
            sample_rate = self._engine.tts_model.sample_rate
            
            buf = io.BytesIO()
            sf.write(buf, wav, sample_rate, format='WAV')
            buf.seek(0)
            audio_bytes = buf.read()
            
            return TTSResult(
                audio_data=audio_bytes,
                sample_rate=sample_rate,
                format="wav",
                text=text
            )
            
        except Exception as e:
            logger.error(f"VoxCPM synthesis failed: {e}")
            return None
