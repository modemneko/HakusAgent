"""Built-in tools, one file per concern.

This replaces the old `hakus/builtin_tools.py` (a 600-line monolith
with 11 classes) and the duplicate implementations in
`hakus/tool_system.py` and `core/tools/search_plugins.py`.

Adding a new tool: drop a new file in this directory, append the
class name to `BUILTIN_TOOL_CLASSES` below. No other wiring needed.
"""
from __future__ import annotations

from .browser import BrowserUse
from .directory import ListDir, Tree
from .file import (
    AppendFile, CopyFile, CreateDirectory, DeleteFile, EditFile,
    FileStat, MoveFile, MultiEditFile, ReadFile, ReadMultipleFiles,
    WriteFile,
)
from .search import Glob, Grep
from .shell import Bash
from .task import TaskManage
from .task_done import TaskDoneTool
from .web import WebFetch, WebSearch

# Single source of truth for the canonical built-in tool list.
# Order is preserved for stable schema ordering (helps model attention).
BUILTIN_TOOL_CLASSES = [
    ReadFile,           # local files
    WriteFile,          # local files
    EditFile,           # local files
    MultiEditFile,      # local files — batch edit
    AppendFile,         # local files — append
    MoveFile,           # local files — move/rename
    CopyFile,           # local files — copy
    DeleteFile,         # local files — delete
    FileStat,           # local files — metadata
    ReadMultipleFiles,  # local files — batch read
    CreateDirectory,    # local files — mkdir
    Bash,               # shell
    Glob,               # local files — search
    Grep,               # local files — search
    ListDir,            # local files — browse
    Tree,               # local files — browse
    WebSearch,          # network
    WebFetch,           # network
    BrowserUse,         # browser
    TaskManage,         # tasks
    TaskDoneTool,       # task completion signal (trae-agent style)
]


__all__ = [
    "ReadFile", "WriteFile", "EditFile", "MultiEditFile", "AppendFile",
    "MoveFile", "CopyFile", "DeleteFile", "FileStat", "ReadMultipleFiles",
    "CreateDirectory",
    "Bash",
    "Glob", "Grep",
    "ListDir", "Tree",
    "WebSearch", "WebFetch",
    "BrowserUse",
    "TaskManage",
    "TaskDoneTool",
    "BUILTIN_TOOL_CLASSES",
]
