"""Local file tools: ReadFile, WriteFile, EditFile, and extended file operations."""
from __future__ import annotations

import asyncio
import datetime
import mimetypes
import os
import re
import shutil
import stat
from typing import Any, Dict, List

from ..base import Tool

# Optional chardet for encoding detection
try:
    import chardet
    _HAS_CHARDET = True
except ImportError:
    _HAS_CHARDET = False


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

_BINARY_EXTENSIONS: Dict[str, str] = {
    ".png": "PNG Image",
    ".jpg": "JPEG Image",
    ".jpeg": "JPEG Image",
    ".gif": "GIF Image",
    ".bmp": "BMP Image",
    ".ico": "ICO Image",
    ".webp": "WebP Image",
    ".svg": "SVG Image",
    ".pdf": "PDF Document",
    ".doc": "Word Document",
    ".docx": "Word Document",
    ".xls": "Excel Spreadsheet",
    ".xlsx": "Excel Spreadsheet",
    ".ppt": "PowerPoint Presentation",
    ".pptx": "PowerPoint Presentation",
    ".zip": "ZIP Archive",
    ".rar": "RAR Archive",
    ".7z": "7-Zip Archive",
    ".tar": "TAR Archive",
    ".gz": "GZIP Archive",
    ".bz2": "BZIP2 Archive",
    ".exe": "Windows Executable",
    ".dll": "Windows DLL",
    ".so": "Shared Library",
    ".pyc": "Python Bytecode",
    ".class": "Java Class File",
    ".mp3": "MP3 Audio",
    ".mp4": "MP4 Video",
    ".avi": "AVI Video",
    ".mov": "QuickTime Video",
    ".wav": "WAV Audio",
    ".flac": "FLAC Audio",
    ".sqlite": "SQLite Database",
    ".db": "Database File",
}


def _is_binary(data: bytes) -> bool:
    """Check if data looks binary by scanning for null bytes."""
    return b"\x00" in data


def _detect_encoding(raw: bytes) -> str:
    """Detect text encoding from raw bytes.

    Strategy: chardet (if available) → utf-8 → gbk → latin-1.
    """
    if _HAS_CHARDET:
        try:
            result = chardet.detect(raw)
            if result and result.get("encoding"):
                return result["encoding"]
        except Exception:
            pass
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


