"""AGENTS.md auto-generation and project intelligence extraction.

Codex CLI's AGENTS.md is a project-level instruction file that tells the
agent how to behave in this specific project. It goes beyond CLAUDE.md
by being auto-generated from project analysis:

1. **Auto-discovery**: Scan project for tech stack, build tools, conventions
2. **Intelligent extraction**: Parse package.json, pyproject.toml, Makefile, etc.
3. **Convention inference**: Detect linting, formatting, testing conventions
4. **Git-aware**: Extract branch strategy, commit conventions from history
5. **Dependency mapping**: Map imports to understand project structure

Generated AGENTS.md includes:
  - Project identity (name, language, framework)
  - Build/test/lint commands
  - Code conventions (formatting, naming)
  - File structure rules
  - Common pitfalls and project-specific instructions
  - Git workflow conventions
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProjectIntelligence:
    """Extracted project metadata for AGENTS.md generation."""
    name: str = ""
    language: str = ""
    framework: str = ""
    description: str = ""

    # Build system
    build_tool: str = ""
    build_command: str = ""
    test_command: str = ""
    lint_command: str = ""
    format_command: str = ""
    dev_command: str = ""

    # Tech stack
    dependencies: List[str] = field(default_factory=list)
    dev_dependencies: List[str] = field(default_factory=list)
    python_version: Optional[str] = None
    node_version: Optional[str] = None

    # Structure
    src_dirs: List[str] = field(default_factory=list)
    test_dirs: List[str] = field(default_factory=list)
    config_files: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)

    # Conventions
    formatting: str = ""  # e.g. "black", "prettier"
    linting: str = ""     # e.g. "ruff", "eslint"
    testing: str = ""     # e.g. "pytest", "jest"
    naming_convention: str = ""  # e.g. "snake_case", "camelCase"

    # Git
    default_branch: str = "main"
    commit_convention: str = ""  # e.g. "conventional-commits"

    # Custom rules (from existing AGENTS.md/.hakus.md)
    existing_rules: List[str] = field(default_factory=list)


class AgentsMdGenerator:
    """Auto-generate AGENTS.md from project analysis.

    Usage::
        gen = AgentsMdGenerator(project_root="/path/to/project")
        intel = gen.analyze()
        content = gen.generate(intel)
        gen.write(content)
    """

    def __init__(self, project_root: str):
        self._root = Path(project_root).resolve()
        self._intel = ProjectIntelligence(name=self._root.name)

    def analyze(self) -> ProjectIntelligence:
        """Run full project analysis and return extracted intelligence."""
        self._detect_language_and_framework()
        self._detect_build_system()
        self._detect_dependencies()
        self._detect_structure()
        self._detect_conventions()
        self._detect_git_conventions()
        self._load_existing_rules()
        return self._intel

    def generate(self, intel: Optional[ProjectIntelligence] = None) -> str:
        """Generate AGENTS.md content from project intelligence."""
        intel = intel or self._intel
        sections = []

        # Header
        sections.append(f"# {intel.name}")
        if intel.description:
            sections.append(f"\n{intel.description}")

        # Tech stack
        tech_items = []
        if intel.language:
            tech_items.append(f"- **Language**: {intel.language}")
        if intel.framework:
            tech_items.append(f"- **Framework**: {intel.framework}")
        if intel.python_version:
            tech_items.append(f"- **Python**: {intel.python_version}")
        if intel.node_version:
            tech_items.append(f"- **Node**: {intel.node_version}")
        if intel.build_tool:
            tech_items.append(f"- **Build**: {intel.build_tool}")
        if tech_items:
            sections.append("\n## Tech Stack\n" + "\n".join(tech_items))

        # Commands
        cmd_items = []
        if intel.dev_command:
            cmd_items.append(f"- **Dev**: `{intel.dev_command}`")
        if intel.build_command:
            cmd_items.append(f"- **Build**: `{intel.build_command}`")
        if intel.test_command:
            cmd_items.append(f"- **Test**: `{intel.test_command}`")
        if intel.lint_command:
            cmd_items.append(f"- **Lint**: `{intel.lint_command}`")
        if intel.format_command:
            cmd_items.append(f"- **Format**: `{intel.format_command}`")
        if cmd_items:
            sections.append("\n## Commands\n" + "\n".join(cmd_items))

        # Project Structure
        struct_items = []
        if intel.src_dirs:
            struct_items.append(f"- **Source**: {', '.join(intel.src_dirs)}")
        if intel.test_dirs:
            struct_items.append(f"- **Tests**: {', '.join(intel.test_dirs)}")
        if intel.entry_points:
            struct_items.append(f"- **Entry points**: {', '.join(intel.entry_points)}")
        if struct_items:
            sections.append("\n## Project Structure\n" + "\n".join(struct_items))

        # Code Conventions
        conv_items = []
        if intel.formatting:
            conv_items.append(f"- **Formatting**: {intel.formatting}")
        if intel.linting:
            conv_items.append(f"- **Linting**: {intel.linting}")
        if intel.testing:
            conv_items.append(f"- **Testing**: {intel.testing}")
        if intel.naming_convention:
            conv_items.append(f"- **Naming**: {intel.naming_convention}")
        if conv_items:
            sections.append("\n## Code Conventions\n" + "\n".join(conv_items))

        # Git Workflow
        git_items = []
        if intel.default_branch:
            git_items.append(f"- **Default branch**: {intel.default_branch}")
        if intel.commit_convention:
            git_items.append(f"- **Commit convention**: {intel.commit_convention}")
        if git_items:
            sections.append("\n## Git Workflow\n" + "\n".join(git_items))

        # Existing rules (preserved from .hakus.md / AGENTS.md)
        if intel.existing_rules:
            sections.append("\n## Project Rules\n" + "\n".join(f"- {r}" for r in intel.existing_rules))

        # Standard HakusAI rules
        sections.append("""
