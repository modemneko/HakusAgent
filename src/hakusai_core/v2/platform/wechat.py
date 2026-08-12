"""
微信 ClawBot 平台适配器

使用 wechat-clawbot-sdk 接入微信，支持：
- 二维码扫码登录
- 长轮询接收消息
- 文本/图片/文件发送
- context_token 持久化与自动复用
- typing 状态控制
"""

import asyncio
import base64
import io
import logging
import time
from typing import Optional, Dict, Any, AsyncIterator
from dataclasses import dataclass, field

from .base import BasePlatform, PlatformConfig, PlatformType, PlatformMessage, SendMessage, PlatformError

logger = logging.getLogger(__name__)

# Lazy import — SDK may not be installed in all environments
_sdk = None

def _get_sdk():
    global _sdk
    if _sdk is None:
        try:
            from wechat_clawbot_sdk import AsyncWeChatBotClient, PollEventType
            from wechat_clawbot_sdk import AccountSession, QRCodeSession
            _sdk = {
                'AsyncWeChatBotClient': AsyncWeChatBotClient,
                'PollEventType': PollEventType,
                'AccountSession': AccountSession,
                'QRCodeSession': QRCodeSession,
            }
        except ImportError:
            raise PlatformError("wechat-clawbot-sdk not installed. Run: pip install wechat-clawbot-sdk")
    return _sdk


@dataclass
class WeChatConfig:
    """微信 ClawBot 配置"""
    enabled: bool = False
    auto_reply: bool = True           # 收到消息后自动通过 AgentCore 回复
    typing_status: bool = True         # 发送 typing 状态
    max_reply_length: int = 2000       # 微信单条消息最大长度
    state_dir: Optional[str] = None    # SDK 状态持久化目录，None 使用默认


