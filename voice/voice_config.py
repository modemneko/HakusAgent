import os
import json
from dataclasses import dataclass, field
from typing import Optional

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ASRConfig:
    provider: str = "funasr"
    model: str = "SenseVoiceSmall"
    sample_rate: int = 16000
    language: str = "auto"
    threshold: int = 600
    min_duration: float = 0.3
    silence_timeout: float = 1.0


@dataclass
class VoiceTTSConfig:
    provider: str = "bert-vits2"
    model_dir: str = ""
    voice_id: str = ""
    sample_rate: int = 22050
    output_dir: str = "./output"


@dataclass
class VoiceLiveConfig:
    enabled: bool = False
    character_name: str = "羽汐"


@dataclass
class VoiceConfig:
    asr: ASRConfig = field(default_factory=ASRConfig)
    tts: VoiceTTSConfig = field(default_factory=VoiceTTSConfig)
    live: VoiceLiveConfig = field(default_factory=VoiceLiveConfig)

    @classmethod
    def from_config(cls) -> "VoiceConfig":
        config = cls()

        voice_cfg = BASE_CONFIG.get("VOICE", {})

        if "asr" in voice_cfg:
            for k, v in voice_cfg["asr"].items():
                if k in ASRConfig.__dataclass_fields__:
                    setattr(config.asr, k, v)

        if "tts" in voice_cfg:
            for k, v in voice_cfg["tts"].items():
                if k in VoiceTTSConfig.__dataclass_fields__:
                    setattr(config.tts, k, v)

        if "live" in voice_cfg:
            for k, v in voice_cfg["live"].items():
                if k in VoiceLiveConfig.__dataclass_fields__:
                    setattr(config.live, k, v)

        return config

    @classmethod
    def from_file(cls, path: str = "voice_config.json") -> "VoiceConfig":
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> "VoiceConfig":
        config = cls()
        if "asr" in data:
            config.asr = ASRConfig(**{k: v for k, v in data["asr"].items() if k in ASRConfig.__dataclass_fields__})
        if "tts" in data:
            config.tts = VoiceTTSConfig(**{k: v for k, v in data["tts"].items() if k in VoiceTTSConfig.__dataclass_fields__})
        if "live" in data:
            config.live = VoiceLiveConfig(**{k: v for k, v in data["live"].items() if k in VoiceLiveConfig.__dataclass_fields__})
        return config

    def to_dict(self) -> dict:
        return {
            "asr": self.asr.__dict__,
            "tts": self.tts.__dict__,
            "live": self.live.__dict__,
        }