def _human_size(size: int) -> str:
    """Return human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _format_line_numbers(lines: List[str], start: int = 1) -> str:
    """Format lines with right-aligned line numbers."""
    max_line = start + len(lines) - 1
    width = len(str(max_line))
    result = []
    for i, line in enumerate(lines):
        # Strip the trailing newline for formatting, then add it back
        stripped = line.rstrip("\n")
        result.append(f"{start + i:>{width}}→{stripped}")
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Enhanced ReadFile
# ---------------------------------------------------------------------------

class ReadFile(Tool):
    name = "read_file"
    description = "Read the contents of a local file. Supports line ranges, auto encoding detection, and binary file detection."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file to read."},
            "offset": {"type": "integer", "description": "Line number to start reading from (1-based)."},
            "limit": {"type": "integer", "description": "Maximum number of lines to return."},
            "show_line_numbers": {"type": "boolean", "description": "Show line numbers in output (default True)."},
        },
        "required": ["path"],
    }
    is_concurrency_safe = True
    is_dangerous = False
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = ['read-only']

    async def execute(self, path: str, offset: int = 1, limit: int = 500,
                      show_line_numbers: bool = True, **kwargs) -> str:
        try:
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            if not os.path.isfile(path):
                return f"Error: Not a regular file: {path}"
            return await asyncio.to_thread(self._read, path, offset, limit, show_line_numbers)
        except Exception as e:
            return f"Error reading file: {e}"

    @staticmethod
    def _read(path: str, offset: int, limit: int, show_line_numbers: bool) -> str:
        file_size = os.path.getsize(path)

        # Binary file detection
        with open(path, "rb") as f:
            head = f.read(8192)
        if _is_binary(head):
            ext = os.path.splitext(path)[1].lower()
            type_hint = _BINARY_EXTENSIONS.get(ext, "Binary File")
            return f"Binary file: {path} ({_human_size(file_size)}, {type_hint})"

        # Encoding detection
        with open(path, "rb") as f:
            raw = f.read()
        encoding = _detect_encoding(raw)

        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            text = raw.decode("latin-1")

        lines = text.splitlines(keepends=True)

        # Build header
        header_parts: List[str] = []
        if file_size > 1 * 1024 * 1024:
            header_parts.append(f"[WARNING: File is large ({_human_size(file_size)})]")
        if encoding.lower() not in ("utf-8", "ascii"):
            header_parts.append(f"[Detected encoding: {encoding}]")

        start = max(1, offset) - 1
        end = start + max(1, limit)
        selected = lines[start:end]

        if not selected:
            return "\n".join(header_parts) + "\n(empty file or no lines in range)" if header_parts else "(empty file or no lines in range)"

        if show_line_numbers:
            content = _format_line_numbers(selected, start=start + 1)
        else:
            content = "".join(selected)

        if header_parts:
            return "\n".join(header_parts) + "\n" + content
        return content


# ---------------------------------------------------------------------------
# WriteFile (unchanged logic, kept for completeness)
# ---------------------------------------------------------------------------

class WriteFile(Tool):
    name = "write_file"
    description = "Create or overwrite a local file with the given content."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file to write."},
            "content": {"type": "string", "description": "The full content to write to the file."},
        },
        "required": ["path", "content"],
    }
    is_concurrency_safe = False
    is_dangerous = True
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = []

    async def execute(self, path: str, content: str, **kwargs) -> str:
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            return await asyncio.to_thread(self._write, path, content)
        except Exception as e:
            return f"Error writing file: {e}"

    @staticmethod
    def _write(path: str, content: str) -> str:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} characters to {path}"


# ---------------------------------------------------------------------------
# Enhanced EditFile
# ---------------------------------------------------------------------------

class EditFile(Tool):
    name = "edit_file"
    description = "Edit a local file by finding and replacing text. Supports regex, replace_all, and dry_run modes."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file to edit."},
            "old_str": {"type": "string", "description": "The text to find (or regex pattern if regex=True)."},
            "new_str": {"type": "string", "description": "The text to replace it with."},
            "dry_run": {"type": "boolean", "description": "If True, show what would change without modifying the file."},
            "replace_all": {"type": "boolean", "description": "If True, replace ALL occurrences instead of requiring a unique match."},
            "regex": {"type": "boolean", "description": "If True, treat old_str as a regex pattern."},
        },
        "required": ["path", "old_str", "new_str"],
    }
    is_concurrency_safe = False
    is_dangerous = True
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = []

    async def execute(self, path: str, old_str: str, new_str: str,
                      dry_run: bool = False, replace_all: bool = False,
                      regex: bool = False, **kwargs) -> str:
        try:
            return await asyncio.to_thread(
                self._edit, path, old_str, new_str, dry_run, replace_all, regex
            )
        except Exception as e:
            return f"Error editing file: {e}"

    @staticmethod
    def _edit(path: str, old_str: str, new_str: str,
              dry_run: bool, replace_all: bool, regex: bool) -> str:
        if not os.path.exists(path):
            return f"Error: File not found: {path}"

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.splitlines()

        # --- Find matches ---
        if regex:
            try:
                pattern = re.compile(old_str)
            except re.error as e:
                return f"Error: Invalid regex pattern: {e}"
            matches = list(pattern.finditer(content))
            if not matches:
                # Provide line number hints
                for i, line in enumerate(lines, 1):
                    if pattern.search(line):
                        return f"Error: Regex pattern not found in {path}. (Pattern partially matches line {i}, but not in full content context)"
                return f"Error: Regex pattern not found in {path}"
        else:
            count = content.count(old_str)
            if count == 0:
                # Provide line number hints
                for i, line in enumerate(lines, 1):
                    if old_str.strip() and old_str.strip() in line:
                        return (f"Error: Search text not found in {path}. "
                                f"(Similar text found on line {i} — check whitespace/exact match)")
                return f"Error: Search text not found in {path}"
            if not replace_all and count > 1:
                # Show all line numbers where it appears
                found_lines = []
                for i, line in enumerate(lines, 1):
                    if old_str in line:
                        found_lines.append(i)
                return (f"Error: Search text appears {count} times in {path} "
                        f"(lines {found_lines}); provide more context to make it unique, "
                        f"or set replace_all=True.")
            matches = None  # literal replacement uses str.replace

        # --- Perform replacement ---
        if regex:
            if replace_all:
                new_content = pattern.sub(new_str, content)
                replacement_count = len(matches)
            else:
                if len(matches) > 1:
                    return (f"Error: Regex pattern matches {len(matches)} times in {path}; "
                            f"set replace_all=True to replace all, or make the pattern more specific.")
                new_content = pattern.sub(new_str, content, count=1)
                replacement_count = 1
        else:
            if replace_all:
                new_content = content.replace(old_str, new_str)
                replacement_count = count
            else:
                new_content = content.replace(old_str, new_str, 1)
                replacement_count = 1

        if new_content == content:
            return f"Error: Replacement produced no changes in {path}"

        # --- Dry run: show diff preview ---
        if dry_run:
            old_lines = content.splitlines()
            new_lines = new_content.splitlines()
            preview_lines = []
            max_preview = 50
            for i, (o, n) in enumerate(zip(old_lines, new_lines)):
                if o != n:
                    preview_lines.append(f"  Line {i + 1}:")
                    preview_lines.append(f"    - {o}")
                    preview_lines.append(f"    + {n}")
                if len(preview_lines) >= max_preview:
                    preview_lines.append(f"  ... (more changes, truncated)")
                    break
            # Check for added/deleted lines at the end
            if len(new_lines) > len(old_lines):
                preview_lines.append(f"  +{len(new_lines) - len(old_lines)} line(s) added at end")
            elif len(old_lines) > len(new_lines):
                preview_lines.append(f"  -{len(old_lines) - len(new_lines)} line(s) removed at end")

            header = f"[DRY RUN] Would make {replacement_count} replacement(s) in {path}:"
            return header + "\n" + "\n".join(preview_lines)

        # --- Write the file ---
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"Successfully edited {path} ({replacement_count} replacement(s))"


# ---------------------------------------------------------------------------
# MultiEditFile
# ---------------------------------------------------------------------------

class MultiEditFile(Tool):
    name = "multi_edit_file"
    description = "Apply multiple find-and-replace edits to a file in one operation."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file to edit."},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_str": {"type": "string", "description": "Text to find."},
                        "new_str": {"type": "string", "description": "Text to replace with."},
                    },
                    "required": ["old_str", "new_str"],
                },
                "description": "Array of {old_str, new_str} edit objects to apply sequentially.",
            },
        },
        "required": ["path", "edits"],
    }
    is_concurrency_safe = False
    is_dangerous = True
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = []

    async def execute(self, path: str, edits: List[Dict[str, str]], **kwargs) -> str:
        try:
            return await asyncio.to_thread(self._multi_edit, path, edits)
        except Exception as e:
            return f"Error in multi_edit: {e}"

    @staticmethod
    def _multi_edit(path: str, edits: List[Dict[str, str]]) -> str:
        if not os.path.exists(path):
            return f"Error: File not found: {path}"

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        results: List[str] = []
        for i, edit in enumerate(edits):
            old_str = edit.get("old_str", "")
            new_str = edit.get("new_str", "")
            if not old_str:
                results.append(f"  Edit {i + 1}: Skipped (empty old_str)")
                continue
            count = content.count(old_str)
            if count == 0:
                results.append(f"  Edit {i + 1}: Not found")
                continue
            if count > 1:
                results.append(f"  Edit {i + 1}: Found {count} times, replacing all")
                content = content.replace(old_str, new_str)
            else:
                content = content.replace(old_str, new_str, 1)
                results.append(f"  Edit {i + 1}: Replaced (1 occurrence)")

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Multi-edit applied to {path}:\n" + "\n".join(results)


# ---------------------------------------------------------------------------
# MoveFile
# ---------------------------------------------------------------------------

class MoveFile(Tool):
    name = "move_file"
    description = "Move or rename a file or directory."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path."},
            "destination": {"type": "string", "description": "Destination path."},
        },
        "required": ["source", "destination"],
    }
    is_concurrency_safe = False
    is_dangerous = True
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = []

    async def execute(self, source: str, destination: str, **kwargs) -> str:
        try:
            return await asyncio.to_thread(self._move, source, destination)
        except Exception as e:
            return f"Error moving file: {e}"

    @staticmethod
    def _move(source: str, destination: str) -> str:
        if not os.path.exists(source):
            return f"Error: Source not found: {source}"
        dest_parent = os.path.dirname(destination)
        if dest_parent:
            os.makedirs(dest_parent, exist_ok=True)
        try:
            shutil.move(source, destination)
        except shutil.Error as e:
            return f"Error: {e}"
        return f"Successfully moved {source} → {destination}"


# ---------------------------------------------------------------------------
# CopyFile
# ---------------------------------------------------------------------------

class CopyFile(Tool):
    name = "copy_file"
    description = "Copy a file or directory."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path."},
            "destination": {"type": "string", "description": "Destination path."},
        },
        "required": ["source", "destination"],
    }
    is_concurrency_safe = True
    is_dangerous = False
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = ['read-only']

    async def execute(self, source: str, destination: str, **kwargs) -> str:
        try:
            return await asyncio.to_thread(self._copy, source, destination)
        except Exception as e:
            return f"Error copying file: {e}"

    @staticmethod
    def _copy(source: str, destination: str) -> str:
        if not os.path.exists(source):
            return f"Error: Source not found: {source}"
        dest_parent = os.path.dirname(destination)
        if dest_parent:
            os.makedirs(dest_parent, exist_ok=True)
        if os.path.isdir(source):
            shutil.copytree(source, destination)
            return f"Successfully copied directory {source} → {destination}"
        else:
            shutil.copy2(source, destination)
            return f"Successfully copied {source} → {destination}"


# ---------------------------------------------------------------------------
# DeleteFile
# ---------------------------------------------------------------------------

class DeleteFile(Tool):
    name = "delete_file"
    description = "Delete a file or empty directory. Non-empty directories require explicit confirmation."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to delete."},
        },
        "required": ["path"],
    }
    is_concurrency_safe = False
    is_dangerous = True
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = []

    async def execute(self, path: str, **kwargs) -> str:
        try:
            return await asyncio.to_thread(self._delete, path)
        except Exception as e:
            return f"Error deleting file: {e}"

    @staticmethod
    def _delete(path: str) -> str:
        if not os.path.exists(path):
            return f"Error: Path not found: {path}"
        if os.path.isfile(path):
            os.remove(path)
            return f"Successfully deleted file: {path}"
        if os.path.isdir(path):
            # Check if directory is empty
            contents = os.listdir(path)
            if contents:
                # Non-empty directory — use rmtree with warning
                shutil.rmtree(path)
                return (f"Successfully deleted non-empty directory: {path} "
                        f"(contained {len(contents)} item(s))")
            else:
                os.rmdir(path)
                return f"Successfully deleted empty directory: {path}"
        return f"Error: Unknown file type: {path}"


# ---------------------------------------------------------------------------
# FileStat
# ---------------------------------------------------------------------------

class FileStat(Tool):
    name = "file_stat"
    description = "Get detailed metadata about a file or directory (size, timestamps, permissions, type)."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to inspect."},
        },
        "required": ["path"],
    }
    is_concurrency_safe = True
    is_dangerous = False
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = ['read-only']

    async def execute(self, path: str, **kwargs) -> str:
        try:
            return await asyncio.to_thread(self._stat, path)
        except Exception as e:
            return f"Error getting file stats: {e}"

    @staticmethod
    def _stat(path: str) -> str:
        if not os.path.exists(path):
            return f"Error: Path not found: {path}"

        st = os.stat(path)
        is_file = os.path.isfile(path)
        is_dir = os.path.isdir(path)

        # Timestamps
        created = datetime.datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        modified = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        accessed = datetime.datetime.fromtimestamp(st.st_atime).strftime("%Y-%m-%d %H:%M:%S")

        # Permissions
        perms = oct(stat.S_IMODE(st.st_mode))

        # Extension and MIME type
        _, ext = os.path.splitext(path)
        mime_type, _ = mimetypes.guess_type(path)

        lines = [
            f"Path:         {path}",
            f"Type:         {'File' if is_file else 'Directory' if is_dir else 'Other'}",
            f"Size:         {_human_size(st.st_size)} ({st.st_size} bytes)",
            f"Created:      {created}",
            f"Modified:     {modified}",
            f"Accessed:     {accessed}",
            f"Permissions:  {perms}",
        ]
        if ext:
            lines.append(f"Extension:    {ext}")
        if mime_type:
            lines.append(f"MIME Type:    {mime_type}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ReadMultipleFiles
# ---------------------------------------------------------------------------

class ReadMultipleFiles(Tool):
    name = "read_multiple_files"
    description = "Read the contents of multiple files at once. Returns each file's content with a header."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of absolute file paths to read.",
            },
            "max_lines_per_file": {
                "type": "integer",
                "description": "Maximum number of lines to read per file (default 500).",
            },
        },
        "required": ["paths"],
    }
    is_concurrency_safe = True
    is_dangerous = False
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = ['read-only']

    async def execute(self, paths: List[str], max_lines_per_file: int = 500, **kwargs) -> str:
        try:
            return await asyncio.to_thread(self._read_multiple, paths, max_lines_per_file)
        except Exception as e:
            return f"Error reading multiple files: {e}"

    @staticmethod
    def _read_multiple(paths: List[str], max_lines_per_file: int) -> str:
        results: List[str] = []
        for p in paths:
            if not os.path.exists(p):
                results.append(f"=== {p} ===\nError: File not found")
                continue
            if not os.path.isfile(p):
                results.append(f"=== {p} ===\nError: Not a regular file")
                continue
            # Binary check
            with open(p, "rb") as f:
                head = f.read(8192)
            if _is_binary(head):
                ext = os.path.splitext(p)[1].lower()
                type_hint = _BINARY_EXTENSIONS.get(ext, "Binary File")
                file_size = os.path.getsize(p)
                results.append(f"=== {p} ===\nBinary file: {_human_size(file_size)}, {type_hint}")
                continue
            # Read with encoding detection
            with open(p, "rb") as f:
                raw = f.read()
            encoding = _detect_encoding(raw)
            try:
                text = raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                text = raw.decode("latin-1")
            lines = text.splitlines(keepends=True)
            selected = lines[:max_lines_per_file]
            content = _format_line_numbers(selected, start=1)
            if len(lines) > max_lines_per_file:
                content += f"\n... ({len(lines) - max_lines_per_file} more lines)"
            results.append(f"=== {p} ===\n{content}")
        return "\n\n".join(results)


# ---------------------------------------------------------------------------
# CreateDirectory
# ---------------------------------------------------------------------------

class CreateDirectory(Tool):
    name = "create_directory"
    description = "Create a directory and any necessary parent directories."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to create."},
        },
        "required": ["path"],
    }
    is_concurrency_safe = False
    is_dangerous = False
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = []

    async def execute(self, path: str, **kwargs) -> str:
        try:
            return await asyncio.to_thread(self._create, path)
        except Exception as e:
            return f"Error creating directory: {e}"

    @staticmethod
    def _create(path: str) -> str:
        os.makedirs(path, exist_ok=True)
        return f"Successfully created directory: {path}"


# ---------------------------------------------------------------------------
# AppendFile
# ---------------------------------------------------------------------------

class AppendFile(Tool):
    name = "append_file"
    description = "Append content to an existing file (or create it if it doesn't exist)."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file."},
            "content": {"type": "string", "description": "Content to append."},
        },
        "required": ["path", "content"],
    }
    is_concurrency_safe = False
    is_dangerous = True
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "filesystem"
    tags: list = []

    async def execute(self, path: str, content: str, **kwargs) -> str:
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            return await asyncio.to_thread(self._append, path, content)
        except Exception as e:
            return f"Error appending to file: {e}"

    @staticmethod
    def _append(path: str, content: str) -> str:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully appended {len(content)} characters to {path}"
