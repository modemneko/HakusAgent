"""
HakusAI 项目记忆 (CLAUDE.md / .hakus.md / MEMORY.md)
支持多层记忆:
  ~/.hakus/CLAUDE.md       个人全局
  <project>/.hakus.md      项目级 (推荐)
  <project>/CLAUDE.md      Claude Code 兼容
  <project>/.hakus.local.md 本地私有
  <dir>/CLAUDE.md          目录级 (进入时加载)
"""
import os
from pathlib import Path
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

GLOBAL_MEMORY = os.path.join(os.path.expanduser("~"), ".hakus", "CLAUDE.md")
GLOBAL_HAKUS_MD = os.path.join(os.path.expanduser("~"), ".hakus", ".hakus.md")
MAX_MEMORY_LINES = 200


class ProjectMemory:
    """项目记忆加载器"""

    def __init__(self, working_dir: str):
        self.working_dir = Path(working_dir).resolve()
        self._loaded: List[Dict[str, str]] = []
        self._session_notes: List[str] = []
        self._user_preferences: List[str] = []

    def load(self) -> str:
        """加载所有层级的记忆, 返回合并后的内容."""
        self._loaded = []
        self._add_global()
        self._add_project()
        self._add_directory()
        return self._render()

    def add_session_note(self, note: str) -> None:
        """添加会话笔记 (运行时, 不持久化到磁盘)."""
        self._session_notes.append(note.strip())

    def add_user_preference(self, pref: str) -> None:
        """添加用户偏好 (运行时, 不持久化)."""
        self._user_preferences.append(pref.strip())

    def get_injection(self) -> str:
        """获取注入到系统提示词的内容."""
        sections = []
        if self._user_preferences:
            sections.append("## 用户偏好\n" + chr(10).join(f"- {p}" for p in self._user_preferences))
        if self._session_notes:
            sections.append("## 会话笔记\n" + chr(10).join(f"- {n}" for n in self._session_notes))
        if not sections:
            return ""
        return "# Project Memory\n\n" + "\n\n".join(sections)

    def _add_global(self) -> None:
        for path in [GLOBAL_MEMORY, GLOBAL_HAKUS_MD]:
            if os.path.exists(path):
                self._add_file(path, "global")

    def _add_project(self) -> None:
        candidates = [".hakus.md", "CLAUDE.md", ".claude.md"]
        for name in candidates:
            path = self.working_dir / name
            if path.exists():
                self._add_file(str(path), "project")

        local = self.working_dir / ".hakus.local.md"
        if local.exists():
            self._add_file(str(local), "project-local")

    def _add_directory(self) -> None:
        depth = 0
        current = self.working_dir
        while depth < 3:
            for name in ["CLAUDE.md", ".claude.md"]:
                path = current / name
                if path.exists():
                    self._add_file(str(path), f"dir:{current.name}")
            parent = current.parent
            if parent == current:
                break
            current = parent
            depth += 1

    def _add_file(self, path: str, scope: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > MAX_MEMORY_LINES:
                lines = lines[:MAX_MEMORY_LINES]
                total = self._count_lines(path)
                lines.append(f"\n[... 截断, 共 {len(lines)} 行, 文件总计 {total} 行]")
            content = "".join(lines).strip()
            if content:
                self._loaded.append({"scope": scope, "path": path, "content": content})
        except Exception as e:
            logger.warning(f"Failed to load memory file {path}: {e}")

    def _count_lines(self, path: str) -> int:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        except Exception:
            return 0

    def _render(self) -> str:
        if not self._loaded:
            return ""
        sections = []
        for item in self._loaded:
            scope = item["scope"]
            header = f"## [{scope}] {item['path']}"
            sections.append(f"{header}\n\n{item['content']}")
        return "# Project Memory\n\n" + "\n\n---\n\n".join(sections)

    def list_loaded(self) -> List[Dict[str, str]]:
        return list(self._loaded)


def discover_memory_files(working_dir: str) -> List[str]:
    """扫描项目目录, 列出所有记忆文件 (供 /memory 命令使用)."""
    base = Path(working_dir).resolve()
    found = []
    candidates = [".hakus.md", "CLAUDE.md", ".claude.md", ".hakus.local.md", "MEMORY.md"]
    for name in candidates:
        path = base / name
        if path.exists():
            found.append(str(path))
    for sub in ["docs", ".claude", ".hakus"]:
        sub_path = base / sub
        if sub_path.exists() and sub_path.is_dir():
            for p in sub_path.rglob("*.md"):
                found.append(str(p))
    return found


def create_project_memory(
    working_dir: str,
    project_name: Optional[str] = None,
    description: Optional[str] = None,
    tech_stack: Optional[List[str]] = None,
    build_commands: Optional[Dict[str, str]] = None,
    conventions: Optional[List[str]] = None,
) -> str:
    """根据提供的项目信息自动创建 .hakus.md 文件."""
    base = Path(working_dir).resolve()
    project_name = project_name or base.name
    description = description or f"{project_name} 项目"
    tech_stack = tech_stack or []
    build_commands = build_commands or {}
    conventions = conventions or []

    NEWLINE = chr(10)
    tech_section = NEWLINE.join(f"- {t}" for t in tech_stack) if tech_stack else "- 暂无"
    build_section = NEWLINE.join(f"### {k}\n```bash\n{v}\n```" for k, v in build_commands.items()) if build_commands else "暂无"
    conv_section = NEWLINE.join(f"- {c}" for c in conventions) if conventions else "- 暂无"

    content = f"""# {project_name}

{description}

## 技术栈
{tech_section}

## 项目结构
```
{project_name}/
```

## 构建与运行
{build_section}

## 代码规范
{conv_section}

## 重要约定
- 使用 HakusAI 时, 优先使用专用工具 (Read/Edit/Write/Glob/Grep), 避免 cat/grep/find 等命令
- 修改文件前先 Read
- 编辑字符串必须唯一, 否则使用 replace_all 或提供更多上下文

## 注意事项
- 在此添加项目特定注意事项
"""
    target = base / ".hakus.md"
    target.write_text(content, encoding="utf-8")
    return str(target)