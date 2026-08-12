"""
错误类型定义 - 借鉴 OpenCode 的类型化错误设计
提供清晰的错误层次结构
"""

from typing import Any, Optional
from pydantic import BaseModel


class HakusAIError(Exception):
    """HakusAI 错误基类"""
    
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR", details: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
    
    def to_dict(self) -> dict:
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "code": self.code,
            "details": self.details,
        }


class ToolError(HakusAIError):
    """工具执行错误"""
    
    def __init__(self, tool_name: str, message: str, details: Any = None):
        super().__init__(
            message=f"Tool '{tool_name}' failed: {message}",
            code="TOOL_ERROR",
            details={"tool": tool_name, "details": details},
        )
        self.tool_name = tool_name


class PermissionError(HakusAIError):
    """权限错误"""
    
    def __init__(self, tool_name: str, required_level: str, current_level: str):
        super().__init__(
            message=f"Permission denied for tool '{tool_name}'",
            code="PERMISSION_ERROR",
            details={
                "tool": tool_name,
                "required": required_level,
                "current": current_level,
            },
        )
        self.tool_name = tool_name
        self.required_level = required_level
        self.current_level = current_level


class SessionError(HakusAIError):
    """会话错误"""
    
    def __init__(self, session_id: str, message: str, details: Any = None):
        super().__init__(
            message=f"Session '{session_id}' error: {message}",
            code="SESSION_ERROR",
            details={"session_id": session_id, "details": details},
        )
        self.session_id = session_id


class ModelError(HakusAIError):
    """模型调用错误"""
    
    def __init__(self, provider: str, model: str, message: str, details: Any = None):
        super().__init__(
            message=f"Model '{provider}/{model}' error: {message}",
            code="MODEL_ERROR",
            details={"provider": provider, "model": model, "details": details},
        )
        self.provider = provider
        self.model = model


class ConfigError(HakusAIError):
    """配置错误"""
    
    def __init__(self, key: str, message: str, details: Any = None):
        super().__init__(
            message=f"Config '{key}' error: {message}",
            code="CONFIG_ERROR",
            details={"key": key, "details": details},
        )
        self.key = key


class ValidationError(HakusAIError):
    """验证错误"""
    
    def __init__(self, field: str, message: str, details: Any = None):
        super().__init__(
            message=f"Validation error for '{field}': {message}",
            code="VALIDATION_ERROR",
            details={"field": field, "details": details},
        )
        self.field = field


class NotFoundError(HakusAIError):
    """资源未找到错误"""
    
    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            message=f"{resource_type} '{resource_id}' not found",
            code="NOT_FOUND",
            details={"resource_type": resource_type, "resource_id": resource_id},
        )
        self.resource_type = resource_type
        self.resource_id = resource_id