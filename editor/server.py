import asyncio
import json
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any

from utils.config import BASE_CONFIG
from utils.logger import get_logger

try:
    from hakus.agent import AgentCore
    from hakus.protocol import (
        TextDelta,
        TurnCompleted,
        TurnFailed,
        Cancelled as CancelledEvent,
    )
except ImportError:
    AgentCore = None
    TextDelta = None
    TurnCompleted = None
    TurnFailed = None
    CancelledEvent = None

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import JSONResponse
    import uvicorn
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

logger = get_logger(__name__)

WORK_DIR = os.getcwd()

_task_store: Dict[str, dict] = {}
_task_lock = threading.Lock()
_agent_instances: Dict[str, Any] = {}
_agent_lock = threading.Lock()
_terminal_sessions: Dict[str, subprocess.Popen] = {}

if _HAS_FASTAPI:
    app = FastAPI(title="HakusAI Code Editor", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _get_agent(session_id: str) -> Optional[AgentCore]:
    if AgentCore is None:
        return None
    if session_id in _agent_instances:
        return _agent_instances[session_id]
    with _agent_lock:
        if session_id not in _agent_instances:
            try:
                agent = AgentCore(
                    session_id=session_id,
                    working_dir=WORK_DIR,
                )
                _agent_instances[session_id] = agent
            except Exception as e:
                logger.error(f"Failed to create agent for {session_id}: {e}")
                return None
        return _agent_instances.get(session_id)


def _safe_path(requested: str) -> str:
    base = Path(WORK_DIR).resolve()
    if os.path.isabs(requested):
        target = Path(requested).resolve()
    else:
        target = (base / requested).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal denied")
    return str(target)


_SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build',
            '.idea', '.vscode', 'chat-app', 'Mate-Engine', 'N.E.K.O',
            'Open-LLM-VTuber', 'tts_engines', 'hakusai_data', 'output',
            'configs', '.trae', 'models/tts/bert_vits2'}

def _build_file_tree(path: str, max_depth: int = 3, depth: int = 0) -> List[dict]:
    if depth >= max_depth or not os.path.isdir(path):
        return []
    entries = []
    try:
        items = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        for item in items:
            name = item.name
            if name.startswith('.') and name not in ('.git', '.github'):
                continue
            if name in _SKIP_DIRS:
                continue
            entry = {
                "name": name,
                "path": os.path.relpath(item.path, WORK_DIR),
                "type": "directory" if item.is_dir() else "file",
            }
            if item.is_dir():
                children = _build_file_tree(item.path, max_depth, depth + 1)
                if children:
                    entry["children"] = children
                else:
                    entry["children"] = []
            entries.append(entry)
    except PermissionError:
        pass
    return entries


@app.get("/api/files")
async def list_files(path: str = "."):
    try:
        real = _safe_path(path)
        if not os.path.isdir(real):
            raise HTTPException(status_code=404, detail="Not a directory")
        tree = _build_file_tree(real)
        return {"path": path, "entries": tree}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_files error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/file")
