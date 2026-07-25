"""
平台集成系统 - 支持 WeChat 等平台
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

from .wechat import (
    WeChatConfig,
    WeChatPlatform,
)

# bilibili/discord removed — not yet implemented


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

    # WeChat
    "WeChatConfig",
    "WeChatPlatform",
]