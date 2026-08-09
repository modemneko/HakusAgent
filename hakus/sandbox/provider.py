"""SandboxProvider — auto-detect and delegate to the best available backend.

Detection order (when backend=AUTO):
  1. macOS  → Seatbelt (sandbox-exec, always available)
  2. Linux  → Landlock (kernel ≥5.13, python-landlock)
  3. Linux  → Bubblewrap (bwrap, common on distros with Flatpak)
  4. Fallback → Process (restricted subprocess, no kernel enforcement)

Each backend is a private async method that:
  - Builds the sandbox command/arguments
  - Runs the command via asyncio.create_subprocess_exec
  - Captures stdout/stderr with output size limits
  - Returns a SandboxResult
"""
from __future__ import annotations

import asyncio
import os
import platform
import shutil
import time
from typing import Dict, List, Optional

from utils.logger import get_logger
from .config import SandboxBackend, SandboxConfig, SandboxNetworkPolicy, SandboxResult

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

_LINUX_KERNEL_MIN_LANDLOCK = (5, 13)


def _linux_kernel_version() -> tuple[int, int]:
    """Parse Linux kernel version from uname."""
    try:
        release = platform.release()  # e.g. "6.1.0-13-amd64"
        parts = release.split(".")
        return int(parts[0]), int(parts[1])
    except Exception:
        return (0, 0)


def _has_landlock_python() -> bool:
    """Check if the Python 'landlock' package is importable."""
    try:
        import landlock  # noqa: F401
        return True
    except ImportError:
        return False


def _has_bwrap() -> bool:
    """Check if bwrap binary exists and is executable."""
    return shutil.which("bwrap") is not None


def _has_seatbelt() -> bool:
    """Check if sandbox-exec (macOS Seatbelt) is available."""
    return platform.system() == "Darwin" and shutil.which("sandbox-exec") is not None


def detect_best_backend() -> SandboxBackend:
    """Auto-detect the best available sandbox backend for this system."""
    system = platform.system()

    if system == "Darwin":
        if _has_seatbelt():
            return SandboxBackend.SEATBELT

    if system == "Linux":
        # Prefer Landlock (kernel-level, no external binary needed)
        if _has_landlock_python():
            kv = _linux_kernel_version()
            if kv >= _LINUX_KERNEL_MIN_LANDLOCK:
                return SandboxBackend.LANDLOCK
        # Fall back to bwrap
        if _has_bwrap():
            return SandboxBackend.BUBBLEWRAP

    return SandboxBackend.PROCESS


# ---------------------------------------------------------------------------
# SandboxProvider
# ---------------------------------------------------------------------------