async def read_file(path: str):
    try:
        real = _safe_path(path)
        if not os.path.isfile(real):
            raise HTTPException(status_code=404, detail="File not found")
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": path, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/file")
async def write_file(body: dict):
    try:
        path = body.get("path", "")
        content = body.get("content", "")
        real = _safe_path(path)
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, "w", encoding="utf-8") as f:
            f.write(content)
        return {"path": path, "status": "saved"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/execute")
async def execute_command(body: dict):
    command = body.get("command", "")
    if not command:
        raise HTTPException(status_code=400, detail="No command provided")
    try:
        if os.name == 'nt':
            result = subprocess.run(
                ['cmd', '/c', command],
                capture_output=True, text=True,
                timeout=30, cwd=WORK_DIR,
            )
        else:
            result = subprocess.run(
                ['/bin/bash', '-c', command],
                capture_output=True, text=True,
                timeout=30, cwd=WORK_DIR,
            )
        output = (result.stdout or "") + (result.stderr or "")
        return {
            "command": command,
            "returncode": result.returncode,
            "output": output[:20000],
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Command timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/task/start")
async def start_task(body: dict):
    description = body.get("description", "")
    if not description:
        raise HTTPException(status_code=400, detail="No description provided")
    task_id = str(uuid.uuid4())[:8]
    with _task_lock:
        _task_store[task_id] = {
            "id": task_id,
            "description": description,
            "status": "running",
            "progress": 0,
            "result": None,
        }

    def _run():
        try:
            agent = _get_agent(f"task_{task_id}")
            if agent is None:
                with _task_lock:
                    _task_store[task_id]["status"] = "failed"
                    _task_store[task_id]["result"] = "AgentCore unavailable"
                return
            loop = asyncio.new_event_loop()
            response = loop.run_until_complete(agent.process(description))
            loop.close()
            with _task_lock:
                _task_store[task_id]["status"] = "completed"
                _task_store[task_id]["progress"] = 100
                _task_store[task_id]["result"] = getattr(response, 'content', str(response))
        except Exception as e:
            with _task_lock:
                _task_store[task_id]["status"] = "failed"
                _task_store[task_id]["result"] = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"task_id": task_id, "status": "started"}


@app.get("/api/task/status")
async def task_status(task_id: str = ""):
    if not task_id:
        with _task_lock:
            return {"tasks": list(_task_store.values())}
    with _task_lock:
        task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid.uuid4())[:8]
    logger.info(f"WebSocket connected: {session_id}")
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "data": {"message": "Invalid JSON"}})
                continue

            msg_type = msg.get("type", "")

            handlers = {
                "get_file_tree": _ws_get_file_tree,
                "get_file": _ws_get_file,
                "save_file": _ws_save_file,
                "create_file": _ws_create_file,
                "ai_chat": _ws_ai_chat,
                "inline_edit": _ws_inline_edit,
                "completion": _ws_completion,
                "terminal_input": _ws_terminal_input,
                "terminal_execute": _ws_terminal_execute,
                "task_start": _ws_task_start,
                "voice_toggle": _ws_voice_toggle,
                "get_settings": _ws_get_settings,
            }
            handler = handlers.get(msg_type)
            if handler:
                await handler(ws, session_id, msg)
            else:
                await ws.send_json({"type": "error", "data": {"message": f"Unknown type: {msg_type}"}})
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error ({session_id}): {e}")
        try:
            await ws.close()
        except Exception:
            pass


async def _send_json(ws: WebSocket, msg: dict):
    try:
        await ws.send_json(msg)
    except Exception:
        pass


async def _ws_get_file_tree(ws: WebSocket, session_id: str, msg: dict):
    path = msg.get("path", ".")
    try:
        real = _safe_path(path)
        tree = _build_file_tree(real)
        await _send_json(ws, {"type": "file_tree", "data": tree})
    except Exception as e:
        await _send_json(ws, {"type": "error", "data": {"message": str(e)}})


async def _ws_get_file(ws: WebSocket, session_id: str, msg: dict):
    path = msg.get("path", "")
    try:
        real = _safe_path(path)
        if not os.path.isfile(real):
            await _send_json(ws, {"type": "error", "data": {"message": f"Not found: {path}"}})
            return
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        await _send_json(ws, {"type": "file_content", "data": {"path": path, "content": content}})
    except Exception as e:
        await _send_json(ws, {"type": "error", "data": {"message": str(e)}})


async def _ws_save_file(ws: WebSocket, session_id: str, msg: dict):
    path = msg.get("path", "")
    content = msg.get("content", "")
    try:
        real = _safe_path(path)
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, "w", encoding="utf-8") as f:
            f.write(content)
        await _send_json(ws, {"type": "file_saved", "data": {"path": path}})
    except Exception as e:
        await _send_json(ws, {"type": "error", "data": {"message": str(e)}})


async def _ws_create_file(ws: WebSocket, session_id: str, msg: dict):
    path = msg.get("path", "")
    content = msg.get("content", "")
    try:
        real = _safe_path(path)
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, "w", encoding="utf-8") as f:
            f.write(content)
        await _send_json(ws, {"type": "file_created", "data": {"path": path}})
    except Exception as e:
        await _send_json(ws, {"type": "error", "data": {"message": str(e)}})


