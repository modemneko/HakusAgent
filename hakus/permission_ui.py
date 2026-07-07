"""Synchronous permission prompts compatible with prompt_toolkit TUI."""
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

try:
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.formatted_text import HTML
    _HAS_PROMPT = True
except ImportError:
    pt_prompt = None
    HTML = None
    _HAS_PROMPT = False


def sync_confirm_yes_no(
    title: str,
    action: str,
    detail: str,
    *,
    default_no: bool = True,
) -> bool:
    """Ask y/n without breaking an active prompt_toolkit session."""
    prompt_text = f"{title}: {action}"
    if detail:
        short = detail if len(detail) <= 120 else detail[:117] + "..."
        prompt_text = f"{prompt_text} — {short}"

    try:
        if _HAS_PROMPT and pt_prompt is not None:
            answer = pt_prompt(
                HTML(f"<ansiyellow>{prompt_text}</ansiyellow> [y/N] "),
            ).strip().lower()
            return answer in ("y", "yes", "ok")
        answer = input(f"{prompt_text} [y/N] ").strip().lower()
        return answer in ("y", "yes", "ok")
    except (EOFError, KeyboardInterrupt):
        return False
    except Exception as e:
        logger.warning(f"Permission prompt failed: {e}")
        return False