class SandboxProvider:
    """Unified sandbox runner — delegates to the best available backend.

    Usage::

        config = SandboxConfig(
            allowed_read_paths=["/project"],
            allowed_write_paths=["/project/src"],
            network=SandboxNetworkPolicy.DENY,
        )
        provider = SandboxProvider(config)
        result = await provider.run(
            cmd="python3",
            args=["-c", "import os; print(os.listdir('/'))"],
            project_root="/project",
        )
    """

    def __init__(self, config: Optional[SandboxConfig] = None):
        self._config = config or SandboxConfig()
        self._detected_backend: Optional[SandboxBackend] = None

    @property
    def backend(self) -> SandboxBackend:
        """The backend that will be used (lazy-detected on first access)."""
        if self._detected_backend is None:
            if self._config.backend == SandboxBackend.AUTO:
                self._detected_backend = detect_best_backend()
            else:
                self._detected_backend = self._config.backend
        return self._detected_backend

    async def run(
        self,
        cmd: str,
        args: Optional[List[str]] = None,
        *,
        project_root: Optional[str] = None,
        stdin_data: Optional[str] = None,
        timeout: Optional[float] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> SandboxResult:
        """Run a command inside the sandbox.

        Args:
            cmd: The command to execute (must be in allowed_exec_paths).
            args: Command arguments.
            project_root: Project root for resolving relative paths.
            stdin_data: Optional stdin content.
            timeout: Max execution time in seconds (overrides config).
            extra_env: Additional env vars for this invocation only.

        Returns:
            SandboxResult with exit code, stdout, stderr, and metadata.
        """
        args = args or []
        root = project_root or self._config.working_dir or os.getcwd()
        resolved_config = self._config.resolve_paths(root)
        timeout = timeout or resolved_config.max_cpu_seconds

        # Merge extra env
        env = resolved_config.filter_env()
        if extra_env:
            env.update(extra_env)

        backend = self.backend
        t0 = time.monotonic()

        try:
            if backend == SandboxBackend.SEATBELT:
                result = await self._run_seatbelt(cmd, args, resolved_config, env, stdin_data, timeout)
            elif backend == SandboxBackend.LANDLOCK:
                result = await self._run_landlock(cmd, args, resolved_config, env, stdin_data, timeout)
            elif backend == SandboxBackend.BUBBLEWRAP:
                result = await self._run_bwrap(cmd, args, resolved_config, env, stdin_data, timeout)
            else:
                result = await self._run_process(cmd, args, resolved_config, env, stdin_data, timeout)
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - t0) * 1000)
            return SandboxResult(
                exit_code=-1, timed_out=True,
                backend_used=backend.value, duration_ms=elapsed,
                stderr=f"Command timed out after {timeout}s",
            )
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            return SandboxResult(
                exit_code=-1, stderr=str(e),
                backend_used=backend.value, duration_ms=elapsed,
            )

        # Override backend_used
        return SandboxResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=result.timed_out,
            sandbox_violation=result.sandbox_violation,
            violation_detail=result.violation_detail,
            backend_used=backend.value,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    # ------------------------------------------------------------------
    # Seatbelt backend (macOS)
    # ------------------------------------------------------------------

    async def _run_seatbelt(
        self,
        cmd: str,
        args: List[str],
        config: SandboxConfig,
        env: Dict[str, str],
        stdin_data: Optional[str],
        timeout: float,
    ) -> SandboxResult:
        """Run command under macOS sandbox-exec (Seatbelt)."""
        # Build Seatbelt profile
        profile = self._build_seatbelt_profile(config)

        # sandbox-exec -p <profile> <cmd> <args...>
        exec_args = ["sandbox-exec", "-p", profile, cmd] + args

        return await self._exec_subprocess(exec_args, config, env, stdin_data, timeout)

    def _build_seatbelt_profile(self, config: SandboxConfig) -> str:
        """Generate a Seatbelt profile string.

        Seatbelt uses Apple's Sandbox Profile Schema (SBPL-like).
        We generate a simple allowlist-based profile.
        """
        rules = []

        # Deny all by default
        rules.append("(version 1)")
        rules.append("(deny default)")

        # Allow reading from specified paths
        for p in config.allowed_read_paths:
            rules.append(f'(allow file-read* (subpath "{p}"))')

        # Allow writing to specified paths
        for p in config.allowed_write_paths:
            rules.append(f'(allow file-write* (subpath "{p}"))')
            rules.append(f'(allow file-read* (subpath "{p}"))')  # write implies read

        # Allow executing specific binaries
        for p in config.allowed_exec_paths:
            rules.append(f'(allow process-exec (literal "{p}"))')

        # Network policy
        if config.network == SandboxNetworkPolicy.DENY:
            rules.append("(deny network*)")
        elif config.network == SandboxNetworkPolicy.ALLOW_LOOPBACK:
            rules.append("(deny network*)")
            rules.append('(allow network* (local ip "127.0.0.1"))')
        # ALLOW: don't add any network deny rule

        # Allow sysctl and process info (needed for basic operation)
        rules.append("(allow sysctl*)")
        rules.append("(allow process-info*)")

        return "\n".join(rules)

    # ------------------------------------------------------------------
    # Landlock backend (Linux ≥5.13)
    # ------------------------------------------------------------------

    async def _run_landlock(
        self,
        cmd: str,
        args: List[str],
        config: SandboxConfig,
        env: Dict[str, str],
        stdin_data: Optional[str],
        timeout: float,
    ) -> SandboxResult:
        """Run command with Landlock fs isolation.

        Uses the Python 'landlock' package to set up rules before exec.
        Falls back to Process backend if landlock is not available.
        """
        try:
            from landlock import Landlock, AccessFS
        except ImportError:
            logger.warning("landlock package not available, falling back to process isolation")
            return await self._run_process(cmd, args, config, env, stdin_data, timeout)

        # Build Landlock ruleset
        ll = Landlock()
        ll.abi_version = 1  # Use ABI v1 for maximum compatibility

        # Map read/write paths to Landlock access flags
        read_access = (
            AccessFS.READ_FILE | AccessFS.READ_DIR
            | AccessFS.EXECUTE | AccessFS.CHDIR
        )
        write_access = read_access | (
            AccessFS.WRITE_FILE | AccessFS.CREATE_FILE
            | AccessFS.CREATE_DIR | AccessFS.RENAME
            | AccessFS.LINK | AccessFS.TRUNCATE
            | AccessFS.REMOVE_DIR | AccessFS.REMOVE_FILE
        )

        # Add read-only paths
        for p in config.allowed_read_paths:
            try:
                ll.add_path(read_access, p)
            except Exception as e:
                logger.debug(f"Landlock: skipped read path {p}: {e}")

        # Add write paths
        for p in config.allowed_write_paths:
            try:
                ll.add_path(write_access, p)
            except Exception as e:
                logger.debug(f"Landlock: skipped write path {p}: {e}")

        # Restrict self and exec the command
        # Landlock.apply() restricts the current process (and children)
        # We fork+exec via subprocess — Landlock rules persist across fork
        try:
            ll.apply()
        except Exception as e:
            logger.warning(f"Landlock apply failed: {e}, falling back to process isolation")
            return await self._run_process(cmd, args, config, env, stdin_data, timeout)

        # Run the command (Landlock is already active in this process)
        result = await self._exec_subprocess([cmd] + args, config, env, stdin_data, timeout)
        return result

    # ------------------------------------------------------------------
    # Bubblewrap backend (Linux)
    # ------------------------------------------------------------------

    async def _run_bwrap(
        self,
        cmd: str,
        args: List[str],
        config: SandboxConfig,
        env: Dict[str, str],
        stdin_data: Optional[str],
        timeout: float,
    ) -> SandboxResult:
        """Run command under Bubblewrap (bwrap) namespace isolation.

        bwrap creates a new mount namespace with only the specified
        bind mounts visible, providing strong fs isolation without
        requiring kernel LSM support.
        """
        bwrap = config.bwrap_path
        if not shutil.which(bwrap):
            logger.warning(f"bwrap not found at {bwrap}, falling back to process isolation")
            return await self._run_process(cmd, args, config, env, stdin_data, timeout)

        bwrap_args = [bwrap]

        # Mount /usr, /lib, /lib64 read-only (needed for basic binaries)
        for d in ["/usr", "/lib", "/lib64", "/bin", "/sbin"]:
            if os.path.isdir(d):
                bwrap_args.extend(["--ro-bind", d, d])

        # Proc and dev
        bwrap_args.extend(["--proc", "/proc"])
        bwrap_args.extend(["--dev", "/dev"])

        # Mount tmpfs on /tmp
        bwrap_args.extend(["--tmpfs", "/tmp"])

        # Bind project directories
        # Read paths → ro-bind; write paths → bind
        for p in config.allowed_read_paths:
            if os.path.isdir(p):
                bwrap_args.extend(["--ro-bind", p, p])
            elif os.path.isfile(p):
                bwrap_args.extend(["--ro-bind", p, p])

        for p in config.allowed_write_paths:
            if os.path.isdir(p):
                bwrap_args.extend(["--bind", p, p])
            elif os.path.isfile(p):
                bwrap_args.extend(["--bind", p, p])

        # Working directory
        if config.working_dir:
            bwrap_args.extend(["--chdir", config.working_dir])

        # Network policy
        if config.network == SandboxNetworkPolicy.DENY:
            bwrap_args.append("--unshare-net")
        elif config.network == SandboxNetworkPolicy.ALLOW_LOOPBACK:
            # bwrap with --unshare-net + --share-net doesn't work;
            # we deny all and the host loopback is inaccessible
            bwrap_args.append("--unshare-net")

        # Die on parent death
        bwrap_args.append("--die-with-parent")

        # Resource limits via --rlimit-*
        bwrap_args.extend(["--rlimit-as", str(config.max_memory_mb * 1024 * 1024)])
        bwrap_args.extend(["--rlimit-nproc", str(config.max_processes)])

        # Command to execute inside sandbox
        bwrap_args.append("--")
        bwrap_args.append(cmd)
        bwrap_args.extend(args)

        return await self._exec_subprocess(bwrap_args, config, env, stdin_data, timeout)

    # ------------------------------------------------------------------
    # Process fallback (no kernel enforcement)
    # ------------------------------------------------------------------

    async def _run_process(
        self,
        cmd: str,
        args: List[str],
        config: SandboxConfig,
        env: Dict[str, str],
        stdin_data: Optional[str],
        timeout: float,
    ) -> SandboxResult:
        """Run command in a restricted subprocess (best-effort isolation).

        This is the fallback when no kernel-level sandbox is available.
        It provides:
          - Filtered environment variables
          - Resource limits via ulimit (RLIMIT_AS, RLIMIT_CPU, RLIMIT_NPROC)
          - Working directory restriction
          - Output size truncation

        It does NOT provide fs access control — that relies on the
        PermissionChecker to deny dangerous paths before execution.
        """
        return await self._exec_subprocess(
            [cmd] + args, config, env, stdin_data, timeout,
            set_limits=True,
        )

    # ------------------------------------------------------------------
    # Shared subprocess execution
    # ------------------------------------------------------------------

    async def _exec_subprocess(
        self,
        exec_args: List[str],
        config: SandboxConfig,
        env: Dict[str, str],
        stdin_data: Optional[str],
        timeout: float,
        set_limits: bool = False,
    ) -> SandboxResult:
        """Execute a subprocess with output capture and resource limits."""
        import resource

        # Set resource limits if requested (Process fallback)
        preexec_fn = None
        if set_limits:
            def _set_limits():
                try:
                    # Memory limit (RLIMIT_AS)
                    memory_bytes = config.max_memory_mb * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
                except (ValueError, resource.error):
                    pass
                try:
                    # CPU time limit
                    resource.setrlimit(resource.RLIMIT_CPU, (config.max_cpu_seconds, config.max_cpu_seconds))
                except (ValueError, resource.error):
                    pass
                try:
                    # Process count limit
                    resource.setrlimit(resource.RLIMIT_NPROC, (config.max_processes, config.max_processes))
                except (ValueError, resource.error):
                    pass
            preexec_fn = _set_limits

        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_args,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env if env else None,
                cwd=config.working_dir,
                preexec_fn=preexec_fn,
            )
        except FileNotFoundError as e:
            return SandboxResult(
                exit_code=127,
                stderr=f"Command not found: {exec_args[0]} ({e})",
                backend_used=config.backend.value,
            )
        except PermissionError as e:
            return SandboxResult(
                exit_code=126,
                stderr=f"Permission denied: {exec_args[0]} ({e})",
                sandbox_violation=True,
                violation_detail=str(e),
                backend_used=config.backend.value,
            )

        # Write stdin and wait for completion
        try:
            stdout, stderr = await asyncio.wait_for(
                self._communicate_with_limit(proc, stdin_data, config.max_output_bytes),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(
                exit_code=-1, timed_out=True,
                backend_used=config.backend.value,
                stderr=f"Timed out after {timeout}s",
            )

        exit_code = await proc.wait()

        # Check for sandbox violations in stderr (Seatbelt/bwrap report them)
        violation = False
        violation_detail = ""
        if "sandbox-violation" in stderr.lower() or "landlock" in stderr.lower():
            violation = True
            violation_detail = stderr[:500]

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            sandbox_violation=violation,
            violation_detail=violation_detail,
            backend_used=config.backend.value,
        )

    async def _communicate_with_limit(
        self,
        proc: asyncio.subprocess.Process,
        stdin_data: Optional[str],
        max_bytes: int,
    ) -> tuple[str, str]:
        """Communicate with subprocess, truncating output at max_bytes."""
        if stdin_data:
            proc.stdin.write(stdin_data.encode())
            proc.stdin.close()

        # Read stdout and stderr with size limits
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        stdout_total = 0
        stderr_total = 0

        async def _read_stream(stream, chunks, total_ref):
            while True:
                chunk = await stream.read(8192)
                if not chunk:
                    break
                if total_ref + len(chunk) <= max_bytes:
                    chunks.append(chunk)
                    total_ref += len(chunk)
                elif total_ref < max_bytes:
                    remaining = max_bytes - total_ref
                    chunks.append(chunk[:remaining])
                    total_ref = max_bytes
                # else: discard overflow
            return total_ref

        stdout_total = await _read_stream(proc.stdout, stdout_chunks, stdout_total)
        stderr_total = await _read_stream(proc.stderr, stderr_chunks, stderr_total)

        stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")

        if stdout_total >= max_bytes:
            stdout += "\n...[output truncated at max_output_bytes]"
        if stderr_total >= max_bytes:
            stderr += "\n...[stderr truncated at max_output_bytes]"

        return stdout, stderr

    # ------------------------------------------------------------------
    # Convenience: check sandbox availability
    # ------------------------------------------------------------------

    @staticmethod
    def check_availability() -> Dict[str, bool]:
        """Check which sandbox backends are available on this system."""
        return {
            "seatbelt": _has_seatbelt(),
            "landlock": _has_landlock_python() and _linux_kernel_version() >= _LINUX_KERNEL_MIN_LANDLOCK,
            "bubblewrap": _has_bwrap(),
            "process": True,  # Always available (fallback)
        }


# Type alias for import convenience
from typing import Dict  # noqa: E402 (already imported above, but re-ensure)
