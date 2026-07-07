# HakusAI 2.0 Live2D 虚拟形象系统 - 使用指南

## 📋 概述

本项目集成了改进的 Live2D 控制系统，融合了 **Open-LLM-VTuber** 和 **ZerolanLiveRobot** 两个项目的优势：

### ✨ 核心特性

1. **高精度口型同步 (LipSyncEngine V2)**
   - RMS 音量分析（借鉴 ZerolanLiveRobot）
   - 指数移动平均平滑
   - 自适应灵敏度调节
   - 多遍滤波处理

2. **情感控制系统 (ExpressionController)**
   - 情感映射表（借鉴 Open-LLM-VTuber）
   - 自动眨眼、呼吸、待机动作
   - 鼠标视线追踪
   - 平滑过渡动画

3. **模型管理器 (Live2DModelManager)**
   - 多模型配置支持
   - 热切换功能
   - JSON 配置文件

4. **Web 架构 (WebLive2DAvatar)**
   - WebSocket 实时通信
   - 前端渲染，后端控制
   - 低延迟响应

---

## 🚀 快速开始

### 1. 配置 Live2D 模型

编辑 `src/hakusai_core/avatar/model_dict.json`：

```json
[
  {
    "name": "shizuku",
    "description": "雫 - Live2D模型",
    "url": "../live2d-models/shizuku/runtime/shizuku.model3.json",
    "emotionMap": {
      "neutral": 0,
      "joy": 3,
      "anger": 2,
      "sadness": 1
    }
  }
]
```

### 2. 在代码中使用

```python
from hakusai_core.avatar import (
    create_web_live2d_avatar,
    live2d_model_manager,
    EmotionType,
)

# 创建虚拟形象
avatar = await create_web_live2d_avatar(
    model_name="shizuku",
    websocket_send=your_ws_send_function
)

# 设置表情
avatar.set_emotion(EmotionType.JOY, intensity=0.8)

# 手动更新嘴型（通常由 LipSyncEngine 自动调用）
from hakusai_core.avatar import LipSyncData
avatar.update_lipsync(LipSyncData(mouth_open=0.7))

# 切换模型
await live2d_model_manager.set_model("mao_pro")
await avatar.load()
```

### 3. WebSocket 通信协议

#### 客户端 -> 服务端

```json
// 设置表情
{"action": "emotion", "emotion": "joy", "intensity": 0.8}

// 切换模型
{"action": "switch_model", "model_name": "mao_pro"}

// 打断当前对话
{"action": "interrupt"}
```

#### 服务端 -> 客户端

```json
// 发送音频 + 口型数据
{
  "action": "audio_chunk",
  "audio": "<base64 encoded wav>",
  "text": "你好世界",
  "format": "wav"
}

// 口型同步数据（V2 引擎）
{
  "action": "lip_sync",
  "data": [
    {"time": 0.0, "mouth_open": 0.5, "amplitude": 0.3},
    {"time": 0.02, "mouth_open": 0.8, "amplitude": 0.6}
  ],
  "engine_version": "v2"
}

// 表情更新
{
  "type": "expression",
  "expression": "3",
  "intensity": 0.8
}

// 模型配置
{
  "type": "set-model-and-conf",
  "model_info": {
    "name": "shizuku",
    "url": "...",
    "emotionMap": {...}
  }
}
```

---

## 🎛️ 高级配置

### LipSyncConfig（口型同步配置）

```python
from hakusai_core.avatar import LipSyncConfig

config = LipSyncConfig(
    sample_rate=22050,           # 采样率
    frame_duration_ms=20,        # 帧时长
    smoothing_factor=0.3,        # 平滑系数 (0-1)
    sensitivity=1.5,             # 全局灵敏度
    lip_sync_multiplier=3.0,     # 口型放大系数
    adaptive_sensitivity=True,   # 自适应灵敏度
)
```

### AnimationConfig（动画配置）

```python
from hakusai_core.avatar import AnimationConfig

config = AnimationConfig(
    auto_blink=True,
    blink_interval=(2.0, 5.0),     # 眨眼间隔范围
    auto_breath=True,
    breath_intensity=0.5,          # 呼吸强度
    mouse_tracking=True,
    tracking_smoothing=0.3,        # 追踪平滑度
)
```

---

## 🔧 架构图

