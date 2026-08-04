import logging
import os
import sys
from pathlib import Path
from typing import Optional

from .config import BASE_CONFIG

_LOG_FILE_HANDLE: Optional["logging.FileHandler"] = None
_QUIETED = False


def _resolve_log_file() -> Optional[str]:
    """将日志写入 logs/hakusai.log，方便和 sidecar 日志统一查看。

    环境变量覆盖：
      - HAKUS_LOG_FILE=<path>   写指定路径
      - HAKUS_LOG_FILE=stderr   不写文件，只输出到 stderr
      - HAKUS_LOG_FILE=off      禁用日志
    """
    explicit = os.environ.get("HAKUS_LOG_FILE", "").strip().lower()
    if explicit == "stderr" or explicit == "console":
        return None
    if explicit == "off":
        return None
    if explicit:
        log_path = Path(explicit)
    else:
        # 默认: 当前工作目录/logs/hakusai.log
        log_path = Path.cwd() / "logs" / "hakusai.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return str(log_path)
    except Exception:
        return None


def _make_emit(original_emit):
    """包装 emit 方法, 强制在 emit 后立刻 flush (Claude Code 风格: 即时输出)."""
    def emit_with_flush(record):
        try:
            original_emit(record)
        finally:
            try:
                if hasattr(record, "stream") and record.stream:
                    pass
                stream = sys.stderr
                if hasattr(stream, "flush"):
                    stream.flush()
            except Exception:
                pass
    return emit_with_flush


def _try_sidecar_logger(name: str) -> Optional[logging.Logger]:
    """尝试使用 sidecar 的结构化日志系统。

    如果 sidecar 的 logging_config 模块可以导入，就委托给它，
    让日志按分类写入 sidecar.log/agent.log/orchestrator.log/
    tools.log/llm.log。

    即使 setup_logging 还没被调用，get_logger 也会正确创建文件 handler。
    """
    try:
        import sys as _sys
        # sidecar 的 src/ 目录在 sys.path 中时才能导入
        for p in ("src", "hakusai_server"):
            rp = Path.cwd() / p
            if rp.exists() and str(rp) not in _sys.path:
                _sys.path.insert(0, str(rp))
        from hakusai_server.logging_config import get_logger as _sidecar_get_logger
        return _sidecar_get_logger(name)
    except Exception:
        pass
    return None


def get_logger(name: str, log_file: Optional[str] = None) -> logging.Logger:
    """获取配置好的日志记录器.

    优先使用 sidecar 的结构化日志系统（按分类写入不同文件）。
    如果 sidecar 未初始化，回退到本地 hakusai.log 文件。

    Claude Code 风格:
      - INFO 及以上 → 写入日志文件
      - 控制台不输出常规日志
      - 仅 ERROR/CRITICAL 输出到 stderr (除非明确禁用)
    """
    global _LOG_FILE_HANDLE

    # 优先委托给 sidecar 的分类日志系统
    sidecar_logger = _try_sidecar_logger(name)
    if sidecar_logger is not None:
        return sidecar_logger

    logger = logging.getLogger(name)
    logger.setLevel(BASE_CONFIG["LOG_LEVEL"])

    if not getattr(logger, "_hakus_configured", False):
        setattr(logger, "_hakus_configured", True)
        # 阻止日志向父 logger 冒泡到 root (避免重复输出)
        logger.propagate = False

        # 移除 root handler 重复 (防止 logging.basicConfig 介入)
        for h in list(logger.handlers):
            logger.removeHandler(h)

        # 1) 文件 handler (主日志通道)
        target_file = log_file or _resolve_log_file()
        if target_file:
            try:
                fh = logging.FileHandler(target_file, encoding="utf-8")
                fh.setLevel(logging.DEBUG)
                fh.setFormatter(logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                ))
                logger.addHandler(fh)
                _LOG_FILE_HANDLE = fh
            except Exception:
                pass

        # 2) stderr handler — 默认只显示 ERROR, 详细模式下显示 INFO
        verbose = os.environ.get("HAKUS_VERBOSE", "").strip() in ("1", "true", "yes")
        sh = logging.StreamHandler(stream=sys.stderr)
        sh.setLevel(logging.INFO if verbose else logging.ERROR)
        sh.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        # 强制 flush — Claude Code 风格: 输出立刻可见
        sh.emit = _make_emit(sh.emit)
        logger.addHandler(sh)

    return logger


def quiet_console_loggers() -> None:
    """Claude Code 风格: 把所有内部 logger 静默, 只保留 WARNING+ 输出到 stderr.
    用户设置 HAKUS_VERBOSE=1 可恢复 INFO 输出到 stderr."""
    global _QUIETED
    if _QUIETED:
        return
    _QUIETED = True

    if os.environ.get("HAKUS_VERBOSE", "").strip() in ("1", "true", "yes"):
        # 详细模式: 全部 INFO 输出到 stderr
        for name in _HAKUS_INTERNAL_LOGGERS:
            lg = logging.getLogger(name)
            for h in lg.handlers:
                if isinstance(h, logging.StreamHandler) and h.stream in (sys.stderr, sys.stdout):
                    h.setLevel(logging.INFO)
        return

    # 静默模式: 这些 logger 完全静默
    for name in _HAKUS_INTERNAL_LOGGERS:
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        lg.propagate = False


_HAKUS_INTERNAL_LOGGERS = [
    "hakus", "hakus.hooks", "hakus.agent", "hakus.entry",
    "hakus.cli", "hakus.tui", "hakus.tool_system", "hakus.builtin_tools",
    "hakus.dev_tools", "hakus.computer_control", "hakus.voice_bridge",
    "hakus.sub_agents", "hakus.orchestrator", "hakus.context",
    "hakus.checkpoint", "hakus.permission", "hakus.memory", "hakus.memory_vector",
    "hakus.session_store", "hakus.plan_mode", "hakus.task_board",
    "hakus.workspace", "hakus.multi_dim_test", "hakus.long_task_tools",
    "core", "core.tools", "core.tools.base", "core.task_templates",
    "core.tools.long_task_plugins", "core.tools.search_plugins",
    "core.tools.web_plugins", "core.tools.content_plugins",
    "core.sub_agent_factory", "core.simple_chat", "core.orchestrator",
    "core.orchestrator_workspace", "core.scheduler", "core.inner_mind",
    "core.memory", "core.memory_compressor", "core.file_state_store",
    "core.file_parser", "core.search_skills", "core.meme",
    "models", "models.deepseek_model", "models.qwen_model",
    "models.glm_model", "models.gemini_model", "models.mimo_model",
    "utils", "voice", "tts", "tts.api_tts", "tts.cosyvoice_tts",
    "tts.sherpa_onnx_tts", "tts.tts_manager",
    "voice.asr_engine", "voice.bert_vits2_tts", "voice.voice_live",
    "voice.voice_config",
]
