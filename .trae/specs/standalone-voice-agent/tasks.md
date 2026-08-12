# Tasks

- [x] Task 1: 重写 VoiceAgent 为独立 LLM 调用
  - [x] 重写 `src/hakusai_core/agent/voice_agent.py`：使用 `openai.AsyncOpenAI` 直接调用 LLM
  - [x] `__init__(self, api_key, base_url, model_name, system_prompt=None)` 接收 LLM 配置
  - [x] 内部维护 `_sessions: Dict[str, List[dict]]` 存储每个 session 的对话历史
  - [x] `chat_stream(user_text, session_id)` 维护历史并流式调用 LLM
  - [x] `set_system_prompt(session_id, prompt)` 动态更新系统提示
  - [x] GPT-Live 风格默认系统提示
  - [x] 对话历史上限 20 条消息（10 轮），超出自动截断
  - [x] session 结束时清理历史（`clear_session(session_id)` 方法）

- [x] Task 2: 扩展 VoiceCallConfig
  - [x] 在 `VoiceCallConfig` 中新增 `llm_api_key: str = ""`、`llm_base_url: str = ""`、`llm_model_name: str = ""`
  - [x] `agent_bridge` 参数保持可选（默认 None），向后兼容

- [x] Task 3: 修改 VoiceCallHandler
  - [x] `_init_voice_agent` 改为从 config 的 LLM 配置创建 VoiceAgent，不依赖 agent_bridge
  - [x] 注释掉 `_write_user_message_to_bridge` 和 `_write_assistant_message_to_bridge` 调用
  - [x] 在 `handle_connection` 结束时调用 `voice_agent.clear_session(session_id)` 清理历史

- [x] Task 4: 修改 server.py WebSocket 端点
  - [x] 从 `config.model` 读取 `api_key`、`base_url`、`model_name`
  - [x] 传递给 `VoiceCallConfig` 的 `llm_api_key`、`llm_base_url`、`llm_model_name`
  - [x] 不再传 `agent_bridge=self` 给 VoiceCallHandler

# Task Dependencies
- [Task 2] 无依赖，可独立执行
- [Task 1] 无依赖，可独立执行
- [Task 3] depends on [Task 1, Task 2]
- [Task 4] depends on [Task 2]
