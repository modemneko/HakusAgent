"""
Agent 工厂 - 负责创建不同类型的 Agent
"""

from typing import Optional
from ...schema.models import AgentConfig, AgentMode
from .base import BaseAgent
from .build import BuildAgent
from .plan import PlanAgent


class AgentFactory:
    """Agent 工厂"""
    
    _agents = {
        "build": BuildAgent,
        "plan": PlanAgent,
    }
    
    @classmethod
    def create(
        cls,
        agent_type: str,
        tool_registry,
        llm_client=None,
        config: Optional[AgentConfig] = None,
    ) -> BaseAgent:
        """创建 Agent"""
        agent_class = cls._agents.get(agent_type)
        if not agent_class:
            raise ValueError(f"Unknown agent type: {agent_type}")
        
        kwargs = {
            "tool_registry": tool_registry,
            "llm_client": llm_client,
        }
        
        if config:
            kwargs["config"] = config
        
        return agent_class(**kwargs)
    
    @classmethod
    def register(cls, name: str, agent_class: type):
        """注册 Agent 类型"""
        cls._agents[name] = agent_class
    
    @classmethod
    def list_agents(cls) -> list[str]:
        """列出所有可用的 Agent 类型"""
        return list(cls._agents.keys())