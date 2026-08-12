"""Pytest configuration: ensure hakus imports work without loading NoneBot plugin."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

collect_ignore = [str(ROOT / "__init__.py")]
