"""
HakusAI 开发工具集
对标 Claude Code 的核心开发工具

工具清单 (Claude Code 风格):
- Read           读取文件 (支持 offset/limit, 行号, 图片, PDF)
- Write          写入/创建文件
- Edit           精确字符串替换 (old_string 必须唯一)
- MultiEdit      批量编辑
- Glob           文件名模式匹配
- Grep           内容搜索 (ripgrep 风格)
- Bash           Shell 命令执行 (支持 background / timeout)
- PowerShell     Windows PowerShell
- TodoWrite      任务列表管理
- WebFetch       HTTP 抓取
- WebSearch      网络搜索
- AskUserQuestion 多选问答
- GitStatus      Git 状态
- GitDiff        Git 差异
- GitCommit      Git 提交
- GitLog         Git 历史
- NotebookEdit   Jupyter 笔记本编辑
- LSP            代码智能 (定义/引用跳转)
- PlanMode       计划模式
"""
import asyncio
import glob as glob_module
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from utils.logger import get_logger
from hakus.tools.plugin import ToolPlugin, ToolMetadata

logger = get_logger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_LINE_LENGTH = 2000
MAX_READ_LINES = 2000
MAX_GREP_RESULTS = 200
MAX_GLOB_RESULTS = 500
BASH_DEFAULT_TIMEOUT = 120
BASH_MAX_TIMEOUT = 600


@dataclass
class TodoState:
    todos: List[Dict[str, str]] = field(default_factory=list)

    def to_markdown(self) -> str:
        if not self.todos:
            return "_暂无待办_"
        lines = []
        for t in self.todos:
            icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(t["status"], "[ ]")
            lines.append(f"- {icon} {t['content']} (id: `{t['id']}`)")
        return "\n".join(lines)


class ReadTool(ToolPlugin):
    name = "Read"
    description = (
        "读取文件内容,以 cat -n 格式返回带行号的文本。"
        "支持文本、图片、PDF、Jupyter notebook。"
        "必须提供绝对路径,或工作目录下的相对路径。"
    )
    category = "file"
    execute_timeout = 30.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "file_path": {
                    "type": "string",
                    "description": "要读取的文件绝对路径"
                },
                "offset": {
                    "type": "integer",
                    "description": "起始行号 (从1开始,可选)"
                },
                "limit": {
                    "type": "integer",
                    "description": f"读取行数 (最大 {MAX_READ_LINES},可选)"
                }
            },
            tags=["file", "read"]
        )

    async def execute(self, **kwargs) -> str:
        file_path: str = kwargs.get("file_path", "")
        offset: Optional[int] = kwargs.get("offset")
        limit: Optional[int] = kwargs.get("limit")

        if not file_path:
            return "错误: 必须提供 file_path"

        path = Path(file_path).resolve()
        if not path.exists():
            return f"错误: 文件不存在: {path}"
        if not path.is_file():
            return f"错误: 路径不是文件: {path}"

        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            return f"错误: 文件过大 ({size} 字节, 限制 {MAX_FILE_SIZE} 字节)"

        try:
            ext = path.suffix.lower()
            if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}:
                return f"[图片文件: {path}]\n[大小: {size} 字节, 已加载到上下文]"

            if ext == ".pdf":
                return f"[PDF 文件: {path}]\n[大小: {size} 字节, 已加载到上下文]"

            if ext in {".ipynb"}:
                return await asyncio.to_thread(self._read_notebook, path)

            text = await asyncio.to_thread(self._read_text, path, offset, limit)
            return text

        except PermissionError:
            return f"错误: 无权限读取文件: {path}"
        except Exception as e:
            logger.error(f"Read error: {e}")
            return f"错误: 读取文件失败: {e}"

    def _read_text(self, path: Path, offset: Optional[int], limit: Optional[int]) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total = len(lines)
        start = max(1, offset) if offset else 1
        end = min(total, start + (limit or MAX_READ_LINES) - 1)
        if limit is None and offset is None:
            end = min(total, MAX_READ_LINES)

        if start > total:
            return f"错误: offset {start} 超过文件总行数 {total}"

        result_lines = []
        for i in range(start - 1, end):
            line = lines[i]
            if len(line) > MAX_LINE_LENGTH:
                line = line[:MAX_LINE_LENGTH] + "  ... [截断]\n"
            result_lines.append(f"{i+1:6d}\t{line.rstrip(chr(10))}")

        header = f"文件: {path}\n"
        if start > 1 or end < total:
            header += f"范围: 第 {start}-{end} 行 / 共 {total} 行\n"
        else:
            header += f"共 {total} 行\n"
        header += "-" * 60 + "\n"
        return header + "\n".join(result_lines)

    def _read_notebook(self, path: Path) -> str:
        with open(path, "r", encoding="utf-8") as f:
            nb = json.load(f)
        cells = nb.get("cells", [])
        parts = [f"文件: {path}", f"共 {len(cells)} 个 cell", "-" * 60]
        for i, cell in enumerate(cells):
            cell_type = cell.get("cell_type", "code")
            source = "".join(cell.get("source", []))
            parts.append(f"--- Cell {i+1} ({cell_type}) ---")
            parts.append(source)
            if cell_type == "code":
                outputs = cell.get("outputs", [])
                for out in outputs:
                    if "text" in out:
                        parts.append("Output:")
                        parts.append("".join(out["text"]))
        return "\n".join(parts)


