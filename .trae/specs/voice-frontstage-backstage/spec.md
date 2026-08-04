# 语音前台/后台分离与压缩推理 Spec

## Why

当前语音通话管线是纯线性阻塞式：`VAD → ASR → LLM 流式(等待首个 token) → 句切分 → TTS → 音频推送`。用户说完话后，需要等待 LLM 首个 token（1-5 秒）+ TTS 合成（1-3 秒）才能听到回应，总延迟 2-8 秒，体验不佳。

两篇文章提供了明确的技术方向：
1. **GPT-Live / TML 的前台-后台分离架构**：前台模型负责即时响应（填充语、简单回答），后台模型负责复杂推理，中间有调度层决定何时衔接
2. **ECoM Reasoning 的压缩推理**：将完整推理链压缩至 40% token，首帧延迟从 4.9s 降至 1.6s

## What Changes

- **新增前台快速响应层**：ASR 完成后，根据用户意图分类，立即决定是直接回答还是先发填充语
- **新增后台推理调度器**：复杂问题在后台推理，前台同步播放填充语，推理完成后无缝衔接
- **压缩推理 prompt**：语音模式下使用压缩推理系统提示，减少 LLM 输出 token 数量，降低首句延迟
- **新增语音场景模式**：companion（陪伴）/ assistant（助手）/ balanced（均衡），不同模式调整 VAD 参数、系统提示、TTS 语速
- **优化 SentenceSplitter**：首句最小长度缩短，让第一个 TTS 请求尽快发出

## Impact

- Affected code:
  - `src/hakusai_server/voice_call_handler.py` — 核心管线重构
  - `src/hakusai_core/agent/voice_agent.py` — 增加意图分类和压缩推理
  - `src/hakusai_core/config/schema.py` — 新增场景模式配置
  - `frontend/client/src/lib/voiceCall.ts` — 前端处理填充语状态
  - `frontend/client/src/components/chat/ChatView.tsx` — 场景模式 UI

## ADDED Requirements

### Requirement: 前台快速响应层

系统 SHALL 在 ASR 识别完成后、LLM 推理开始前，对用户输入进行意图分类，分为简单/复杂两类：
- 简单意图（问候、简单事实、指令）：跳过填充语，直接进入 LLM 流式响应
- 复杂意图（推理、计算、长文生成）：先播放填充语（如"让我想想…"），同时后台启动 LLM 推理

#### Scenario: 简单问候快速响应
- **WHEN** 用户说"你好"
- **THEN** 系统在 500ms 内开始 TTS 播放回应，无填充语

#### Scenario: 复杂问题后台推理
- **WHEN** 用户说"帮我算一下 123 乘以 456 等于多少"
- **THEN** 系统在 300ms 内播放填充语"让我想想…"
- **AND** 后台并行启动 LLM 推理
- **AND** 推理完成后无缝切换到实际回答的 TTS 播放

### Requirement: 压缩推理模式

系统 SHALL 在语音通话模式下使用压缩推理系统提示，使 LLM 输出更简洁的推理过程：
- 移除冗余解释和过渡语句
- 保留核心推理骨架（关键步骤、计算过程）
- 最终回答保持自然口语化

#### Scenario: 压缩推理减少延迟
- **WHEN** 用户问"北京到上海高铁大概多久"
- **THEN** LLM 输出 "北京到上海高铁约 4.5 小时，复兴号最快 4 小时 18 分" 而非长篇推理
- **AND** 首句 TTS 音频在 1.5s 内开始播放

### Requirement: 语音场景模式

系统 SHALL 支持三种语音场景模式，每种模式有不同的参数配置：

| 模式 | VAD 静音阈值 | LLM 系统提示风格 | TTS 语速 | 填充语 | 打断灵敏度 |
|------|-------------|----------------|---------|--------|-----------|
| companion | 800ms | 温暖、耐心、有情感 | 0.9x | 启用 | 低 |
| assistant | 400ms | 简洁、精确、高效 | 1.1x | 禁用 | 高 |
| balanced | 600ms | 自然、均衡 | 1.0x | 启用 | 中 |

#### Scenario: 切换场景模式
- **WHEN** 用户在前端设置中选择"陪伴模式"
- **THEN** VAD 静音判定延长到 800ms（给用户更多思考时间）
- **AND** LLM 系统提示变为温暖耐心风格
- **AND** TTS 语速降低到 0.9x

### Requirement: 填充语音频预缓存

系统 SHALL 预先生成并缓存常用填充语音频，避免实时 TTS 合成延迟：
- "让我想想…" / "嗯…" / "好的，我看看…" 等
- 按 TTS voice 缓存，切换 voice 时重新生成

#### Scenario: 填充语即时播放
- **WHEN** 系统决定需要填充语
- **THEN** 从缓存中立即取出预生成音频播放，延迟 < 50ms

## MODIFIED Requirements

### Requirement: 语音通话管线流程

原流程：`ASR → LLM流式 → 句切分 → TTS → 音频`

新流程：
```
ASR → 意图分类 →
  ├─ 简单 → LLM流式 → 句切分 → TTS → 音频
  └─ 复杂 → 播放填充语(缓存) → LLM流式(后台) → 句切分 → TTS → 音频
```

### Requirement: SentenceSplitter 首句优化

首句最小长度从 4 字符降至 2 字符，让第一个 TTS 请求尽快发出。对于简单回答（如"好的"、"是的"），可以立即触发 TTS。

### Requirement: VoiceCallConfig 扩展

新增字段：
- `voice_mode: str = "balanced"` — 语音场景模式
- `enable_filler: bool = True` — 是否启用填充语
- `enable_compressed_reasoning: bool = True` — 是否启用压缩推理
- `filler_phrases: list = ["让我想想…", "嗯…", "好的，我看看…"]` — 填充语列表
