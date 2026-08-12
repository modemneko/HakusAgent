"""
HakusAI 独立语音 Agent

直接使用 OpenAI 兼容 API 调用 LLM，不经过 agent_bridge / AgentCore。
维护独立的 per-session 对话历史，不共享 Coding Agent 的 session。
"""

import logging
from typing import AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)


# GPT-Live 风格系统提示 —— 简短、口语化、有情感温度
DEFAULT_VOICE_SYSTEM_PROMPT = """\
你是 HakusAI 的语音助手，正在和用户进行实时语音对话。

核心原则：
1. 回复极简——通常 1-2 句话，不超过 3 句。像发语音消息一样简短。
2. 自然口语化——用"嗯"、"哦"、"啊"等语气词，不要书面语。
3. 有情感温度——感知用户情绪，适时共情、鼓励、调侃。
4. 不要 Markdown、代码块、列表、标题。
5. 不要说"作为AI助手"——你就是你。
6. 用户问编程问题，简短给方向，建议去聊天框详聊。
7. 不确定时坦诚说"我不太确定"，不要编造。
8. 用户沉默或犹豫时，可以主动接话或追问。\
"""

# 对话历史上限（条消息数，不含系统提示）
_MAX_HISTORY_MESSAGES = 20


class VoiceAgent:
    """
    独立语音 Agent，直接调用 LLM API。

    - 不依赖 agent_bridge / AgentCore
    - 维护独立的 per-session 对话历史
    - 无工具调用，纯对话
    - GPT-Live 风格简短回复
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        model_name: str = "deepseek-chat",
        system_prompt: Optional[str] = None,
    ):
        """
        初始化 VoiceAgent。

        Args:
            api_key: LLM API Key
            base_url: LLM API Base URL（OpenAI 兼容）
            model_name: 模型名称
            system_prompt: 自定义系统提示（None 则使用默认 GPT-Live 风格提示）
        """
        from openai import AsyncOpenAI

        self._api_key = api_key
        self._base_url = base_url or None
        self._model_name = model_name
        self._default_system_prompt = system_prompt or DEFAULT_VOICE_SYSTEM_PROMPT
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=self._base_url,
        )
        # per-session 对话历史: {session_id: [{"role": "...", "content": "..."}, ...]}
        self._sessions: Dict[str, List[dict]] = {}
        self._agent_bridge = None

        logger.info(f"VoiceAgent 初始化完成: model={model_name}, base_url={base_url or 'default'}")

    def _get_messages(self, session_id: str) -> List[dict]:
        """获取 session 的完整消息列表（含系统提示）"""
        if session_id not in self._sessions:
            self._sessions[session_id] = [
                {"role": "system", "content": self._default_system_prompt}
            ]
        return self._sessions[session_id]

    def _trim_history(self, session_id: str):
        """截断对话历史，保留系统提示 + 最近 _MAX_HISTORY_MESSAGES 条消息"""
        messages = self._sessions.get(session_id, [])
        if len(messages) > _MAX_HISTORY_MESSAGES + 1:  # +1 for system prompt
            # 保留系统提示 + 最后 _MAX_HISTORY_MESSAGES 条
            self._sessions[session_id] = [messages[0]] + messages[-(_MAX_HISTORY_MESSAGES):]
            logger.debug(f"VoiceAgent: session {session_id} 历史已截断至 {_MAX_HISTORY_MESSAGES} 条")

    def set_system_prompt(self, session_id: str, prompt: str):
        """动态更新系统提示（兼容 voice_call_handler 调用）"""
        messages = self._get_messages(session_id)
        messages[0] = {"role": "system", "content": prompt}
        logger.debug(f"VoiceAgent: session {session_id} 系统提示已更新")

    def clear_session(self, session_id: str):
        """清理 session 的对话历史"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.debug(f"VoiceAgent: session {session_id} 历史已清理")

    async def chat_stream(
        self,
        user_text: str,
        session_id: str = "default",
    ) -> AsyncIterator[str]:
        """
        流式对话，yield 文本片段。

        直接调用 LLM API，维护独立对话历史。

        Args:
            user_text: 用户输入文本
            session_id: 会话 ID

        Yields:
            文本片段字符串
        """
        if not self._api_key:
            logger.error("VoiceAgent: api_key 未设置")
            yield "抱歉，语音服务未配置 API Key。"
            return

        # 获取/创建 session 历史
        messages = self._get_messages(session_id)

        # 添加用户消息
        messages.append({"role": "user", "content": user_text})

        # 截断历史
        self._trim_history(session_id)

        try:
            # 流式调用 LLM
            response = await self._client.chat.completions.create(
                model=self._model_name,
                messages=messages,
                stream=True,
                temperature=0.8,  # 稍高温度，让回复更自然多样
                max_tokens=300,   # 限制回复长度，保持简短
            )

            full_response = ""
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_response += text
                    yield text

            # 将助手回复添加到历史
            if full_response:
                messages.append({"role": "assistant", "content": full_response})
            else:
                # 如果 LLM 返回空，移除刚添加的用户消息
                messages.pop()
                logger.warning(f"VoiceAgent: session {session_id} LLM 返回空响应")

        except Exception as e:
            logger.error(f"VoiceAgent: LLM 调用失败: {e}")
            # 移除刚添加的用户消息（避免历史中有问无答）
            if messages and messages[-1].get("role") == "user":
                messages.pop()
            yield "抱歉，处理时出现错误，请稍后再试。"

    async def _post_correct_asr(self, text: str, session_id: str) -> str:
        """
        ASR 后纠正：结合对话历史消除同音异义错误。
        超时 2s 时跳过，返回原文。
        """
        if not text or len(text) < 2:
            return text

        # 获取最近 3 轮对话历史
        messages = self._sessions.get(session_id, [])
        # 过滤出非系统消息，取最后 6 条（3 轮）
        history_msgs = [m for m in messages if m.get("role") != "system"][-6:]
        if not history_msgs:
            return text  # 无历史不需要纠正

        # 构造历史摘要
        history_text = ""
        for m in history_msgs:
            role = "用户" if m["role"] == "user" else "AI"
            history_text += f"{role}: {m['content']}\n"

        try:
            import asyncio
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "根据对话历史，纠正语音识别结果中的同音异义错误。只输出纠正后的文本，不要解释，不要加引号。"
                        },
                        {
                            "role": "user",
                            "content": f"对话历史:\n{history_text}\n识别结果: {text}\n纠正后:"
                        }
                    ],
                    max_tokens=100,
                    temperature=0.1,
                    stream=False,
                ),
                timeout=2.0,
            )
            corrected = response.choices[0].message.content.strip()
            if corrected and corrected != text:
                logger.info(f"VoiceAgent: ASR后纠正 '{text}' -> '{corrected}'")
                return corrected
            return text
        except asyncio.TimeoutError:
            logger.warning(f"VoiceAgent: ASR后纠正超时，使用原文")
            return text
        except Exception as e:
            logger.warning(f"VoiceAgent: ASR后纠正失败: {e}")
            return text

    # 编程任务关键词
    _CODING_KEYWORDS = [
        "修", "fix", "bug", "写代码", "code", "创建文件", "create file",
        "运行", "run", "测试", "test", "重构", "refactor", "部署", "deploy",
        "错误", "error", "实现", "implement", "添加功能", "删除", "优化",
        "新建项目", "安装依赖", "编译", "build", "调试", "debug",
    ]

    def _detect_coding_intent(self, text: str) -> bool:
        """检测是否是编程任务意图"""
        text_lower = text.lower()
        for keyword in self._CODING_KEYWORDS:
            if keyword.lower() in text_lower:
                return True
        return False

    def set_agent_bridge(self, agent_bridge):
        """注入 agent_bridge（仅用于委派 Coding Agent）"""
        self._agent_bridge = agent_bridge

    async def delegate_to_coding_agent(
        self,
        text: str,
        session_id: str = "default",
    ) -> AsyncIterator[str]:
        """
        委派任务给 Coding Agent。
        
        yield 文本片段或进度标记：
        - 普通文本：LLM 生成的回答
        - "[PROGRESS]xxx"：进度播报文本
        """
        if not hasattr(self, '_agent_bridge') or self._agent_bridge is None:
            yield "抱歉，Coding Agent 未连接，无法处理编程任务。"
            return

        try:
            # 调用 agent_bridge.run_turn_stream
            async for event in self._agent_bridge.run_turn_stream(text, session_id):
                event_type = event.get("type", "")
                
                if event_type == "text_delta":
                    content = event.get("content", "")
                    if content:
                        yield content
                
                elif event_type == "tool_call_started":
                    tool_name = event.get("tool_name", "")
                    args = event.get("args", {})
                    
                    # 生成进度文本
                    if any(kw in tool_name.lower() for kw in ["write", "edit", "file", "create"]):
                        filename = args.get("path", args.get("file_path", args.get("filename", "")))
                        if filename:
                            # 只取文件名部分
                            filename = filename.split("/")[-1].split("\\")[-1]
                            yield f"[PROGRESS]我正在修改{filename}"
                        else:
                            yield "[PROGRESS]我正在修改文件"
                    elif any(kw in tool_name.lower() for kw in ["run", "exec", "bash", "command", "terminal"]):
                        yield "[PROGRESS]我正在执行命令"
                    elif any(kw in tool_name.lower() for kw in ["search", "grep", "find", "glob"]):
                        yield "[PROGRESS]我正在搜索"
                
                elif event_type == "turn_completed":
                    yield "[PROGRESS]完成了"
                
                elif event_type == "turn_failed":
                    error = event.get("error", "未知错误")
                    yield f"[PROGRESS]处理时出了点问题"
                
                elif event_type == "cancelled":
                    yield "[PROGRESS]任务已取消"
                    break

        except Exception as e:
            logger.error(f"VoiceAgent: 委派失败: {e}")
            yield f"[PROGRESS]处理时出了点问题"

    def _compress_history(self, messages: List[dict]) -> List[dict]:
        """
        Token 级压缩对话历史（P2 功能，当前仅设计）。
        
        使用 LLMLingua-2 将历史消息压缩至 40%。
        只压缩历史消息，不压缩系统提示。
        当对话 < 5 轮时不压缩。
        """
        # 分离系统提示和历史消息
        system_msgs = [m for m in messages if m.get("role") == "system"]
        history_msgs = [m for m in messages if m.get("role") != "system"]
        
        # 不足 5 轮（10 条消息）不压缩
        if len(history_msgs) < 10:
            return messages
        
        try:
            # TODO: 实现 LLMLingua-2 压缩
            # from llmlingua import PromptCompressor
            # compressor = PromptCompressor()
            # compressed = compressor.compress_prompt(...)
            logger.debug("VoiceAgent: token压缩未启用，返回原始消息")
            return messages
        except Exception as e:
            logger.warning(f"VoiceAgent: 压缩失败，使用原始消息: {e}")
            return messages
