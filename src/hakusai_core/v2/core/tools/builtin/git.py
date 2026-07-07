"""
Git 操作工具 - 借鉴 OpenCode 的 Git 集成设计
提供 Git 版本控制能力
"""

import asyncio
from typing import Optional
from ....schema.models import ToolDefinition, ToolResult


class GitStatusTool:
    """Git 状态工具"""
    
    definition = ToolDefinition(
        name="git_status",
        description="Get git status of the repository",
        parameters={
            "path": {"type": "string", "description": "Repository path"},
        },
        required=[],
        category="git",
    )
    
    @staticmethod
    async def execute(path: str = ".") -> ToolResult:
        """执行 git status"""
        try:
            process = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=path,
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return ToolResult(
                    success=False,
                    error=stderr.decode('utf-8', errors='replace')
                )
            
            output = stdout.decode('utf-8', errors='replace')
            return ToolResult(
                success=True,
                output=output or "(no changes)",
                metadata={"path": path}
            )
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GitDiffTool:
    """Git Diff 工具"""
    
    definition = ToolDefinition(
        name="git_diff",
        description="Show git diff",
        parameters={
            "path": {"type": "string", "description": "Repository path"},
            "file": {"type": "string", "description": "Specific file to diff"},
            "staged": {"type": "boolean", "description": "Show staged changes"},
        },
        required=[],
        category="git",
    )
    
    @staticmethod
    async def execute(
        path: str = ".",
        file: Optional[str] = None,
        staged: bool = False,
    ) -> ToolResult:
        """执行 git diff"""
        try:
            cmd = ["git", "diff"]
            if staged:
                cmd.append("--staged")
            if file:
                cmd.append(file)
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=path,
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return ToolResult(
                    success=False,
                    error=stderr.decode('utf-8', errors='replace')
                )
            
            output = stdout.decode('utf-8', errors='replace')
            return ToolResult(
                success=True,
                output=output or "(no changes)",
                metadata={"path": path, "file": file, "staged": staged}
            )
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GitCommitTool:
    """Git Commit 工具"""
    
    definition = ToolDefinition(
        name="git_commit",
        description="Create a git commit",
        parameters={
            "message": {"type": "string", "description": "Commit message"},
            "path": {"type": "string", "description": "Repository path"},
            "add_all": {"type": "boolean", "description": "Stage all changes"},
        },
        required=["message"],
        category="git",
    )
    
    @staticmethod
    async def execute(
        message: str,
        path: str = ".",
        add_all: bool = False,
    ) -> ToolResult:
        """执行 git commit"""
        try:
            # 先添加文件
            if add_all:
                add_process = await asyncio.create_subprocess_exec(
                    "git", "add", "-A",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=path,
                )
                await add_process.communicate()
            
            # 执行 commit
            process = await asyncio.create_subprocess_exec(
                "git", "commit", "-m", message,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=path,
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return ToolResult(
                    success=False,
                    error=stderr.decode('utf-8', errors='replace')
                )
            
            output = stdout.decode('utf-8', errors='replace')
            return ToolResult(
                success=True,
                output=output,
                metadata={"path": path, "message": message}
            )
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GitLogTool:
    """Git Log 工具"""
    
    definition = ToolDefinition(
        name="git_log",
        description="Show git log",
        parameters={
            "path": {"type": "string", "description": "Repository path"},
            "count": {"type": "integer", "description": "Number of commits to show"},
            "oneline": {"type": "boolean", "description": "Show oneline format"},
        },
        required=[],
        category="git",
    )
    
    @staticmethod
    async def execute(
        path: str = ".",
        count: int = 10,
        oneline: bool = True,
    ) -> ToolResult:
        """执行 git log"""
        try:
            cmd = ["git", "log", f"-{count}"]
            if oneline:
                cmd.append("--oneline")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=path,
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return ToolResult(
                    success=False,
                    error=stderr.decode('utf-8', errors='replace')
                )
            
            output = stdout.decode('utf-8', errors='replace')
            return ToolResult(
                success=True,
                output=output or "(no commits)",
                metadata={"path": path, "count": count}
            )
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))