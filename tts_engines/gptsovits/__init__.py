"""
GPT-SoVITS TTS 引擎适配器 (v2)
支持零样本 TTS (5秒参考音频) 和少样本微调 TTS
可运行在 CPU 模式（速度较慢但可用）

官方仓库: https://github.com/RVC-Boss/GPT-SoVITS
"""

import os
import sys
import asyncio
import subprocess
import requests
import tempfile
from typing import Optional, Dict, Any, List
import logging
import time

from ..base import BaseTTSEngine, TTSResult
from ..registry import register_tts

logger = logging.getLogger(__name__)


@register_tts("gptsovits")
class GPTSoVITSEngine(BaseTTSEngine):
    """GPT-SoVITS v2 TTS 引擎"""
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.config = config or {}
        self.server_url = self.config.get("server_url", "http://127.0.0.1:9880")
        self.ref_audio_path = self.config.get("ref_audio_path", "")
        self.ref_text = self.config.get("ref_text", "")
        self.language = self.config.get("language", "zh")
        self.gpt_model_path = self.config.get("gpt_model_path", "")
        self.sovits_model_path = self.config.get("sovits_model_path", "")
        self._server_process = None
    
    @property
    def engine_name(self) -> str:
        return "gptsovits"
    
    async def initialize(self) -> bool:
        try:
            gptsovits_path = self.config.get(
                "gptsovits_path",
                r"D:\项目\HakusAI_chat\tts_engines\models\GPT-SoVITS"
            )
            
            if not os.path.exists(gptsovits_path):
                logger.warning(f"GPT-SoVITS path not found: {gptsovits_path}")
                logger.info("Please run: git clone https://github.com/RVC-Boss/GPT-SoVITS")
                return False
            
            pretrained_dir = os.path.join(gptsovits_path, "GPT_SoVITS", "pretrained_models", "gsv-v2final-pretrained")
            if not os.path.exists(pretrained_dir):
                logger.warning(f"Pretrained models not found: {pretrained_dir}")
                logger.info("Please download from: https://huggingface.co/lj1995/GPT-SoVITS-v2")
                return False
            
            if not self.config.get("auto_start_server", True):
                logger.info("GPT-SoVITS server auto-start disabled")
                self._initialized = True
                return True
            
            import torch
            device = "cpu"
            if torch.cuda.is_available():
                device = "cuda"
            
            python_exe = sys.executable
            server_script = os.path.join(gptsovits_path, "api.py")
            if not os.path.exists(server_script):
                server_script = os.path.join(gptsovits_path, "GPT_SoVITS", "api.py")
            
            if not os.path.exists(server_script):
                logger.error(f"api.py not found in {gptsovits_path}")
                return False
            
            env = os.environ.copy()
            env["is_half"] = "false" if device == "cpu" else "true"
            
            cmd = [python_exe, server_script, "--device", device, "--port", "9880"]
            
            logger.info(f"Starting GPT-SoVITS API server (device={device})...")
            
            self._server_process = subprocess.Popen(
                cmd,
                cwd=gptsovits_path,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            logger.info("Waiting for GPT-SoVITS server to start (this may take 30-60s on CPU)...")
            for i in range(30):
                await asyncio.sleep(2)
                try:
                    response = requests.get(f"{self.server_url}/ping", timeout=3)
                    if response.status_code == 200:
                        logger.info("GPT-SoVITS server started successfully")
                        self._initialized = True
                        return True
                except requests.exceptions.ConnectionError:
                    pass
            
            logger.warning("Server may still be starting, will try on first request")
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize GPT-SoVITS: {e}")
            return False
    
    async def synthesize(self, text: str, **kwargs) -> Optional[TTSResult]:
        if not self._initialized:
            success = await self.initialize()
            if not success:
                return None
        
        ref_audio = kwargs.get("ref_audio_path", self.ref_audio_path)
        ref_text = kwargs.get("ref_text", self.ref_text)
        language = kwargs.get("language", self.language)
        
        if not ref_audio or not os.path.exists(ref_audio):
            logger.error("Reference audio path is required and must exist")
            return None
        
        if not ref_text:
            logger.error("Reference text is required")
            return None
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                url = f"{self.server_url}"
                
                payload = {
                    "text": text,
                    "text_lang": language,
                    "ref_audio_path": ref_audio,
                    "prompt_text": ref_text,
                    "prompt_lang": language,
                }
                
                loop = asyncio.get_event_loop()
                
                def _post():
                    response = requests.post(url, json=payload, timeout=180)
                    response.raise_for_status()
                    return response.content
                
                audio_data = await loop.run_in_executor(None, _post)
                
                if audio_data and len(audio_data) > 0:
                    return TTSResult(
                        audio_data=audio_data,
                        sample_rate=32000,
                        format="wav",
                        text=text
                    )
                else:
                    logger.error("GPT-SoVITS returned empty audio")
                    return None
                    
            except Exception as e:
                logger.error(f"GPT-SoVITS synthesis failed (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                else:
                    return None
        
        return None
    
    async def synthesize_with_ref(self, text: str, ref_audio_path: str, ref_text: str, **kwargs) -> Optional[TTSResult]:
        """零样本 TTS：使用参考音频直接合成"""
        return await self.synthesize(
            text,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            **kwargs
        )
    
    async def list_voices(self) -> List[Dict[str, str]]:
        return [{"id": "zero_shot", "name": "零样本 TTS", "description": "需要参考音频"}]
    
    async def close(self):
        if self._server_process:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5)
            except Exception:
                self._server_process.kill()
            self._server_process = None
        await super().close()
