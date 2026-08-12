"""
HakusAI 2.0 配置模块
"""

from .schema import (
    HakusAIConfig,
    default_config,
    ModelConfig,
    VoiceConfig,
    AvatarConfig,
    MemoryConfig,
    PlatformConfig,
    ServerConfig,
    CharacterConfig,
    ModelProvider,
    ASRProvider,
    TTSProvider,
    VADProvider,
    AvatarType,
    LogLevel,
)

from .manager import ConfigManager, config_manager

__all__ = [
    # 配置类
    "HakusAIConfig",
    "default_config",
    "ModelConfig",
    "VoiceConfig",
    "AvatarConfig",
    "MemoryConfig",
    "PlatformConfig",
    "ServerConfig",
    "CharacterConfig",
    # 枚举
    "ModelProvider",
    "ASRProvider",
    "TTSProvider",
    "VADProvider",
    "AvatarType",
    "LogLevel",
    # 管理器
    "ConfigManager",
    "config_manager",
]
