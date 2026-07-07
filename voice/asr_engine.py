import threading
import os
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

FUNASR_AVAILABLE = False
try:
    from funasr import AutoModel
    FUNASR_AVAILABLE = True
except ImportError:
    pass

_GLOBAL_ASR_ENGINE = None
_ASR_ENGINE_LOCK = threading.Lock()


class ASREngine:
    def __new__(cls, model_name: str = "SenseVoiceSmall", language: str = "auto"):
        global _GLOBAL_ASR_ENGINE

        if _GLOBAL_ASR_ENGINE is not None:
            return _GLOBAL_ASR_ENGINE

        with _ASR_ENGINE_LOCK:
            if _GLOBAL_ASR_ENGINE is None:
                instance = super().__new__(cls)
                instance._initialize(model_name, language)
                _GLOBAL_ASR_ENGINE = instance

        return _GLOBAL_ASR_ENGINE

    def _initialize(self, model_name: str = "SenseVoiceSmall", language: str = "auto"):
        try:
            if not FUNASR_AVAILABLE:
                raise ImportError("FunASR 未安装，请运行: pip install funasr")

            self.model_name = model_name
            self.language = language
            self.model = None
            self._ready = False

            logger.info(f"正在加载 ASR 模型: {model_name}...")
            self.model = AutoModel(
                model=model_name,
                trust_remote_code=True,
                disable_update=True
            )
            self._ready = True
            logger.info(f"✓ ASR 模型加载完成: {model_name}")

        except ImportError as e:
            logger.error(f"ASR 初始化失败: {e}")
            logger.info("请安装 FunASR: pip install funasr modelscope")
            self._ready = False
        except Exception as e:
            logger.error(f"ASR 模型加载失败: {e}")
            self._ready = False

    def transcribe(self, audio_path: str) -> str:
        if not self._ready or not self.model:
            logger.error("ASR 未初始化，无法识别")
            return ""

        try:
            if not os.path.exists(audio_path):
                logger.error(f"音频文件不存在: {audio_path}")
                return ""

            result = self.model.generate(
                input=audio_path,
                cache={},
                language=self.language,
                use_itn=False
            )

            if result and len(result) > 0:
                text = result[0]['text']
                if ">" in text:
                    text = text.split(">")[-1]
                return text.strip()

            return ""

        except Exception as e:
            logger.error(f"ASR 识别失败: {e}")
            return ""

    def transcribe_bytes(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        try:
            import tempfile
            import wave

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name

            with wave.open(temp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data)

            text = self.transcribe(temp_path)

            try:
                os.unlink(temp_path)
            except Exception:
                pass

            return text

        except Exception as e:
            logger.error(f"ASR 字节识别失败: {e}")
            return ""

    @property
    def is_ready(self) -> bool:
        return self._ready

    def reset(self):
        global _GLOBAL_ASR_ENGINE
        with _ASR_ENGINE_LOCK:
            _GLOBAL_ASR_ENGINE = None