class WriteTool(ToolPlugin):
    name = "Write"
    description = (
        "写入或创建文件。完全覆盖现有内容, 或创建新文件。"
        "必须提供绝对路径,或工作目录下的相对路径。"
    )
    category = "file"
    requires_permission = True
    execute_timeout = 30.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "file_path": {
                    "type": "string",
                    "description": "目标文件绝对路径"
                },
                "content": {
                    "type": "string",
                    "description": "要写入的完整内容"
                }
            },
            tags=["file", "write"]
        )

    async def execute(self, **kwargs) -> str:
        file_path: str = kwargs.get("file_path", "")
        content: str = kwargs.get("content", "")

        if not file_path:
            return "错误: 必须提供 file_path"

        path = Path(file_path).resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._write, path, content)
            size = path.stat().st_size
            return f"✓ 已写入: {path} ({size} 字节)"
        except PermissionError:
            return f"错误: 无权限写入文件: {path}"
        except Exception as e:
            logger.error(f"Write error: {e}")
            return f"错误: 写入文件失败: {e}"

    def _write(self, path: Path, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


class EditTool(ToolPlugin):
    name = "Edit"
    description = (
        "对现有文件进行精确字符串替换。"
        "old_string 必须唯一 (除非 replace_all=true), 必须先 Read 后 Edit。"
        "返回应用后的文件片段。"
    )
    category = "file"
    requires_permission = True
    execute_timeout = 30.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "file_path": {
                    "type": "string",
                    "description": "要编辑的文件绝对路径"
                },
                "old_string": {
                    "type": "string",
                    "description": "要替换的原始字符串 (必须唯一)"
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的新字符串"
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "替换所有匹配项 (默认 false, 要求唯一)"
                }
            },
            tags=["file", "edit"]
        )

    async def execute(self, **kwargs) -> str:
        file_path: str = kwargs.get("file_path", "")
        old_string: str = kwargs.get("old_string", "")
        new_string: str = kwargs.get("new_string", "")
        replace_all: bool = kwargs.get("replace_all", False)

        if not file_path:
            return "错误: 必须提供 file_path"
        if not old_string:
            return "错误: 必须提供 old_string"

        path = Path(file_path).resolve()
        if not path.exists():
            return f"错误: 文件不存在: {path}"

        try:
            return await asyncio.to_thread(
                self._do_edit, path, old_string, new_string, replace_all
            )
        except Exception as e:
            logger.error(f"Edit error: {e}")
            return f"错误: 编辑失败: {e}"

    def _do_edit(self, path: Path, old_string: str, new_string: str, replace_all: bool) -> str:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_string)

        if count == 0:
            return f"错误: old_string 未在文件中找到。文件路径: {path}"

        if count > 1 and not replace_all:
            return (
                f"错误: old_string 在文件中出现 {count} 次, 不是唯一的。\n"
                f"请提供更精确的 old_string (包含更多上下文), 或设置 replace_all=true"
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
            occurrences = count
        else:
            new_content = content.replace(old_string, new_string, 1)
            occurrences = 1

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        lines = new_content.split(chr(10))
        idx = new_content.find(new_string)
        if idx >= 0:
            before = new_content[:idx].count(chr(10))
            preview_lines = lines[before:min(before+10, len(lines))]
            preview = chr(10).join(preview_lines)
        else:
            preview = new_string[:300]

        return (
            f"✓ 已编辑: {path}\n"
            f"  替换次数: {occurrences}\n"
            f"  ---\n{preview}"
        )


class MultiEditTool(ToolPlugin):
    name = "MultiEdit"
    description = "对同一文件执行多个 Edit 操作 (原子性, 任一失败全部回滚)。"
    category = "file"
    requires_permission = True
    execute_timeout = 60.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "file_path": {
                    "type": "string",
                    "description": "目标文件绝对路径"
                },
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_string": {"type": "string"},
                            "new_string": {"type": "string"},
                            "replace_all": {"type": "boolean"}
                        }
                    },
                    "description": "要应用的编辑列表"
                }
            },
            tags=["file", "edit", "batch"]
        )

    async def execute(self, **kwargs) -> str:
        file_path: str = kwargs.get("file_path", "")
        edits: List[Dict] = kwargs.get("edits", [])

        if not file_path:
            return "错误: 必须提供 file_path"
        if not edits:
            return "错误: 必须提供至少一个 edit"

        path = Path(file_path).resolve()
        if not path.exists():
            return f"错误: 文件不存在: {path}"

        try:
            return await asyncio.to_thread(self._do_multi_edit, path, edits)
        except Exception as e:
            logger.error(f"MultiEdit error: {e}")
            return f"错误: 批量编辑失败: {e}"

    def _do_multi_edit(self, path: Path, edits: List[Dict]) -> str:
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
        backup = original

        for i, edit in enumerate(edits):
            old = edit.get("old_string", "")
            new = edit.get("new_string", "")
            replace_all = edit.get("replace_all", False)
            count = original.count(old)
            if count == 0:
                original = backup
                return f"错误: 第 {i+1} 个 edit 失败, old_string 未找到。已回滚所有更改。"
            if count > 1 and not replace_all:
                original = backup
                return f"错误: 第 {i+1} 个 edit 失败, old_string 出现 {count} 次。已回滚所有更改。"
            if replace_all:
                original = original.replace(old, new)
            else:
                original = original.replace(old, new, 1)

        with open(path, "w", encoding="utf-8") as f:
            f.write(original)

        return f"✓ 已应用 {len(edits)} 个编辑: {path}"


