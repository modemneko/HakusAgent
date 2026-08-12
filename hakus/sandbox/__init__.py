"""Sandbox isolation for tool execution.

Three-layer sandbox strategy (inspired by Codex Exec Server):

1. **Seatbelt** (macOS) — Apple's built-in sandboxing via sandbox-exec
2. **Landlock** (Linux ≥5.13) — kernel-level fs access control via landlock LSM
3. **Bubblewrap** (Linux) — namespace-based isolation via bwrap (Flatpak)

Fallback: if none available, runs with restricted PATH + dropped env vars
(best-effort isolation, no kernel enforcement).

Usage:
    from hakus.sandbox import SandboxProvider, SandboxConfig

    config = SandboxConfig(
        allowed_read_paths=["/project/src"],
        allowed_write_paths=["/project/src", "/tmp/hakus"],
        allowed_exec_paths=["/usr/bin/python3", "/usr/bin/node"],
        network=False,
    )
    provider = SandboxProvider(config)
    result = await provider.run("python3", ["-c", "print('hello')"])
"""
from .config import SandboxConfig, SandboxResult
from .provider import SandboxProvider

__all__ = ["SandboxConfig", "SandboxResult", "SandboxProvider"]
