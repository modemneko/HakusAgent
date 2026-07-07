"""
Plan mode 简单 yes/no 自然语言检测 (复用 tui.py 已有逻辑)
"""
from __future__ import annotations

import re

# 单词边界 token (用 \b 避免与中文/emoji 冲突)
YES_WORDS = (
    r"yes|approve|ok|okay|y|"
    r"yeah|ya|sure|do it|"
    r"proceed|go ahead|please|please proceed|"
    r"ye[sp]?|sounds good|looks good"
)
YES_CN = (
    r"同意|好|好的|可以|可以的|批准|"
    r"嗯|对|是的|确认|继续|开始|做吧|"
    r"批准了|可以继续|没问题|可以呀|行|行吧|可以哈|行哈"
)
YES_EMOJI = "👍|✓|✅|👌"
# Use word boundary for words, but allow emojis to match without boundary
# Pattern: start of string -> optional whitespace -> (word with boundary OR emoji)
YES_PATTERNS = re.compile(
    rf"^\s*({YES_WORDS})\b|^\s*({YES_EMOJI})|^\s*({YES_CN})",
    re.IGNORECASE | re.UNICODE,
)

NO_WORDS = (
    r"no|reject|stop|don't|do not|n|"
    r"no thanks|not really|never mind|nah|nope"
)
NO_CN = (
    r"不|不要|拒绝|取消|不要继续|不行|"
    r"暂停|取消批准|否"
)
NO_EMOJI = "❌|✗|🚫|👎"
NO_PATTERNS = re.compile(
    rf"^\s*({NO_WORDS})\b|^\s*({NO_EMOJI})|^\s*({NO_CN})",
    re.IGNORECASE | re.UNICODE,
)


def is_plan_yes(text: str) -> bool:
    return bool(YES_PATTERNS.match(text.strip()))


def is_plan_no(text: str) -> bool:
    return bool(NO_PATTERNS.match(text.strip()))