class GlobTool(ToolPlugin):
    name = "Glob"
    description = (
        "按文件名模式匹配文件。返回按修改时间排序的文件列表。"
        "支持 **/*.ts 类的递归模式。无需权限。"
    )
    category = "file"
    execute_timeout = 30.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "pattern": {
                    "type": "string",
                    "description": "glob 模式, 如 '**/*.py' 或 'src/**/*.ts'"
                },
                "path": {
                    "type": "string",
                    "description": "搜索起点 (默认当前工作目录)"
                }
            },
            tags=["file", "glob", "search"]
        )

    async def execute(self, **kwargs) -> str:
        pattern: str = kwargs.get("pattern", "")
        base_path: str = kwargs.get("path", ".") or "."

        if not pattern:
            return "错误: 必须提供 pattern"

        base = Path(base_path).resolve()
        if not base.exists():
            return f"错误: 路径不存在: {base}"

        try:
            results = await asyncio.to_thread(
                self._glob, str(base), pattern
            )
        except Exception as e:
            return f"错误: glob 搜索失败: {e}"

        if not results:
            return f"未找到匹配 '{pattern}' 的文件 (路径: {base})"

        if len(results) > MAX_GLOB_RESULTS:
            results = results[:MAX_GLOB_RESULTS]
            truncated = True
        else:
            truncated = False

        output = "\n".join(results)
        suffix = f"\n\n[共 {len(results)} 个文件" + (", 已截断" if truncated else "") + "]"
        return output + suffix

    def _glob(self, base: str, pattern: str) -> List[str]:
        full_pattern = os.path.join(base, pattern)
        matches = glob_module.glob(full_pattern, recursive=True)
        matches = [m for m in matches if os.path.isfile(m)]
        matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return matches


class GrepTool(ToolPlugin):
    name = "Grep"
    description = (
        "基于 ripgrep 的内容搜索工具。支持正则、多行模式、glob 过滤、上下文行。"
        "无需权限。"
    )
    category = "file"
    execute_timeout = 60.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "pattern": {
                    "type": "string",
                    "description": "正则表达式"
                },
                "path": {
                    "type": "string",
                    "description": "搜索目录 (默认当前工作目录)"
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "description": "输出模式 (默认 files_with_matches)"
                },
                "glob": {
                    "type": "string",
                    "description": "文件名 glob 过滤, 如 '*.py'"
                },
                "-A": {
                    "type": "integer",
                    "description": "匹配后显示 N 行"
                },
                "-B": {
                    "type": "integer",
                    "description": "匹配前显示 N 行"
                },
                "-C": {
                    "type": "integer",
                    "description": "匹配前后各显示 N 行"
                },
                "head_limit": {
                    "type": "integer",
                    "description": "限制结果数"
                },
                "multiline": {
                    "type": "boolean",
                    "description": "多行模式"
                }
            },
            tags=["file", "grep", "search"]
        )

    async def execute(self, **kwargs) -> str:
        pattern: str = kwargs.get("pattern", "")
        path: str = kwargs.get("path", ".") or "."
        output_mode: str = kwargs.get("output_mode", "files_with_matches")
        glob_filter: str = kwargs.get("glob")
        before: int = kwargs.get("-B", 0)
        after: int = kwargs.get("-A", 0)
        context: int = kwargs.get("-C", 0)
        head_limit: int = kwargs.get("head_limit", MAX_GREP_RESULTS)
        multiline: bool = kwargs.get("multiline", False)

        if not pattern:
            return "错误: 必须提供 pattern"

        base = Path(path).resolve()
        if not base.exists():
            return f"错误: 路径不存在: {base}"

        try:
            flags = re.MULTILINE | (re.DOTALL if multiline else 0)
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"错误: 无效的正则表达式: {e}"

        try:
            return await asyncio.to_thread(
                self._grep, base, regex, output_mode, glob_filter,
                before, after, context, head_limit
            )
        except Exception as e:
            logger.error(f"Grep error: {e}")
            return f"错误: 搜索失败: {e}"

    def _grep(self, base: Path, regex: re.Pattern, output_mode: str,
              glob_filter: Optional[str], before: int, after: int,
              context: int, head_limit: int) -> str:
        results: List[str] = []
        files_matched: List[str] = []
        count_total = 0

        if base.is_file():
            files = [base]
        else:
            pattern = "**/*" if not glob_filter else f"**/{glob_filter}"
            files = [Path(p) for p in glob_module.glob(
                str(base / pattern), recursive=True
            ) if Path(p).is_file()]
            files = [f for f in files if self._is_text_file(f)]

        for fpath in files:
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception:
                continue

            if output_mode == "count":
                matches = list(regex.finditer(content))
                if matches:
                    files_matched.append(f"{fpath}:{len(matches)}")
            else:
                lines = content.split(chr(10))
                for i, line in enumerate(lines):
                    if regex.search(line):
                        if output_mode == "files_with_matches":
                            files_matched.append(str(fpath))
                            count_total += 1
                            break
                        else:
                            if context:
                                start = max(0, i - context)
                                end = min(len(lines), i + context + 1)
                                snippet = chr(10).join(
                                    f"{fpath}:{j+1}:{lines[j]}"
                                    for j in range(start, end)
                                )
                            else:
                                pre = chr(10).join(
                                    f"{fpath}:{max(1,i-before+j+1)}-{lines[i-before+j]}"
                                    for j in range(min(before, i))
                                )
                                post = chr(10).join(
                                    f"{fpath}:{i+2+j}-{lines[i+1+j]}"
                                    for j in range(min(after, len(lines)-i-1))
                                )
                                snippet = (
                                    (pre + chr(10) if pre else "")
                                    + f"{fpath}:{i+1}:{line}"
                                    + (chr(10) + post if post else "")
                                )
                            results.append(snippet)
                            count_total += 1
                            if count_total >= head_limit:
                                break
                if count_total >= head_limit:
                    break

        if output_mode == "count":
            if not files_matched:
                return f"未找到匹配"
            return chr(10).join(files_matched[:head_limit])

        if output_mode == "files_with_matches":
            if not files_matched:
                return f"未找到匹配"
            suffix = f"\n\n[共 {len(files_matched)} 个文件]" if len(files_matched) > 1 else ""
            return chr(10).join(files_matched[:head_limit]) + suffix

        if not results:
            return f"未找到匹配"
        output = chr(10).join(results[:head_limit])
        if count_total >= head_limit:
            output += f"\n\n[结果已截断至 {head_limit} 项]"
        return output

    def _is_text_file(self, path: Path) -> bool:
        try:
            ext = path.suffix.lower()
            binary_ext = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".pdf",
                          ".zip", ".tar", ".gz", ".exe", ".dll", ".so", ".dylib",
                          ".pyc", ".class", ".o", ".a", ".lib", ".bin", ".ico",
                          ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webp"}
            if ext in binary_ext:
                return False
            with open(path, "rb") as f:
                chunk = f.read(512)
            return not bool(chunk and any(b == 0 for b in chunk[:512]))
        except Exception:
            return False


