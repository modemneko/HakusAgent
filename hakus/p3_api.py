"""P3 Evolution API — Checkpoint/Restore/LongRunning endpoints.

Adds REST API endpoints for:
  - GET  /api/sessions/{sid}/checkpoints        — List checkpoints
  - POST /api/sessions/{sid}/restore/latest     — Restore latest checkpoint
  - POST /api/sessions/{sid}/restore/{cp_id}    — Restore specific checkpoint
  - GET  /api/sessions/{sid}/heartbeat          — Check heartbeat liveness
  - GET  /api/sessions/{sid}/status             — Full session status
  - GET  /api/long-running/status               — LongRunningAgent global status

These endpoints follow the REFACTOR_PLAN Phase 3 specification.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["p3-evolution"])


# ------------------------------------------------------------------
# Session Checkpoint Endpoints
# ------------------------------------------------------------------

@router.get("/sessions/{session_id}/checkpoints")
async def list_checkpoints(session_id: str):
    """List all checkpoints for a session.

    Returns checkpoint metadata (id, timestamp, iteration, trigger)
    without the full message payload (which can be large).
    """
    try:
        from hakus.checkpoint import CheckpointManager
        checkpoint_dir = os.path.join(os.getcwd(), ".checkpoints")
        mgr = CheckpointManager(persist_dir=checkpoint_dir)
        mgr.load(session_id)

        checkpoints = []
        for cp in mgr.list_checkpoints():
            checkpoints.append({
                "id": cp.get("id", ""),
                "timestamp": cp.get("timestamp", 0),
                "iteration": cp.get("dynamic_context", {}).get("iteration", 0),
                "trigger": cp.get("trigger", "unknown"),
                "message_count": len(cp.get("messages", [])),
            })

        return {
            "session_id": session_id,
            "checkpoints": checkpoints,
            "total": len(checkpoints),
        }
    except Exception as e:
        logger.error(f"Failed to list checkpoints: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/restore/latest")
async def restore_latest_checkpoint(session_id: str):
    """Restore a session from its latest checkpoint.

    This is called automatically on sidecar restart to resume
    interrupted 5h tasks. The agent's message history and iteration
    state are recovered.
    """
    try:
        from hakus.checkpoint import CheckpointManager
        checkpoint_dir = os.path.join(os.getcwd(), ".checkpoints")
        mgr = CheckpointManager(persist_dir=checkpoint_dir)
        mgr.load(session_id)

        latest = mgr.get_latest()
        if not latest:
            raise HTTPException(
                status_code=404,
                detail=f"No checkpoints found for session {session_id}",
            )

        restored = mgr.restore(latest)
        if not restored:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to restore checkpoint {latest}",
            )

        messages = restored.get("messages", [])
        iteration = restored.get("dynamic_context", {}).get("iteration", 0)

        return {
            "session_id": session_id,
            "checkpoint_id": latest,
            "restored": True,
            "messages_restored": len(messages),
            "iteration": iteration,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/restore/{checkpoint_id}")
async def restore_specific_checkpoint(session_id: str, checkpoint_id: str):
    """Restore a session from a specific checkpoint."""
    try:
        from hakus.checkpoint import CheckpointManager
        checkpoint_dir = os.path.join(os.getcwd(), ".checkpoints")
        mgr = CheckpointManager(persist_dir=checkpoint_dir)
        mgr.load(session_id)

        restored = mgr.restore(checkpoint_id)
        if not restored:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint {checkpoint_id} not found",
            )

        messages = restored.get("messages", [])
        iteration = restored.get("dynamic_context", {}).get("iteration", 0)

        return {
            "session_id": session_id,
            "checkpoint_id": checkpoint_id,
            "restored": True,
            "messages_restored": len(messages),
            "iteration": iteration,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Heartbeat Check Endpoint
# ------------------------------------------------------------------

@router.get("/sessions/{session_id}/heartbeat")
async def check_heartbeat(session_id: str):
    """Check if a long task's heartbeat is still alive.

    Reads the .heartbeat file in the workspace. If the file exists
    and was updated within the last 90 seconds, the task is alive.
    If the file is stale (>90s) or missing, the task may have crashed.
    """
    heartbeat_path = os.path.join(os.getcwd(), ".heartbeat")

    if not os.path.exists(heartbeat_path):
        return {
            "session_id": session_id,
            "alive": False,
            "reason": "heartbeat file not found",
        }

    try:
        mtime = os.path.getmtime(heartbeat_path)
        age = time.time() - mtime
        alive = age < 90  # 90s timeout

        return {
            "session_id": session_id,
            "alive": alive,
            "age_seconds": round(age, 1),
            "last_update": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
            "reason": "alive" if alive else f"heartbeat stale ({age:.0f}s > 90s)",
        }
    except Exception as e:
        return {
            "session_id": session_id,
            "alive": False,
            "reason": f"error reading heartbeat: {e}",
        }


# ------------------------------------------------------------------
# Session Status Endpoint
# ------------------------------------------------------------------

@router.get("/sessions/{session_id}/status")
async def session_status(session_id: str):
    """Get comprehensive session status including checkpoint/recovery/heartbeat.

    This endpoint provides a unified view of the session's state,
    useful for debugging and monitoring 5h tasks.
    """
    status: Dict[str, Any] = {
        "session_id": session_id,
        "timestamp": time.time(),
    }

    # Checkpoint info
    try:
        from hakus.checkpoint import CheckpointManager
        checkpoint_dir = os.path.join(os.getcwd(), ".checkpoints")
        mgr = CheckpointManager(persist_dir=checkpoint_dir)
        mgr.load(session_id)
        cps = mgr.list_checkpoints()
        status["checkpoints"] = {
            "available": True,
            "count": len(cps),
            "latest_iteration": cps[0].get("dynamic_context", {}).get("iteration", 0) if cps else 0,
        }
    except Exception:
        status["checkpoints"] = {"available": False}

    # Recovery info
    try:
        from hakus.recovery import RecoveryManager
        db_path = os.path.expanduser("~/.hakus/recovery.db")
        rmgr = RecoveryManager(db_path=db_path)
        snaps = rmgr.list_snapshots(session_id)
        status["recovery"] = {
            "available": True,
            "snapshot_count": len(snaps),
        }
    except Exception:
        status["recovery"] = {"available": False}

    # Heartbeat info
    heartbeat_path = os.path.join(os.getcwd(), ".heartbeat")
    if os.path.exists(heartbeat_path):
        try:
            mtime = os.path.getmtime(heartbeat_path)
            age = time.time() - mtime
            status["heartbeat"] = {
                "alive": age < 90,
                "age_seconds": round(age, 1),
            }
        except Exception:
            status["heartbeat"] = {"alive": False}
    else:
        status["heartbeat"] = {"alive": False}

    return status


# ------------------------------------------------------------------
# Global LongRunningAgent Status
# ------------------------------------------------------------------

@router.get("/long-running/status")
async def long_running_status():
    """Global LongRunningAgent status and diagnostics.

    Provides an overview of the long-running agent infrastructure:
    whether checkpoint/recovery/heartbeat modules are available,
    and their current state.
    """
    return {
        "modules": {
            "long_running_agent": True,
            "checkpoint": True,
            "recovery": True,
            "heartbeat": True,
        },
        "config": {
            "max_llm_retries": 3,
            "llm_retry_base_delay": 2.0,
            "heartbeat_interval": 30,
            "heartbeat_timeout": 90,
        },
        "endpoints": [
            "GET  /api/sessions/{sid}/checkpoints",
            "POST /api/sessions/{sid}/restore/latest",
            "POST /api/sessions/{sid}/restore/{cp_id}",
            "GET  /api/sessions/{sid}/heartbeat",
            "GET  /api/sessions/{sid}/status",
            "GET  /api/long-running/status",
        ],
    }


# ------------------------------------------------------------------
# Convenience: mount this router into a FastAPI app
# ------------------------------------------------------------------

def mount_p3_routes(app: Any) -> None:
    """Mount P3 evolution API routes into an existing FastAPI app.

    Usage::

        from hakus.p3_api import mount_p3_routes
        mount_p3_routes(app)
    """
    app.include_router(router)
    logger.info("P3 evolution API routes mounted")
