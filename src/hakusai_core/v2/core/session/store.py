"""
会话存储 - 借鉴 OpenCode 的 SQLite 持久化设计
"""

import sqlite3
import json
import uuid
from datetime import datetime
from typing import Optional
from ...schema.models import SessionConfig, SessionState, Message, AgentState, AgentMode


class SessionStore:
    """会话存储"""
    
    def __init__(self, db_path: str = "hakusai.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建会话表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                config TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """)
        
        # 创建消息表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TIMESTAMP NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        
        conn.commit()
        conn.close()
    
    def create_session(
        self,
        project_id: str,
        agent_type: str = "build",
        model_provider: str = "openai",
        model_name: str = "gpt-4",
    ) -> SessionState:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        
        # 创建 Agent 配置
        from ...schema.models import AgentConfig
        agent_config = AgentConfig(
            name=agent_type,
            mode=AgentMode.BUILD if agent_type == "build" else AgentMode.PLAN,
        )
        
        # 创建会话配置
        config = SessionConfig(
            project_id=project_id,
            agent_config=agent_config,
            model_provider=model_provider,
            model_name=model_name,
        )
        
        # 创建 Agent 状态
        agent_state = AgentState(
            session_id=session_id,
            mode=agent_config.mode,
        )
        
        # 创建会话状态
        session = SessionState(
            id=session_id,
            config=config,
            agent_state=agent_state,
        )
        
        # 保存到数据库
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO sessions (id, project_id, config, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                project_id,
                config.model_dump_json(),
                session.agent_state.model_dump_json(),
                datetime.now().isoformat(),
                datetime.now().isoformat(),
            )
        )
        
        conn.commit()
        conn.close()
        
        return session
    
    def get_session(self, session_id: str) -> Optional[SessionState]:
        """获取会话"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT id, project_id, config, state, created_at, updated_at FROM sessions WHERE id = ?",
            (session_id,)
        )
        
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        
        # 解析配置
        config = SessionConfig.model_validate_json(row[2])
        agent_state = AgentState.model_validate_json(row[3])
        
        # 获取消息
        cursor.execute(
            "SELECT id, role, content, metadata, created_at FROM messages WHERE session_id = ? ORDER BY created_at",
            (session_id,)
        )
        
        messages = []
        for msg_row in cursor.fetchall():
            metadata = json.loads(msg_row[3]) if msg_row[3] else {}
            messages.append(Message(
                id=msg_row[0],
                role=msg_row[1],
                content=msg_row[2],
                metadata=metadata,
                created_at=datetime.fromisoformat(msg_row[4]),
            ))
        
        conn.close()
        
        return SessionState(
            id=row[0],
            config=config,
            messages=messages,
            agent_state=agent_state,
        )
    
    def save_message(self, session_id: str, message: Message):
        """保存消息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO messages (id, session_id, role, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                session_id,
                message.role,
                message.content,
                json.dumps(message.metadata),
                message.timestamp.isoformat(),
            )
        )
        
        # 更新会话的 updated_at
        cursor.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id)
        )
        
        conn.commit()
        conn.close()
    
    def list_sessions(self, project_id: Optional[str] = None) -> list[SessionState]:
        """列出会话"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if project_id:
            cursor.execute(
                "SELECT id, project_id, config, state, created_at, updated_at FROM sessions WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,)
            )
        else:
            cursor.execute(
                "SELECT id, project_id, config, state, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
            )
        
        sessions = []
        for row in cursor.fetchall():
            config = SessionConfig.model_validate_json(row[2])
            agent_state = AgentState.model_validate_json(row[3])
            sessions.append(SessionState(
                id=row[0],
                config=config,
                agent_state=agent_state,
            ))
        
        conn.close()
        return sessions
    
    def delete_session(self, session_id: str):
        """删除会话"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        
        conn.commit()
        conn.close()