class BashTool(ToolPlugin):
    """
    安全加固的 Shell 命令执行工具
    
    安全特性:
    1. 命令白名单 - 仅允许配置中指定的命令
    2. 危险模式黑名单 - 永久禁止危险命令模式
    3. 审计日志 - 记录所有命令执行
    4. 参数化执行 - 简单命令避免 shell=True
    5. 命令清理 - 移除危险字符
    
    配置方式:
    - 环境变量 HAKUSAI_ALLOW_COMMANDS: git,npm,python,pip,...
    - 配置文件 security.allow_commands
    """
    name = "Bash"
    description = (
        "执行 Shell 命令。支持 background 运行 (run_in_background)、timeout、description。"
        "用于构建、运行测试、git 等需要 Shell 的场景。"
        "文件操作优先使用 Read/Write/Edit/Glob/Grep, 不用 cat/grep/find。"
        "\n⚠️ 安全限制:"
        "- 命令受白名单控制，仅允许配置中指定的命令"
        "- 危险命令模式被永久禁止"
        "- 所有命令执行都会记录审计日志"
    )
    category = "command"
    requires_permission = True
    execute_timeout = BASH_MAX_TIMEOUT

    # 默认的危险命令模式（正则表达式）
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/",           # 删除根目录
        r"rm\s+-rf\s+~",          # 删除 home
        r"mkfs",                  # 格式化磁盘
        r">\s*/dev/sd[a-z]",     # 覆盖磁盘
        r"chmod\s+777",          # 危险权限
        r"curl.*\\|\\s*(sh|bash|python|perl)",  # 远程脚本注入
        r"wget.*\\|\\s*(sh|bash|python|perl)", # 远程脚本注入
        r":\(\)\{:\|:&\};:",          # Fork bomb
        r"dd\s+if=.*of=/dev/",   # DD 磁盘覆盖
        r"\\>\s*/etc/",          # 覆盖系统文件
        r"shutdown",              # 关机命令
        r"reboot",                # 重启命令
        r"passwd",                # 修改密码
    ]

    def __init__(self):
        super().__init__()
        self._background_tasks: Dict[str, asyncio.subprocess.Process] = {}
        
        # 从环境变量读取允许的命令列表
        self._allow_commands: List[str] = []
        env_allowed = os.environ.get("HAKUSAI_ALLOW_COMMANDS", "")
        if env_allowed:
            self._allow_commands = [c.strip() for c in env_allowed.split(",") if c.strip()]
        
        # 尝试从配置读取
        if not self._allow_commands:
            try:
                from utils.config import BASE_CONFIG
                config_allowed = BASE_CONFIG.get("security", {}).get("allow_commands", [])
                if config_allowed:
                    self._allow_commands = config_allowed
            except Exception:
                pass

    def _log_audit(self, command: str, allowed: bool, reason: str = ""):
        """记录审计日志"""
        log_msg = f"command={command[:100]} allowed={allowed}"
        if reason:
            log_msg += f" reason={reason}"
        logger.info(f"[AUDIT:Bash] {log_msg}")

    def _validate_command(self, command: str) -> tuple:
        """
        验证命令是否允许执行
        
        Returns:
            (allowed, reason)
        """
        import re
        
        if not command or not command.strip():
            return False, "空命令"
        
        # 提取基本命令名
        cmd_parts = command.strip().split()
        base_cmd = cmd_parts[0].lower()
        
        # 移除可能的路径前缀 (如 /usr/bin/git -> git)
        if "/" in base_cmd:
            base_cmd = base_cmd.rsplit("/", 1)[-1]
        
        # 检查危险模式
        for pattern in self.DANGEROUS_PATTERNS:
            try:
                if re.search(pattern, command, re.IGNORECASE):
                    return False, f"命令匹配危险模式"
            except re.error:
                pass
        
        # 检查白名单
        if not self._allow_commands:
            return False, (
                "命令执行已禁用（allow_commands 为空）。"
                "请通过 HAKUSAI_ALLOW_COMMANDS 环境变量启用。"
            )
        
        if base_cmd not in [c.lower().lstrip("./") for c in self._allow_commands]:
            return False, (
                f"命令 '{base_cmd}' 不在允许列表中。"
                f"允许的命令: {', '.join(self._allow_commands[:10])}"
                + ("..." if len(self._allow_commands) > 10 else "")
            )
        
        return True, "OK"

    def _sanitize_command(self, command: str) -> str:
        """清理命令字符串（基础清理）"""
        # 移除换行和特殊字符（防止命令注入）
        sanitized = command.replace("\n", " ").replace("\r", " ")
        # 移除连续空格
        while "  " in sanitized:
            sanitized = sanitized.replace("  ", " ")
        return sanitized.strip()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "command": {
                    "type": "string",
                    "description": "要执行的 Shell 命令（受白名单控制）"
                },
                "description": {
                    "type": "string",
                    "description": "人类可读的命令说明"
                },
                "timeout": {
                    "type": "integer",
                    "description": f"超时秒数 (最大 {BASH_MAX_TIMEOUT}, 默认 {BASH_DEFAULT_TIMEOUT})"
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "后台运行, 不等待完成"
                },
                "cwd": {
                    "type": "string",
                    "description": "工作目录 (可选)"
                }
            },
            tags=["command", "shell", "bash"]
        )

    async def execute(self, **kwargs) -> str:
        command: str = kwargs.get("command", "")
        description: str = kwargs.get("description", "")
        timeout: int = min(kwargs.get("timeout", BASH_DEFAULT_TIMEOUT), BASH_MAX_TIMEOUT)
        run_in_background: bool = kwargs.get("run_in_background", False)
        cwd: str = kwargs.get("cwd", os.getcwd())

        if not command:
            return "错误: 必须提供 command"
        
        # ===== 安全验证 =====
        allowed, reason = self._validate_command(command)
        if not allowed:
            self._log_audit(command, allowed=False, reason=reason)
            return f"[SECURITY BLOCKED] {reason}"
        
        # 清理命令
        safe_command = self._sanitize_command(command)
        
        # 记录审计日志
        self._log_audit(safe_command, allowed=True)

        if run_in_background:
            return await self._run_background(safe_command, description, cwd)

        try:
            return await asyncio.to_thread(self._run_sync, safe_command, description, timeout, cwd)
        except Exception as e:
            logger.error(f"Bash error: {e}")
            return f"错误: 命令执行失败: {e}"

    def _run_sync(self, command: str, description: str, timeout: int, cwd: str) -> str:
        try:
            # 安全改进：尽可能避免 shell=True
            # 对于简单命令（无管道、重定向、通配符），使用列表形式
            should_use_shell = any(char in command for char in ["|", "&", ";", ">", "<", "$", "*", "?", "`", "\\"])
            
            if should_use_shell:
                # 复杂命令必须用 shell=True，但已经过白名单验证
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=cwd,
                    encoding="utf-8",
                    errors="replace"
                )
            else:
                # 简单命令：参数化执行（更安全）
                cmd_parts = command.split()
                result = subprocess.run(
                    cmd_parts,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=cwd,
                    encoding="utf-8",
                    errors="replace"
                )
            
            output = []
            if description:
                output.append(f"$ {description}")
            output.append(f"$ {command}")
            if result.stdout:
                output.append(result.stdout)
            if result.stderr:
                output.append(f"[stderr]\n{result.stderr}")
            output.append(f"[exit code: {result.returncode}]")
            return chr(10).join(output)
        except subprocess.TimeoutExpired:
            return f"错误: 命令执行超时 ({timeout}秒)。\n命令: {command}"
        except Exception as e:
            return f"错误: {e}"

    async def _run_background(self, command: str, description: str, cwd: str) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            bg_id = f"bg_{int(time.time())}_{proc.pid}"
            self._background_tasks[bg_id] = proc
            self._log_audit(f"[BG] {command}", allowed=True, reason=f"pid={proc.pid}")
            return (
                f"✓ 后台任务已启动 (id: {bg_id}, pid: {proc.pid})\n"
                f"  命令: {command}\n"
                f"  使用 BashOutput 工具查看输出"
            )
        except Exception as e:
            return f"错误: 启动后台任务失败: {e}"


