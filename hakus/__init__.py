# Suppress ALL warnings and noisy prints before any imports (must be first)
import warnings
warnings.filterwarnings("ignore")
import os
import sys
os.environ.setdefault("TORCHAUDIO_USE_FFMPEG", "0")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

# Redirect stdout/stderr to suppress ffmpeg/torchaudio Notice prints
class _Quiet:
    def __init__(self, orig):
        self._orig = orig
    def write(self, s):
        if s and any(kw in s for kw in ('ffmpeg', 'torchaudio', 'Notice:', 'avconv')):
            return len(s)
        return self._orig.write(s)
    def flush(self):
        self._orig.flush()
    def __getattr__(self, name):
        return getattr(self._orig, name)

_orig_out = sys.stdout
_orig_err = sys.stderr
sys.stdout = _Quiet(_orig_out)
sys.stderr = _Quiet(_orig_err)

from .agent import AgentCore, SubAgent
from .tools import Tool, ToolRegistry
from .context import ContextManager
from .permission import PermissionManager, PermissionMode
from .checkpoint import CheckpointManager
from .computer_control import ComputerController
from .workspace import Workspace
from .task_board import TaskBoard, TaskStatus, TaskPriority

# Restore stdout/stderr
sys.stdout = _orig_out
sys.stderr = _orig_err

try:
    from .cli import HakusCLI
except ImportError:
    HakusCLI = None

try:
    from .sub_agents import DevAgent, TesterAgent, PlannerAgent, ResearcherAgent
except ImportError:
    DevAgent = TesterAgent = PlannerAgent = ResearcherAgent = None

try:
    from .orchestrator import Orchestrator, OrchestratorPhase, OrchestratorConfig
except ImportError:
    Orchestrator = OrchestratorPhase = OrchestratorConfig = None

try:
    from .voice_bridge import VoiceBridge
except ImportError:
    VoiceBridge = None

__all__ = [
    "AgentCore",
    "SubAgent",
    "Tool",
    "ToolRegistry",
    "ContextManager",
    "PermissionManager",
    "PermissionMode",
    "CheckpointManager",
    "ComputerController",
    "Workspace",
    "TaskBoard",
    "TaskStatus",
    "TaskPriority",
    "DevAgent",
    "TesterAgent",
    "PlannerAgent",
    "ResearcherAgent",
    "Orchestrator",
    "OrchestratorPhase",
    "OrchestratorConfig",
    "VoiceBridge",
]
