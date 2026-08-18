"""HakusCLI — 新一代终端 AI Coding Agent.

替代旧 ``frontend/terminal/`` (Ink v5) 与历史 ``hakus/tui_v2/`` (Textual)。
本模块用纯 Python + Textual + Rich 渲染，直接 in-process 调用
``hakus.agent.AgentCore``，无 HTTP server / 子进程边界。

入口：``hakus.entry:main`` (pyproject.toml 的 ``hakusai`` script)。

参考：``HAKUS_CLI_DESIGN.md`` (项目根)。
"""
from .app import HakusCLI

__all__ = ["HakusCLI"]
