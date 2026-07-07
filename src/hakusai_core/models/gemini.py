"""
HakusAI 2.0 Google Gemini 模型适配器
"""

import logging
from typing import AsyncIterator, Dict, List, Optional, Any

from .base import (
    BaseModelAdapter,
    Message,
    ChatOptions,
    ChatResponse,
    ToolDefinition,
    register_model,
)

logger = logging.getLogger(__name__)


@register_model("gemini")
class GeminiAdapter(BaseModelAdapter):
    """
    Google Gemini 模型适配器
    
    支持模型：
    - gemini-1.5-flash
    - gemini-1.5-pro
    - gemini-1.0-pro
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._model = None
        
    @property
    def provider_name(self) -> str:
        return "gemini"
    
    async def initialize(self):
        """初始化Gemini客户端"""
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai not installed. Run: pip install google-generativeai")
        
        if not self.api_key:
            raise ValueError("Gemini API key is required")
        
        # 配置API密钥
        genai.configure(api_key=self.api_key)
        
        # 创建模型实例
        generation_config = {
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
        }
        
        self._model = genai.GenerativeModel(
            model_name=self.model_name,
            generation_config=generation_config,
        )
        
        logger.info(f"Gemini adapter initialized with model: {self.model_name}")
    
    async def chat(
        self,
        messages: List[Message],
        options: Optional[ChatOptions] = None
    ) -> ChatResponse:
        """
        非流式对话
        
        Args:
            messages: 消息列表
            options: 聊天选项
            
        Returns:
            聊天响应
        """
        if not self._model:
            await self.initialize()
        
        if options is None:
            options = ChatOptions()
        
        # 转换消息格式
        history = self._convert_messages(messages[:-1]) if len(messages) > 1 else []
        current_message = self._convert_message(messages[-1]) if messages else ""
        
        # 开始聊天
        chat = self._model.start_chat(history=history)
        
        # 发送消息
        response = chat.send_message(current_message)
        
        return ChatResponse(
            content=response.text,
            usage={
                "prompt_tokens": response.usage_metadata.prompt_token_count if hasattr(response, 'usage_metadata') else 0,
                "completion_tokens": response.usage_metadata.candidates_token_count if hasattr(response, 'usage_metadata') else 0,
                "total_tokens": response.usage_metadata.total_token_count if hasattr(response, 'usage_metadata') else 0,
            },
            model=self.model_name,
            finish_reason="stop" if response.candidates else "error",
        )
    
    async def chat_stream(
        self,
        messages: List[Message],
        options: Optional[ChatOptions] = None
    ) -> AsyncIterator[str]:
        """
        流式对话
        
        Args:
            messages: 消息列表
            options: 聊天选项
            
        Yields:
            生成的文本片段
        """
        if not self._model:
            await self.initialize()
        
        if options is None:
            options = ChatOptions()
        
        # 转换消息格式
        history = self._convert_messages(messages[:-1]) if len(messages) > 1 else []
        current_message = self._convert_message(messages[-1]) if messages else ""
        
        # 开始聊天
        chat = self._model.start_chat(history=history)
        
        # 发送流式消息
        response = chat.send_message(current_message, stream=True)
        
        for chunk in response:
            if chunk.text:
                yield chunk.text
    
    def _convert_messages(self, messages: List[Message]) -> List[Dict]:
        """转换消息列表为Gemini格式"""
        history = []
        for msg in messages:
            role = "user" if msg.role.value in ["user", "system"] else "model"
            history.append({
                "role": role,
                "parts": [msg.content]
            })
        return history
    
    def _convert_message(self, message: Message) -> str:
        """转换单条消息"""
        return message.content
    
    def supports_tools(self) -> bool:
        """Gemini支持工具调用"""
        return True
    
    def supports_vision(self) -> bool:
        """Gemini支持视觉输入"""
        return True
    
    def supports_streaming(self) -> bool:
        """Gemini支持流式输出"""
        return True
