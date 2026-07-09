"""Session persistence for --continue resume."""
import json
import os
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

HAKUS_HOME = os.path.join(os.path.expanduser("~"), ".hakus")
SESSION_FILE = os.path.join(HAKUS_HOME, "last_session.json")

__all__ = [
    "save_last_session",
    "load_last_session",
    "restore_latest_checkpoint",
]


def save_last_session(session_id: str, working_dir: str) -> None:
    os.makedirs(HAKUS_HOME, exist_ok=True)
    data = {"session_id": session_id, "working_dir": working_dir}
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.debug(f"Saved last session: {session_id}")


def load_last_session() -> Optional[Dict[str, Any]]:
    if not os.path.isfile(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("session_id"):
            return data
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning(f"Failed to load last session: {e}")
    return None


def restore_latest_checkpoint(agent) -> bool:
    latest = agent._checkpoint.get_latest()
    if not latest:
        return False
    restored = agent.rollback(latest)
    if restored:
        logger.info(f"Restored session {agent._session_id} from checkpoint {latest}")
    return restored
