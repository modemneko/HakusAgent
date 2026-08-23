"""Project registry — Codex-style "work on a project" feature.

A project is just a named folder on disk. The user picks a folder from
the desktop client (Tauri folder dialog), we register it here, and
subsequent chat turns are run with that folder as the agent's
``working_dir`` — so the agent's read_file / write_file / bash tools
all operate inside that folder without the user having to spell out
the path.

Storage: ~/.hakus/projects.json — a flat JSON file with a single list.
SQLite would be overkill for ~tens of projects, and a JSON file is
trivial to hand-edit / back up / version-control.

Thread safety: a single threading.Lock guards all reads+writes. The
file is small and operations are O(n) — lock contention is a non-issue.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logging_config import get_logger

logger = get_logger("haku.sidecar.projects")


def _projects_file() -> Path:
    """Return the path to ~/.hakus/projects.json (creating ~/.hakus/ if needed)."""
    p = Path(os.path.expanduser("~/.hakus")) / "projects.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        # If we can't create ~/.hakus/, fall back to an in-memory-only mode.
        # The caller will see load() return [] and save() log a warning.
        pass
    return p


_LOCK = threading.Lock()
_CACHE: Optional[List[Dict[str, Any]]] = None


def _load() -> List[Dict[str, Any]]:
    """Load the projects list from disk (cached after first call)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = _projects_file()
    if not path.exists():
        _CACHE = []
        return _CACHE
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else []
        if not isinstance(data, list):
            logger.warning(
                f"projects.json was not a list (got {type(data).__name__}), resetting to []"
            )
            data = []
        _CACHE = data
    except Exception as e:
        logger.warning(f"Failed to load projects.json: {e}; starting with empty list")
        _CACHE = []
    return _CACHE


def _save_unlocked(projects: List[Dict[str, Any]]) -> None:
    """Write projects list to disk. Caller must hold _LOCK."""
    global _CACHE
    _CACHE = projects
    path = _projects_file()
    try:
        path.write_text(
            json.dumps(projects, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Failed to write projects.json: {e}")


# ── Public API ─────────────────────────────────────────────────────────────


def list_projects() -> List[Dict[str, Any]]:
    """Return all registered projects, sorted by last_used_at desc (then created_at)."""
    with _LOCK:
        items = list(_load())
    # Sort: pinned first, then most-recently-used. Stable sort preserves
    # insertion order for ties.
    items.sort(
        key=lambda p: (
            not bool(p.get("pinned", False)),
            -(p.get("last_used_at") or p.get("created_at") or 0),
        )
    )
    return items


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    """Return a single project by id, or None if not found."""
    with _LOCK:
        for p in _load():
            if p.get("id") == project_id:
                return dict(p)
    return None


def create_project(name: str, path: str, *, pinned: bool = False) -> Dict[str, Any]:
    """Register a new project.

    ``path`` should be an absolute filesystem path to an existing directory.
    We do NOT create the directory if it doesn't exist — the Tauri folder
    picker only returns existing directories, and silently creating one
    here would let users register ``/`` or other dangerous paths.

    Returns the newly created project dict.
    Raises ValueError if path doesn't exist or isn't a directory.
    """
    # Expand ~ and env vars (mainly for power users who hand-edit projects.json)
    expanded = os.path.expanduser(os.path.expandvars(path))
    if not os.path.isabs(expanded):
        raise ValueError(f"Project path must be absolute: {path}")
    if not os.path.isdir(expanded):
        raise ValueError(
            f"Project path does not exist or is not a directory: {expanded}"
        )

    # Deduplicate by absolute path — if the same folder is already
    # registered under a different name, just return the existing entry.
    # Users get confused when "HakusAgent" and "HakusAE" point to the
    # same folder and switching between them silently reuses the same agent.
    abs_path = os.path.realpath(expanded)
    with _LOCK:
        projects = _load()
        for p in projects:
            if os.path.realpath(p.get("path", "")) == abs_path:
                # Update last_used_at so it floats to the top of the list
                p["last_used_at"] = int(time.time())
                _save_unlocked(projects)
                return dict(p)

        project = {
            "id": f"proj_{uuid.uuid4().hex[:12]}",
            "name": name.strip() or os.path.basename(abs_path) or "Untitled",
            "path": abs_path,
            "pinned": bool(pinned),
            "created_at": int(time.time()),
            "last_used_at": int(time.time()),
        }
        projects.append(project)
        _save_unlocked(projects)
        return dict(project)


def rename_project(project_id: str, new_name: str) -> Optional[Dict[str, Any]]:
    """Rename a project. Returns the updated project, or None if not found."""
    with _LOCK:
        projects = _load()
        for p in projects:
            if p.get("id") == project_id:
                p["name"] = new_name.strip() or p["name"]
                _save_unlocked(projects)
                return dict(p)
    return None


def set_pinned(project_id: str, pinned: bool) -> Optional[Dict[str, Any]]:
    """Pin or unpin a project. Returns the updated project, or None if not found."""
    with _LOCK:
        projects = _load()
        for p in projects:
            if p.get("id") == project_id:
                p["pinned"] = bool(pinned)
                _save_unlocked(projects)
                return dict(p)
    return None


def touch_project(project_id: str) -> None:
    """Update last_used_at for a project (called when a chat turn uses it)."""
    with _LOCK:
        projects = _load()
        for p in projects:
            if p.get("id") == project_id:
                p["last_used_at"] = int(time.time())
                _save_unlocked(projects)
                return


def delete_project(project_id: str) -> bool:
    """Remove a project from the registry. Returns True if it existed."""
    with _LOCK:
        projects = _load()
        before = len(projects)
        projects = [p for p in projects if p.get("id") != project_id]
        if len(projects) == before:
            return False
        _save_unlocked(projects)
        return True


def resolve_working_dir(project_id: Optional[str]) -> Optional[str]:
    """Resolve a project_id to an absolute filesystem path.

    Returns None if:
      - project_id is None / empty / "none" (user chose "不在项目中工作")
      - project_id doesn't exist in the registry (deleted?)
      - the project's folder no longer exists on disk

    The caller (agent_bridge) treats None as "use the default workspace"
    (the user's home, or $HAKUS_WORKSPACE if set) — NOT the sidecar's
    source tree. An active project is what pins the agent to a folder.
    """
    if not project_id or project_id == "none":
        return None
    p = get_project(project_id)
    if p is None:
        logger.warning(f"Project {project_id!r} not found in registry; using default workspace")
        return None
    path = p.get("path", "")
    if not path or not os.path.isdir(path):
        logger.warning(
            f"Project {project_id!r} path {path!r} does not exist on disk; using default workspace"
        )
        return None
    # Side effect: bump last_used_at so the project floats to the top
    # of the picker next time. This matches Codex behavior — projects
    # you're actively using sort first.
    try:
        touch_project(project_id)
    except Exception:
        pass
    return path