class BashOutputTool(ToolPlugin):
    name = "BashOutput"
    description = "读取后台任务的输出。"
    category = "command"
    execute_timeout = 30.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "task_id": {
                    "type": "string",
                    "description": "后台任务 ID"
                },
                "block": {
                    "type": "boolean",
                    "description": "阻塞等待任务完成 (默认 true)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "等待超时 (毫秒, 默认 30000)"
                }
            },
            tags=["command", "background"]
        )

    async def execute(self, **kwargs) -> str:
        task_id: str = kwargs.get("task_id", "")
        block: bool = kwargs.get("block", True)
        timeout_ms: int = kwargs.get("timeout", 30000)

        if not task_id:
            return "错误: 必须提供 task_id"

        return f"后台任务 '{task_id}' 状态查询 (此实现为简化版, 实际使用请结合 Bash 工具)"


class PowerShellTool(ToolPlugin):
    name = "PowerShell"
    description = "Windows 专用。执行 PowerShell 命令, 功能与 Bash 类似。"
    category = "command"
    requires_permission = True
    execute_timeout = BASH_MAX_TIMEOUT

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "command": {
                    "type": "string",
                    "description": "PowerShell 命令"
                },
                "description": {
                    "type": "string",
                    "description": "命令说明"
                },
                "timeout": {
                    "type": "integer",
                    "description": f"超时秒数 (默认 {BASH_DEFAULT_TIMEOUT})"
                }
            },
            tags=["command", "powershell", "windows"]
        )

    async def execute(self, **kwargs) -> str:
        command: str = kwargs.get("command", "")
        description: str = kwargs.get("description", "")
        timeout: int = min(kwargs.get("timeout", BASH_DEFAULT_TIMEOUT), BASH_MAX_TIMEOUT)

        if not command:
            return "错误: 必须提供 command"
        if sys.platform != "win32":
            return "错误: PowerShell 工具仅在 Windows 上可用"

        try:
            return await asyncio.to_thread(self._run, command, description, timeout)
        except Exception as e:
            return f"错误: {e}"

    def _run(self, command: str, description: str, timeout: int) -> str:
        full_cmd = f'powershell -NoProfile -Command "{command}"'
        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )
        parts = []
        if description:
            parts.append(f"$ {description}")
        parts.append(f"$ {command}")
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        parts.append(f"[exit code: {result.returncode}]")
        return chr(10).join(parts)


