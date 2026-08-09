"""Sandbox configuration and result types."""
from __future__ import annotations

import os
import platform
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set


class SandboxBackend(str, Enum):
    """Which sandboxing mechanism to use."""

    SEATBELT = "seatbelt"      # macOS sandbox-exec
    LANDLOCK = "landlock"      # Linux kernel LSM (≥5.13)
    BUBBLEWRAP = "bubblewrap"  # Linux bwrap (namespace-based)
    PROCESS = "process"        # Fallback: restricted subprocess (no kernel enforcement)
    AUTO = "auto"              # Auto-detect best available


class SandboxNetworkPolicy(str, Enum):
    """Network access policy inside sandbox."""

    DENY = "deny"        # No network access
    ALLOW_LOOPBACK = "loopback"  # Only 127.0.0.1
    ALLOW = "allow"      # Full network (use with caution)


@dataclass(frozen=True)
class SandboxResult:
    """Result of a sandboxed command execution."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    sandbox_violation: bool = False
    violation_detail: str = ""
    backend_used: str = ""  # Which SandboxBackend was actually used
    duration_ms: int = 0


@dataclass
class SandboxConfig:
    """Configuration for sandbox isolation.

    Paths are resolved at bind time (when run() is called),
    not at config creation time, to support relative paths.
    """

    # --- Filesystem access ---
    allowed_read_paths: List[str] = field(default_factory=list)
    allowed_write_paths: List[str] = field(default_factory=list)
    allowed_exec_paths: List[str] = field(default_factory=list)

    # Explicit deny patterns (always blocked even if in allowed_*)
    denied_path_patterns: List[str] = field(default_factory=lambda: [
        "*/.ssh/*", "*/.aws/*", "*/.gnupg/*", "*/.env", "*/.env.*",
        "*/credentials*", "*/.pem", "*/.key", "*/.kube/*",
    ])

    # --- Network ---
    network: SandboxNetworkPolicy = SandboxNetworkPolicy.DENY

    # --- Resource limits ---
    max_memory_mb: int = 512
    max_cpu_seconds: int = 60
    max_output_bytes: int = 1_000_000  # 1 MB stdout+stderr
    max_processes: int = 10

    # --- Environment ---
    # Env vars to pass into sandbox (subset of current env)
    allowed_env_vars: List[str] = field(default_factory=lambda: [
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM",
        "PYTHONPATH", "NODE_PATH", "VIRTUAL_ENV",
    ])
    # Extra env vars to inject
    extra_env: Dict[str, str] = field(default_factory=dict)

    # --- Backend selection ---
    backend: SandboxBackend = SandboxBackend.AUTO
    # Working directory inside sandbox (defaults to project root)
    working_dir: Optional[str] = None
    # Temp directory inside sandbox
    temp_dir: Optional[str] = None

    # --- Sandbox-specific ---
    # Bubblewrap: path to bwrap binary
    bwrap_path: str = "/usr/bin/bwrap"
    # Seatbelt: profile template
    seatbelt_profile: Optional[str] = None

    def resolve_paths(self, project_root: str) -> "SandboxConfig":
        """Return a copy with all relative paths resolved against project_root.

        This is called at run() time to support relative path configs.
        """
        root = Path(project_root).resolve()

        def _resolve(paths: List[str]) -> List[str]:
            resolved = []
            for p in paths:
                pp = Path(p)
                if pp.is_absolute():
                    resolved.append(str(pp))
                else:
                    resolved.append(str(root / pp))
            return resolved

        return SandboxConfig(
            allowed_read_paths=_resolve(self.allowed_read_paths),
            allowed_write_paths=_resolve(self.allowed_write_paths),
            allowed_exec_paths=_resolve(self.allowed_exec_paths),
            denied_path_patterns=list(self.denied_path_patterns),
            network=self.network,
            max_memory_mb=self.max_memory_mb,
            max_cpu_seconds=self.max_cpu_seconds,
            max_output_bytes=self.max_output_bytes,
            max_processes=self.max_processes,
            allowed_env_vars=list(self.allowed_env_vars),
            extra_env=dict(self.extra_env),
            backend=self.backend,
            working_dir=self.working_dir or str(root),
            temp_dir=self.temp_dir or tempfile.gettempdir(),
            bwrap_path=self.bwrap_path,
            seatbelt_profile=self.seatbelt_profile,
        )

    def filter_env(self) -> Dict[str, str]:
        """Build the environment dict for sandbox execution.

        Only includes vars listed in allowed_env_vars from the current
        process environment, plus extra_env overrides.
        """
        env = {}
        for key in self.allowed_env_vars:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val
        env.update(self.extra_env)
        return env
