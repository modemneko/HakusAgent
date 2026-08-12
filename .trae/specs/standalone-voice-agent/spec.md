# 独立语音 Agent Spec

## Why

当前语音通话通过 `agent_bridge.run_turn_stream()` 接入 Coding Agent（AgentCore），共享 session 和对话历史。这导致：
1. 语音对话会加载 Coding Agent 的全部上下文（工具定义、代码历史），增加延迟和 token 消耗
2. Coding Agent 的系统提示是为编程设计的，不适合自然对话
3. 工具调用事件会干扰语音流式输出
4. 语音对话的消息会污染 Coding Agent 的 session

需要构建一个**独立的语音 Agent**，直接调用 LLM API，有自己的对话历史和系统提示，仿 GPT-Live 的自然对话体验。

## What Changes

- **重写 VoiceAgent**：不再通过 `agent_bridge`，直接使用 OpenAI 兼容 API 调用 LLM
- **独立对话历史**：语音 Agent 维护自己的 message list，不共享 Coding Agent 的 session
- **GPT-Live 风格系统提示**：简短、口语化、有情感、有温度的对话风格
- **无工具调用**：语音 Agent 不执行任何工具，纯粹对话
- **VoiceCallHandler 解耦**：不再注入 `agent_bridge`，改为注入模型配置（api_key, base_url, model_name）

## Impact

- Affected code:
  - `src/hakusai_core/agent/voice_agent.py` — 完全重写
  - `src/hakusai_server/voice_call_handler.py` — 移除 agent_bridge 依赖，改用 VoiceAgent 直接调用
  - `src/hakusai_server/server.py` — WebSocket 端点改为传递模型配置而非 agent_bridge

## ADDED Requirements

### Requirement: 独立 LLM 调用

VoiceAgent SHALL 直接使用 OpenAI 兼容 API（`openai.AsyncOpenAI`）调用 LLM，不经过 `agent_bridge` 或 `AgentCore`。

#### Scenario: 语音对话独立调用 LLM
- **WHEN** 用户说话并完成 ASR 识别
- **THEN** VoiceAgent 直接向 LLM API 发起流式请求
- **AND** 不加载任何工具定义
- **AND** 不访问 Coding Agent 的 session 或历史

### Requirement: 独立对话历史

VoiceAgent SHALL 维护独立的对话历史，每个语音通话 session 有自己的 message list。

#### Scenario: 多轮语音对话上下文
- **WHEN** 用户在同一个语音通话中进行多轮对话
- **THEN** VoiceAgent 维护该 session 的消息历史（系统提示 + 用户/助手消息）
- **AND** 历史不与 Coding Agent 的 session 共享
- **AND** 通话结束后历史清除（不持久化）

#### Scenario: 语音对话不污染 Coding Agent
- **WHEN** 用户先进行语音对话，再使用 Coding Agent
- **THEN** Coding Agent 的 session 中不包含语音对话的消息

### Requirement: GPT-Live 风格系统提示

VoiceAgent SHALL 使用专为语音对话设计的系统提示，风格仿 GPT-Live：

```
你是 HakusAI 的语音助手，正在和用户进行实时语音对话。

核心原则：
1. 回复极简——通常 1-2 句话，不超过 3 句。像发语音消息一样简短。
2. 自然口语化——用"嗯"、"哦"、"啊"等语气词，不要书面语。
3. 有情感温度——感知用户情绪，适时共情、鼓励、调侃。
4. 不要 Markdown、代码块、列表、标题。
5. 不要说"作为AI助手"——你就是你。
6. 用户问编程问题，简短给方向，建议去聊天框详聊。
7. 不确定时坦诚说"我不太确定"，不要编造。
8. 用户沉默或犹豫时，可以主动接话或追问。
```

#### Scenario: 简短回复
- **WHEN** 用户说"今天天气怎么样"
- **THEN** VoiceAgent 回复 "今天天气挺好的，你出门了吗？" 而非长篇天气分析

#### Scenario: 情感共情
- **WHEN** 用户说"今天好累啊"
- **THEN** VoiceAgent 回复 "辛苦了，早点休息吧。要不要聊聊天放松一下？"

### Requirement: 上下文窗口管理

VoiceAgent SHALL 限制对话历史长度，超过阈值时自动截断旧消息：

- 保留系统提示 + 最近 10 轮对话（20 条消息）
- 超出时移除最早的非系统消息
- 单次 LLM 调用的 token 预算控制在 2000 以内

#### Scenario: 长对话自动截断
- **WHEN** 对话超过 10 轮
- **THEN** 最早的对话消息被移除
- **AND** 系统提示始终保留

## MODIFIED Requirements

### Requirement: VoiceAgent 类重写

原 VoiceAgent 通过 `agent_bridge.run_turn_stream()` 调用 Coding Agent。

新 VoiceAgent：
- `__init__(self, api_key, base_url, model_name, system_prompt)` — 接收 LLM 配置
- `chat_stream(user_text, session_id)` — 维护独立历史，直接调 LLM 流式 API
- `set_system_prompt(session_id, prompt)` — 动态更新系统提示（兼容 voice_call_handler 调用）
- 内部维护 `_sessions: Dict[str, List[Message]]` — 每个 session 的对话历史

### Requirement: VoiceCallHandler 初始化变更

- `_init_voice_agent` 不再从 `agent_bridge` 创建 VoiceAgent
- 改为从 `VoiceCallConfig` 中的 `llm_api_key`、`llm_base_url`、`llm_model_name` 创建
- `VoiceCallConfig` 新增字段：`llm_api_key: str`、`llm_base_url: str`、`llm_model_name: str`

### Requirement: server.py WebSocket 端点变更

`/api/voice/call` WebSocket 端点：
- 不再传递 `agent_bridge=self`
- 改为从 `config.model` 读取 `api_key`、`base_url`、`model_name` 传给 `VoiceCallConfig`
- `VoiceCallHandler(config=voice_call_config)` — 不传 agent_bridge

## REMOVED Requirements

### Requirement: VoiceAgent 依赖 agent_bridge

**Reason**: 语音对话不需要 Coding Agent 的工具、权限、编排器
**Migration**: VoiceAgent 直接使用 OpenAI 兼容 API，配置从 VoiceCallConfig 获取