class TodoWriteTool(ToolPlugin):
    name = "TodoWrite"
    description = (
        "更新任务列表。每个任务有 content (描述) 和 status "
        "(pending / in_progress / completed)。"
        "使用此工具跟踪开发进度。"
    )
    category = "task"
    execute_timeout = 5.0

    _state: Optional[TodoState] = None

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"]
                            },
                            "id": {"type": "string"}
                        }
                    },
                    "description": "完整的待办列表 (替换整个列表)"
                }
            },
            tags=["task", "todo"]
        )

    async def execute(self, **kwargs) -> str:
        todos: List[Dict] = kwargs.get("todos", [])
        if TodoWriteTool._state is None:
            TodoWriteTool._state = TodoState()

        normalized = []
        for t in todos:
            normalized.append({
                "content": str(t.get("content", "")).strip(),
                "status": t.get("status", "pending"),
                "id": str(t.get("id", f"todo_{len(normalized)+1}"))
            })
        normalized = [t for t in normalized if t["content"]]
        TodoWriteTool._state.todos = normalized

        return TodoWriteTool._state.to_markdown()

    @classmethod
    def get_state(cls) -> TodoState:
        if cls._state is None:
            cls._state = TodoState()
        return cls._state

    @classmethod
    def reset(cls) -> None:
        cls._state = TodoState()


class WebFetchTool(ToolPlugin):
    name = "WebFetch"
    description = "获取 URL 内容并转 Markdown。支持大多数网页。"
    category = "web"
    requires_permission = True
    execute_timeout = 60.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "url": {
                    "type": "string",
                    "description": "目标 URL"
                },
                "prompt": {
                    "type": "string",
                    "description": "可选: 关注点, 提示 LLM 提取相关信息"
                }
            },
            tags=["web", "fetch"]
        )

    async def execute(self, **kwargs) -> str:
        url: str = kwargs.get("url", "")
        if not url:
            return "错误: 必须提供 url"
        if not url.startswith(("http://", "https://")):
            return f"错误: 无效的 URL: {url}"

        try:
            import aiohttp
        except ImportError:
            return "错误: aiohttp 未安装"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status >= 400:
                        return f"HTTP {resp.status}: {resp.reason}"
                    content = await resp.text()
            return await asyncio.to_thread(self._format, url, content)
        except Exception as e:
            logger.error(f"WebFetch error: {e}")
            return f"错误: 获取失败: {e}"

    def _format(self, url: str, content: str) -> str:
        content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content)
        content = content.replace("&nbsp;", " ").replace("&amp;", "&")
        content = content.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        content = content.strip()
        if len(content) > 8000:
            content = content[:8000] + "\n\n[内容已截断]"
        return f"URL: {url}\n\n{content}"


class WebSearchTool(ToolPlugin):
    name = "WebSearch"
    description = (
        "Search the PUBLIC INTERNET. "
        "Use this ONLY when the user asks about online content, news, "
        "or knowledge that is not on the local machine. "
        "For local files and directories, use `list_dir`, `glob`, `grep`, "
        "or `read_file` instead — never use WebSearch for local paths."
    )
    category = "web"
    requires_permission = True
    execute_timeout = 60.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "query": {
                    "type": "string",
                    "description": "搜索关键词"
                },
                "num_results": {
                    "type": "integer",
                    "description": "结果数量 (默认 10, 最大 20)"
                }
            },
            tags=["web", "search"]
        )

    async def execute(self, **kwargs) -> str:
        query: str = kwargs.get("query", "")
        num: int = min(kwargs.get("num_results", 10), 20)
        if not query:
            return "错误: 必须提供 query"

        # Prefer the legacy `core` Google-CSE backend when it's
        # actually configured (i.e. the user has set GOOGLE_API_KEY
        # and GOOGLE_CSE_ID). When it's not, the previous version
        # silently returned "未找到关于 'X' 的搜索结果" — useless
        # and indistinguishable from a real "no results" response.
        # In that case, fall back to the self-contained DuckDuckGo
        # HTML scraper from `hakus.tool_system`, so the user gets
        # either real results or a clear "network unavailable"
        # message — never a fake "no results" stub.
        try:
            from hakus.tools.web_google import WebSearcher  # type: ignore
            from utils.config import BASE_CONFIG  # type: ignore
            has_google = bool(
                BASE_CONFIG.get("GOOGLE_API_KEY")
                and BASE_CONFIG.get("GOOGLE_CSE_ID")
            )
        except Exception:
            WebSearcher = None  # type: ignore
            has_google = False

        if WebSearcher is not None and has_google:
            try:
                search_results = await WebSearcher.search(query, k=num)
            except Exception as e:
                return f"错误: 搜索失败: {e}"

            if search_results:
                lines = [f"搜索: {query}", ""]
                for i, r in enumerate(search_results, 1):
                    title = r.title or "(无标题)"
                    url = r.url or ""
                    snippet = (r.snippet or "")[:200]
                    lines.append(f"{i}. **{title}**")
                    lines.append(f"   URL: {url}")
                    if snippet:
                        lines.append(f"   {snippet}")
                    lines.append("")
                return chr(10).join(lines)

        # Fallback: self-contained DuckDuckGo scrape. This gives the
        # user a real "no network" / "no results" signal instead of
        # the silent empty-list that the Google-CSE path produced.
        try:
            from hakus.tools.builtin.web import _duckduckgo_search
            return await _duckduckgo_search(query, max_results=num)
        except Exception as e:
            return f"错误: 搜索失败: {e}"


