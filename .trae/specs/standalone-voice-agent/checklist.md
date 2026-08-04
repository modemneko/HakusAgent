# Checklist

- [x] VoiceAgent 使用 openai.AsyncOpenAI 直接调用 LLM，不经过 agent_bridge
- [x] VoiceAgent 维护独立的 per-session 对话历史
- [x] VoiceAgent 默认系统提示是 GPT-Live 风格（简短、口语化、有情感）
- [x] VoiceAgent 不加载任何工具定义
- [x] 对话历史超过 20 条消息时自动截断
- [x] VoiceCallConfig 新增 llm_api_key、llm_base_url、llm_model_name 字段
- [x] VoiceCallHandler 不再依赖 agent_bridge
- [x] VoiceCallHandler 不再调用 _write_user_message_to_bridge / _write_assistant_message_to_bridge
- [x] 通话结束时清理 VoiceAgent 的 session 历史
- [x] server.py 从 config.model 读取 LLM 配置传给 VoiceCallConfig
- [x] server.py 不再传 agent_bridge=self 给 VoiceCallHandler
- [x] 语音对话消息不出现在 Coding Agent 的 session 中