## Agent Instructions
- Use HakusAI tools (Read/Edit/Write/Glob/Grep) instead of cat/grep/find
- Read files before modifying them
- Run tests after making changes if a test command is available
- Follow the project's existing code style and conventions
- Preserve existing formatting — do not reformat unchanged code
""")

        return "\n".join(sections)

    def write(self, content: Optional[str] = None, path: Optional[str] = None) -> str:
        """Write AGENTS.md to the project root.

        Args:
            content: AGENTS.md content (generated if not provided)
            path: Custom path (defaults to <root>/AGENTS.md)

        Returns:
            Path to the written file.
        """
        if content is None:
            content = self.generate()
        target = Path(path) if path else self._root / "AGENTS.md"
        target.write_text(content, encoding="utf-8")
        logger.info(f"AGENTS.md written to {target}")
        return str(target)

    # ------------------------------------------------------------------
    # Detection methods
    # ------------------------------------------------------------------

    def _detect_language_and_framework(self) -> None:
        """Detect primary language and framework."""
        # Python
        if (self._root / "pyproject.toml").exists() or (self._root / "setup.py").exists():
            self._intel.language = "Python"
            self._detect_python_framework()
        elif (self._root / "requirements.txt").exists():
            self._intel.language = "Python"

        # JavaScript/TypeScript
        if (self._root / "package.json").exists():
            self._detect_js_framework()

        # Rust
        if (self._root / "Cargo.toml").exists():
            self._intel.language = "Rust"
            self._intel.framework = self._intel.framework or "Cargo"
            self._intel.build_tool = "cargo"

        # Go
        if (self._root / "go.mod").exists():
            self._intel.language = "Go"
            self._intel.build_tool = "go"

    def _detect_python_framework(self) -> None:
        """Detect Python framework from dependencies."""
        deps = self._read_pyproject_deps() or self._read_requirements()
        dep_set = {d.lower() for d in deps}

        if "fastapi" in dep_set:
            self._intel.framework = "FastAPI"
        elif "django" in dep_set:
            self._intel.framework = "Django"
        elif "flask" in dep_set:
            self._intel.framework = "Flask"
        elif "langchain" in dep_set:
            self._intel.framework = "LangChain"

    def _detect_js_framework(self) -> None:
        """Detect JS/TS framework from package.json."""
        pkg = self._read_json(self._root / "package.json")
        if not pkg:
            self._intel.language = "JavaScript"
            return

        deps = set()
        deps.update(pkg.get("dependencies", {}).keys())
        deps.update(pkg.get("devDependencies", {}).keys())
        deps_lower = {d.lower() for d in deps}

        if "typescript" in deps_lower or (self._root / "tsconfig.json").exists():
            self._intel.language = "TypeScript"
        else:
            self._intel.language = "JavaScript"

        if "next" in deps_lower:
            self._intel.framework = "Next.js"
        elif "react" in deps_lower:
            self._intel.framework = "React"
        elif "vue" in deps_lower:
            self._intel.framework = "Vue"
        elif "svelte" in deps_lower:
            self._intel.framework = "Svelte"
        elif "express" in deps_lower:
            self._intel.framework = "Express"

    def _detect_build_system(self) -> None:
        """Detect build tool and commands."""
        # Python
        if (self._root / "pyproject.toml").exists():
            self._intel.build_tool = self._intel.build_tool or "hatch/poetry/setuptools"
            self._intel.test_command = self._intel.test_command or "pytest"
            # Check for specific tools
            pyproject = self._read_toml(self._root / "pyproject.toml")
            if pyproject:
                # Check for hatch, poetry, setuptools
                if "hatch" in str(pyproject):
                    self._intel.build_tool = "hatch"
                elif "poetry" in str(pyproject):
                    self._intel.build_tool = "poetry"
                else:
                    self._intel.build_tool = "setuptools"

        if (self._root / "Makefile").exists():
            self._intel.build_tool = self._intel.build_tool or "make"

        # JS
        pkg = self._read_json(self._root / "package.json")
        if pkg:
            scripts = pkg.get("scripts", {})
            if "dev" in scripts:
                self._intel.dev_command = f"npm run dev"
            if "build" in scripts:
                self._intel.build_command = f"npm run build"
            if "test" in scripts:
                self._intel.test_command = f"npm run test"
            if "lint" in scripts:
                self._intel.lint_command = f"npm run lint"
            if "format" in scripts:
                self._intel.format_command = f"npm run format"

    def _detect_dependencies(self) -> None:
        """Detect project dependencies."""
        # Python
        pyproject = self._read_toml(self._root / "pyproject.toml")
        if pyproject:
            self._intel.dependencies = self._read_pyproject_deps() or []
            self._intel.dev_dependencies = self._read_pyproject_dev_deps() or []

        # JS
        pkg = self._read_json(self._root / "package.json")
        if pkg:
            self._intel.dependencies = list(pkg.get("dependencies", {}).keys())
            self._intel.dev_dependencies = list(pkg.get("devDependencies", {}).keys())

    def _detect_structure(self) -> None:
        """Detect project directory structure."""
        # Common source directories
        for d in ["src", "lib", "app", "hakus", "pkg", "crate"]:
            if (self._root / d).is_dir():
                self._intel.src_dirs.append(d)

        # Common test directories
        for d in ["tests", "test", "spec", "__tests__", "e2e"]:
            if (self._root / d).is_dir():
                self._intel.test_dirs.append(d)

        # Config files
        for f in ["pyproject.toml", "package.json", "Cargo.toml", "go.mod",
                   "tsconfig.json", ".eslintrc.*", ".prettierrc.*",
                   "Makefile", "Dockerfile", "docker-compose.*"]:
            matches = list(self._root.glob(f)) if "*" in f else [self._root / f]
            for m in matches:
                if m.exists():
                    self._intel.config_files.append(m.name)

        # Entry points
        for f in ["main.py", "app.py", "index.ts", "index.js", "main.rs", "main.go"]:
            for d in ["", "src", "cmd", "bin"]:
                path = self._root / d / f if d else self._root / f
                if path.exists():
                    self._intel.entry_points.append(str(path.relative_to(self._root)))

    def _detect_conventions(self) -> None:
        """Detect code conventions from config files."""
        # Python formatting
        if (self._root / "pyproject.toml").exists():
            content = (self._root / "pyproject.toml").read_text()
            if "black" in content:
                self._intel.formatting = "black"
                self._intel.format_command = self._intel.format_command or "black ."
            if "ruff" in content:
                self._intel.linting = "ruff"
                self._intel.lint_command = self._intel.lint_command or "ruff check ."
            if "isort" in content:
                self._intel.formatting += " + isort" if self._intel.formatting else "isort"
            if "pytest" in content:
                self._intel.testing = "pytest"

        # JS/TS conventions
        if (self._root / ".eslintrc.json").exists() or (self._root / ".eslintrc.js").exists():
            self._intel.linting = "eslint"
        if (self._root / ".prettierrc").exists() or (self._root / ".prettierrc.json").exists():
            self._intel.formatting = self._intel.formatting or "prettier"

        # Naming convention inference from existing files
        py_files = list(self._root.rglob("*.py"))[:20]
        if py_files:
            snake_count = sum(1 for f in py_files if "_" in f.stem and f.stem.islower())
            if snake_count > len(py_files) * 0.5:
                self._intel.naming_convention = "snake_case"

    def _detect_git_conventions(self) -> None:
        """Detect git workflow conventions."""
        try:
            # Default branch
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                capture_output=True, text=True, timeout=5, cwd=str(self._root),
            )
            if result.returncode == 0:
                self._intel.default_branch = result.stdout.strip().split("/")[-1]
        except Exception:
            pass

        # Commit convention (conventional commits check)
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-20"],
                capture_output=True, text=True, timeout=5, cwd=str(self._root),
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                conv_count = sum(
                    1 for l in lines
                    if re.match(r'^[a-f0-9]+ (feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)', l)
                )
                if conv_count > len(lines) * 0.5:
                    self._intel.commit_convention = "conventional-commits"
        except Exception:
            pass

    def _load_existing_rules(self) -> None:
        """Load existing rules from .hakus.md or AGENTS.md."""
        for filename in [".hakus.md", "AGENTS.md", "CLAUDE.md"]:
            path = self._root / filename
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8")
                    # Extract rules (lines starting with -)
                    for line in content.split("\n"):
                        line = line.strip()
                        if line.startswith("- ") and len(line) > 5:
                            self._intel.existing_rules.append(line[2:])
                except Exception as e:
                    logger.warning(f"Failed to read {path}: {e}")

    # ------------------------------------------------------------------
    # File parsers
    # ------------------------------------------------------------------

    def _read_json(self, path: Path) -> Optional[Dict[str, Any]]:
        """Read a JSON file."""
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    def _read_toml(self, path: Path) -> Optional[Dict[str, Any]]:
        """Read a TOML file (basic parser, no external deps)."""
        try:
            if path.exists():
                # Use tomllib if available (Python 3.11+)
                try:
                    import tomllib
                    with open(path, "rb") as f:
                        return tomllib.load(f)
                except ImportError:
                    pass
                # Fallback: use toml package
                try:
                    import toml
                    return toml.load(str(path))
                except ImportError:
                    pass
        except Exception:
            pass
        return None

    def _read_pyproject_deps(self) -> List[str]:
        """Read dependencies from pyproject.toml."""
        data = self._read_toml(self._root / "pyproject.toml")
        if not data:
            return []
        # Poetry format
        try:
            return list(data["tool"]["poetry"]["dependencies"].keys())
        except KeyError:
            pass
        # PEP 621 format
        try:
            return [d.split(">=")[0].split("==")[0].split("[")[0]
                    for d in data["project"]["dependencies"]]
        except KeyError:
            pass
        return []

    def _read_pyproject_dev_deps(self) -> List[str]:
        """Read dev dependencies from pyproject.toml."""
        data = self._read_toml(self._root / "pyproject.toml")
        if not data:
            return []
        # Poetry format
        try:
            return list(data["tool"]["poetry"]["group"]["dev"]["dependencies"].keys())
        except KeyError:
            pass
        # PEP 621 format
        try:
            groups = data["project"]["optional-dependencies"]
            dev = groups.get("dev", []) + groups.get("test", [])
            return [d.split(">=")[0].split("==")[0].split("[")[0] for d in dev]
        except KeyError:
            pass
        return []

    def _read_requirements(self) -> List[str]:
        """Read dependencies from requirements.txt."""
        path = self._root / "requirements.txt"
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").split("\n")
            return [l.split(">=")[0].split("==")[0].split("[")[0]
                    for l in lines if l.strip() and not l.startswith("#")]
        except Exception:
            return []
