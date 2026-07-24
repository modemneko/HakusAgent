"""
HakusAI 安全鉴权中间件

提供 API Key 鉴权和安全相关的中间件功能：

1. AuthMiddleware - HTTP 请求鉴权中间件
   - 检查 X-API-Key 头（可配置）
   - 跳过公开端点（/health, /docs, /openapi.json）
   - 支持速率限制

2. WebSocketAuth - WebSocket 连接鉴权
   - 通过 query parameter 鉴权
   - 支持首次消息鉴权

安全设计原则：
- 默认不阻断（向后兼容），配置 api_key 后启用
- 使用自定义头避免浏览器 CORS 预检问题
- 详细的审计日志
- 优雅降级（鉴权失败返回 401，不崩溃）
"""

import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field

from fastapi import Request, Response, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint

logger = logging.getLogger(__name__)


# ==================== 公开端点白名单 ====================

# 不需要鉴权的路径前缀
PUBLIC_PATH_PREFIXES: Set[str] = {
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon",
    "/static",
}

# 不需要鉴权的完整路径
PUBLIC_PATHS: Set[str] = set()


def is_public_path(path: str) -> bool:
    """检查路径是否为公开端点"""
    # 精确匹配
    if path in PUBLIC_PATHS:
        return True
    
    # 前缀匹配
    for prefix in PUBLIC_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    
    return False


# ==================== 速率限制器 ====================

