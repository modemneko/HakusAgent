"""
平台集成系统 - 支持 Bilibili、Discord、YouTube 等平台
"""

from .base import (
    BasePlatform,
    PlatformType,
    PlatformConfig,
    PlatformManager,
    platform_manager,
    PlatformError,
    PlatformMessage,
    SendMessage,
)

from .bilibili import (
    BilibiliConfig,
    BilibiliPlatform,
    Gift,
    Danmaku,
)

from .discord import (
    DiscordConfig,
    DiscordPlatform,
    VoiceState,
)

from .wechat import (
    WeChatConfig,
    WeChatPlatform,
)


__all__ = [
    # 基础
    "BasePlatform",
    "PlatformType",
    "PlatformConfig",
    "PlatformManager",
    "platform_manager",
    "PlatformError",
    "PlatformMessage",
    "SendMessage",
    
    # Bilibili
    "BilibiliConfig",
    "BilibiliPlatform",
    "Gift",
    "Danmaku",
    
    # Discord
    "DiscordConfig",
    "DiscordPlatform",
    "VoiceState",
    
    # WeChat
    "WeChatConfig",
    "WeChatPlatform",
]