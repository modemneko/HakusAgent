"""Permission mode definitions."""
from enum import Enum


class PermissionMode(str, Enum):
    """Supported permission modes.

    Mapping from the old PermissionMode (hakus/permission.py):
      - AUTO  → DEFAULT  (safe ops auto-approve, mutating ops need confirmation)
      - ASK   → DEFAULT  (same behaviour — confirmation required)
      - BYPASS → FULL_AUTO (allow everything)

    PLAN is a new mode that provides read-only access, blocking all
    mutating tools.
    """

    DEFAULT = "default"       # Safe ops auto-approve, mutating ops need confirmation
    PLAN = "plan"             # Read-only, block all mutating tools
    FULL_AUTO = "full_auto"   # Allow everything
