"""
文件操作工具 - 借鉴 OpenCode 的 Read/Write/Edit 设计
提供安全的文件读写能力
"""

import os
import aiofiles
from pathlib import Path
from typing import Optional
from ....schema.models import ToolDefinition, ToolResult
from ....schema.errors import ToolError


class ReadTool:
    """读取文件工具"""
    
    definition = ToolDefinition(
        name="read",
        description="Read a file from the filesystem",
        parameters={
            "filePath": {"type": "string", "description": "Absolute path to file"},
            "offset": {"type": "integer", "description": "Line number to start from (0-indexed)"},
            "limit": {"type": "integer", "description": "Maximum lines to read"},
        },
        required=["filePath"],
        category="file",
    )
    
    @staticmethod
    async def execute(
        filePath: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> ToolResult:
        """执行读取"""
        try:
            path = Path(filePath)
            if not path.exists():
                return ToolResult(success=False, error=f"File not found: {filePath}")
            
            if not path.is_file():
                return ToolResult(success=False, error=f"Not a file: {filePath}")
            
            # 检查文件大小
            file_size = path.stat().st_size
            if file_size > 10 * 1024 * 1024:  # 10MB
                return ToolResult(
                    success=False,
                    error=f"File too large ({file_size / 1024 / 1024:.1f}MB). Maximum: 10MB"
                )
            
            async with aiofiles.open(filePath, 'r', encoding='utf-8', errors='replace') as f:
                lines = await f.readlines()
                
                # 应用偏移和限制
                start = min(offset, len(lines))
                end = min(start + limit, len(lines))
                selected_lines = lines[start:end]
                
                # 格式化输出
                output = ""
                for i, line in enumerate(selected_lines, start=start + 1):
                    output += f"{i}: {line}"
                
                return ToolResult(
                    success=True,
                    output=output,
                    metadata={
                        "file_path": filePath,
                        "total_lines": len(lines),
                        "selected_lines": len(selected_lines),
                        "offset": offset,
                        "limit": limit,
                    }
                )
                
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class WriteTool:
    """写入文件工具"""
    
    definition = ToolDefinition(
        name="write",
        description="Write content to a file, creating it if it doesn't exist",
        parameters={
            "filePath": {"type": "string", "description": "Absolute path to file"},
            "content": {"type": "string", "description": "Content to write"},
        },
        required=["filePath", "content"],
        category="file",
    )
    
    @staticmethod
    async def execute(filePath: str, content: str) -> ToolResult:
        """执行写入"""
        try:
            path = Path(filePath)
            
            # 创建父目录
            path.parent.mkdir(parents=True, exist_ok=True)
            
            async with aiofiles.open(filePath, 'w', encoding='utf-8') as f:
                await f.write(content)
            
            return ToolResult(
                success=True,
                output=f"File written: {filePath}",
                metadata={
                    "file_path": filePath,
                    "bytes_written": len(content.encode('utf-8')),
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class EditTool:
    """编辑文件工具"""
    
    definition = ToolDefinition(
        name="edit",
        description="Edit a file by replacing exact string matches",
        parameters={
            "filePath": {"type": "string", "description": "Absolute path to file"},
            "oldString": {"type": "string", "description": "Text to replace"},
            "newString": {"type": "string", "description": "Replacement text"},
            "replaceAll": {"type": "boolean", "description": "Replace all occurrences"},
        },
        required=["filePath", "oldString", "newString"],
        category="file",
    )
    
    @staticmethod
    async def execute(
        filePath: str,
        oldString: str,
        newString: str,
        replaceAll: bool = False,
    ) -> ToolResult:
        """执行编辑"""
        try:
            path = Path(filePath)
            if not path.exists():
                return ToolResult(success=False, error=f"File not found: {filePath}")
            
            async with aiofiles.open(filePath, 'r', encoding='utf-8') as f:
                content = await f.read()
            
            # 检查旧字符串是否存在
            if oldString not in content:
                return ToolResult(
                    success=False,
                    error=f"String not found in file: {oldString[:50]}..."
                )
            
            # 执行替换
            if replaceAll:
                new_content = content.replace(oldString, newString)
                count = content.count(oldString)
            else:
                # 检查唯一性
                count = content.count(oldString)
                if count > 1:
                    return ToolResult(
                        success=False,
                        error=f"Found {count} matches. Use replaceAll or provide more context."
                    )
                new_content = content.replace(oldString, newString, 1)
            
            # 写入文件
            async with aiofiles.open(filePath, 'w', encoding='utf-8') as f:
                await f.write(new_content)
            
            return ToolResult(
                success=True,
                output=f"File edited: {filePath}",
                metadata={
                    "file_path": filePath,
                    "replacements": count if replaceAll else 1,
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))