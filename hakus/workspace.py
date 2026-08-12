import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

WORKSPACE_DIRS = ["doc", "src", "logs", "test-reports"]


@dataclass
class FileRecord:
    path: str
    filename: str
    size: int
    checksum: str
    category: str
    created_by: str
    created_at: str
    modified_at: str
    description: str = ""


@dataclass
class WorkspaceState:
    project_name: str
    root_dir: str
    created_at: str
    updated_at: str
    files: List[FileRecord] = field(default_factory=list)
    plan_file: Optional[str] = None
    lessons_file: Optional[str] = None


class Workspace:
    def __init__(self, root_dir: str, project_name: str = "default"):
        self.root_dir = Path(root_dir).resolve()
        self.project_name = project_name
        self._state_file = self.root_dir / ".workspace_state.json"
        self._state: Optional[WorkspaceState] = None

    def initialize(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        for d in WORKSPACE_DIRS:
            (self.root_dir / d).mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        if self._state is None:
            now = datetime.now().isoformat()
            self._state = WorkspaceState(
                project_name=self.project_name,
                root_dir=str(self.root_dir),
                created_at=now,
                updated_at=now,
            )
            self._save_state()
        logger.info(f"Workspace initialized: {self.root_dir}")

    @property
    def doc_dir(self) -> Path:
        return self.root_dir / "doc"

    @property
    def src_dir(self) -> Path:
        return self.root_dir / "src"

    @property
    def logs_dir(self) -> Path:
        return self.root_dir / "logs"

    @property
    def test_reports_dir(self) -> Path:
        return self.root_dir / "test-reports"

    def ensure_dirs(self) -> None:
        for d in WORKSPACE_DIRS:
            (self.root_dir / d).mkdir(parents=True, exist_ok=True)

    def track_file(self, file_path: str, created_by: str = "unknown",
                   description: str = "") -> Optional[FileRecord]:
        p = Path(file_path)
        if not p.exists():
            logger.warning(f"File not found for tracking: {file_path}")
            return None
        if self._state is None:
            return None
        now = datetime.now().isoformat()
        try:
            content = p.read_bytes()
            checksum = hashlib.md5(content).hexdigest()
            size = len(content)
        except Exception:
            checksum = ""
            size = 0
        record = FileRecord(
            path=str(p),
            filename=p.name,
            size=size,
            checksum=checksum,
            category=self._categorize(p),
            created_by=created_by,
            created_at=now,
            modified_at=now,
            description=description,
        )
        existing = [f for f in self._state.files if f.path == record.path]
        if existing:
            idx = self._state.files.index(existing[0])
            record.created_at = existing[0].created_at
            self._state.files[idx] = record
        else:
            self._state.files.append(record)
        self._state.updated_at = now
        self._save_state()
        return record

    def untrack_file(self, file_path: str) -> None:
        if self._state is None:
            return
        self._state.files = [f for f in self._state.files if f.path != str(Path(file_path))]
        self._state.updated_at = datetime.now().isoformat()
        self._save_state()

    def get_file_record(self, file_path: str) -> Optional[FileRecord]:
        if self._state is None:
            return None
        target = str(Path(file_path))
        for f in self._state.files:
            if f.path == target:
                return f
        return None

    def list_files(self, category: Optional[str] = None) -> List[FileRecord]:
        if self._state is None:
            return []
        if category:
            return [f for f in self._state.files if f.category == category]
        return list(self._state.files)

    def scan_and_sync(self, created_by: str = "scanner") -> List[FileRecord]:
        if self._state is None:
            return []
        existing_paths = {f.path for f in self._state.files}
        new_records = []
        for d in WORKSPACE_DIRS:
            target = self.root_dir / d
            if not target.exists():
                continue
            for f in target.rglob("*"):
                if not f.is_file():
                    continue
                if str(f) not in existing_paths:
                    record = self.track_file(str(f), created_by=created_by)
                    if record:
                        new_records.append(record)
                        existing_paths.add(str(f))
        logger.info(f"Workspace scan: {len(new_records)} new files found")
        return new_records

    def write_plan(self, content: str) -> Path:
        self.doc_dir.mkdir(parents=True, exist_ok=True)
        plan_path = self.doc_dir / "plan.md"
        plan_path.write_text(content, encoding="utf-8")
        if self._state is not None:
            self._state.plan_file = str(plan_path)
            self._state.updated_at = datetime.now().isoformat()
            self._save_state()
        self.track_file(str(plan_path), created_by="planner", description="Development plan")
        logger.info(f"Plan written: {plan_path}")
        return plan_path

    def read_plan(self) -> Optional[str]:
        if self._state is not None and self._state.plan_file:
            p = Path(self._state.plan_file)
            if p.exists():
                return p.read_text(encoding="utf-8")
        plan_path = self.doc_dir / "plan.md"
        if plan_path.exists():
            return plan_path.read_text(encoding="utf-8")
        return None

    def write_lessons(self, content: str) -> Path:
        self.doc_dir.mkdir(parents=True, exist_ok=True)
        lessons_path = self.doc_dir / "lessons-learned.md"
        lessons_path.write_text(content, encoding="utf-8")
        if self._state is not None:
            self._state.lessons_file = str(lessons_path)
            self._state.updated_at = datetime.now().isoformat()
            self._save_state()
        self.track_file(str(lessons_path), created_by="system", description="Lessons learned")
        return lessons_path

    def read_lessons(self) -> Optional[str]:
        if self._state is not None and self._state.lessons_file:
            p = Path(self._state.lessons_file)
            if p.exists():
                return p.read_text(encoding="utf-8")
        lessons_path = self.doc_dir / "lessons-learned.md"
        if lessons_path.exists():
            return lessons_path.read_text(encoding="utf-8")
        return None

    def append_lesson(self, title: str, content: str) -> None:
        existing = self.read_lessons() or "# Lessons Learned\n\n"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## {now} - {title}\n\n{content}\n"
        self.write_lessons(existing + entry)

    def append_structured_lesson(
        self,
        category: str,
        title: str,
        principle: str,
        counter_example: str = "",
        example: str = "",
        abstraction_check: str = "",
    ) -> None:
        existing = self.read_lessons() or "# Lessons Learned\n\n"
        now = datetime.now().strftime("%y%m%d %H%M")
        lines = [
            "",
            f"## [{category}] {now} - {title}",
            "",
            f"**原则**: {principle}",
        ]
        if counter_example:
            lines.append(f"\n**反例**: {counter_example}")
        if example:
            lines.append(f"\n**正例**: {example}")
        if abstraction_check:
            lines.append(f"\n**抽象检查**: {abstraction_check}")
        lines.append("")
        entry = "\n".join(lines) + "\n"
        self.write_lessons(existing + entry)

    def condense_lessons(self, max_entries: int = 200) -> int:
        existing = self.read_lessons()
        if not existing:
            return 0
        parts = existing.split("\n## ")
        if len(parts) <= max_entries:
            return 0
        header = parts[0]
        rest = ["## " + p for p in parts[1:]]
        rest.sort(key=lambda s: s[:30], reverse=True)
        kept = rest[:max_entries]
        self.write_lessons(header + "\n" + "".join(kept))
        return len(rest) - max_entries

    def write_log(self, log_name: str, content: str) -> Path:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_dir / log_name
        log_path.write_text(content, encoding="utf-8")
        self.track_file(str(log_path), created_by="system", description=f"Log: {log_name}")
        return log_path

    def append_log(self, log_name: str, message: str, level: str = "INFO") -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_dir / log_name
        now = datetime.now().strftime("%y%m%d %H%M")
        line = f"- {now} [{level}] {message}\n"
        if log_path.exists():
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)
        else:
            log_path.write_text(line, encoding="utf-8")

    def append_structured_log(
        self,
        log_name: str,
        actor: str,
        action: str,
        target: str = "",
        extra: str = "",
    ) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_dir / log_name
        now = datetime.now().strftime("%y%m%d %H%M")
        parts = [now, actor, action]
        if target:
            parts.append(target)
        if extra:
            parts.append(extra)
        line = "- " + " | ".join(parts) + "\n"
        if log_path.exists():
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)
        else:
            log_path.write_text(line, encoding="utf-8")

    def write_test_report(self, report_name: str, content: str) -> Path:
        self.test_reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.test_reports_dir / report_name
        report_path.write_text(content, encoding="utf-8")
        self.track_file(str(report_path), created_by="tester", description=f"Test report: {report_name}")
        return report_path

    def get_summary(self) -> Dict[str, Any]:
        if self._state is None:
            return {"error": "Workspace not initialized"}
        by_category: Dict[str, int] = {}
        total_size = 0
        for f in self._state.files:
            by_category[f.category] = by_category.get(f.category, 0) + 1
            total_size += f.size
        return {
            "project_name": self._state.project_name,
            "root_dir": self._state.root_dir,
            "created_at": self._state.created_at,
            "updated_at": self._state.updated_at,
            "total_files": len(self._state.files),
            "total_size": total_size,
            "by_category": by_category,
            "has_plan": self._state.plan_file is not None,
            "has_lessons": self._state.lessons_file is not None,
        }

    def cleanup(self, max_age_days: int = 30) -> int:
        if self._state is None:
            return 0
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        to_keep = []
        for f in self._state.files:
            p = Path(f.path)
            if not p.exists():
                removed += 1
                continue
            try:
                if p.stat().st_mtime < cutoff and f.category == "log":
                    p.unlink(missing_ok=True)
                    removed += 1
                    continue
            except Exception:
                pass
            to_keep.append(f)
        self._state.files = to_keep
        self._save_state()
        return removed

    def _categorize(self, path: Path) -> str:
        ext = path.suffix.lower()
        code_exts = {'.py', '.js', '.ts', '.html', '.css', '.java', '.go', '.rs', '.cpp', '.c', '.h', '.vue', '.jsx', '.tsx'}
        doc_exts = {'.md', '.txt', '.pdf', '.rst'}
        config_exts = {'.json', '.yaml', '.yml', '.toml', '.ini', '.cfg'}
        if ext in code_exts:
            return "code"
        if ext in doc_exts:
            return "doc"
        if ext in config_exts:
            return "config"
        if path.parent.name == "logs":
            return "log"
        if path.parent.name == "test-reports":
            return "test-report"
        return "other"

    def _load_state(self) -> Optional[WorkspaceState]:
        if not self._state_file.exists():
            return None
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            files = []
            for fd in data.get("files", []):
                files.append(FileRecord(**fd))
            return WorkspaceState(
                project_name=data.get("project_name", self.project_name),
                root_dir=data.get("root_dir", str(self.root_dir)),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                files=files,
                plan_file=data.get("plan_file"),
                lessons_file=data.get("lessons_file"),
            )
        except Exception as e:
            logger.warning(f"Failed to load workspace state: {e}")
            return None

    def _save_state(self) -> None:
        if self._state is None:
            return
        data = {
            "project_name": self._state.project_name,
            "root_dir": self._state.root_dir,
            "created_at": self._state.created_at,
            "updated_at": self._state.updated_at,
            "plan_file": self._state.plan_file,
            "lessons_file": self._state.lessons_file,
            "files": [
                {
                    "path": f.path,
                    "filename": f.filename,
                    "size": f.size,
                    "checksum": f.checksum,
                    "category": f.category,
                    "created_by": f.created_by,
                    "created_at": f.created_at,
                    "modified_at": f.modified_at,
                    "description": f.description,
                }
                for f in self._state.files
            ],
        }
        self._state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
