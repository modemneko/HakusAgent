"""ask_user tool — allows the agent to ask the user a multiple-choice question.

The actual question/answer flow is handled by AgentCore (see hakus/agent.py);
this module only provides the tool schema so the model knows it can call
``ask_user`` when it needs clarification.
"""
from __future__ import annotations

from typing import Any, Dict

from ..base import Tool


class AskUser(Tool):
    name = "ask_user"
    description = (
        "Ask the user a clarifying question with multiple-choice options "
        "during task execution. Use this when the user's request is ambiguous, "
        "requires a preference, or needs confirmation before proceeding. "
        "The execution will pause until the user selects an option."
    )
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the user.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of options the user can choose from. "
                    "Provide 2-5 concise, mutually exclusive options."
                ),
            },
            "allow_free_text": {
                "type": "boolean",
                "description": (
                    "If true, the user can type a free-text answer instead of "
                    "choosing one of the predefined options."
                ),
            },
        },
        "required": ["question", "options"],
    }
    is_concurrency_safe = False
    is_dangerous = False
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "interactive"
    tags: list = []

    async def execute(self, **kwargs) -> str:
        # The real implementation lives in AgentCore._execute_tool_call,
        # which intercepts ask_user and emits a QuestionAsked event.
        # This stub should never be reached.
        return "Error: ask_user must be handled by AgentCore."
