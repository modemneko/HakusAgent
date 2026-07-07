"""
会话管理 - 负责会话的创建、存储和恢复
"""

from .store import SessionStore


__all__ = [
    "SessionStore",
]