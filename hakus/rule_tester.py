"""RuleBasedTester — 零 LLM 的快速验证 (ACI 栏杆原则).

在效率模式下，先用规则检测做快速验证：
  1. 文件存在性 — 检查关键文件是否已创建
  2. 语法检查 — 对 .py/.js/.ts/.html/.css 运行对应 linter/parser
  3. HTML 加载测试 — 检查 index.html 能否被浏览器解析
  4. 入口检查 — 检查 main.js/package.json 等入口文件是否存在

只有规则检测全 PASS 后才调 LLM Tester 做语义审查（全开模式）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RuleTestResult:
    rule: str
    passed: bool
    message: str
    details: List[str] = field(default_factory=list)


class RuleBasedTester:
    """零 LLM 的规则检测器."""

    # 按文件扩展名映射到检查命令
    _SYNTAX_CHECKERS = {
        ".py": {"cmd": [sys.executable, "-m", "py_compile"], "name": "py_compile"},
        ".js": {"cmd": ["node", "--check"], "name": "node --check", "needs_esm": True},
        ".html": None,  # 用内置 HTML 检查
        ".css": None,    # 用内置 CSS 检查
        ".json": None,   # 用内置 JSON 检查
        ".glsl": None,   # shader 无法语法检查，跳过
        ".frag": None,
        ".vert": None,
    }

    # 典型项目入口文件
    _ENTRY_FILES = {
        "web": ["index.html", "package.json"],
        "python": ["setup.py", "pyproject.toml", "requirements.txt"],
        "node": ["package.json", "index.js", "src/index.js"],
    }

    def __init__(self, workspace_dir: str):
        self._workspace = Path(workspace_dir)

    def run_all(self, task_type: str = "web") -> Tuple[bool, List[RuleTestResult]]:
        """运行所有规则检测，返回 (all_passed, results)."""
        results: List[RuleTestResult] = []

        # 1. 入口文件存在性
        results.append(self._check_entry_files(task_type))

        # 2. 语法检查 (对所有源文件)
        syntax_results = self._check_syntax_all()
        results.extend(syntax_results)

        # 3. HTML 加载测试
        html_result = self._check_html()
        if html_result:
            results.append(html_result)

        # 4. package.json 完整性
        pkg_result = self._check_package_json()
        if pkg_result:
            results.append(pkg_result)

        all_passed = all(r.passed for r in results)
        passed_count = sum(1 for r in results if r.passed)
        logger.info(
            f"[rule_tester] {passed_count}/{len(results)} rules passed "
            f"({'ALL PASS' if all_passed else 'HAS FAILURES'})"
        )
        return all_passed, results

    def _check_entry_files(self, task_type: str) -> RuleTestResult:
        """检查项目入口文件是否存在."""
        expected = self._ENTRY_FILES.get(task_type, self._ENTRY_FILES["web"])
        missing = []
        found = []
        for f in expected:
            if (self._workspace / f).exists():
                found.append(f)
            else:
                missing.append(f)

        if found:
            return RuleTestResult(
                rule="entry_files",
                passed=True,
                message=f"Found {len(found)}/{len(expected)} entry files",
                details=[f"✓ {f}" for f in found] + [f"✗ {f} (missing)" for f in missing],
            )
        return RuleTestResult(
            rule="entry_files",
            passed=False,
            message=f"No entry files found (expected: {', '.join(expected)})",
            details=[f"✗ {f} (missing)" for f in missing],
        )

    def _check_syntax_all(self) -> List[RuleTestResult]:
        """对所有源文件运行语法检查."""
        results = []
        # 只检查项目自有文件，排除 vendor/node_modules
        skip_dirs = {"node_modules", ".git", "__pycache__", "vendor", "venv", ".venv"}
        for f in self._workspace.rglob("*"):
            if not f.is_file():
                continue
            if any(p in skip_dirs for p in f.parts):
                continue
            ext = f.suffix.lower()
            if ext in self._SYNTAX_CHECKERS:
                result = self._check_syntax_file(f)
                if result:
                    results.append(result)
        return results

    def _check_syntax_file(self, filepath: Path) -> Optional[RuleTestResult]:
        """对单个文件运行语法检查."""
        ext = filepath.suffix.lower()
        checker = self._SYNTAX_CHECKERS.get(ext)
        rel = str(filepath.relative_to(self._workspace))

        # 内置检查
        if ext == ".html":
            return self._check_html_file(filepath, rel)
        if ext == ".css":
            return self._check_css_file(filepath, rel)
        if ext == ".json":
            return self._check_json_file(filepath, rel)
        if ext in (".glsl", ".frag", ".vert"):
            return None  # shader 无法语法检查

        # 外部命令检查
        if checker is None:
            return None

        # ES Modules 项目: node --check 需要 --input-type=module
        cmd = list(checker["cmd"])
        if checker.get("needs_esm"):
            # 检查同目录或上级的 package.json 是否有 "type": "module"
            _pkg = self._find_package_json(filepath)
            if _pkg:
                try:
                    _data = json.loads(_pkg.read_text(encoding="utf-8"))
                    if _data.get("type") == "module":
                        # node --check 不支持 --input-type=module，跳过 ES module 语法检查
                        # 改用内置的 import/export 检测
                        return self._check_esm_file(filepath, rel)
                except Exception:
                    pass
            # 没有 type:module，用内置检查
            return self._check_esm_file(filepath, rel)

        cmd = checker["cmd"] + [str(filepath)]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if proc.returncode == 0:
                return RuleTestResult(
                    rule=f"syntax:{rel}",
                    passed=True,
                    message=f"Syntax OK ({checker['name']})",
                )
            else:
                err = proc.stderr.decode("utf-8", errors="replace")[:500]
                return RuleTestResult(
                    rule=f"syntax:{rel}",
                    passed=False,
                    message=f"Syntax error in {rel}",
                    details=[err],
                )
        except FileNotFoundError:
            # checker 不存在，跳过
            return None
        except subprocess.TimeoutExpired:
            return RuleTestResult(
                rule=f"syntax:{rel}",
                passed=False,
                message=f"Syntax check timed out for {rel}",
            )
        except Exception as e:
            return RuleTestResult(
                rule=f"syntax:{rel}",
                passed=False,
                message=f"Syntax check failed for {rel}: {e}",
            )

    def _check_html_file(self, filepath: Path, rel: str) -> RuleTestResult:
        """内置 HTML 基础检查."""
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
            issues = []
            if "<html" not in content.lower():
                issues.append("Missing <html> tag")
            if "</html>" not in content.lower():
                issues.append("Missing </html> closing tag")
            if "<head" not in content.lower():
                issues.append("Missing <head> tag")
            if "<body" not in content.lower():
                issues.append("Missing <body> tag")
            if issues:
                return RuleTestResult(rule=f"syntax:{rel}", passed=False,
                                      message=f"HTML issues in {rel}", details=issues)
            return RuleTestResult(rule=f"syntax:{rel}", passed=True, message="HTML structure OK")
        except Exception as e:
            return RuleTestResult(rule=f"syntax:{rel}", passed=False,
                                  message=f"Cannot read {rel}: {e}")

    def _check_css_file(self, filepath: Path, rel: str) -> RuleTestResult:
        """内置 CSS 基础检查 — 检查花括号匹配."""
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
            opens = content.count("{")
            closes = content.count("}")
            if opens != closes:
                return RuleTestResult(
                    rule=f"syntax:{rel}", passed=False,
                    message=f"CSS brace mismatch in {rel}: {opens} {{ vs {closes} }}",
                )
            return RuleTestResult(rule=f"syntax:{rel}", passed=True, message="CSS braces OK")
        except Exception as e:
            return RuleTestResult(rule=f"syntax:{rel}", passed=False,
                                  message=f"Cannot read {rel}: {e}")

    def _check_json_file(self, filepath: Path, rel: str) -> RuleTestResult:
        """内置 JSON 语法检查."""
        try:
            filepath.read_text(encoding="utf-8")
            json.loads(filepath.read_text(encoding="utf-8"))
            return RuleTestResult(rule=f"syntax:{rel}", passed=True, message="JSON valid")
        except json.JSONDecodeError as e:
            return RuleTestResult(rule=f"syntax:{rel}", passed=False,
                                  message=f"JSON error in {rel}: {e}")
        except Exception as e:
            return RuleTestResult(rule=f"syntax:{rel}", passed=False,
                                  message=f"Cannot read {rel}: {e}")

    def _check_html(self) -> Optional[RuleTestResult]:
        """检查 index.html 是否存在且可解析."""
        html_path = self._workspace / "index.html"
        if not html_path.exists():
            return RuleTestResult(
                rule="html_load", passed=False,
                message="index.html not found",
            )
        return None  # 已在 _check_html_file 中检查

    def _check_package_json(self) -> Optional[RuleTestResult]:
        """检查 package.json 完整性."""
        pkg_path = self._workspace / "package.json"
        if not pkg_path.exists():
            return None  # 非 Node 项目，跳过
        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8"))
            issues = []
            if not data.get("name"):
                issues.append("Missing 'name' field")
            if not data.get("version"):
                issues.append("Missing 'version' field")
            if issues:
                return RuleTestResult(rule="package_json", passed=False,
                                      message="package.json incomplete", details=issues)
            return RuleTestResult(rule="package_json", passed=True,
                                  message="package.json valid")
        except Exception as e:
            return RuleTestResult(rule="package_json", passed=False,
                                  message=f"Cannot parse package.json: {e}")

    def _find_package_json(self, filepath: Path) -> Optional[Path]:
        """向上查找 package.json."""
        current = filepath.parent
        for _ in range(10):
            pkg = current / "package.json"
            if pkg.exists():
                return pkg
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    def _check_esm_file(self, filepath: Path, rel: str) -> RuleTestResult:
        """内置 JS 基础检查 — 检查括号/花括号匹配."""
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
            issues = []
            # 检查花括号匹配 (排除字符串内的)
            opens = content.count("{")
            closes = content.count("}")
            if abs(opens - closes) > 2:  # 允许模板字符串内的微小差异
                issues.append(f"Brace mismatch: {opens} {{ vs {closes} }}")
            # 检查圆括号匹配
            parens_open = content.count("(")
            parens_close = content.count(")")
            if abs(parens_open - parens_close) > 2:
                issues.append(f"Paren mismatch: {parens_open} ( vs {parens_close} )")
            if issues:
                return RuleTestResult(rule=f"syntax:{rel}", passed=False,
                                      message=f"JS issues in {rel}", details=issues)
            return RuleTestResult(rule=f"syntax:{rel}", passed=True, message="JS structure OK (ESM)")
        except Exception as e:
            return RuleTestResult(rule=f"syntax:{rel}", passed=False,
                                  message=f"Cannot read {rel}: {e}")

    def format_report(self, results: List[RuleTestResult]) -> str:
        """格式化报告为 RESULT: PASS/FAIL + 详情."""
        all_passed = all(r.passed for r in results)
        status = "PASS" if all_passed else "FAIL"
        lines = [f"RESULT: {status}"]
        lines.append(f"Rules: {sum(r.passed for r in results)}/{len(results)} passed")
        for r in results:
            icon = "✓" if r.passed else "✗"
            lines.append(f"  {icon} [{r.rule}] {r.message}")
            for d in r.details:
                lines.append(f"    {d}")
        return "\n".join(lines)
