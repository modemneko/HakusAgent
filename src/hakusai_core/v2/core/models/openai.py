"""
OpenAI 客户端 - 支持 OpenAI 和兼容 API
"""

from typing import AsyncIterator, Optional
import aiohttp
from .base import LLMClient
from ...schema.models import Message, ModelConfig


class OpenAIClient(LLMClient):
    """OpenAI 客户端"""
    
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url
    
    async def chat(
        self,
        messages: list[Message],
        config: ModelConfig,
    ) -> AsyncIterator[str]:
        """流式对话"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": config.model,
            "messages": [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": True,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    raise Exception(f"OpenAI API error: {error}")
                
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        try:
                            import json
                            chunk = json.loads(data)
                            if 'choices' in chunk and chunk['choices']:
                                delta = chunk['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    yield delta['content']
                        except json.JSONDecodeError:
                            continue
    
    async def chat_completion(
        self,
        messages: list[Message],
        config: ModelConfig,
    ) -> str:
        """非流式对话"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": config.model,
            "messages": [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": False,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    raise Exception(f"OpenAI API error: {error}")
                
                result = await response.json()
                return result['choices'][0]['message']['content']