class AskUserQuestionTool(ToolPlugin):
    name = "AskUserQuestion"
    description = "向用户提出多选问题以澄清需求。最多 4 个选项。"
    category = "interaction"
    execute_timeout = 300.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "question": {
                    "type": "string",
                    "description": "问题内容"
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "preview": {"type": "string"}
                        }
                    },
                    "description": "选项 (2-4 个)"
                },
                "multi_select": {
                    "type": "boolean",
                    "description": "是否多选 (默认 false)"
                }
            },
            tags=["interaction", "question"]
        )

    async def execute(self, **kwargs) -> str:
        question: str = kwargs.get("question", "")
        options: List[Dict] = kwargs.get("options", [])
        multi_select: bool = kwargs.get("multi_select", False)

        if not question:
            return "错误: 必须提供 question"
        if not options or len(options) < 2:
            return "错误: 至少需要 2 个选项"
        if len(options) > 4:
            options = options[:4]

        print(f"\n❓ {question}")
        for i, opt in enumerate(options, 1):
            label = opt.get("label", f"选项 {i}")
            desc = opt.get("description", "")
            print(f"  {i}. {label}" + (f" — {desc}" if desc else ""))

        prompt = "请选择 (多个用逗号分隔)" if multi_select else "请选择"
        try:
            answer = input(f"\n{prompt} [1-{len(options)}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return "[用户中断]"

        try:
            if multi_select:
                selected = [int(s.strip()) for s in answer.split(",") if s.strip().isdigit()]
                selected = [s for s in selected if 1 <= s <= len(options)]
                if not selected:
                    return "[未选择有效选项]"
                labels = [options[i-1].get("label") for i in selected]
                return f"用户选择: {', '.join(labels)}"
            else:
                n = int(answer)
                if 1 <= n <= len(options):
                    return f"用户选择: {options[n-1].get('label')}"
                return "[无效选择]"
        except ValueError:
            return f"[无效输入: {answer}]"


class GitStatusTool(ToolPlugin):
    name = "GitStatus"
    description = "获取 Git 仓库状态: 改动的文件、未跟踪的文件、分支信息。"
    category = "git"
    execute_timeout = 15.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "cwd": {
                    "type": "string",
                    "description": "Git 仓库目录 (默认当前工作目录)"
                }
            },
            tags=["git", "status"]
        )

    async def execute(self, **kwargs) -> str:
        cwd: str = kwargs.get("cwd", os.getcwd())
        try:
            return await asyncio.to_thread(self._status, cwd)
        except Exception as e:
            return f"错误: {e}"

    def _status(self, cwd: str) -> str:
        if not self._is_git_repo(cwd):
            return f"错误: {cwd} 不是 Git 仓库"

        parts = []
        branch = subprocess.run(
            "git rev-parse --abbrev-ref HEAD",
            shell=True, capture_output=True, text=True, cwd=cwd
        )
        if branch.returncode == 0:
            parts.append(f"分支: {branch.stdout.strip()}")

        status = subprocess.run(
            "git status --porcelain",
            shell=True, capture_output=True, text=True, cwd=cwd
        )
        if status.stdout.strip():
            parts.append("改动文件:")
            for line in status.stdout.strip().split(chr(10)):
                parts.append(f"  {line}")
        else:
            parts.append("无改动")

        untracked = subprocess.run(
            "git ls-files --others --exclude-standard",
            shell=True, capture_output=True, text=True, cwd=cwd
        )
        if untracked.stdout.strip():
            parts.append("未跟踪文件:")
            for line in untracked.stdout.strip().split(chr(10))[:20]:
                parts.append(f"  {line}")
        return chr(10).join(parts)

    def _is_git_repo(self, cwd: str) -> bool:
        result = subprocess.run(
            "git rev-parse --git-dir",
            shell=True, capture_output=True, text=True, cwd=cwd
        )
        return result.returncode == 0


class GitDiffTool(ToolPlugin):
    name = "GitDiff"
    description = "获取 Git 差异 (staged 或 unstaged)。"
    category = "git"
    execute_timeout = 15.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "staged": {
                    "type": "boolean",
                    "description": "显示已暂存的差异 (默认 false)"
                },
                "file": {
                    "type": "string",
                    "description": "只看指定文件的差异"
                },
                "cwd": {
                    "type": "string",
                    "description": "Git 仓库目录"
                }
            },
            tags=["git", "diff"]
        )

    async def execute(self, **kwargs) -> str:
        staged: bool = kwargs.get("staged", False)
        file: str = kwargs.get("file", "")
        cwd: str = kwargs.get("cwd", os.getcwd())
        try:
            return await asyncio.to_thread(self._diff, staged, file, cwd)
        except Exception as e:
            return f"错误: {e}"

    def _diff(self, staged: bool, file: str, cwd: str) -> str:
        cmd = f"git diff {'--staged' if staged else ''}"
        if file:
            cmd += f" -- {file}"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=cwd
        )
        output = result.stdout
        if not output:
            return "无差异"
        if len(output) > 5000:
            output = output[:5000] + "\n\n[diff 已截断]"
        return output


