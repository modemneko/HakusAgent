#!/usr/bin/env python3
"""
HakusAgent sidecar PyInstaller hidden-imports scanner.

Goal: Walk the source tree, extract every top-level third-party module
referenced via `import` / `from ... import`, drop stdlib + first-party
packages, and produce a ready-to-paste `hiddenimports=[...]` list for
the PyInstaller .spec file.

This is a STATIC scan only. It does NOT execute the code, so it cannot
catch dynamic imports done via importlib / __import__ / pkgutil. Those
must be cross-checked with a runtime import smoke test.

Usage:
    python scan_imports.py /path/to/HakusAgent/src
"""

from __future__ import annotations

import ast
import os
import sys
import sysconfig
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# First-party packages that should NOT be in hiddenimports (they are part of
# the project itself and bundled as source by PyInstaller).
# ---------------------------------------------------------------------------
FIRST_PARTY = {
    "hakusai_server",
    "hakusai_core",
    "hakus",
    "hakusai",
    "tests",
}


# ---------------------------------------------------------------------------
# Known stdlib top-level modules (Python 3.11+). Generated from
# sys.stdlib_module_names when run on a 3.11+ interpreter; we hardcode the
# common subset so the script also works on 3.10.
# ---------------------------------------------------------------------------
STDLIB = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else {
    "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio",
    "asyncore", "atexit", "audioop", "base64", "bdb", "binascii", "binhex",
    "bisect", "builtins", "bz2", "cProfile", "calendar", "cgi", "cgitb",
    "chunk", "cmath", "cmd", "code", "codecs", "codeop", "collections",
    "colorsys", "compileall", "concurrent", "configparser", "contextlib",
    "contextvars", "copy", "copyreg", "crypt", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis", "distutils",
    "doctest", "email", "encodings", "ensurepip", "enum", "errno", "faulthandler",
    "fcntl", "filecmp", "fileinput", "fnmatch", "fractions", "ftplib",
    "functools", "gc", "genericpath", "getopt", "getpass", "gettext", "glob",
    "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect", "io",
    "ipaddress", "itertools", "json", "keyword", "lib2to3", "linecache",
    "locale", "logging", "lzma", "mailbox", "mailcap", "marshal", "math",
    "mimetypes", "mmap", "modulefinder", "multiprocessing", "netrc", "nis",
    "nntplib", "ntpath", "numbers", "opcode", "operator", "optparse", "os",
    "ossaudiodev", "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil",
    "platform", "plistlib", "poplib", "posix", "posixpath", "pprint", "profile",
    "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc", "pydoc_data",
    "pyexpat", "queue", "quopri", "random", "re", "readline", "reprlib",
    "resource", "rlcompleter", "runpy", "sched", "secrets", "select", "selectors",
    "shelve", "shlex", "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr",
    "socket", "socketserver", "spwd", "sqlite3", "sre_compile", "sre_constants",
    "sre_parse", "ssl", "stat", "statistics", "string", "stringprep", "struct",
    "subprocess", "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny",
    "tarfile", "telnetlib", "tempfile", "termios", "test", "textwrap", "threading",
    "time", "timeit", "tkinter", "token", "tokenize", "tomllib", "trace",
    "traceback", "tracemalloc", "tty", "turtle", "turtledemo", "types",
    "typing", "unicodedata", "unittest", "urllib", "uu", "uuid", "venv",
    "warnings", "wave", "weakref", "webbrowser", "winreg", "winsound", "wsgiref",
    "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    "zoneinfo", "__future__", "_thread", "_abc", "_aix_support", "_ast",
    "_asyncio", "_bisect", "_blake2", "_bootsubprocess", "_bz2", "_codecs",
    "_collections", "_compat_pickle", "_compression", "_contextvars",
    "_crypt", "_csv", "_ctypes", "_curses", "_datetime", "_dbm", "_decimal",
    "_elementtree", "_functools", "_gdbm", "_hashlib", "_heapq", "_imp",
    "_io", "_json", "_locale", "_lsprof", "_lzma", "_markupbase", "_md5",
    "_msi", "_multibytecodec", "_multiprocessing", "_opcode", "_operator",
    "_osx_support", "_overlapped", "_pickle", "_posixshmem", "_posixsubprocess",
    "_py_abc", "_pydecimal", "_pyio", "_queue", "_random", "_scproxy",
    "_sha1", "_sha256", "_sha3", "_sha512", "_signal", "_sitebuiltins",
    "_socket", "_sqlite3", "_sre", "_ssl", "_stat", "_statistics", "_string",
    "_strptime", "_struct", "_symtable", "_thread", "_threading_local",
    "_tracemalloc", "_uuid", "_warnings", "_weakref", "_weakrefset",
    "_winapi", "_xxsubinterpreters", "_zoneinfo",
}


def extract_top_level_modules(tree: ast.AST) -> set[str]:
    """Return set of top-level module names referenced in `tree`."""
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # absolute import only
                mods.add(node.module.split(".")[0])
    return mods


def scan_file(path: Path) -> set[str]:
    """Parse a single .py file and return its top-level imports."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"  ! parse error in {path}: {e}", file=sys.stderr)
        return set()
    return extract_top_level_modules(tree)


def scan_tree(roots: Iterable[Path]) -> set[str]:
    """Walk all .py files under each root and accumulate imports."""
    all_mods: set[str] = set()
    for root in roots:
        if not root.exists():
            print(f"  ! root not found: {root}", file=sys.stderr)
            continue
        for py in root.rglob("*.py"):
            mods = scan_file(py)
            all_mods |= mods
            if mods:
                rel = py.relative_to(root)
                third = sorted(m for m in mods
                               if m not in STDLIB and m not in FIRST_PARTY
                               and not m.startswith("_"))
                if third:
                    print(f"  {rel}: {third}")
    return all_mods


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    roots = [Path(a).resolve() for a in argv[1:]]
    print(f"==> Scanning roots: {[str(r) for r in roots]}")
    all_mods = scan_tree(roots)

    third_party = sorted(
        m for m in all_mods
        if m and m not in STDLIB and m not in FIRST_PARTY
        and not m.startswith("_")
    )

    print()
    print("==> Third-party top-level modules found:")
    for m in third_party:
        print(f"    {m}")

    print()
    print("==> Paste this into the .spec file:")
    print("hiddenimports = [")
    for m in third_party:
        print(f"    '{m}',")
    print("]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
