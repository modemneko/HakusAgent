"""
HakusAI v2 核心模块 - 借鉴 OpenCode 的架构设计
"""

# core removed — real implementation lives in hakus/
# voice removed — real implementation lives in hakusai_core/voice/
try:
    from .schema import *
except ImportError:
    pass
try:
    from .avatar import *
except ImportError:
    pass
try:
    from .platform import *
except ImportError:
    pass


__version__ = "0.1.0"
__author__ = "HakusAI Team"