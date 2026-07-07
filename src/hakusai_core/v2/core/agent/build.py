"""
Build Agent - 借鉴 OpenCode 的 build Agent 设计
全能开发 Agent，可以读写文件、执行命令
"""

from typing import AsyncIterator
from ...schema.models import AgentConfig, AgentMode, Message
from ...schema.events import ToolEvent
from .base import BaseAgent


class BuildAgent(BaseAgent):
    """Build Agent - 全能开发 Agent"""
    
    def __init__(self, **kwargs):
        config = AgentConfig(
            name="build",
            mode=AgentMode.BUILD,
            permissions={
                "read": "allow",
                "write": "ask",
                "edit": "ask",
                "bash": "ask",
                "git_*": "ask",
                "web_*": "allow",
            },
            max_iterations=15,
        )
        super().__init__(config=config, **kwargs)
    
    def get_system_prompt(self) -> str:
        """获取系统提示词"""
        return """You are a powerful AI coding agent built by HakusAI.

You have access to a set of tools that allow you to help the user with software engineering tasks:

1. **File Operations**: Read, write, and edit files
2. **Shell Execution**: Run shell commands
3. **Search**: Find files and search content
4. **Git**: Version control operations
5. **Web**: Fetch and search the web

When the user asks you to make changes:
- First, understand the codebase by reading relevant files
- Make changes incrementally and test as you go
- Use the edit tool for precise changes to existing files
- Use the write tool only for new files or complete rewrites

When you encounter errors:
- Read error messages carefully
- Fix issues one at a time
- Test your changes after each fix

Always explain what you're doing and why."""
    
    async def execute(self, task: str) -> str:
        """执行任务"""
        self.add_message("user", task)
        
        # 简化的执行循环
        # 实际实现应该包含 LLM 调用和工具执行循环
        iterations = 0
        while iterations < self.config.max_iterations:
            # 调用 LLM 获取响应
            # 这里应该调用 LLM 并解析工具调用
            # 暂时返回占位符
            iterations += 1
            
            if iterations >= self.config.max_iterations:
                break
        
        return "Task completed"
    
    def _check_permission(self, tool_name: str, args: dict) -> bool:
        """检查权限"""
        # 检查工具是否在权限列表中
        for pattern, level in self.config.permissions.items():
            if tool_name.startswith(pattern.replace("*", "")):
                if level == "allow":
                    return True
                elif level == "deny":
                    return False
                elif level == "ask":
                    # 在实际实现中，这里应该询问用户
                    return True
        
        # 默认允许
        return True