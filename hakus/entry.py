"""HakusCLI — HakusAgent 终端版入口.

pyproject.toml 中: ``hakusai = "hakus.entry:main"`` 与别名 ``hakuscli``。

用法::

    hakuscli                             # 启动 TUI (默认 Work 模式 + dark 主题)
    hakuscli --mode code                 # 启动 TUI (Code 模式)
    hakuscli --effort deep               # 启动 TUI (深度思考)
    hakuscli --model glm-4.5             # 指定模型
    hakuscli --theme light               # 切换主题
    hakuscli --cwd /path/to/project      # 设置 working dir

环境变量:
    HAKUS_MODEL           默认模型名 (default: deepseek)
    HAKUS_MODE             默认模式 (swift/deep, default: swift)
    HAKUS_EFFORT           默认思考强度 (quick/deep/ultra, default: quick)
    HAKUS_THEME            默认主题 (dark/light/auto, default: dark)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys


def _force_utf8_stdio() -> None:
    """Windows 中文系统下，stdout/stderr 被管道/重定向接管时 Python 默认
    用 GBK 编码，消费方按 UTF-8 解码 → 中文全乱码。强制对齐 UTF-8。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _normalize_effort(effort: str) -> str | None:
    """用户输入 → reasoning_effort 值."""
    m = {
        "quick": None,
        "fast": None,
        "low": "low",
        "deep": "high",
        "high": "high",
        "ultra": "max",
        "max": "max",
    }
    return m.get(effort.lower(), None)


def main() -> int:
    """主入口."""
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="hakuscli",
        description="HakusCLI — HakusAgent 终端版 (macOS/Linux/Windows/Termux)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "环境变量:\n"
            "  HAKUS_MODEL    默认模型名 (default: deepseek)\n"
            "  HAKUS_MODE      默认模式 (swift/deep, default: swift)\n"
            "  HAKUS_EFFORT    默认思考强度 (quick/deep/ultra, default: quick)\n"
            "  HAKUS_THEME     默认主题 (dark/light/auto, default: dark)\n"
        ),
    )
    parser.add_argument(
        "--model", "-m",
        default=os.environ.get("HAKUS_MODEL", "deepseek"),
        help="模型名 (deepseek / glm / qwen / openai / anthropic / ...)",
    )
    parser.add_argument(
        "--mode",
        choices=["work", "code", "swift", "deep"],
        default=os.environ.get("HAKUS_MODE", "swift"),
        help="运行模式 (work/code 别名 swift/deep)",
    )
    parser.add_argument(
        "--effort",
        choices=["quick", "deep", "ultra", "low", "high", "max", "fast"],
        default=os.environ.get("HAKUS_EFFORT", "quick"),
        help="思考强度档位",
    )
    parser.add_argument(
        "--theme",
        choices=["dark", "light", "auto"],
        default=os.environ.get("HAKUS_THEME", "dark"),
        help="配色主题",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="Agent 的 working directory (default: 当前目录)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细日志 (debug)",
    )

    args = parser.parse_args()

    _setup_logging(args.verbose)

    # 归一化
    mode = args.mode
    if mode == "work":
        mode = "swift"
    elif mode == "code":
        mode = "deep"

    effort = _normalize_effort(args.effort)

    # 静默掉 hakus.* 子模块的 DEBUG 噪音
    if not args.verbose:
        for name in ("hakus", "hakus.agent", "hakus.tools", "httpx", "openai"):
            logging.getLogger(name).setLevel(logging.WARNING)

    # 启动 TUI
    try:
        from .cli import HakusCLI
    except ImportError as e:
        print(f"无法加载 HakusCLI: {e}", file=sys.stderr)
        print("请确认 textual / rich 已安装: pip install textual rich", file=sys.stderr)
        return 2

    app = HakusCLI(
        model_type=args.model,
        run_mode=mode,
        reasoning_effort=effort,
        working_dir=args.cwd,
        theme=args.theme,
    )
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
