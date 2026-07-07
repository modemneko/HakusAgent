import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Task:
    id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    assigned_to: Optional[str] = None
    parent_id: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    agent_id: Optional[str] = None
    output_files: List[str] = field(default_factory=list)
    test_result: Optional[str] = None
    test_issues: List[str] = field(default_factory=list)
    heartbeat_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "assigned_to": self.assigned_to,
            "parent_id": self.parent_id,
            "dependencies": self.dependencies,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "agent_id": self.agent_id,
            "output_files": self.output_files,
            "test_result": self.test_result,
            "test_issues": self.test_issues,
            "heartbeat_at": self.heartbeat_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            status=TaskStatus(data.get("status", "pending")),
            priority=TaskPriority(data.get("priority", 2)),
            assigned_to=data.get("assigned_to"),
            parent_id=data.get("parent_id"),
            dependencies=data.get("dependencies", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            agent_id=data.get("agent_id"),
            output_files=data.get("output_files", []),
            test_result=data.get("test_result"),
            test_issues=data.get("test_issues", []),
            heartbeat_at=data.get("heartbeat_at"),
            metadata=data.get("metadata", {}),
        )


HEARTBEAT_TIMEOUT_SECONDS = 300
HALLUCINATION_PATTERNS = [
    "I cannot",
    "As an AI",
    "I'm sorry",
    "I don't have access",
    "Error: Unknown tool",
    "Sub-agent reached maximum iterations",
]