class WeChatPlatform(BasePlatform):
    """
    微信 ClawBot 平台适配器
    
    扫码登录 → 长轮询收消息 → 转发 AgentCore → 回复微信
    """
    
    def __init__(self, config: PlatformConfig, wechat_config: WeChatConfig = None):
        super().__init__(config)
        self.wechat_config = wechat_config or WeChatConfig()
        self._client = None
        self._account_id: Optional[str] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._qrcode_base64: Optional[str] = None  # 当前二维码（base64 编码）
        self._login_status: str = "disconnected"    # disconnected / qrcode / waiting / connected
        self._last_alive_check: float = 0.0         # 上次 session 存活验证时间戳
    
    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.WECHAT
    
    @property
    def platform_name(self) -> str:
        return "微信 ClawBot"
    
    @property
    def login_status(self) -> str:
        return self._login_status

    @property
    def qrcode_base64(self) -> Optional[str]:
        return self._qrcode_base64

    async def check_session_alive(self, force: bool = False) -> bool:
        """检查 session 是否存活。默认每 60 秒最多验证一次，force=True 跳过限频。"""
        if not self._client or not self._account_id:
            return False
        now = time.time()
        if not force and (now - self._last_alive_check) < 60:
            return self._connected
        self._last_alive_check = now
        try:
            alive = await self._client.is_account_session_alive(self._account_id)
            if not alive:
                self._login_status = "disconnected"
                self._connected = False
                logger.info("WeChat: Session expired, status reset to disconnected")
            return alive
        except Exception:
            # 探测失败不改变状态
            return self._connected
    
    async def connect(self):
        """连接微信 — 自动复用已有会话或触发扫码登录"""
        sdk = _get_sdk()
        AsyncWeChatBotClient = sdk['AsyncWeChatBotClient']
        
        # 创建客户端
        kwargs = {}
        if self.wechat_config.state_dir:
            kwargs['state_dir'] = self.wechat_config.state_dir
        self._client = AsyncWeChatBotClient.create(
            logger=logger,
            debug=False,
            **kwargs,
        )
        
        # 尝试复用已持久化的账号
        # SDK 的 FileStateStore 没有 list_accounts()，直接扫描 accounts 目录
        try:
            state_store = getattr(self._client, '_state_store', None)
            if state_store and hasattr(state_store, '_root_dir'):
                accounts_dir = state_store._root_dir / "accounts"
                if accounts_dir.is_dir():
                    for f in accounts_dir.iterdir():
                        if f.suffix == '.json' and 'sync' not in f.name and 'context-tokens' not in f.name:
                            account_id = f.stem
                            try:
                                alive = await self._client.is_account_session_alive(account_id)
                                if alive:
                                    self._account_id = account_id
                                    self._connected = True
                                    self._login_status = "connected"
                                    logger.info(f"WeChat: Reused existing session for account {account_id}")
                                    # 启动消息轮询
                                    self._poll_task = asyncio.create_task(self._poll_loop())
                                    return
                                else:
                                    logger.info(f"WeChat: Saved session for {account_id} expired, need re-login")
                            except Exception as e:
                                logger.debug(f"WeChat: Session probe failed for {account_id}: {e}")
        except Exception as e:
            logger.debug(f"WeChat: No saved session to reuse: {e}")
        
        # 没有可用会话，触发扫码登录
        self._login_status = "qrcode"
    
    async def start_qrcode_login(self) -> str:
        """触发扫码登录，返回二维码的 base64 编码图片"""
        if not self._client:
            sdk = _get_sdk()
            AsyncWeChatBotClient = sdk['AsyncWeChatBotClient']
            kwargs = {}
            if self.wechat_config.state_dir:
                kwargs['state_dir'] = self.wechat_config.state_dir
            self._client = AsyncWeChatBotClient.create(logger=logger, debug=False, **kwargs)
        
        login_session = await self._client.start_login()
        raw = login_session.qrcode_image_content

        # SDK 返回的 qrcode_image_content 通常是二维码图片内容（base64/bytes），
        # 也可能在某些情况下是二维码 URL。统一转成 PNG base64 图片返回给前端。
        if isinstance(raw, bytes):
            self._qrcode_base64 = base64.b64encode(raw).decode('utf-8')
        elif isinstance(raw, str) and raw.strip().startswith('http'):
            # URL 形式：用 qrcode 库把 URL 转成二维码图片
            import qrcode as _qrcode_module
            img = _qrcode_module.make(raw)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            self._qrcode_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        elif isinstance(raw, str):
            # 已经是 base64 字符串
            self._qrcode_base64 = raw
        else:
            self._qrcode_base64 = base64.b64encode(str(raw).encode('utf-8')).decode('utf-8')
        self._login_status = "waiting"

        # 后台等待扫码完成
        asyncio.create_task(self._wait_for_login(login_session))
        
        return self._qrcode_base64
    
    async def _wait_for_login(self, qrcode_session):
        """等待扫码完成"""
        try:
            sdk = _get_sdk()
            session = await self._client.wait_for_login(qrcode_session.qrcode)
            self._account_id = session.account_id
            self._connected = True
            self._login_status = "connected"
            self._qrcode_base64 = None
            logger.info(f"WeChat: Login successful, account_id={self._account_id}")
            # 启动消息轮询
            self._poll_task = asyncio.create_task(self._poll_loop())
        except Exception as e:
            import traceback
            logger.error(f"WeChat: Login failed: {e}\n{traceback.format_exc()}")
            self._login_status = "disconnected"
            self._qrcode_base64 = None
    
    async def _poll_loop(self):
        """后台轮询微信消息"""
        if not self._client or not self._account_id:
            return
        
        sdk = _get_sdk()
        PollEventType = sdk['PollEventType']
        
        logger.info(f"WeChat: Starting message poll for account {self._account_id}")
        try:
            async for event in self._client.poll_events(self._account_id):
                if event.event_type is not PollEventType.MESSAGE or event.message is None:
                    continue
                
                # 构造 PlatformMessage 并分发给消息处理器
                msg = PlatformMessage(
                    id=str(event.message.user_id),  # user_id 作为消息标识
                    content=event.message.text or "",
                    author_id=str(event.message.user_id),
                    author_name=str(event.message.user_id),  # SDK 不提供昵称
                    metadata={
                        "platform": "wechat",
                        "account_id": self._account_id,
                        "user_id": event.message.user_id,
                        "raw_message": event.message,
                    },
                )
                await self._handle_message(msg)
        except Exception as e:
            logger.error(f"WeChat: Poll loop error: {e}")
            self._connected = False
            self._login_status = "disconnected"
    
    async def disconnect(self):
        """断开微信连接"""
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        
        if self._client:
            try:
                await self._client.close()
            except Exception as e:
                logger.error(f"WeChat: Close error: {e}")
        
        self._connected = False
        self._login_status = "disconnected"
        self._account_id = None
    
    async def send_message(self, message: SendMessage) -> bool:
        """发送文本消息到微信"""
        if not self._client or not self._account_id:
            return False
        
        user_id = message.metadata.get("user_id") or message.reply_to
        if not user_id:
            logger.error("WeChat: Cannot send message without user_id")
            return False
        
        try:
            # 微信单条消息长度限制，超长则分段
            text = message.content
            if len(text) <= self.wechat_config.max_reply_length:
                await self._client.send_text(
                    account_id=self._account_id,
                    user_id=user_id,
                    text=text,
                )
            else:
                # 分段发送
                for i in range(0, len(text), self.wechat_config.max_reply_length):
                    chunk = text[i:i + self.wechat_config.max_reply_length]
                    await self._client.send_text(
                        account_id=self._account_id,
                        user_id=user_id,
                        text=chunk,
                    )
                    if i + self.wechat_config.max_reply_length < len(text):
                        await asyncio.sleep(0.5)  # 避免发送过快
            return True
        except Exception as e:
            logger.error(f"WeChat: Send message error: {e}")
            return False
    
    async def send_image(self, user_id: str, image_path: str) -> bool:
        """发送图片到微信"""
        if not self._client or not self._account_id:
            return False
        try:
            await self._client.send_image(
                account_id=self._account_id,
                user_id=user_id,
                image_path=image_path,
            )
            return True
        except Exception as e:
            logger.error(f"WeChat: Send image error: {e}")
            return False
    
    async def send_typing(self, user_id: str, typing: bool = True):
        """发送 typing 状态"""
        if not self._client or not self._account_id:
            return
        try:
            from wechat_clawbot_sdk.api import TypingStatus
            status = TypingStatus.TYPING if typing else TypingStatus.CANCEL
            await self._client.send_typing(
                account_id=self._account_id,
                user_id=user_id,
                status=int(status),
            )
        except Exception as e:
            logger.debug(f"WeChat: Typing status error: {e}")
    
    async def receive_messages(self) -> AsyncIterator[PlatformMessage]:
        """接收消息（由 _poll_loop 处理，此处为接口兼容）"""
        # 消息通过 _poll_loop -> _handle_message 分发
        # 此处不直接使用
        return
        yield  # make it an async generator