class GitCommitTool(ToolPlugin):
    name = "GitCommit"
    description = "暂存并提交改动。自动生成 commit message 或使用指定 message。"
    category = "git"
    requires_permission = True
    execute_timeout = 30.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "message": {
                    "type": "string",
                    "description": "commit message"
                },
                "add_all": {
                    "type": "boolean",
                    "description": "暂存所有改动 (git add -A)"
                },
                "cwd": {
                    "type": "string",
                    "description": "Git 仓库目录"
                }
            },
            tags=["git", "commit"]
        )

    async def execute(self, **kwargs) -> str:
        message: str = kwargs.get("message", "")
        add_all: bool = kwargs.get("add_all", True)
        cwd: str = kwargs.get("cwd", os.getcwd())

        if not message:
            return "错误: 必须提供 commit message"

        try:
            return await asyncio.to_thread(self._commit, message, add_all, cwd)
        except Exception as e:
            return f"错误: {e}"

    def _commit(self, message: str, add_all: bool, cwd: str) -> str:
        if add_all:
            subprocess.run("git add -A", shell=True, cwd=cwd, check=True)
        result = subprocess.run(
            f'git commit -m "{message}"',
            shell=True, capture_output=True, text=True, cwd=cwd
        )
        if result.returncode != 0:
            return f"提交失败:\n{result.stderr}"

        log = subprocess.run(
            "git log -1 --stat",
            shell=True, capture_output=True, text=True, cwd=cwd
        )
        return f"✓ 提交成功:\n{log.stdout}"


class GitLogTool(ToolPlugin):
    name = "GitLog"
    description = "查看 Git 提交历史。"
    category = "git"
    execute_timeout = 15.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "num": {
                    "type": "integer",
                    "description": "显示条数 (默认 10)"
                },
                "oneline": {
                    "type": "boolean",
                    "description": "一行格式 (默认 false)"
                },
                "cwd": {
                    "type": "string",
                    "description": "Git 仓库目录"
                }
            },
            tags=["git", "log"]
        )

    async def execute(self, **kwargs) -> str:
        num: int = kwargs.get("num", 10)
        oneline: bool = kwargs.get("oneline", False)
        cwd: str = kwargs.get("cwd", os.getcwd())
        try:
            return await asyncio.to_thread(self._log, num, oneline, cwd)
        except Exception as e:
            return f"错误: {e}"

    def _log(self, num: int, oneline: bool, cwd: str) -> str:
        fmt = "--oneline" if oneline else "--pretty=format:%h %an %ad %s%n  %b%n  ---%n" + "----" + "---"
        cmd = f"git log -{num} {fmt} --date=short"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
        return result.stdout or "无提交记录"


class TreeTool(ToolPlugin):
    name = "Tree"
    description = "显示项目目录树结构。"
    category = "file"
    execute_timeout = 15.0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters_schema={
                "path": {
                    "type": "string",
                    "description": "目录路径"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "最大深度 (默认 3)"
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "包含隐藏文件 (默认 false)"
                }
            },
            tags=["file", "tree"]
        )

    async def execute(self, **kwargs) -> str:
        path: str = kwargs.get("path", ".") or "."
        max_depth: int = kwargs.get("max_depth", 3)
        include_hidden: bool = kwargs.get("include_hidden", False)

        base = Path(path).resolve()
        if not base.exists():
            return f"错误: 路径不存在: {base}"
        if not base.is_dir():
            return f"错误: 路径不是目录: {base}"

        try:
            return await asyncio.to_thread(self._tree, base, max_depth, include_hidden)
        except Exception as e:
            return f"错误: {e}"

    def _tree(self, base: Path, max_depth: int, include_hidden: bool) -> str:
        ignore_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv",
                       "dist", "build", ".next", ".cache", "target", ".idea",
                       ".vscode", ".DS_Store", "*.egg-info"}

        def should_ignore(name: str) -> bool:
            if not include_hidden and name.startswith("."):
                return True
            return any(glob_module.fnmatch.fnmatch(name, p) for p in ignore_dirs)

        def build_tree(p: Path, prefix: str, depth: int) -> List[str]:
            if depth > max_depth:
                return []
            try:
                entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            except PermissionError:
                return [f"{prefix}└── [无权限]"]
            entries = [e for e in entries if not should_ignore(e.name)]

            lines = []
            for i, entry in enumerate(entries):
                is_last = i == len(entries) - 1
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{entry.name}" + ("/" if entry.is_dir() else ""))
                if entry.is_dir() and depth < max_depth:
                    extension = "    " if is_last else "│   "
                    lines.extend(build_tree(entry, prefix + extension, depth + 1))
            return lines

        lines = [f"{base.name}/"] + build_tree(base, "", 1)
        return chr(10).join(lines)


def register_dev_tools(registry) -> int:
    """注册所有开发工具到 registry. 返回注册数量."""
    tools = [
        ReadTool(),
        WriteTool(),
        EditTool(),
        MultiEditTool(),
        GlobTool(),
        GrepTool(),
        BashTool(),
        BashOutputTool(),
        PowerShellTool(),
        TodoWriteTool(),
        WebFetchTool(),
        WebSearchTool(),
        AskUserQuestionTool(),
        GitStatusTool(),
        GitDiffTool(),
        GitCommitTool(),
        GitLogTool(),
        TreeTool(),
    ]
    for tool in tools:
        registry.register(tool)
    return len(tools)