```
┌─────────────────────────────────────────────┐
│              Frontend (Browser)              │
│  ┌─────────────────────────────────────┐    │
│  │       Live2D Model (Pixi.js/Cubism) │    │
│  └─────────────────────────────────────┘    │
│                    ↕ WebSocket               │
├─────────────────────────────────────────────┤
│              Backend (Python)                │
│                                             │
│  ┌──────────────┐  ┌────────────────────┐  │
│  │ VTuberWSHandler│  │  WebLive2DAvatar   │  │
│  └──────┬────────┘  └────────┬───────────┘  │
│         │                     │              │
│  ┌──────▼─────────────────────▼───────────┐ │
│  │        Avatar Subsystems               │ │
│  │  ┌─────────────┐ ┌─────────────────┐  │ │
│  │  │ LipSync V2  │ │ExpressionCtrl   │  │ │
│  │  │ • RMS分析    │ │ • 情感管理       │  │ │
│  │  │ • 平滑滤波   │ │ • 动作队列       │  │ │
│  │  │ • 自适应灵敏度│ │ • 自动行为       │  │ │
│  │  └─────────────┘ └─────────────────┘  │ │
│  │  ┌─────────────┐ ┌─────────────────┐  │ │
│  │  │ModelManager │ │ AudioAnalyzer    │  │ │
│  │  │ • 模型配置   │ │ • WAV解析        │  │ │
│  │  │ • 热切换     │ │ • 分贝转换       │  │ │
│  │  └─────────────┘ └─────────────────┘  │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## 📊 性能对比

| 特性 | Open-LLM-VTuber | ZerolanLiveRobot | **HakusAI 2.0 (Ours)** |
|------|----------------|-------------------|------------------------|
| 架构 | 前端渲染 | 本地OpenGL | **前端渲染 + 后端智能控制** |
| 口型精度 | ★★★☆☆ | ★★★★★ | **★★★★★** (RMS+EMA+自适应) |
| 情感系统 | ★★★★★ | ★★☆☆☆ | **★★★★★** (完整映射+自动行为) |
| 跨平台 | ★★★★★ | ★★☆☆☆ | **★★★★★** (纯Web) |
| 延迟 | 中等 | 极低 | **低** (优化后的流式管线) |
| 可扩展性 | 中等 | 低 | **高** (模块化设计) |

---

## 🎯 使用场景

### 场景 1: AI 虚拟主播

```python
# LLM 输出包含情感标签
response = "[joy] 大家好！今天我很开心能和大家聊天！"

# 自动提取情感并应用
avatar.set_emotion_from_text(response)

# TTS 生成音频后自动同步口型
lip_data = await lip_sync_engine.process_audio_file(audio_bytes)
ws_send({"action": "lip_sync", "data": lip_data})
```

### 场景 2: 实时语音对话

```python
async def handle_user_speech(audio_data):
    # ASR 识别文本
    text = await asr.transcribe(audio_data)

    # LLM 生成回复（流式）
    async for token in llm.stream(text):
        # 标点切分 -> TTS -> 口型同步
        sentence = splitter.feed(token)
        if sentence:
            audio = await tts.synthesize(sentence)
            lip_data = analyzer.analyze_audio_stream(audio)
            await ws_send({
                "action": "audio_chunk",
                "audio": base64encode(audio),
                "lip_sync": lip_data
            })
```

### 场景 3: 情感交互游戏

```python
# 用户点击角色
def on_click(x, y):
    avatar.on_click(x, y)  # 触发点击动作

# 根据对话内容动态调整表情
def update_emotion(sentiment_score):
    if sentiment_score > 0.8:
        avatar.set_emotion(EmotionType.JOY, 1.0)
    elif sentiment_score < -0.5:
        avatar.set_emotion(EmotionType.SADNESS, 0.8)
```

---

## 📝 API 参考

### 主要类

- `WebLive2DAvatar`: Web 端 Live2D 形象
- `ExpressionController`: 表情和动作控制器
- `LipSyncEngineV2`: 高级嘴型同步引擎
- `Live2DModelManager`: 模型配置管理器
- `AudioAnalyzer`: 音频分析工具

### 主要函数

- `create_web_live2d_avatar()`: 创建形象实例
- `get_lip_sync_engine()`: 获取全局口型引擎
- `live2d_model_manager`: 全局模型管理器

---

## 🐛 故障排除

### 问题：口型不同步

**解决方案**：
1. 检查 TTS 输出采样率是否与 `LipSyncConfig.sample_rate` 匹配
2. 调整 `smoothing_factor`（越小越平滑但延迟更高）
3. 启用 `adaptive_sensitivity` 自动适配

### 问题：表情不变化

**解决方案**：
1. 检查 `model_dict.json` 中的 `emotionMap` 配置
2. 确保使用正确的情感名称（小写）
3. 查看 WebSocket 消息是否正常发送

### 问题：性能问题

**优化建议**：
1. 减小 `frame_duration_ms`（降低帧率）
2. 关闭不必要的自动行为（`auto_blink=False`）
3. 使用 V1 引擎作为回退（更轻量）

---

## 🔗 相关资源

- [Open-LLM-VTuber](https://github.com/openLLM-VTuber/Open-LLM-VTuber): 原始灵感来源
- [ZerolanLiveRobot](https://github.com/ZeroLemon/ZerolanLiveRobot): 本地渲染参考
- [live2d-py](https://github.com/Arkueid/live2d-py): Python Live2D 库
- [Pixi.js](https://pixijs.com/): 前端渲染引擎推荐

---

## 📄 许可证

MIT License

---

**版本**: 2.0.0  
**更新日期**: 2026-05-05  
**作者**: HakusAI Team