class TaskBoard:
    def __init__(self, persist_path: Optional[str] = None):
        self._tasks: Dict[str, Task] = {}
        self._persist_path = Path(persist_path) if persist_path else None
        self._on_status_change: Optional[Callable[[Task, TaskStatus], None]] = None
        if self._persist_path:
            self._load()

    def set_status_callback(self, callback: Callable[[Task, TaskStatus], None]) -> None:
        self._on_status_change = callback

    def add_task(
        self,
        title: str,
        description: str = "",
        priority: TaskPriority = TaskPriority.MEDIUM,
        dependencies: Optional[List[str]] = None,
        parent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        task_id = f"T{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        task = Task(
            id=task_id,
            title=title,
            description=description,
            priority=priority,
            dependencies=dependencies or [],
            parent_id=parent_id,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._tasks[task_id] = task
        self._persist()
        logger.info(f"Task added: {task_id} - {title}")
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def update_status(self, task_id: str, status: TaskStatus) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        old_status = task.status
        task.status = status
        task.updated_at = datetime.now().isoformat()
        if status == TaskStatus.IN_PROGRESS and task.started_at is None:
            task.started_at = task.updated_at
        if status == TaskStatus.COMPLETED:
            task.completed_at = task.updated_at
        self._persist()
        if self._on_status_change and old_status != status:
            self._on_status_change(task, old_status)
        logger.info(f"Task {task_id}: {old_status.value} -> {status.value}")
        return True

    def assign_agent(self, task_id: str, agent_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.assigned_to = agent_id
        task.agent_id = agent_id
        task.updated_at = datetime.now().isoformat()
        self._persist()
        return True

    def update_heartbeat(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.heartbeat_at = datetime.now().isoformat()
        self._persist()
        return True

    def record_test_result(self, task_id: str, result: str, issues: Optional[List[str]] = None) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.test_result = result
        task.test_issues = issues or []
        task.updated_at = datetime.now().isoformat()
        if result == "PASS":
            self.update_status(task_id, TaskStatus.COMPLETED)
        else:
            task.retry_count += 1
            if task.retry_count >= task.max_retries:
                self.update_status(task_id, TaskStatus.FAILED)
            else:
                self.update_status(task_id, TaskStatus.IN_PROGRESS)
        self._persist()
        return True

    def add_output_file(self, task_id: str, file_path: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if file_path not in task.output_files:
            task.output_files.append(file_path)
            task.updated_at = datetime.now().isoformat()
            self._persist()
        return True

    def get_pending(self) -> List[Task]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]

    def get_in_progress(self) -> List[Task]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.IN_PROGRESS]

    def get_testing(self) -> List[Task]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.TESTING]

    def get_completed(self) -> List[Task]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.COMPLETED]

    def get_failed(self) -> List[Task]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.FAILED]

    def get_ready_tasks(self) -> List[Task]:
        ready = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            if not task.dependencies:
                ready.append(task)
                continue
            all_deps_done = all(
                self._tasks.get(dep_id, Task(id="", title="", description="")).status
                in (TaskStatus.COMPLETED,)
                for dep_id in task.dependencies
                if dep_id in self._tasks
            )
            if all_deps_done:
                ready.append(task)
        ready.sort(key=lambda t: t.priority.value, reverse=True)
        return ready

    def get_next_batch(self, batch_size: int = 5) -> List[Task]:
        return self.get_ready_tasks()[:batch_size]

    def check_heartbeats(self) -> List[Task]:
        stale = []
        now = time.time()
        for task in self._tasks.values():
            if task.status not in (TaskStatus.IN_PROGRESS, TaskStatus.TESTING):
                continue
            if task.heartbeat_at is None:
                continue
            try:
                hb_time = datetime.fromisoformat(task.heartbeat_at).timestamp()
                if now - hb_time > HEARTBEAT_TIMEOUT_SECONDS:
                    stale.append(task)
            except Exception:
                pass
        return stale

    def detect_hallucination(self, task_id: str, output: str) -> bool:
        if not output:
            return True
        for pattern in HALLUCINATION_PATTERNS:
            if pattern.lower() in output.lower():
                return True
        return False

    def recover_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.status not in (TaskStatus.IN_PROGRESS, TaskStatus.TESTING, TaskStatus.FAILED):
            return False
        if task.retry_count >= task.max_retries:
            logger.warning(f"Task {task_id} exceeded max retries, cannot recover")
            return False
        task.status = TaskStatus.PENDING
        task.assigned_to = None
        task.agent_id = None
        task.heartbeat_at = None
        task.updated_at = datetime.now().isoformat()
        self._persist()
        logger.info(f"Task {task_id} recovered to PENDING")
        return True

    def get_statistics(self) -> Dict[str, Any]:
        counts = {}
        for status in TaskStatus:
            counts[status.value] = 0
        for task in self._tasks.values():
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        total_retries = sum(t.retry_count for t in self._tasks.values())
        return {
            "total": len(self._tasks),
            "by_status": counts,
            "total_retries": total_retries,
            "ready_tasks": len(self.get_ready_tasks()),
        }

    def get_kanban_view(self) -> Dict[str, List[Dict]]:
        columns = {}
        for status in TaskStatus:
            columns[status.value] = [
                t.to_dict() for t in self._tasks.values() if t.status == status
            ]
        return columns

    def clear_completed(self, older_than_days: int = 7) -> int:
        cutoff = time.time() - (older_than_days * 86400)
        to_remove = []
        for tid, task in self._tasks.items():
            if task.status != TaskStatus.COMPLETED:
                continue
            if task.completed_at:
                try:
                    ct = datetime.fromisoformat(task.completed_at).timestamp()
                    if ct < cutoff:
                        to_remove.append(tid)
                except Exception:
                    pass
        for tid in to_remove:
            del self._tasks[tid]
        if to_remove:
            self._persist()
        return len(to_remove)

    def _load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for td in data.get("tasks", []):
                task = Task.from_dict(td)
                self._tasks[task.id] = task
            logger.info(f"TaskBoard loaded {len(self._tasks)} tasks from {self._persist_path}")
        except Exception as e:
            logger.warning(f"Failed to load TaskBoard: {e}")

    def _persist(self) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "tasks": [t.to_dict() for t in self._tasks.values()],
                "updated_at": datetime.now().isoformat(),
            }
            self._persist_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to persist TaskBoard: {e}")
