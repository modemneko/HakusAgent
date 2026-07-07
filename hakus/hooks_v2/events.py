"""Hook event definitions."""
from enum import Enum


class HookEvent(str, Enum):
    """Lifecycle events that hooks can subscribe to."""
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    TURN_COMPLETE = "turn_complete"
    COMPACT_START = "compact_start"
    COMPACT_END = "compact_end"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
