import os
import sys
import re
import json
import threading
import asyncio
import tempfile
from typing import Optional

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

_GLOBAL_BERT_VITS2_TTS = None
_BERT_VITS2_TTS_LOCK = threading.Lock()


class BertVITS2TTS:
    def __new__(cls):
        global _GLOBAL_BERT_VITS2_TTS

        if _GLOBAL_BERT_VITS2_TTS is not None:
            return _GLOBAL_BERT_VITS2_TTS

        with _BERT_VITS2_TTS_LOCK:
            if _GLOBAL_BERT_VITS2_TTS is None:
                instance = super().__new__(cls)
                instance._initialize()
                _GLOBAL_BERT_VITS2_TTS = instance

        return _GLOBAL_BERT_VITS2_TTS

    def _initialize(self):
        try:
            self.model_dir = BASE_CONFIG.get("BERT_VITS2_MODEL_DIR", "./models/tts/bert_vits2")
            self.gen_config_path = BASE_CONFIG.get("BERT_VITS2_GEN_CONFIG", "./configs/gen_config.json")
            self.output_dir = BASE_CONFIG.get("VOICE_OUTPUT_DIR", "./output")
            self.sample_rate = 22050
            self._generate_func = None
            self._ready = False

            if not os.path.exists(self.model_dir):
                logger.warning(f"BertVITS2 模型目录不存在: {self.model_dir}")
                logger.info("BertVITS2 TTS 功能将不可用")
                return

            if self.model_dir not in sys.path:
                sys.path.insert(0, self.model_dir)

            if not os.path.exists(self.gen_config_path):
                logger.warning(f"找不到 TTS 配置文件: {self.gen_config_path}")
                logger.info("BertVITS2 TTS 功能将不可用")
                return

            with open(self.gen_config_path, "r", encoding="utf-8") as f:
                gen_config = json.load(f)
            models = gen_config.get("models")
            if not models:
                raise ValueError(f"gen_config 中缺少 'models' 字段: {self.gen_config_path}")
            self.sample_rate = models[0].get("sampling_rate", 22050)

            self._ready = True
            logger.info(f"✓ BertVITS2 TTS 初始化完成 (采样率: {self.sample_rate})")

        except Exception as e:
            logger.error(f"BertVITS2 TTS 初始化失败: {e}")
            self._ready = False

    def _lazy_load_model(self):
        if self._generate_func is not None:
            return True

        try:
            from bert_vits2.ts_generator import generate_audio_standalone
            self._generate_func = generate_audio_standalone
            logger.info("✓ BertVITS2 模型懒加载成功")
            return True
        except ImportError as e:
            logger.error(f"BertVITS2 模型加载失败: {e}")
            return False

    def generate(self, text: str) -> Optional[str]:
        if not self._ready:
            logger.error("BertVITS2 TTS 未初始化")
            return None

        if not self._lazy_load_model():
            return None

        text = self._clean_text_for_tts(text)
        if not text.strip():
            return None

        os.makedirs(self.output_dir, exist_ok=True)
        output_path = f"{self.output_dir}/tts_{int(__import__('time').time() * 1000)}.wav"

        try:
            self._generate_func(text, output_path, self.gen_config_path)
            return output_path
        except Exception as e:
            logger.error(f"BertVITS2 生成失败: {e}")
            return None

    def _clean_text_for_tts(self, text: str) -> str:
        text = re.sub(r'[（(][^）)]*[）)]', '', text)
        text = re.sub(r'[【\[].*?[】\]]', '', text)
        text = re.sub(r'\[MSG_SPLIT\]', '', text)
        text = re.sub(r'\[戳一戳\]', '', text)
        text = re.sub(r'\[戳回去\]', '', text)
        text = re.sub(r'\[EMOJI:\d+\]', '', text)
        text = re.sub(r'&&[^&]+&&', '', text)
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9，。！？、；：""''\s\.\!\?\,\;\:\'\-\n]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) > 80:
            sentences = re.split(r'([。！？])', text)
            truncated = ""
            for i in range(0, len(sentences) - 1, 2):
                sentence = sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else '')
                if len(truncated) + len(sentence) > 80:
                    break
                truncated += sentence

            if not truncated.strip():
                truncated = text[:80]

            text = truncated.rstrip('。！？，、')

        return text

    async def generate_and_play(self, text: str, speed: float = None, volume: float = None, pitch: float = None) -> Optional[str]:
        try:
            loop = asyncio.get_event_loop()
            audio_path = await loop.run_in_executor(None, self.generate, text)

            if audio_path and BASE_CONFIG.get("ENABLE_TTS_AUDIO_OUTPUT", True):
                await loop.run_in_executor(None, self._play_audio, audio_path)

            return audio_path

        except Exception as e:
            logger.error(f"BertVITS2 生成并播放失败: {e}")
            return None

    def _play_audio(self, audio_path: str):
        try:
            import sounddevice as sd
            import soundfile as sf

            data, samplerate = sf.read(audio_path)
            logger.debug(f"播放 BertVITS2 音频，时长: {len(data) / samplerate:.2f}秒")
            sd.play(data, samplerate)
            sd.wait()
        except Exception as e:
            logger.error(f"播放 BertVITS2 音频失败: {e}")

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def audio_format(self) -> str:
        return "wav"
