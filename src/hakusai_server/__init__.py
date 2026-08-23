"""
HakusAI 2.0 服务器模块

Re-exports are lazy (PEP 562): importing ``hakusai_server`` or its
lightweight submodules (e.g. ``provider_ops``, used by ``hakus.mcp.config``)
must NOT pull in FastAPI/uvicorn — the terminal CLI (HakusCLI) imports
``hakus.agent`` which imports ``hakus.mcp.config`` and has to stay
installable with the slim dependency set. The server itself is started via
``python -m hakusai_server.server`` which loads the module directly.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .server import HakusAIServer, server, WebSocketManager

__all__ = [
    "HakusAIServer",
    "server",
    "WebSocketManager",
]


def __getattr__(name: str):
    if name in __all__:
        from . import server as _server
        return getattr(_server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals()) + __all__)
