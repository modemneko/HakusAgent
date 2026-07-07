"""
HakusAI 2.0 虚拟形象系统
提供 Live2D/VRM 虚拟形象控制功能

模块：
- base: 基础接口定义
- model_manager: Live2D 模型配置管理
- expression_controller: 表情和动作控制
- lip_sync: 嘴型同步引擎（V1，保留兼容）
- lip_sync_v2: 高级嘴型同步引擎 V2
- web_live2d: Web 端 Live2D 实现

使用示例：
```python
from hakusai_core.avatar import create_web_live2d_avatar, live2d_model_manager

# 创建形象
avatar = await create_web_live2d_avatar("shizuki", websocket_send=send_func)

# 设置表情
avatar.set_expression("joy", 0.8)

# 查看可用模型
print(live2d_model_manager.model_names)
```
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
)

from .model_manager import (
    ModelInfo,
    Live2DModelManager,
    live2d_model_manager,
)

from .expression_controller import (
    EmotionType,
    EmotionState,
    AnimationConfig,
    ExpressionController,
)

from .lip_sync import (
    LipSyncConfig as LipSyncConfigV1,
    LipSyncAnalyzer,
    LipSyncEngine,
    PhonemeMapper,
    get_lip_sync_engine as get_lip_sync_v1,
    stop_lip_sync_engine as stop_lip_sync_v1,
)

from .lip_sync_v2 import (
    LipSyncMode,
    LipSyncConfig,
    AudioAnalyzer,
    Smoother,
    AdaptiveSensitivity,
    LipSyncAnalyzerV2,
    LipSyncEngineV2,
    get_lip_sync_engine,
    stop_lip_sync_engine,
)

from .web_live2d import (
    Live2DConfig,
    WebLive2DAvatar,
    create_web_live2d_avatar,
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

    # 模型管理
    "ModelInfo",
    "Live2DModelManager",
    "live2d_model_manager",

    # 表情控制
    "EmotionType",
    "EmotionState",
    "AnimationConfig",
    "ExpressionController",

    # 口型同步 V1（兼容）
    "LipSyncConfigV1",
    "LipSyncAnalyzer",
    "LipSyncEngine",
    "PhonemeMapper",
    "get_lip_sync_v1",
    "stop_lip_sync_v1",

    # 口型同步 V2（推荐）
    "LipSyncMode",
    "LipSyncConfig",
    "AudioAnalyzer",
    "Smoother",
    "AdaptiveSensitivity",
    "LipSyncAnalyzerV2",
    "LipSyncEngineV2",
    "get_lip_sync_engine",
    "stop_lip_sync_engine",

    # Web Live2D
    "Live2DConfig",
    "WebLive2DAvatar",
    "create_web_live2d_avatar",
]
