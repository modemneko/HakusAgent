"""
恢复管理器 - 借鉴 OpenCode 的中断恢复机制
提供会话持久化、状态恢复、工具清理等功能
"""

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Optional, Any, Dict, List
from dataclasses import dataclass, field
from datetime import datetime
import logging
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class ToolState:
    """工具状态"""
    tool_call_id: str
    tool_name: str
    status: str  # "pending", "running", "completed", "failed", "interrupted"
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Any = None
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    interrupted: bool = False


@dataclass
class SessionSnapshot:
    """会话快照"""
    session_id: str
    iteration: int
    messages: List[Dict[str, Any]]
    tool_states: Dict[str, ToolState]
    context_tokens: int
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class RecoveryManager:
    """恢复管理器"""
    
    def __init__(self, db_path: str = "~/.hakus/recovery.db"):
        self.db_path = Path(db_path).expanduser()
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # 会话快照表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                messages TEXT NOT NULL,
                tool_states TEXT NOT NULL,
                context_tokens INTEGER,
                timestamp REAL NOT NULL,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 工具状态表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tool_states (
                session_id TEXT NOT NULL,
                tool_call_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL,
                input_data TEXT,
                output_data TEXT,
                error TEXT,
                start_time REAL,
                end_time REAL,
                interrupted BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (session_id, tool_call_id)
            )
        """)
        
        # 检查点表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                session_id TEXT NOT NULL,
                checkpoint_id TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                snapshot_id TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, checkpoint_id)
            )
        """)
        
        conn.commit()
        conn.close()
    
    def save_snapshot(self, snapshot: SessionSnapshot) -> str:
        """保存会话快照"""
        snapshot_id = hashlib.md5(
            f"{snapshot.session_id}_{snapshot.timestamp}".encode()
        ).hexdigest()
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO snapshots (id, session_id, iteration, messages, tool_states, 
                                   context_tokens, timestamp, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                snapshot.session_id,
                snapshot.iteration,
                json.dumps(snapshot.messages, ensure_ascii=False),
                json.dumps(
                    {k: self._tool_state_to_dict(v) for k, v in snapshot.tool_states.items()},
                    ensure_ascii=False,
                ),
                snapshot.context_tokens,
                snapshot.timestamp,
                json.dumps(snapshot.metadata, ensure_ascii=False),
            )
        )
        
        conn.commit()
        conn.close()
        
        logger.info(f"Snapshot saved: {snapshot_id}")
        return snapshot_id
    
    def load_snapshot(self, snapshot_id: str) -> Optional[SessionSnapshot]:
        """加载会话快照"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM snapshots WHERE id = ?",
            (snapshot_id,)
        )
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return SessionSnapshot(
            session_id=row[1],
            iteration=row[2],
            messages=json.loads(row[3]),
            tool_states={
                k: self._dict_to_tool_state(v)
                for k, v in json.loads(row[4]).items()
            },
            context_tokens=row[5],
            timestamp=row[6],
            metadata=json.loads(row[7]) if row[7] else {},
        )
    
    def get_latest_snapshot(self, session_id: str) -> Optional[SessionSnapshot]:
        """获取最新的会话快照"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT id FROM snapshots WHERE session_id = ? ORDER BY timestamp DESC LIMIT 1",
            (session_id,)
        )
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self.load_snapshot(row[0])
        return None
    
    def save_tool_state(self, session_id: str, tool_state: ToolState):
        """保存工具状态"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT OR REPLACE INTO tool_states 
            (session_id, tool_call_id, tool_name, status, input_data, output_data, 
             error, start_time, end_time, interrupted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                tool_state.tool_call_id,
                tool_state.tool_name,
                tool_state.status,
                json.dumps(tool_state.input_data, ensure_ascii=False),
                json.dumps(tool_state.output_data, ensure_ascii=False) if tool_state.output_data else None,
                tool_state.error,
                tool_state.start_time,
                tool_state.end_time,
                tool_state.interrupted,
            )
        )
        
        conn.commit()
        conn.close()
    
    def get_interrupted_tools(self, session_id: str) -> List[ToolState]:
        """获取被中断的工具"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT * FROM tool_states 
            WHERE session_id = ? AND (status = 'running' OR interrupted = TRUE)
            """,
            (session_id,)
        )
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            ToolState(
                tool_call_id=row[1],
                tool_name=row[2],
                status=row[3],
                input_data=json.loads(row[4]) if row[4] else {},
                output_data=json.loads(row[5]) if row[5] else None,
                error=row[6],
                start_time=row[7],
                end_time=row[8],
                interrupted=bool(row[9]),
            )
            for row in rows
        ]
    
    def cleanup_interrupted_tools(self, session_id: str):
        """清理被中断的工具"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # 将运行中的工具标记为中断
        cursor.execute(
            """
            UPDATE tool_states 
            SET status = 'interrupted', interrupted = TRUE, 
                error = 'Tool execution interrupted by user'
            WHERE session_id = ? AND status = 'running'
            """,
            (session_id,)
        )
        
        conn.commit()
        conn.close()
    
    def save_checkpoint(self, session_id: str, checkpoint_id: str, 
                        iteration: int, snapshot_id: str, description: str = ""):
        """保存检查点"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO checkpoints (session_id, checkpoint_id, iteration, snapshot_id, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, checkpoint_id, iteration, snapshot_id, description)
        )
        
        conn.commit()
        conn.close()
    
    def get_checkpoint(self, session_id: str, checkpoint_id: str) -> Optional[Dict]:
        """获取检查点"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT * FROM checkpoints 
            WHERE session_id = ? AND checkpoint_id = ?
            """,
            (session_id, checkpoint_id)
        )
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "session_id": row[0],
                "checkpoint_id": row[1],
                "iteration": row[2],
                "snapshot_id": row[3],
                "description": row[4],
            }
        return None
    
    def _tool_state_to_dict(self, state: ToolState) -> dict:
        """ToolState 转字典"""
        return {
            "tool_call_id": state.tool_call_id,
            "tool_name": state.tool_name,
            "status": state.status,
            "input_data": state.input_data,
            "output_data": state.output_data,
            "error": state.error,
            "start_time": state.start_time,
            "end_time": state.end_time,
            "interrupted": state.interrupted,
        }
    
    def _dict_to_tool_state(self, data: dict) -> ToolState:
        """字典转 ToolState"""
        return ToolState(
            tool_call_id=data["tool_call_id"],
            tool_name=data["tool_name"],
            status=data["status"],
            input_data=data.get("input_data", {}),
            output_data=data.get("output_data"),
            error=data.get("error"),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            interrupted=data.get("interrupted", False),
        )
    
    def cleanup_old_snapshots(self, keep_days: int = 7):
        """清理旧的快照"""
        cutoff_time = datetime.now().timestamp() - (keep_days * 24 * 3600)
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute(
            "DELETE FROM snapshots WHERE timestamp < ?",
            (cutoff_time,)
        )
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old snapshots")
    
    def create_autosave(self, session_id: str, iteration: int, 
                        messages: List[Dict], tool_states: Dict[str, ToolState],
                        context_tokens: int) -> str:
        """创建自动保存快照"""
        snapshot = SessionSnapshot(
            session_id=session_id,
            iteration=iteration,
            messages=messages,
            tool_states=tool_states,
            context_tokens=context_tokens,
            timestamp=datetime.now().timestamp(),
            metadata={"type": "autosave"},
        )
        return self.save_snapshot(snapshot)


# 全局实例
recovery_manager = RecoveryManager()