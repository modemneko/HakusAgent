"""
工具注册表 - 借鉴 OpenCode 的 Tool Registry 设计
统一管理所有工具的注册、查找和执行
"""

from typing import Any, Callable, Optional
from ...schema.models import ToolDefinition, ToolResult
from ...schema.errors import ToolError, NotFoundError


class ToolRegistry:
    """统一工具注册表"""
    
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._executors: dict[str, Callable] = {}
        self._aliases: dict[str, str] = {}
    
    def register(
        self,
        name: str,
        definition: ToolDefinition,
        executor: Callable,
        aliases: list[str] = None,
    ):
        """注册工具"""
        self._tools[name] = definition
        self._executors[name] = executor
        if aliases:
            for alias in aliases:
                self._aliases[alias] = name
    
    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义（支持别名）"""
        actual_name = self._aliases.get(name, name)
        return self._tools.get(actual_name)
    
    def get_executor(self, name: str) -> Optional[Callable]:
        """获取工具执行器（支持别名）"""
        actual_name = self._aliases.get(name, name)
        return self._executors.get(actual_name)
    
    def list_tools(self) -> list[ToolDefinition]:
        """列出所有工具"""
        return list(self._tools.values())
    
    def list_tool_names(self) -> list[str]:
        """列出所有工具名称"""
        return list(self._tools.keys())
    
    def has(self, name: str) -> bool:
        """检查工具是否存在"""
        actual_name = self._aliases.get(name, name)
        return actual_name in self._tools
    
    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """执行工具"""
        actual_name = self._aliases.get(name, name)
        
        if actual_name not in self._tools:
            raise NotFoundError("Tool", name)
        
        executor = self._executors.get(actual_name)
        if not executor:
            raise ToolError(name, "No executor registered")
        
        try:
            if callable(executor):
                import asyncio
                if asyncio.iscoroutinefunction(executor):
                    result = await executor(**args)
                else:
                    result = executor(**args)
            else:
                result = executor
            
            if not isinstance(result, ToolResult):
                result = ToolResult(success=True, output=result)
            
            return result
        except Exception as e:
            if isinstance(e, ToolError):
                raise
            raise ToolError(name, str(e))
    
    def unregister(self, name: str):
        """注销工具"""
        actual_name = self._aliases.get(name, name)
        if actual_name in self._tools:
            del self._tools[actual_name]
        if actual_name in self._executors:
            del self._executors[actual_name]
        # 清理别名
        aliases_to_remove = [k for k, v in self._aliases.items() if v == actual_name]
        for alias in aliases_to_remove:
            del self._aliases[alias]