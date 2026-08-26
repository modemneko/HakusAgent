"""User-managed Skills for the desktop Python backend.

The repository does not ship a workspace Skill catalog. Skills are discovered
from Hakus-owned user/project roots and compatible agentskills.io roots. Only
Hakus-owned roots are writable through the desktop API.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tarfile
import tempfile
import threading
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml


MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_SKILL_FILE_BYTES = 256 * 1024
MAX_SELECTED_SKILL_BYTES = 64 * 1024
MAX_SELECTED_SKILLS_BYTES = 192 * 1024
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MENTION_PATTERN = re.compile(r"(?<![\w@])@skill:([A-Za-z0-9][A-Za-z0-9._-]{0,63})")
_STATE_LOCK = threading.Lock()


class SkillError(ValueError):
    """A user-actionable Skill operation error."""


@dataclass(frozen=True)
class SkillRoot:
    path: Path
    source: str
    scope: str
    writable: bool


@dataclass(frozen=True)
class SkillRecord:
    name: str
    description: str
    path: str
    source: str
    scope: str
    enabled: bool
    writable: bool
    is_bundled: bool = False
    plugin_id: None = None
    plugin_generation: None = None
    plugin_content_hash: None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def hakus_home() -> Path:
    configured = os.environ.get("HAKUS_HOME", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise SkillError("HAKUS_HOME must be an absolute path")
        return path.resolve()
    return (Path.home() / ".hakus").resolve()


def skill_roots(project_dir: Optional[Path] = None) -> list[SkillRoot]:
    roots: list[SkillRoot] = []
    if project_dir is not None:
        project = project_dir.expanduser().resolve()
        roots.extend(
            [
                SkillRoot(project / ".hakus" / "skills", "hakus-project", "project", True),
                SkillRoot(project / ".agents" / "skills", "agents-project", "project", False),
            ]
        )

    home = hakus_home()
    roots.append(SkillRoot(home / "skills", "hakus-global", "global", True))

    user_home = Path.home().resolve()
    agents_root = user_home / ".agents" / "skills"
    explicit_home = bool(os.environ.get("HAKUS_HOME", "").strip())
    default_hakus_home = user_home / ".hakus"
    if agents_root != home / "skills" and (not explicit_home or home == default_hakus_home):
        roots.append(SkillRoot(agents_root, "agents-global", "global", False))
    return roots


def _state_path() -> Path:
    return hakus_home() / "skills_state.toml"


def _load_disabled() -> set[str]:
    path = _state_path()
    if not path.exists():
        return set()
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SkillError(f"Could not read Skill state at {path}: {exc}") from exc
    values = parsed.get("disabled", [])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise SkillError(f"Invalid disabled list in {path}")
    return set(values)


def _write_disabled(disabled: set[str]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(json.dumps(value, ensure_ascii=False) for value in sorted(disabled))
    body = f"disabled = [{values}]\n"
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(body, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def set_enabled(name: str, enabled: bool, project_dir: Optional[Path] = None) -> dict[str, Any]:
    record = find_skill(name, project_dir=project_dir, include_disabled=True)
    if record is None:
        raise SkillError(f"Skill '{name}' was not found")
    with _STATE_LOCK:
        disabled = _load_disabled()
        if enabled:
            disabled.discard(record.name)
        else:
            disabled.add(record.name)
        _write_disabled(disabled)
    return {"name": record.name, "enabled": enabled}


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}
    try:
        parsed = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_skill(skill_file: Path, root: SkillRoot, disabled: set[str]) -> Optional[SkillRecord]:
    try:
        if skill_file.stat().st_size > MAX_SKILL_FILE_BYTES:
            return None
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    metadata = _frontmatter(text)
    name = str(metadata.get("name") or skill_file.parent.name).strip()
    if not _NAME_PATTERN.fullmatch(name):
        return None
    description = str(metadata.get("description") or "").strip()
    if not description:
        body_lines = [line.strip() for line in text.splitlines() if line.strip() and line.strip() != "---"]
        description = (body_lines[0].lstrip("# ") if body_lines else "User-installed Skill")[:280]
    return SkillRecord(
        name=name,
        description=description[:280],
        path=str(skill_file.resolve()),
        source=root.source,
        scope=root.scope,
        enabled=name not in disabled,
        writable=root.writable,
    )


def discover_skills(project_dir: Optional[Path] = None) -> dict[str, Any]:
    disabled = _load_disabled()
    records: list[SkillRecord] = []
    warnings: list[str] = []
    seen: set[str] = set()
    roots = skill_roots(project_dir)

    for root in roots:
        if not root.path.is_dir():
            continue
        try:
            candidates = sorted(root.path.rglob("SKILL.md"))
        except OSError as exc:
            warnings.append(f"Could not scan {root.path}: {exc}")
            continue
        for skill_file in candidates:
            record = _parse_skill(skill_file, root, disabled)
            if record is None:
                warnings.append(f"Skipped invalid Skill definition: {skill_file}")
                continue
            canonical = record.name.casefold()
            if canonical in seen:
                continue
            seen.add(canonical)
            records.append(record)

    return {
        "directory": str(hakus_home() / "skills"),
        "directories": [str(root.path) for root in roots],
        "warnings": warnings,
        "skills": [record.to_dict() for record in records],
    }


def find_skill(
    name: str,
    project_dir: Optional[Path] = None,
    include_disabled: bool = False,
) -> Optional[SkillRecord]:
    canonical = name.casefold()
    for raw in discover_skills(project_dir)["skills"]:
        record = SkillRecord(**raw)
        if record.name.casefold() == canonical and (include_disabled or record.enabled):
            return record
    return None


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "HakusAI-Skills/1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, destination.open("wb") as target:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_DOWNLOAD_BYTES:
                raise SkillError("Skill download exceeds the 20 MB limit")
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise SkillError("Skill download exceeds the 20 MB limit")
                target.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise SkillError(f"Could not download Skill: {exc}") from exc


def _safe_archive_path(destination: Path, member_name: str) -> Path:
    member = Path(member_name.replace("\\", "/"))
    if member.is_absolute() or ".." in member.parts:
        raise SkillError(f"Unsafe archive entry: {member_name}")
    resolved = (destination / member).resolve()
    if destination.resolve() not in resolved.parents and resolved != destination.resolve():
        raise SkillError(f"Unsafe archive entry: {member_name}")
    return resolved


def _extract_archive(archive: Path, destination: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            total = 0
            for info in bundle.infolist():
                total += info.file_size
                if total > MAX_DOWNLOAD_BYTES:
                    raise SkillError("Expanded Skill package exceeds the 20 MB limit")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise SkillError("Skill archives may not contain symbolic links")
                target = _safe_archive_path(destination, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return
    try:
        with tarfile.open(archive, mode="r:*") as bundle:
            total = 0
            for member in bundle.getmembers():
                if member.issym() or member.islnk():
                    raise SkillError("Skill archives may not contain links")
                if member.isfile():
                    total += member.size
                    if total > MAX_DOWNLOAD_BYTES:
                        raise SkillError("Expanded Skill package exceeds the 20 MB limit")
                target = _safe_archive_path(destination, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                source = bundle.extractfile(member)
                if source is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except tarfile.TarError as exc:
        raise SkillError("The downloaded file is not a supported ZIP or TAR archive") from exc


def _github_urls(source: str) -> list[str]:
    value = source.strip()
    if value.startswith("github:"):
        repository = value.removeprefix("github:").strip("/")
    else:
        parsed = urllib.parse.urlparse(value)
        if parsed.netloc.lower() != "github.com":
            return []
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            return []
        repository = "/".join(parts[:2])
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise SkillError("GitHub source must look like github:owner/repository")
    owner, repo = repository.split("/", 1)
    repo = repo.removesuffix(".git")
    base = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads"
    return [f"{base}/main", f"{base}/master"]


def _materialize_source(source: str, temp_dir: Path) -> Path:
    local = Path(source).expanduser()
    if local.exists():
        if not local.is_dir():
            raise SkillError("A local Skill source must be a directory containing SKILL.md")
        return local.resolve()

    urls = _github_urls(source)
    if not urls:
        parsed = urllib.parse.urlparse(source)
        if parsed.scheme not in {"http", "https"}:
            raise SkillError("Use a local directory, github:owner/repository, or an HTTP(S) archive")
        urls = [source]

    archive = temp_dir / "skill-download"
    last_error: Optional[Exception] = None
    for url in urls:
        try:
            _download(url, archive)
            break
        except SkillError as exc:
            last_error = exc
            archive.unlink(missing_ok=True)
    else:
        raise SkillError(str(last_error or "Could not download Skill"))

    extracted = temp_dir / "extracted"
    extracted.mkdir()
    _extract_archive(archive, extracted)
    return extracted


def _select_skill_root(source_root: Path) -> Path:
    direct = source_root / "SKILL.md"
    if direct.is_file():
        return source_root
    candidates = sorted(source_root.rglob("SKILL.md"))
    if not candidates:
        raise SkillError("No SKILL.md was found in the source")
    if len(candidates) > 1:
        raise SkillError("The source contains multiple Skills; provide a directory or archive for one Skill")
    return candidates[0].parent


def _copy_skill(source_root: Path, destination: Path) -> None:
    total = 0
    for entry in source_root.rglob("*"):
        if entry.is_symlink():
            raise SkillError("Skill packages may not contain symbolic links")
        if entry.is_file():
            total += entry.stat().st_size
            if total > MAX_DOWNLOAD_BYTES:
                raise SkillError("Skill package exceeds the 20 MB limit")
    temp_destination = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copytree(source_root, temp_destination)
        os.replace(temp_destination, destination)
    finally:
        if temp_destination.exists():
            shutil.rmtree(temp_destination, ignore_errors=True)


def install_skill(source: str, scope: str = "global", project_dir: Optional[Path] = None) -> dict[str, Any]:
    if not source.strip():
        raise SkillError("Skill source is required")
    if scope not in {"global", "project"}:
        raise SkillError("Skill scope must be 'global' or 'project'")
    if scope == "project" and project_dir is None:
        raise SkillError("Select a project before installing a project Skill")

    destination_root = (
        project_dir.expanduser().resolve() / ".hakus" / "skills"
        if scope == "project" and project_dir is not None
        else hakus_home() / "skills"
    )
    destination_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="hakus-skill-") as temp:
        source_root = _select_skill_root(_materialize_source(source.strip(), Path(temp)))
        parsed = _parse_skill(
            source_root / "SKILL.md",
            SkillRoot(source_root, "install-source", scope, False),
            set(),
        )
        if parsed is None:
            raise SkillError("SKILL.md is invalid or exceeds the size limit")
        destination = destination_root / parsed.name
        if destination.exists():
            raise SkillError(f"Skill '{parsed.name}' is already installed in {scope} scope")
        _copy_skill(source_root, destination)

    return {
        "name": parsed.name,
        "outcome": "installed",
        "scope": scope,
        "safe_target_path": str(destination),
    }


def remove_skill(name: str, scope: Optional[str] = None, project_dir: Optional[Path] = None) -> dict[str, Any]:
    matches = [
        SkillRecord(**raw)
        for raw in discover_skills(project_dir)["skills"]
        if raw["name"].casefold() == name.casefold()
        and raw["writable"]
        and (scope is None or raw["scope"] == scope)
    ]
    if not matches:
        raise SkillError(f"Writable Skill '{name}' was not found")
    if len(matches) > 1:
        raise SkillError("Skill exists in both project and global scope; choose a scope")
    record = matches[0]
    skill_dir = Path(record.path).parent.resolve()
    allowed_roots = [root.path.resolve() for root in skill_roots(project_dir) if root.writable]
    if not any(skill_dir.parent == root for root in allowed_roots):
        raise SkillError("Refusing to remove a Skill outside a Hakus-owned root")
    shutil.rmtree(skill_dir)
    return {
        "name": record.name,
        "outcome": "removed",
        "scope": record.scope,
        "safe_target_path": str(skill_dir),
    }


def selected_skill_names(message: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in _MENTION_PATTERN.finditer(message):
        name = match.group(1)
        canonical = name.casefold()
        if canonical not in seen:
            names.append(name)
            seen.add(canonical)
    return names


def expand_skill_mentions(message: str, project_dir: Optional[Path] = None) -> str:
    names = selected_skill_names(message)
    if not names:
        return message

    blocks: list[str] = []
    total = 0
    for name in names:
        record = find_skill(name, project_dir=project_dir, include_disabled=False)
        if record is None:
            raise SkillError(f"Selected Skill '{name}' is disabled or unavailable")
        body = Path(record.path).read_bytes()
        if len(body) > MAX_SELECTED_SKILL_BYTES:
            raise SkillError(f"Selected Skill '{record.name}' exceeds the 64 KB prompt limit")
        total += len(body)
        if total > MAX_SELECTED_SKILLS_BYTES:
            raise SkillError("Selected Skills exceed the 192 KB prompt limit")
        text = body.decode("utf-8", errors="replace")
        blocks.append(
            f'<skill name="{record.name}" path="{record.path}">\n{text}\n</skill>'
        )

    rendered_blocks = "\n".join(blocks)
    return (
        f"{message}\n\n"
        "<selected_skills>\n"
        "The user explicitly selected the following Skills. Follow their instructions for this request. "
        "Resolve relative resource paths from each Skill directory.\n"
        f"{rendered_blocks}\n"
        "</selected_skills>"
    )
