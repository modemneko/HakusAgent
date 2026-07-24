"""
Shell 执行工具 - 借鉴 OpenCode 的 Bash 设计
提供安全的命令执行能力
"""

import asyncio
import subprocess
import shlex
import sys
from typing import Optional
from ....schema.models import ToolDefinition, ToolResult
from ....schema.errors import ToolError


def _decode_process_output(data: bytes) -> str:
    """Decode subprocess output robustly across platforms.

    Windows Chinese editions default to GBK (cp936) for legacy console
    applications, while macOS/Linux typically use UTF-8. We try UTF-8 first,
    then fall back to platform-appropriate legacy encodings to avoid the
    diamond-question-mark mojibake that made the agent hallucinate errors.
    """
    if not data:
        return ""

    # Try UTF-8 first — preferred on modern systems.
    try:
        text = data.decode('utf-8')
        # If it decoded cleanly and has no replacement characters, use it.
        if '\ufffd' not in text:
            return text
    except UnicodeDecodeError:
        pass

    if sys.platform == 'win32':
        for enc in ('gbk', 'gb2312', 'cp936'):
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue

    # Final fallback: UTF-8 with replacement characters.
    return data.decode('utf-8', errors='replace')


class BashTool:
    """Shell 执行工具"""
    
    definition = ToolDefinition(
        name="bash",
        description="Execute a shell command",
        parameters={
            "command": {"type": "string", "description": "Command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120)"},
            "workdir": {"type": "string", "description": "Working directory"},
        },
        required=["command"],
        category="shell",
    )
    
    @staticmethod
    async def execute(
        command: str,
        timeout: int = 120,
        workdir: Optional[str] = None,
    ) -> ToolResult:
        """执行命令"""
        try:
            # 安全检查
            dangerous_commands = ["rm -rf /", "mkfs", "dd if=", "> /dev/sda"]
            for dangerous in dangerous_commands:
                if dangerous in command:
                    return ToolResult(
                        success=False,
                        error=f"Dangerous command detected: {dangerous}"
                    )
            
            # 根据平台选择 shell
            if sys.platform == "win32":
                shell_cmd = ["cmd", "/c", command]
            else:
                shell_cmd = ["bash", "-c", command]
            
            # 执行命令
            process = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {timeout} seconds"
                )
            
            # 解码输出（处理 Windows 中文编码）
            stdout_str = _decode_process_output(stdout)
            stderr_str = _decode_process_output(stderr)
            
            # 截断过长的输出
            max_output = 10000
            if len(stdout_str) > max_output:
                stdout_str = stdout_str[:max_output] + "\n... (truncated)"
            if len(stderr_str) > max_output:
                stderr_str = stderr_str[:max_output] + "\n... (truncated)"
            
            # 组合输出
            output = ""
            if stdout_str:
                output += stdout_str
            if stderr_str:
                output += f"\n[stderr]\n{stderr_str}" if output else stderr_str
            
            return ToolResult(
                success=process.returncode == 0,
                output=output or "(no output)",
                metadata={
                    "command": command,
                    "return_code": process.returncode,
                    "workdir": workdir,
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class PowerShellTool:
    """PowerShell 执行工具"""
    
    definition = ToolDefinition(
        name="powershell",
        description="Execute a PowerShell command",
        parameters={
            "command": {"type": "string", "description": "PowerShell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120)"},
        },
        required=["command"],
        category="shell",
    )
    
    @staticmethod
    async def execute(
        command: str,
        timeout: int = 120,
    ) -> ToolResult:
        """执行 PowerShell 命令"""
        try:
            process = await asyncio.create_subprocess_exec(
                "powershell", "-Command", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {timeout} seconds"
                )
            
            stdout_str = _decode_process_output(stdout)
            stderr_str = _decode_process_output(stderr)
            
            output = ""
            if stdout_str:
                output += stdout_str
            if stderr_str:
                output += f"\n[stderr]\n{stderr_str}" if output else stderr_str
            
            return ToolResult(
                success=process.returncode == 0,
                output=output or "(no output)",
                metadata={
                    "command": command,
                    "return_code": process.returncode,
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))