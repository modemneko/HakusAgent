"""
HakusAI sidecar 结构化日志系统。

把服务端运行、Agent 执行、多 Agent 编排、工具调用、LLM 调用全部按天
持久化到 logs/ 目录，并暴露 /api/logs 给前端拉取/过滤。
"""

import logging
import logging.handlers
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 日志根目录：放在项目根目录 logs/ 下
LOG_DIR = Path(os.environ.get("HAKUSAI_LOG_DIR", "logs"))
LOG_RETENTION_DAYS = int(os.environ.get("HAKUSAI_LOG_RETENTION_DAYS", "7"))
MAX_LOG_BYTES = int(os.environ.get("HAKUSAI_MAX_LOG_BYTES", "20_000_000"))  # 20MB
BACKUP_COUNT = int(os.environ.get("HAKUSAI_LOG_BACKUP_COUNT", "5"))

# 日志文件配置
LOG_FILES = {
    "sidecar": "sidecar.log",
    "agent": "agent.log",
    "orchestrator": "orchestrator.log",
    "tools": "tools.log",
    "llm": "llm.log",
}

# 每个 logger 的默认级别
DEFAULT_LEVELS = {
    "sidecar": logging.INFO,
    "agent": logging.INFO,
    "orchestrator": logging.INFO,
    "tools": logging.INFO,
    "llm": logging.INFO,
}

_formatter_lock = threading.Lock()
_formatters: Dict[str, logging.Formatter] = {}
_handlers: Dict[str, logging.handlers.RotatingFileHandler] = {}
_loggers: Dict[str, logging.Logger] = {}


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


class _JsonFormatter(logging.Formatter):
    """NDJSON 格式：每行一个 JSON，msg 字段正确转义。

    - structured() 记录的 msg 是 JSON 字符串 (e.g. '{"event":"tool.start",...}')
      → 解析后嵌入为对象
    - 普通 logger.info("text") 记录的 msg 是纯文本
      → 嵌入为字符串
    """

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        # 如果 msg 本身就是 JSON（structured() 传入的），解析为对象
        try:
            msg_value = json.loads(msg)
        except (json.JSONDecodeError, TypeError):
            msg_value = msg
        # 用 ISO 格式时间，带毫秒
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        return json.dumps({
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": msg_value,
        }, ensure_ascii=False, default=str)


def _json_formatter() -> logging.Formatter:
    """NDJSON 格式：每行一个 JSON，方便前端解析和 grep。"""
    return _JsonFormatter()


def _text_formatter() -> logging.Formatter:
    """人类可读格式：保留时间、级别、logger、消息。"""
    return logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _make_handler(name: str, use_json: bool = True) -> logging.handlers.RotatingFileHandler:
    _ensure_log_dir()
    path = LOG_DIR / LOG_FILES[name]
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    formatter = _json_formatter() if use_json else _text_formatter()
    handler.setFormatter(formatter)
    handler.setLevel(DEFAULT_LEVELS.get(name, logging.INFO))
    return handler


def get_logger(name: str) -> logging.Logger:
    """
    获取一个带持久化文件 handler 的命名 logger。

    name 约定：
        haku.sidecar.*   -> sidecar.log
        haku.agent.*     -> agent.log
        haku.orchestrator.* -> orchestrator.log
        haku.tools.*     -> tools.log
        haku.llm.*       -> llm.log
    """
    category = "sidecar"
    if name.startswith(("haku.agent", "hakus.agent", "hakus.agent.bridge")):
        category = "agent"
    elif name.startswith(("haku.orchestrator", "hakus.orchestrator")):
        category = "orchestrator"
    elif name.startswith(("haku.tools", "hakus.tools", "hakus.tools.")):
        category = "tools"
    elif name.startswith(("haku.llm", "hakus.llm", "hakus.models.")):
        category = "llm"

    logger_key = f"{category}:{name}"
    if logger_key in _loggers:
        return _loggers[logger_key]

    with _formatter_lock:
        if logger_key in _loggers:
            return _loggers[logger_key]

        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        # 避免重复添加 handler
        if not logger.handlers:
            handler = _make_handler(category)
            logger.addHandler(handler)
            _handlers[name] = handler
        logger.propagate = False
        _loggers[logger_key] = logger
        return logger


def setup_logging(console_level: int = logging.INFO) -> None:
    """
    配置根日志：
      - console 输出 INFO 以上
      - 各分类 logger 写独立文件
      - 清理超过保留天数的旧日志
    """
    _ensure_log_dir()

    # 根 logger：console + sidecar.log
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(console_level)
        console.setFormatter(_text_formatter())
        root.addHandler(console)

    # 确保关键分类 logger 已创建（从而文件 handler 存在）
    for category in LOG_FILES:
        get_logger(f"haku.{category}.setup")

    _cleanup_old_logs()


def _cleanup_old_logs() -> None:
    """删除超过保留天数的日志文件。"""
    if not LOG_DIR.exists():
        return
    cutoff = datetime.now(timezone.utc).timestamp() - LOG_RETENTION_DAYS * 86400
    for f in LOG_DIR.iterdir():
        if f.is_file() and f.suffix in (".log", ".json", ".ndjson"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass


def structured(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """记录结构化日志事件，字段序列化为 JSON。"""
    record = {"event": event}
    if fields:
        record["fields"] = fields
    logger.log(level, json.dumps(record, ensure_ascii=False, default=str))


class LogTailer:
    """按时间戳读取后端日志文件，支持分页和级别过滤。"""

    def __init__(self, log_dir: Path = LOG_DIR):
        self.log_dir = log_dir

    def list_files(self) -> List[Dict[str, Any]]:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for f in sorted(self.log_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.is_file() and f.suffix in (".log", ".json", ".ndjson"):
                try:
                    st = f.stat()
                    files.append({
                        "name": f.name,
                        "path": str(f.resolve()),
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    })
                except OSError:
                    pass
        return files

    def tail(
        self,
        name: str,
        lines: int = 200,
        level: Optional[str] = None,
        after_ts: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        path = self.log_dir / name
        if not path.exists():
            return []

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw_lines = f.readlines()
        except OSError:
            return []

        results: List[Dict[str, Any]] = []
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            parsed = self._parse_line(line)
            if not parsed:
                parsed = {"raw": line, "ts": None, "level": "INFO", "event": "raw"}

            if level and parsed.get("level") != level.upper():
                continue
            if after_ts:
                ts = self._ts_to_float(parsed.get("ts"))
                if ts is None or ts <= after_ts:
                    continue
            results.append(parsed)

        return results[-lines:]

    def _parse_line(self, line: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                return {
                    "ts": data.get("ts"),
                    "level": data.get("level", "INFO"),
                    "logger": data.get("logger", "unknown"),
                    "msg": data.get("msg", data),
                    "event": data.get("msg", {}).get("event") if isinstance(data.get("msg"), dict) else None,
                    "fields": data.get("msg", {}).get("fields") if isinstance(data.get("msg"), dict) else None,
                }
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def _ts_to_float(self, ts: Any) -> Optional[float]:
        if ts is None:
            return None
        try:
            if isinstance(ts, (int, float)):
                return float(ts)
            # ISO format
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return None


log_tailer = LogTailer()