async def _ws_ai_chat(ws: WebSocket, session_id: str, msg: dict):
    message = msg.get("message", "")
    model_name = msg.get("model", None)
    if not message:
        await _send_json(ws, {"type": "error", "data": {"message": "Empty message"}})
        return
    agent = _get_agent(session_id)
    if agent is None:
        await _send_json(ws, {"type": "ai_done", "data": {"content": "**Error**: AI agent is not available. Please check your API keys."}})
        return
    try:
        full_content = ""
        if hasattr(agent, 'run_turn'):
            async for event in agent.run_turn(message):
                if TextDelta is not None and isinstance(event, TextDelta):
                    full_content += event.text
                    await _send_json(ws, {"type": "ai_stream", "data": {"text": event.text}})
                elif TurnFailed is not None and isinstance(event, TurnFailed):
                    err_msg = f"**Error [{event.code}]**: {event.error}"
                    await _send_json(ws, {"type": "ai_stream", "data": {"text": err_msg}})
                    full_content += err_msg
                elif CancelledEvent is not None and isinstance(event, CancelledEvent):
                    break
        else:
            response = await agent.process(message)
            full_content = getattr(response, 'content', str(response))
            await _send_json(ws, {"type": "ai_stream", "data": {"text": full_content}})
        await _send_json(ws, {"type": "ai_done", "data": {"content": full_content}})
    except Exception as e:
        logger.error(f"AI chat error: {e}")
        err_msg = f"**Error**: {str(e)}"
        await _send_json(ws, {"type": "ai_stream", "data": {"text": err_msg}})
        await _send_json(ws, {"type": "ai_done", "data": {"content": err_msg}})


async def _ws_inline_edit(ws: WebSocket, session_id: str, msg: dict):
    code = msg.get("code", "")
    instruction = msg.get("instruction", "")
    if not code or not instruction:
        await _send_json(ws, {"type": "error", "data": {"message": "Missing code or instruction"}})
        return
    agent = _get_agent(session_id)
    if agent is None:
        await _send_json(ws, {"type": "inline_edit", "data": {"code": code, "error": "AI unavailable"}})
        return
    prompt = (
        f"You are a code editor AI. Modify the following code according to the user's instruction.\n\n"
        f"Instruction: {instruction}\n\n"
        f"Code:\n```\n{code}\n```\n\n"
        f"Return ONLY the complete modified code inside ``` blocks. No explanations, no markdown outside."
    )
    try:
        full_content = ""
        async for event in agent.run_turn(prompt):
            if TextDelta is not None and isinstance(event, TextDelta):
                full_content += event.text
                await _send_json(ws, {"type": "edit_stream", "data": {"token": event.text}})
            elif TurnFailed is not None and isinstance(event, TurnFailed):
                logger.warning(f"Inline edit failed: [{event.code}] {event.error}")
                full_content += f"\n[Error: {event.error}]"
            elif CancelledEvent is not None and isinstance(event, CancelledEvent):
                break
        extracted = _extract_code_block(full_content)
        await _send_json(ws, {"type": "inline_edit", "data": {"code": extracted or full_content}})
    except Exception as e:
        logger.error(f"Inline edit error: {e}")
        await _send_json(ws, {"type": "inline_edit", "data": {"code": code, "error": str(e)}})


async def _ws_completion(ws: WebSocket, session_id: str, msg: dict):
    prefix = msg.get("prefix", "")
    suffix = msg.get("suffix", "")
    file_path = msg.get("path", "")
    if len(prefix.strip()) < 2:
        return
    agent = _get_agent(session_id)
    if agent is None:
        return
    lang_hint = ""
    if file_path:
        ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''
        lang_map = {'py': 'Python', 'js': 'JavaScript', 'ts': 'TypeScript',
                     'html': 'HTML', 'css': 'CSS', 'json': 'JSON', 'md': 'Markdown'}
        lang_hint = lang_map.get(ext, '')
    prompt = (
        f"Complete this {lang_hint} code snippet. Return ONLY the completion text.\n\n"
        f"```{lang_hint.lower()}\n{prefix}"
    )
    try:
        full_content = ""
        async for event in agent.run_turn(prompt):
            if TextDelta is not None and isinstance(event, TextDelta):
                full_content += event.text
            elif TurnFailed is not None and isinstance(event, TurnFailed):
                logger.warning(f"Completion failed: [{event.code}] {event.error}")
                break
            elif CancelledEvent is not None and isinstance(event, CancelledEvent):
                break
        completion = full_content.strip().strip('`').strip()
        completion = completion.lstrip(prefix.rstrip()).lstrip('\n').split('\n')[0] if '\n' in completion else completion
        if completion:
            await _send_json(ws, {"type": "completion", "data": {"text": completion}})
    except Exception:
        pass


