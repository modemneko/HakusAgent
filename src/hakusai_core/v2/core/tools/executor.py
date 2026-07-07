"""
工具执行器 - 负责工具的安全执行
支持并行执行、异常处理、结果截断
"""

import asyncio
from typing import Any, Callable
from ...schema.models import ToolResult
from ...schema.errors import ToolError


class ToolExecutor:
    """工具执行器"""
    
    def __init__(self, max_output_length: int = 3000):
        self.max_output_length = max_output_length
    
    async def execute(
        self,
        executor: Callable,
        args: dict[str, Any],
        concurrency_safe: bool = False,
    ) -> ToolResult:
        """执行工具"""
        try:
            # 检查是否是协程函数
            if asyncio.iscoroutinefunction(executor):
                result = await executor(**args)
            else:
                # 在线程池中执行同步函数
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: executor(**args))
            
            # 转换为 ToolResult
            if not isinstance(result, ToolResult):
                result = ToolResult(success=True, output=result)
            
            # 截断过长的输出
            if result.output and isinstance(result.output, str):
                if len(result.output) > self.max_output_length:
                    result.output = result.output[:self.max_output_length] + "\n... (truncated)"
            
            return result
            
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                metadata={"exception_type": type(e).__name__},
            )
    
    async def execute_batch(
        self,
        tasks: list[tuple[Callable, dict[str, Any]]],
        concurrency_safe: bool = False,
    ) -> list[ToolResult]:
        """批量执行工具"""
        if concurrency_safe:
            # 并行执行
            async_tasks = [
                self.execute(executor, args, concurrency_safe)
                for executor, args in tasks
            ]
            return await asyncio.gather(*async_tasks)
        else:
            # 串行执行
            results = []
            for executor, args in tasks:
                result = await self.execute(executor, args, concurrency_safe)
                results.append(result)
            return results