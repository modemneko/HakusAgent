"""基于文件系统的心跳机制 — Orchestrator 定期写入时间戳文件,TUI 可检测长时任务是否存活.

设计:
- Orchestrator 执行期间每 30 秒写入 `{workspace}/.heartbeat` 文件
- 时间戳格式为 ISO 8601
- TUI 检测到心跳文件超过 90 秒未更新 → 显示警告
- 正常完成时删除心跳文件
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TIMEOUT_SECONDS = 90

__all__ = [
    "HEARTBEAT_INTERVAL_SECONDS",
    "HEARTBEAT_TIMEOUT_SECONDS",
    "WorkspaceHeartbeat",
]


class WorkspaceHeartbeat:
    """基于文件系统的心跳写入器.

    用法:
        heartbeat = WorkspaceHeartbeat(workspace_dir)
        # 启动心跳协程 (非阻塞)
        task = heartbeat.start()
        # ... 长时任务执行 ...
        # 停止心跳并清理文件
        await heartbeat.stop()
    """

    def __init__(self, workspace_dir: str, interval: int = HEARTBEAT_INTERVAL_SECONDS):
        self._workspace_dir = Path(workspace_dir)
        self._interval = interval
        self._heartbeat_path = self._workspace_dir / ".heartbeat"
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def heartbeat_path(self) -> Path:
        return self._heartbeat_path

    def start(self) -> asyncio.Task:
        """启动心跳写入协程 (非阻塞)."""
        if self._running:
            return self._task
        self._running = True
        self._task = asyncio.create_task(self._heartbeat_loop())
        logger.debug(f"Heartbeat started: {self._heartbeat_path}")
        return self._task

    async def stop(self) -> None:
        """停止心跳并删除心跳文件."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Clean up heartbeat file on normal completion
        try:
            if self._heartbeat_path.exists():
                self._heartbeat_path.unlink()
                logger.debug(f"Heartbeat file removed: {self._heartbeat_path}")
        except Exception as e:
            logger.warning(f"Failed to remove heartbeat file: {e}")

    async def _heartbeat_loop(self) -> None:
        """定期写入心跳时间戳."""
        try:
            while self._running:
                self._write_timestamp()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Heartbeat loop error: {e}")

    def _write_timestamp(self) -> None:
        """写入当前时间戳到心跳文件."""
        try:
            self._workspace_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).isoformat()
            self._heartbeat_path.write_text(timestamp, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to write heartbeat: {e}")

    @staticmethod
    def check_alive(workspace_dir: str, timeout: int = HEARTBEAT_TIMEOUT_SECONDS) -> Optional[str]:
        """检查心跳是否存活.

        Returns:
            None if alive, or a warning message if timed out / no heartbeat file.
        """
        heartbeat_path = Path(workspace_dir) / ".heartbeat"
        if not heartbeat_path.exists():
            return None  # No heartbeat file means no long task running

        try:
            timestamp_str = heartbeat_path.read_text(encoding="utf-8").strip()
            last_beat = datetime.fromisoformat(timestamp_str)
            now = datetime.now(timezone.utc)
            elapsed = (now - last_beat).total_seconds()

            if elapsed > timeout:
                return f"心跳超时 ({elapsed:.0f}s > {timeout}s), 长时任务可能已中断"
            return None  # Alive
        except Exception as e:
            return f"心跳文件损坏: {e}"
