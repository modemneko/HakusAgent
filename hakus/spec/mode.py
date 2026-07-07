"""
Spec-driven development 模块

工作流:
- /spec init <name>  创建 spec 目录 + 模板文件
- /spec list         列出所有 spec
- /spec show <name>  显示 spec 内容
- /spec use <name>   切换活跃 spec
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional


SPEC_DIR = os.path.join(os.getcwd(), ".hakus", "specs")
ACTIVE_FILE = os.path.join(SPEC_DIR, ".active")


class SpecMode:
    """Spec 模式管理器."""

    @staticmethod
    def _ensure_dir() -> None:
        os.makedirs(SPEC_DIR, exist_ok=True)

    @staticmethod
    def init(name: str = "") -> str:
        """创建新 spec 目录和模板文件."""
        if not name:
            return "用法: /spec init <name>  (例: /spec init add-auth)"

        # 清理 name
        name = name.strip().lower().replace(" ", "-")
        spec_path = os.path.join(SPEC_DIR, name)

        if os.path.exists(spec_path):
            return f"Spec `{name}` 已存在。使用 `/spec show {name}` 查看。"

        os.makedirs(spec_path, exist_ok=True)

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # spec.md
        spec_md = f"""# {name} Spec

## Why
[1-2 句描述问题/机会]

## What Changes
- [变更列表]

## Impact
- Affected code: [关键文件/系统]

## ADDED Requirements
### Requirement: 新功能
系统 SHALL 提供...

#### Scenario: 成功场景
- **WHEN** 用户执行操作
- **THEN** 预期结果

## MODIFIED Requirements
### Requirement: 已有功能
[修改后的完整需求描述]
"""
        with open(os.path.join(spec_path, "spec.md"), "w", encoding="utf-8") as f:
            f.write(spec_md)

        # tasks.md
        tasks_md = f"""# Tasks

- [ ] Task 1: [描述]
  - [ ] SubTask 1.1: [描述]
  - [ ] SubTask 1.2: [描述]
- [ ] Task 2: [描述]

# Task Dependencies
- [Task 2] depends on [Task 1]
"""
        with open(os.path.join(spec_path, "tasks.md"), "w", encoding="utf-8") as f:
            f.write(tasks_md)

        # checklist.md
        checklist_md = f"""# Checklist

- [ ] [验证项 1]
- [ ] [验证项 2]
"""
        with open(os.path.join(spec_path, "checklist.md"), "w", encoding="utf-8") as f:
            f.write(checklist_md)

        # 设为活跃
        SpecMode._set_active(name)

        return (
            f"Spec `{name}` 已创建!\n\n"
            f"目录: `.hakus/specs/{name}/`\n"
            f"- `spec.md` — 规格说明\n"
            f"- `tasks.md` — 任务列表\n"
            f"- `checklist.md` — 验证清单\n\n"
            f"已设为当前活跃 spec。"
        )

    @staticmethod
    def list() -> str:
        """列出所有 spec."""
        if not os.path.exists(SPEC_DIR):
            return "暂无 spec。使用 `/spec init <name>` 创建。"

        active = SpecMode.get_active()
        entries = []
        for d in sorted(os.listdir(SPEC_DIR)):
            if d.startswith(".") or not os.path.isdir(os.path.join(SPEC_DIR, d)):
                continue
            marker = " ◀ active" if d == active else ""
            # 读取 spec.md 第一行作为标题
            spec_file = os.path.join(SPEC_DIR, d, "spec.md")
            title = d
            if os.path.exists(spec_file):
                try:
                    with open(spec_file, "r", encoding="utf-8") as f:
                        first = f.readline().strip()
                        if first.startswith("# "):
                            title = first[2:]
                except Exception:
                    pass
            entries.append(f"- `{d}` — {title}{marker}")

        if not entries:
            return "暂无 spec。使用 `/spec init <name>` 创建。"

        header = "# Spec 列表\n"
        return header + "\n".join(entries)

    @staticmethod
    def show(name: str) -> str:
        """显示指定 spec 的内容."""
        if not name:
            return "用法: /spec show <name>"

        spec_path = os.path.join(SPEC_DIR, name)
        if not os.path.exists(spec_path):
            return f"Spec `{name}` 不存在。使用 `/spec list` 查看所有 spec。"

        parts = []
        for fname in ("spec.md", "tasks.md", "checklist.md"):
            fpath = os.path.join(spec_path, fname)
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    parts.append(content)
                except Exception:
                    parts.append(f"(无法读取 {fname})")

        return "\n\n---\n\n".join(parts) if parts else f"Spec `{name}` 目录为空。"

    @staticmethod
    def use(name: str) -> str:
        """切换活跃 spec."""
        if not name:
            return "用法: /spec use <name>"

        spec_path = os.path.join(SPEC_DIR, name)
        if not os.path.exists(spec_path):
            return f"Spec `{name}` 不存在。使用 `/spec list` 查看所有 spec。"

        SpecMode._set_active(name)
        return f"已切换到 spec `{name}`。"

    @staticmethod
    def get_active() -> Optional[str]:
        """获取当前活跃 spec 名称."""
        try:
            with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                name = f.read().strip()
                if name and os.path.exists(os.path.join(SPEC_DIR, name)):
                    return name
        except Exception:
            pass
        return None

    @staticmethod
    def _set_active(name: str) -> None:
        SpecMode._ensure_dir()
        try:
            with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
                f.write(name)
        except Exception:
            pass