async def _ws_terminal_input(ws: WebSocket, session_id: str, msg: dict):
    data = msg.get("data", "")
    proc = _terminal_sessions.get(session_id)
    if proc and proc.poll() is None:
        try:
            proc.stdin.write(data.encode())
            proc.stdin.flush()
        except Exception:
            pass


async def _ws_terminal_execute(ws: WebSocket, session_id: str, msg: dict):
    command = msg.get("command", "")
    if not command:
        return
    try:
        if os.name == 'nt':
            proc = subprocess.Popen(
                ['cmd', '/c', command],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=WORK_DIR, bufsize=1,
            )
        else:
            proc = subprocess.Popen(
                ['/bin/bash', '-c', command],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=WORK_DIR, bufsize=1,
            )
        _terminal_sessions[session_id] = proc

        def _read_output():
            for line in iter(proc.stdout.readline, ''):
                line = line.replace('\r\n', '\n').replace('\r', '\n')
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(
                        _send_json(ws, {"type": "terminal_output", "data": line})
                    )
                    loop.close()
                except Exception:
                    break
            _terminal_sessions.pop(session_id, None)

        t = threading.Thread(target=_read_output, daemon=True)
        t.start()
    except Exception as e:
        await _send_json(ws, {"type": "terminal_output", "data": f"Error: {e}\n"})


async def _ws_task_start(ws: WebSocket, session_id: str, msg: dict):
    description = msg.get("description", "")
    task_id = str(uuid.uuid4())[:8]
    with _task_lock:
        _task_store[task_id] = {
            "id": task_id,
            "description": description,
            "status": "running",
        }
    await _send_json(ws, {"type": "task_update", "data": {"id": task_id, "description": description, "status": "running"}})

    def _run():
        try:
            agent = _get_agent(f"task_{task_id}")
            if agent:
                loop = asyncio.new_event_loop()
                resp = loop.run_until_complete(agent.process(description))
                loop.close()
                result = getattr(resp, 'content', str(resp))
            else:
                result = "Agent unavailable"
            status = "done"
        except Exception as e:
            status = "failed"
            result = str(e)
        with _task_lock:
            _task_store[task_id]["status"] = status
            _task_store[task_id]["result"] = result
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                _send_json(ws, {"type": "task_update", "data": {"id": task_id, "status": status, "result": result}})
            )
            loop.close()
        except Exception:
            pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()


async def _ws_voice_toggle(ws: WebSocket, session_id: str, msg: dict):
    enabled = msg.get("enabled", False)
    await _send_json(ws, {"type": "voice_status", "data": {"enabled": enabled}})


async def _ws_get_settings(ws: WebSocket, session_id: str, msg: dict):
    settings = {
        "models": ["deepseek", "qwen", "glm", "mimo", "gemini"],
        "default_model": BASE_CONFIG.get("DEFAULT_MODEL", "deepseek"),
        "work_dir": WORK_DIR,
        "has_voice": bool(os.environ.get("ASR_MODEL")),
    }
    await _send_json(ws, {"type": "settings", "data": settings})


def _extract_code_block(text: str) -> str:
    import re
    matches = re.findall(r'```(?:\w*)\n(.*?)```', text, re.DOTALL)
    if matches:
        return matches[-1].strip()
    return text.strip()


_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")


def main():
    if not _HAS_FASTAPI:
        print("FastAPI/uvicorn not installed. Run: pip install fastapi uvicorn")
        return
    host = BASE_CONFIG.get("EDITOR_HOST", "0.0.0.0")
    port = int(BASE_CONFIG.get("EDITOR_PORT", 8765))
    logger.info(f"Starting editor server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
