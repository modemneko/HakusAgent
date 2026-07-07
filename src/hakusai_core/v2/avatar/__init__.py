"""
虚拟形象系统 - 支持 Live2D 和 VRM
"""

from .base import (
    BaseAvatar,
    AvatarType,
    AvatarPosition,
    LipSyncData,
    Expression,
    Motion,
    AvatarManager,
    avatar_manager,
    AvatarError,
)

from .live2d import (
    Live2DAvatar,
    WebLive2DAvatar,
    create_web_live2d_avatar,
)

from .vrm import (
    VRMAvatar,
    WebVRMAvatar,
    create_web_vrm_avatar,
)


__all__ = [
    # 基础
    "BaseAvatar",
    "AvatarType",
    "AvatarPosition",
    "LipSyncData",
    "Expression",
    "Motion",
    "AvatarManager",
    "avatar_manager",
    "AvatarError",
    
    # Live2D
    "Live2DAvatar",
    "WebLive2DAvatar",
    "create_web_live2d_avatar",
    
    # VRM
    "VRMAvatar",
    "WebVRMAvatar",
    "create_web_vrm_avatar",
]