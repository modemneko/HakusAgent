"""Shared provider resolution — HakusCLI 与桌面端 sidecar 的单一事实源.

两端（终端 in-process / 桌面 FastAPI bridge）必须解析出同一个
provider，否则会出现"桌面切了默认模型、终端还在用旧的"这类漂移。
优先级（高 → 低）：

1. ``explicit`` — 调用方显式传入（CLI ``--model`` / 桌面 ChatRequest.provider）
2. 环境变量 — ``HAKUS_MODEL``（CLI）或 ``HAKUSAI_SIDECAR_PROVIDER``（桌面 launcher）
3. ``models.default_model`` in config.yaml — 经 ``hakus_config.get_config()``
   实时读取，改默认模型即时生效，无需重启
4. ``DEFAULT_MODEL`` in ``utils.config.BASE_CONFIG``
5. ``default`` 兜底（CLI 用 "deepseek"，桌面用 "opencode"）
"""
from __future__ import annotations

import os
from typing import Iterable, Optional


def resolve_provider(
    explicit: Optional[str] = None,
    *,
    env_vars: Iterable[str] = ("HAKUS_MODEL", "HAKUSAI_SIDECAR_PROVIDER"),
    default: str = "deepseek",
) -> str:
    if explicit:
        return explicit.strip().lower()
    for var in env_vars:
        val = os.environ.get(var)
        if val:
            return val.strip().lower()
    try:
        # Prefer the live config (reloaded by hakus_config.reload_config()
        # whenever the default model is changed). This avoids the historic
        # bug where BASE_CONFIG was frozen at process start and a provider
        # switch didn't take effect until restart.
        from utils.hakus_config import get_config

        live = get_config().models.default_model
        if live:
            return str(live).lower()
    except Exception:
        pass
    try:
        from utils.config import BASE_CONFIG

        return str(BASE_CONFIG.get("DEFAULT_MODEL", default)).lower()
    except Exception:
        return default


__all__ = ["resolve_provider"]
