"""
搜索工具 - 借鉴 OpenCode 的 Glob/Grep 设计
提供文件搜索和内容搜索能力
"""

import os
import re
from pathlib import Path
from typing import Optional
from ....schema.models import ToolDefinition, ToolResult


class GlobTool:
    """文件名模式匹配工具"""
    
    definition = ToolDefinition(
        name="glob",
        description="Find files matching a glob pattern",
        parameters={
            "pattern": {"type": "string", "description": "Glob pattern (e.g., **/*.py)"},
            "path": {"type": "string", "description": "Directory to search in (default: current)"},
        },
        required=["pattern"],
        category="search",
    )
    
    @staticmethod
    async def execute(
        pattern: str,
        path: str = ".",
    ) -> ToolResult:
        """执行搜索"""
        try:
            search_path = Path(path)
            if not search_path.exists():
                return ToolResult(success=False, error=f"Path not found: {path}")
            
            matches = list(search_path.glob(pattern))
            
            # 转换为相对路径
            results = []
            for match in matches[:1000]:  # 限制结果数量
                try:
                    rel_path = match.relative_to(search_path)
                    results.append(str(rel_path))
                except ValueError:
                    results.append(str(match))
            
            return ToolResult(
                success=True,
                output="\n".join(results) if results else "(no matches)",
                metadata={
                    "pattern": pattern,
                    "path": path,
                    "match_count": len(results),
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GrepTool:
    """内容搜索工具"""
    
    definition = ToolDefinition(
        name="grep",
        description="Search file contents using regex patterns",
        parameters={
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "Directory or file to search in"},
            "include": {"type": "string", "description": "File pattern to include (e.g., *.py)"},
            "exclude": {"type": "string", "description": "File pattern to exclude"},
        },
        required=["pattern"],
        category="search",
    )
    
    @staticmethod
    async def execute(
        pattern: str,
        path: str = ".",
        include: Optional[str] = None,
        exclude: Optional[str] = None,
    ) -> ToolResult:
        """执行搜索"""
        try:
            search_path = Path(pattern) if Path(pattern).is_file() else Path(path)
            if not search_path.exists():
                return ToolResult(success=False, error=f"Path not found: {path}")
            
            # 编译正则表达式
            regex = re.compile(pattern, re.IGNORECASE)
            
            matches = []
            file_count = 0
            
            # 遍历文件
            if search_path.is_file():
                files = [search_path]
            else:
                files = list(search_path.rglob("*"))
            
            for file_path in files:
                if not file_path.is_file():
                    continue
                
                # 应用过滤器
                if include and not file_path.match(include):
                    continue
                if exclude and file_path.match(exclude):
                    continue
                
                # 跳过二进制文件和大文件
                try:
                    if file_path.stat().st_size > 1024 * 1024:  # 1MB
                        continue
                    
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    # 搜索内容
                    for line_num, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            matches.append({
                                "file": str(file_path),
                                "line": line_num,
                                "content": line.strip(),
                            })
                            
                            if len(matches) >= 1000:  # 限制结果数量
                                break
                    
                    file_count += 1
                    
                    if len(matches) >= 1000:
                        break
                        
                except (UnicodeDecodeError, PermissionError):
                    continue
            
            # 格式化输出
            output_lines = []
            for match in matches:
                output_lines.append(f"{match['file']}:{match['line']}: {match['content']}")
            
            return ToolResult(
                success=True,
                output="\n".join(output_lines) if output_lines else "(no matches)",
                metadata={
                    "pattern": pattern,
                    "path": path,
                    "match_count": len(matches),
                    "files_searched": file_count,
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))