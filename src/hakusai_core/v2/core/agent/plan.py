"""
Plan Agent - 借鉴 OpenCode 的 plan Agent 设计
只读分析 Agent，可以读取文件但不能修改
"""

from typing import AsyncIterator
from ...schema.models import AgentConfig, AgentMode, Message
from .base import BaseAgent


class PlanAgent(BaseAgent):
    """Plan Agent - 只读分析 Agent"""
    
    def __init__(self, **kwargs):
        config = AgentConfig(
            name="plan",
            mode=AgentMode.PLAN,
            permissions={
                "read": "allow",
                "glob": "allow",
                "grep": "allow",
                "web_search": "allow",
                "web_fetch": "allow",
                "write": "deny",
                "edit": "deny",
                "bash": "deny",
                "git_*": "deny",
            },
            max_iterations=20,
        )
        super().__init__(config=config, **kwargs)
    
    def get_system_prompt(self) -> str:
        """获取系统提示词"""
        return """You are a planning and analysis AI agent built by HakusAI.

Your role is to analyze codebases and create detailed plans for implementation.

You have READ-ONLY access to:
1. **File Operations**: Read files (no write/edit)
2. **Search**: Find files and search content
3. **Web**: Fetch and search the web for documentation

Your responsibilities:
1. Understand the user's requirements
2. Explore the codebase to understand the current state
3. Identify what needs to be changed
4. Create a detailed, step-by-step implementation plan
5. Consider potential risks and mitigation strategies

Output format:
- Start with a summary of the task
- List all files that need to be modified or created
- Provide detailed steps for each change
- Include testing recommendations
- Note any dependencies or prerequisites

Remember: You CANNOT make changes. Only analyze and plan."""
    
    async def execute(self, task: str) -> str:
        """执行任务"""
        self.add_message("user", task)
        
        # 简化的执行循环
        # 实际实现应该包含 LLM 调用
        iterations = 0
        while iterations < self.config.max_iterations:
            # 调用 LLM 获取响应
            # 这里应该调用 LLM 并生成计划
            # 暂时返回占位符
            iterations += 1
            
            if iterations >= self.config.max_iterations:
                break
        
        return "Plan completed"
    
    def _check_permission(self, tool_name: str, args: dict) -> bool:
        """检查权限"""
        # 严格只读模式
        read_only_tools = ["read", "glob", "grep", "web_search", "web_fetch"]
        
        if tool_name in read_only_tools:
            return True
        
        # 检查权限列表
        for pattern, level in self.config.permissions.items():
            if tool_name.startswith(pattern.replace("*", "")):
                return level == "allow"
        
        # 默认拒绝
        return False