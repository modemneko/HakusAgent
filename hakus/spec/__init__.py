"""
Spec-driven development 模块

提供 /spec 命令支持:
- /spec init <name>  创建 spec 目录 + 模板
- /spec list         列出所有 spec
- /spec show <name>  显示 spec 内容
- /spec use <name>   切换活跃 spec
"""
from .mode import SpecMode

__all__ = ["SpecMode"]
