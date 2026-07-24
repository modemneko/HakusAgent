"""
工具执行器 - 负责工具的安全执行
支持并行执行、异常处理、结果截断
"""

import asyncio
import os
import shutil
import tempfile
from typing import Any, Callable
from pathlib import Path
from ...schema.models import ToolResult
from ...schema.errors import ToolError


class ToolExecutor:
    """工具执行器"""

    def __init__(self, max_output_length: int = 3000):
        self.max_output_length = max_output_length
        self._temp_paths: set[str] = set()

    def _is_temp_path(self, path: str) -> bool:
        """判断路径是否位于系统临时目录下。"""
        try:
            resolved = Path(path).resolve()
            temp_dirs = [
                Path(tempfile.gettempdir()).resolve(),
                Path(os.environ.get('TEMP', '') or tempfile.gettempdir()).resolve(),
                Path(os.environ.get('TMP', '') or tempfile.gettempdir()).resolve(),
            ]
            # Windows 常见临时根目录
            if os.name == 'nt':
                temp_dirs.append(Path('C:/Temp').resolve())
                temp_dirs.append(Path('C:/Windows/Temp').resolve())
            return any(
                resolved == td or str(resolved).lower().startswith(str(td).lower() + os.sep)
                for td in temp_dirs
                if td.exists() or str(td).startswith(str(temp_dirs[0]))
            )
        except Exception:
            return False

    def _register_temp_path(self, result: ToolResult) -> None:
        """从工具结果元数据中识别并登记临时文件/目录。"""
        if not result or not result.metadata:
            return
        paths: list[str] = []
        for key in ('file_path', 'directory', 'path', 'dir'):
            val = result.metadata.get(key)
            if isinstance(val, str) and val:
                paths.append(val)
        for p in paths:
            if self._is_temp_path(p):
                self._temp_paths.add(p)

    def cleanup_temp_paths(self) -> list[str]:
        """清理本回合登记的临时路径，返回成功删除的列表。"""
        removed: list[str] = []
        remaining: set[str] = set()
        for p in self._temp_paths:
            try:
                path = Path(p)
                if path.exists():
                    if path.is_file() or path.is_symlink():
                        path.unlink()
                    elif path.is_dir():
                        shutil.rmtree(path)
                removed.append(p)
            except Exception as e:
                # 清理失败不阻塞主流程，记录后保留以便调试
                remaining.add(p)
                if result := getattr(self, '_last_result', None):
                    result.output += f"\n[system] 清理临时文件失败 {p}: {e}"
        self._temp_paths = remaining
        return removed

    def _sanitize_output(self, result: ToolResult) -> ToolResult:
        """在把工具输出交给 LLM 之前做清洗和标注，降低误读率。"""
        if not result.output or not isinstance(result.output, str):
            return result

        output = result.output
        annotations: list[str] = []

        # 1. 乱码检测：替换字符比例过高时提醒 LLM 不要据此做结论
        replacement_count = output.count('\ufffd')
        if len(output) > 0 and replacement_count / len(output) > 0.05:
            annotations.append(
                "[system] 工具输出包含大量乱码（编码不匹配），请勿根据乱码内容推断错误。"
            )

        # 2. 失败调用明确标注，避免 LLM 把错误输出当正常结果
        if not result.success:
            annotations.append(
                "[system] 此工具执行失败（success=False），以下输出仅供参考，不可作为事实依据。"
            )

        if annotations:
            output = "\n".join(annotations) + "\n\n" + output

        # 3. 截断过长的输出
        if len(output) > self.max_output_length:
            output = output[:self.max_output_length] + "\n... (truncated)"

        result.output = output
        return result

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

            self._register_temp_path(result)
            return self._sanitize_output(result)

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