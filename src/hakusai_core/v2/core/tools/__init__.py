"""
工具系统 - 统一管理所有工具
"""

from .registry import ToolRegistry
from .executor import ToolExecutor
from .builtin.file import ReadTool, WriteTool, EditTool
from .builtin.shell import BashTool, PowerShellTool
from .builtin.search import GlobTool, GrepTool
from .builtin.git import GitStatusTool, GitDiffTool, GitCommitTool, GitLogTool
from .builtin.web import WebFetchTool, WebSearchTool


def create_default_registry() -> ToolRegistry:
    """创建默认工具注册表"""
    registry = ToolRegistry()
    
    # 文件操作工具
    registry.register(
        "read",
        ReadTool.definition,
        ReadTool.execute,
        aliases=["read_file"],
    )
    registry.register(
        "write",
        WriteTool.definition,
        WriteTool.execute,
        aliases=["write_file"],
    )
    registry.register(
        "edit",
        EditTool.definition,
        EditTool.execute,
        aliases=["edit_file"],
    )
    
    # Shell 工具
    registry.register(
        "bash",
        BashTool.definition,
        BashTool.execute,
        aliases=["shell", "command"],
    )
    registry.register(
        "powershell",
        PowerShellTool.definition,
        PowerShellTool.execute,
        aliases=["ps"],
    )
    
    # 搜索工具
    registry.register(
        "glob",
        GlobTool.definition,
        GlobTool.execute,
        aliases=["find"],
    )
    registry.register(
        "grep",
        GrepTool.definition,
        GrepTool.execute,
        aliases=["search"],
    )
    
    # Git 工具
    registry.register(
        "git_status",
        GitStatusTool.definition,
        GitStatusTool.execute,
        aliases=["git-status"],
    )
    registry.register(
        "git_diff",
        GitDiffTool.definition,
        GitDiffTool.execute,
        aliases=["git-diff"],
    )
    registry.register(
        "git_commit",
        GitCommitTool.definition,
        GitCommitTool.execute,
        aliases=["git-commit"],
    )
    registry.register(
        "git_log",
        GitLogTool.definition,
        GitLogTool.execute,
        aliases=["git-log"],
    )
    
    # Web 工具
    registry.register(
        "web_fetch",
        WebFetchTool.definition,
        WebFetchTool.execute,
        aliases=["fetch"],
    )
    registry.register(
        "web_search",
        WebSearchTool.definition,
        WebSearchTool.execute,
        aliases=["search_web"],
    )
    
    return registry


__all__ = [
    "ToolRegistry",
    "ToolExecutor",
    "create_default_registry",
]