@dataclass
class RateLimiter:
    """
    简单的内存速率限制器
    
    基于 sliding window 算法，按客户端 IP 限制请求频率
    """
    
    enabled: bool = True
    requests_per_minute: int = 60
    _requests: Dict[str, List[float]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    
    async def is_allowed(self, client_ip: str) -> Tuple[bool, str]:
        """
        检查请求是否允许
        
        Returns:
            (allowed, reason) - 是否允许及原因
        """
        if not self.enabled:
            return True, "OK"
        
        now = time.time()
        window_start = now - 60.0  # 1分钟窗口
        
        async with self._lock:
            # 清理过期记录
            if client_ip in self._requests:
                self._requests[client_ip] = [
                    t for t in self._requests[client_ip] if t > window_start
                ]
            else:
                self._requests[client_ip] = []
            
            # 检查是否超限
            request_count = len(self._requests[client_ip])
            if request_count >= self.requests_per_minute:
                retry_after = int(self._requests[client_ip][0] + 60 - now) + 1
                return False, f"Rate limit exceeded. Retry after {retry_after}s"
            
            # 记录请求
            self._requests[client_ip].append(now)
            return True, "OK"
    
    def cleanup_stale_entries(self):
        """清理过期的客户端记录"""
        window_start = time.time() - 60.0
        stale_ips = [
            ip for ip, times in self._requests.items()
            if not times or times[-1] < window_start
        ]
        for ip in stale_ips:
            del self._requests[ip]


# ==================== 审计日志器 ====================

class AuditLogger:
    """操作审计日志"""
    
    def __init__(self, enabled: bool = True, log_path: str = "logs/audit.log"):
        self.enabled = enabled
        self.log_path = log_path
        
        # 确保日志目录存在
        if enabled:
            try:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
            except (OSError, ValueError):
                # 如果路径无效，使用默认路径
                self.log_path = "logs/audit.log"
                os.makedirs("logs", exist_ok=True)
    
    def log(
        self,
        action: str,
        client_ip: str,
        details: Optional[str] = None,
        success: bool = True,
        user_agent: Optional[str] = None
    ):
        """记录审计事件"""
        if not self.enabled:
            return
        
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        status = "OK" if success else "FAIL"
        
        log_line = (
            f"[{timestamp}] [{status}] {action} "
            f"ip={client_ip}"
        )
        if details:
            log_line += f" details={details[:200]}"  # 截断过长内容
        if user_agent:
            log_line += f" ua={user_agent[:100]}"
        
        logger.info(f"[AUDIT] {log_line}")
        
        # 写入审计日志文件
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except (OSError, IOError) as e:
            logger.warning(f"Failed to write audit log: {e}")


# ==================== 主鉴权中间件 ====================

class AuthMiddleware(BaseHTTPMiddleware):
    """
    API Key 鉴权中间件
    
    功能：
    1. 检查 API Key（如果已配置）
    2. 速率限制
    3. 审计日志
    4. 安全头设置
    
    配置来源：config.security.*
    """
    
    def __init__(
        self,
        app,
        api_key: str = "",
        api_key_header: str = "X-API-Key",
        rate_limit_enabled: bool = True,
        rate_limit_rpm: int = 60,
        audit_enabled: bool = True,
        audit_log_path: str = "logs/audit.log",
    ):
        super().__init__(app)
        self.api_key = api_key or ""
        self.api_key_header = api_key_header
        self.audit_logger = AuditLogger(audit_enabled, audit_log_path)
        self.rate_limiter = RateLimiter(rate_limit_enabled, rate_limit_rpm)
        
        # 标记鉴权是否实际启用
        self.auth_enabled = bool(self.api_key)
        
        if self.auth_enabled:
            logger.info(f"[Security] API Key authentication ENABLED (header: {api_key_header})")
        else:
            logger.warning(
                "[Security] API Key authentication DISABLED. "
                "Set security.api_key or HAKUSAI_API_KEY env to enable."
            )
        
        if rate_limit_enabled:
            logger.info(f"[Security] Rate limit enabled: {rate_limit_rpm} req/min")
    
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """处理每个 HTTP 请求"""
        path = request.url.path
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "")
        
        # 跳过公开端点
        if is_public_path(path):
            return await call_next(request)
        
        # 速率检查
        if self.rate_limiter.enabled:
            allowed, reason = await self.rate_limiter.is_allowed(client_ip)
            if not allowed:
                self.audit_logger.log(
                    "RATE_LIMITED",
                    client_ip,
                    f"path={path} reason={reason}",
                    success=False,
                    user_agent=user_agent
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": "rate_limited",
                        "detail": reason,
                        "retry_after": 60
                    }
                )
        
        # API Key 鉴权（仅当配置了 api_key 时）
        if self.auth_enabled:
            provided_key = request.headers.get(self.api_key_header, "")
            
            if not self._verify_key(provided_key):
                self.audit_logger.log(
                    "AUTH_FAILED",
                    client_ip,
                    f"path={path}",
                    success=False,
                    user_agent=user_agent
                )
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={
                        "error": "unauthorized",
                        "detail": "Missing or invalid API key. Provide it via "
                                 f"{self.api_key_header} header."
                    }
                )
                
                # 记录成功鉴权
                self.audit_logger.log(
                    "AUTH_SUCCESS",
                    client_ip,
                    f"path={path}",
                    success=True,
                    user_agent=user_agent
                )
        
        # 处理请求
        response = await call_next(request)
        
        # 添加安全响应头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # 移除服务器版本信息
        response.headers.pop("Server", None)
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP"""
        # 检查代理头
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        
        # 回退到直接连接 IP
        return request.client.host if request.client else "unknown"
    
    def _verify_key(self, provided_key: str) -> bool:
        """验证 API Key"""
        if not self.api_key:
            return True  # 未配置则放行
        
        # 使用常量时间比较防止时序攻击
        import hmac
        import hashlib
        
        return hmac.compare_digest(
            provided_key.encode("utf-8"),
            self.api_key.encode("utf-8")
        )


# ==================== WebSocket 鉴权 ====================

async def authenticate_websocket(
    websocket: WebSocket,
    token: Optional[str],
    expected_token: str,
    query_param: str = "token"
) -> Tuple[bool, str]:
    """
    验证 WebSocket 连接的鉴权 token
    
    Args:
        websocket: WebSocket 连接实例
        token: 提供的 token（从 query param 或首条消息）
        expected_token: 期望的 API key
        query_param: query parameter 名称
    
    Returns:
        (authenticated, error_message)
    """
    if not expected_token:
        # 未配置鉴权，允许连接
        return True, ""
    
    if not token:
        return False, f"Missing authentication token. Use ?{query_param}=<your_api_key>"
    
    import hmac
    if hmac.compare_digest(token.encode("utf-8"), expected_token.encode("utf-8")):
        return True, ""
    
    return False, "Invalid authentication token"


def get_ws_token_from_params(websocket: WebSocket, param_name: str = "token") -> Optional[str]:
    """从 WebSocket 连接参数中提取 token"""
    return websocket.query_params.get(param_name)


# ==================== 辅助函数 ====================

def create_auth_middleware_from_config(config) -> AuthMiddleware:
    """
    从配置对象创建鉴权中间件工厂函数
    
    Args:
        config: HakusAIConfig 实例
    
    Returns:
        配置好的 AuthMiddleware 类（部分应用）
    """
    security = config.security
    
    def middleware_factory(app) -> AuthMiddleware:
        return AuthMiddleware(
            app=app,
            api_key=security.api_key,
            api_key_header=security.api_key_header,
            rate_limit_enabled=security.rate_limit_enabled,
            rate_limit_rpm=security.rate_limit_requests_per_minute,
            audit_enabled=security.audit_log_enabled,
            audit_log_path=security.audit_log_path,
        )
    
    return middleware_factory


# 导入 JSONResponse（延迟导入以避免循环依赖问题）
from fastapi.responses import JSONResponse
