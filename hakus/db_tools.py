"""
HakusAI 数据库工具 — Agent 可调用的 db_* 工具
也支持 Navicat 风格 /db 子命令交互模式
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger
from .db import (
    DB_MANAGER, DBType, ConnectionConfig, HAKUS_HOME, CONNECTIONS_FILE,
    SQLiteDriver,
)
from .tools import Tool, ToolRegistry

logger = get_logger(__name__)


# ============================================================
# 格式化辅助
# ============================================================
def _format_table(columns: List[str], rows: List[List[Any]], max_rows: int = 200) -> str:
    """格式化为 markdown 表格."""
    if not columns:
        return "(无结果)"
    out_lines = ["| " + " | ".join(columns) + " |",
                 "|" + "|".join(["---"] * len(columns)) + "|"]
    for r in rows[:max_rows]:
        cells = ["" if c is None else str(c).replace("|", "\\|").replace("\n", " ")[:200] for c in r]
        out_lines.append("| " + " | ".join(cells) + " |")
    if len(rows) > max_rows:
        out_lines.append(f"\n*…(省略 {len(rows) - max_rows} 行)*")
    out_lines.append(f"\n**共 {len(rows)} 行**")
    return "\n".join(out_lines)


def _format_describe(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "(无字段)"
    out = ["| Column | Type | Nullable | Default | PK |", "|---|---|---|---|---|"]
    for r in rows:
        out.append(
            f"| `{r.get('column','')}` | {r.get('type','')} "
            f"| {'YES' if r.get('nullable') else 'NO'} "
            f"| {r.get('default','') or ''} "
            f"| {'🔑' if r.get('primary_key') else ''} |"
        )
    return "\n".join(out)


# ============================================================
# 工具集 — 注册到 Agent
# ============================================================
class DBConnectTool(Tool):
    name = "db_connect"
    description = "建立/打开一个数据库连接 (Navicat 风格). 支持 sqlite / mysql / postgres / mssql / mongo. " \
                  "可连接已有保存的连接, 或直接传新参数建立新连接."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "连接名 (唯一标识)"},
            "db_type": {"type": "string", "enum": ["sqlite", "mysql", "postgres", "mssql", "mongo"],
                        "description": "数据库类型"},
            "host": {"type": "string", "description": "主机 (mysql/postgres/mssql/mongo)"},
            "port": {"type": "integer", "description": "端口"},
            "user": {"type": "string", "description": "用户名"},
            "password": {"type": "string", "description": "密码"},
            "database": {"type": "string", "description": "数据库名"},
            "path": {"type": "string", "description": "SQLite 文件路径"},
            "save": {"type": "boolean", "description": "是否保存为持久连接 (默认 true)"},
        },
        "required": ["name", "db_type"],
    }
    is_concurrency_safe = False
    is_dangerous = False

    async def execute(self, name: str, db_type: str,
                      host: str = "localhost", port: int = 0,
                      user: str = "", password: str = "",
                      database: str = "", path: str = "",
                      save: bool = True, **kwargs) -> str:
        try:
            existing = DB_MANAGER.get_config(name)
            if existing and not any([host, user, password, database, path]):
                # 已存在同名连接, 直接用
                cfg = existing
            else:
                cfg = ConnectionConfig(
                    name=name, db_type=DBType(db_type),
                    host=host, port=port, user=user, password=password,
                    database=database, path=path,
                )
            ok, msg = DB_MANAGER.connect(cfg)
            if ok and save:
                DB_MANAGER.save_config(cfg)
            status = "✓ 已连接" if ok else "✗ 失败"
            return f"{status}  [{cfg.db_type.value}] {cfg.name}  —  {msg}"
        except Exception as e:
            return f"错误: {e}"


class DBDisconnectTool(Tool):
    name = "db_disconnect"
    description = "关闭指定数据库连接."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "要关闭的连接名"},
        },
        "required": ["name"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, name: str, **kwargs) -> str:
        if DB_MANAGER.disconnect(name):
            return f"✓ 已关闭连接: {name}"
        return f"连接 {name} 不存在或已关闭"


class DBListTool(Tool):
    name = "db_list"
    description = "列出所有数据库连接 (已保存的 / 当前活动的)."
    parameters_schema = {
        "type": "object",
        "properties": {
            "show": {"type": "string", "enum": ["all", "saved", "active"],
                     "description": "显示范围 (默认 all)"},
        },
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, show: str = "all", **kwargs) -> str:
        lines = ["# 📚 数据库连接\n"]
        if show in ("all", "saved"):
            saved = DB_MANAGER.list_configs()
            if saved:
                lines.append("## 已保存的连接")
                for c in saved:
                    active = "🟢" if DB_MANAGER.is_connected(c.name) else "⚪"
                    target = c.path if c.db_type == DBType.SQLITE else f"{c.host}:{c.port or '?'}"
                    lines.append(
                        f"- {active} **{c.name}** · `{c.db_type.value}` · {target} · "
                        f"db=`{c.database or '-'}`"
                    )
            else:
                lines.append("(无保存的连接)")
        if show in ("all", "active"):
            active = DB_MANAGER.list_active()
            if active:
                lines.append("\n## 当前活动连接")
                for n in active:
                    lines.append(f"- 🟢 **{n}**")
        return "\n".join(lines) if len(lines) > 1 else lines[0]


class DBRemoveTool(Tool):
    name = "db_remove"
    description = "删除一个已保存的数据库连接."
    parameters_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    is_concurrency_safe = True
    is_dangerous = True

    async def execute(self, name: str, **kwargs) -> str:
        if DB_MANAGER.remove_config(name):
            return f"✓ 已删除连接: {name}"
        return f"连接 {name} 不存在"


class DBTablesTool(Tool):
    name = "db_tables"
    description = "列出指定连接的所有表/集合. 包含字段信息概览."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "连接名"},
            "database": {"type": "string", "description": "数据库 (可选, mysql/postgres)"},
        },
        "required": ["name"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, name: str, database: str = "", **kwargs) -> str:
        driver = DB_MANAGER.get_driver(name)
        if not driver:
            return f"连接 {name} 未打开, 请先 db_connect"
        try:
            tables = driver.list_tables(database or None)
            lines = [f"# 📋 表/集合 (连接: {name}, 共 {len(tables)} 个)\n"]
            for t in tables[:200]:
                lines.append(f"- `{t}`")
            if len(tables) > 200:
                lines.append(f"\n*… 仅显示前 200 个, 共 {len(tables)}*")
            return "\n".join(lines)
        except Exception as e:
            return f"错误: {e}"


class DBDescribeTool(Tool):
    name = "db_describe"
    description = "查看表结构 (列/类型/约束)."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "连接名"},
            "table": {"type": "string", "description": "表名"},
        },
        "required": ["name", "table"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, name: str, table: str, **kwargs) -> str:
        driver = DB_MANAGER.get_driver(name)
        if not driver:
            return f"连接 {name} 未打开"
        try:
            schema = driver.describe_table(table)
            return f"# 📐 `{table}`\n\n{_format_describe(schema)}"
        except Exception as e:
            return f"错误: {e}"


class DBQueryTool(Tool):
    name = "db_query"
    description = "执行 SQL SELECT 查询并以表格形式返回结果."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "sql": {"type": "string", "description": "SELECT 语句"},
            "limit": {"type": "integer", "description": "最大行数 (默认 100)"},
        },
        "required": ["name", "sql"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, name: str, sql: str, limit: int = 100, **kwargs) -> str:
        driver = DB_MANAGER.get_driver(name)
        if not driver:
            return f"连接 {name} 未打开"
        # 安全: 拦截非 SELECT / PRAGMA / EXPLAIN
        sql_stripped = sql.strip().lower()
        if not (sql_stripped.startswith("select") or sql_stripped.startswith("pragma")
                or sql_stripped.startswith("explain") or sql_stripped.startswith("with")):
            return f"⚠ db_query 仅支持查询语句, 请用 db_execute 跑写操作"
        # 自动 LIMIT (防止 OOM)
        if "limit" not in sql.lower() and driver.name == "sqlite":
            sql = sql.rstrip(";") + f" LIMIT {limit}"
        try:
            cols, rows = driver.fetch_all(sql)
            return f"# 🔍 查询结果\n\n{_format_table(cols, rows)}"
        except Exception as e:
            return f"查询错误: {e}"


class DBExecuteTool(Tool):
    name = "db_execute"
    description = "执行 SQL 写操作 (INSERT/UPDATE/DELETE/CREATE/DROP/...). 危险操作."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "sql": {"type": "string"},
        },
        "required": ["name", "sql"],
    }
    is_concurrency_safe = False
    is_dangerous = True

    async def execute(self, name: str, sql: str, **kwargs) -> str:
        driver = DB_MANAGER.get_driver(name)
        if not driver:
            return f"连接 {name} 未打开"
        try:
            result = driver.execute(sql)
            return f"✓ 执行成功  ·  {result}"
        except Exception as e:
            return f"执行错误: {e}"


class DBImportCSVTool(Tool):
    name = "db_import_csv"
    description = "将 CSV 文件导入到指定表. 第一行为表头."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "table": {"type": "string"},
            "file": {"type": "string", "description": "CSV 文件路径"},
        },
        "required": ["name", "table", "file"],
    }
    is_concurrency_safe = False
    is_dangerous = True

    async def execute(self, name: str, table: str, file: str, **kwargs) -> str:
        driver = DB_MANAGER.get_driver(name)
        if not driver:
            return f"连接 {name} 未打开"
        if not os.path.exists(file):
            return f"文件不存在: {file}"
        try:
            with open(file, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                rows = list(reader)
            if not header:
                return "CSV 无表头"
            placeholders = ",".join(["?"] * len(header))
            cols_csv = ",".join(f"`{h}`" for h in header)
            sql = f"INSERT INTO `{table}` ({cols_csv}) VALUES ({placeholders})"
            inserted = 0
            for r in rows:
                try:
                    driver.execute(sql, tuple(r))
                    inserted += 1
                except Exception as e:
                    logger.warning(f"行 {inserted+1} 导入失败: {e}")
            return f"✓ 导入 {inserted}/{len(rows)} 行到 `{table}`"
        except Exception as e:
            return f"导入错误: {e}"


class DBExportCSVTool(Tool):
    name = "db_export_csv"
    description = "将查询结果导出为 CSV 文件."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "sql": {"type": "string"},
            "file": {"type": "string", "description": "输出 CSV 路径"},
        },
        "required": ["name", "sql", "file"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, name: str, sql: str, file: str, **kwargs) -> str:
        driver = DB_MANAGER.get_driver(name)
        if not driver:
            return f"连接 {name} 未打开"
        try:
            cols, rows = driver.fetch_all(sql)
            os.makedirs(os.path.dirname(os.path.abspath(file)) or ".", exist_ok=True)
            with open(file, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(cols)
                w.writerows(rows)
            return f"✓ 已导出 {len(rows)} 行到 `{file}`"
        except Exception as e:
            return f"导出错误: {e}"


class DBBakcupTool(Tool):
    name = "db_backup"
    description = "备份数据库 (仅 SQLite). 会复制 db 文件到指定路径."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "to": {"type": "string", "description": "备份文件路径"},
        },
        "required": ["name", "to"],
    }
    is_concurrency_safe = False
    is_dangerous = True

    async def execute(self, name: str, to: str, **kwargs) -> str:
        driver = DB_MANAGER.get_driver(name)
        if not driver:
            return f"连接 {name} 未打开"
        if not isinstance(driver, SQLiteDriver):
            return f"暂仅支持 SQLite 备份"
        try:
            import shutil
            os.makedirs(os.path.dirname(os.path.abspath(to)) or ".", exist_ok=True)
            # 触发 checkpoint
            if hasattr(driver, "_ensure"):
                try:
                    driver._ensure().execute("VACUUM INTO ?", (to,))
                    return f"✓ VACUUM INTO 备份完成: {to}"
                except Exception:
                    pass
            shutil.copy2(driver.path, to)
            return f"✓ 已复制到 {to}"
        except Exception as e:
            return f"备份错误: {e}"


# ============================================================
# 工具注册
# ============================================================
_DB_TOOLS_REGISTERED = False


def register_db_tools(registry: ToolRegistry) -> int:
    """注册所有 db_* 工具到 registry."""
    global _DB_TOOLS_REGISTERED
    tools = [
        DBConnectTool(), DBDisconnectTool(), DBListTool(), DBRemoveTool(),
        DBTablesTool(), DBDescribeTool(), DBQueryTool(), DBExecuteTool(),
        DBImportCSVTool(), DBExportCSVTool(), DBBakcupTool(),
    ]
    for t in tools:
        registry.register(t)
    _DB_TOOLS_REGISTERED = True
    logger.info(f"已注册 {len(tools)} 个数据库工具 (Navicat 风格)")
    return len(tools)


# ============================================================
# Navicat 子应用 (REPL 模式)
# ============================================================
class NavicatREPL:
    """Navicat 风格的交互式数据库控制台.

    用法:
        /db navicat                       # 进入 Navicat REPL
        /db navicat <connection>          # 直接进入指定连接
    """

    PROMPT = "(navicat)"

    def __init__(self, console=None) -> None:
        self.console = console
        self._current: Optional[str] = None  # 当前连接名
        self._db: Optional[str] = None
        self._history: List[str] = []

    def set_current(self, name: str) -> Tuple[bool, str]:
        if not DB_MANAGER.is_connected(name):
            return False, f"连接 {name} 未打开"
        self._current = name
        cfg = DB_MANAGER.get_config(name)
        if cfg and cfg.database:
            self._db = cfg.database
        return True, f"已切换到 {name}"

    @property
    def prompt(self) -> str:
        if self._current:
            return f"(navicat:{self._current})"
        return self.PROMPT

    def run_line(self, line: str) -> Tuple[str, bool]:
        """处理一行 REPL 输入. 返回 (输出, 是否退出)."""
        s = line.strip()
        if not s:
            return "", False
        if s in ("/exit", "/quit", "exit", "quit", ":q"):
            return "👋 退出 Navicat", True
        if s in ("/help", "help", "?"):
            return self._help(), False
        if s in ("/list", "list"):
            return self._cmd_list(), False
        if s.startswith("use "):
            return self._cmd_use(s[4:].strip()), False
        if s.startswith("connect "):
            return self._cmd_connect(s[8:].strip()), False
        if s.startswith("disconnect"):
            return self._cmd_disconnect(), False
        if s in ("/tables", "tables", "show tables"):
            return self._cmd_tables(), False
        if s.startswith("desc "):
            return self._cmd_desc(s[5:].strip()), False
        if s in ("/status", "status"):
            return self._cmd_status(), False
        if s.startswith("import "):
            return self._cmd_import(s[7:].strip()), False
        if s.startswith("export "):
            return self._cmd_export(s[7:].strip()), False

        # 默认: 当作 SQL 执行
        if not self._current:
            return "⚠ 未选择连接, 请先 `connect <name>` 或 `use <connection>`", False
        return self._cmd_sql(s), False

    def _help(self) -> str:
        return (
            "# Navicat REPL 命令\n\n"
            "- **`connect <name>`** — 打开/激活一个连接\n"
            "- **`use <name>`** — 同上\n"
            "- **`disconnect`** — 关闭当前连接\n"
            "- **`/list`** / **`list`** — 列出所有连接\n"
            "- **`/tables`** / **`show tables`** — 列出当前连接的表\n"
            "- **`desc <table>`** — 查看表结构\n"
            "- **`import <table> <csv>`** — 导入 CSV 到表\n"
            "- **`export <csv> <sql>`** — 导出查询结果到 CSV\n"
            "- **`/status`** / **`status`** — 当前状态\n"
            "- **`<sql>`** — 直接执行 SQL (SELECT 自动 LIMIT, 其它走 execute)\n"
            "- **`/exit`** / **`:q`** — 退出\n"
        )

    def _cmd_list(self) -> str:
        saved = DB_MANAGER.list_configs()
        active = DB_MANAGER.list_active()
        lines = ["# 数据库连接\n"]
        for c in saved:
            mark = "🟢" if c.name in active else "⚪"
            target = c.path if c.db_type == DBType.SQLITE else f"{c.host}:{c.port or '?'}"
            lines.append(f"- {mark} **{c.name}** · `{c.db_type.value}` · {target} · db=`{c.database or '-'}`")
        return "\n".join(lines)

    def _cmd_use(self, name: str) -> str:
        if not name:
            return "用法: use <connection_name>"
        ok, msg = self.set_current(name)
        return f"{'✓' if ok else '✗'} {msg}"

    def _cmd_connect(self, args: str) -> str:
        if not args:
            return "用法: connect <name> [db_type=sqlite] [host=...] [port=...] [user=...] [password=...] [database=...] [path=...]"
        parts = args.split()
        name = parts[0]
        cfg = DB_MANAGER.get_config(name)
        if cfg is None:
            return f"未找到保存的连接: {name}, 请先调用 db_connect 工具"
        ok, msg = DB_MANAGER.connect(cfg)
        if ok:
            self.set_current(name)
        return f"{'✓' if ok else '✗'} connect {name}: {msg}"

    def _cmd_disconnect(self) -> str:
        if not self._current:
            return "未选择连接"
        name = self._current
        DB_MANAGER.disconnect(name)
        self._current = None
        return f"✓ 已关闭 {name}"

    def _cmd_tables(self) -> str:
        if not self._current:
            return "未选择连接"
        driver = DB_MANAGER.get_driver(self._current)
        if not driver:
            return "连接已失效"
        try:
            tables = driver.list_tables(self._db)
            lines = [f"# 表/集合 (连接: {self._current}, 共 {len(tables)} 个)\n"]
            for t in tables[:100]:
                lines.append(f"- `{t}`")
            return "\n".join(lines)
        except Exception as e:
            return f"错误: {e}"

    def _cmd_desc(self, table: str) -> str:
        if not self._current or not table:
            return "用法: desc <table>"
        driver = DB_MANAGER.get_driver(self._current)
        if not driver:
            return "连接已失效"
        try:
            schema = driver.describe_table(table)
            return f"# 📐 `{table}`\n\n{_format_describe(schema)}"
        except Exception as e:
            return f"错误: {e}"

    def _cmd_sql(self, sql: str) -> str:
        driver = DB_MANAGER.get_driver(self._current)
        if not driver:
            return "连接已失效"
        s_low = sql.strip().lower()
        if s_low.startswith(("select", "pragma", "explain", "with")):
            if "limit" not in sql.lower() and driver.name == "sqlite":
                sql = sql.rstrip(";") + " LIMIT 100"
            try:
                cols, rows = driver.fetch_all(sql)
                return _format_table(cols, rows)
            except Exception as e:
                return f"查询错误: {e}"
        try:
            result = driver.execute(sql)
            return f"✓ 执行成功  ·  {result}"
        except Exception as e:
            return f"执行错误: {e}"

    def _cmd_import(self, args: str) -> str:
        if not self._current:
            return "未选择连接"
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            return "用法: import <table> <csv_path>"
        table, path = parts
        return _run_sync(DBImportCSVTool().execute(
            name=self._current, table=table, file=path))

    def _cmd_export(self, args: str) -> str:
        if not self._current:
            return "未选择连接"
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            return "用法: export <csv_path> <sql>"
        path, sql = parts
        return _run_sync(DBExportCSVTool().execute(
            name=self._current, sql=sql, file=path))

    def _cmd_status(self) -> str:
        saved = len(DB_MANAGER.list_configs())
        active = DB_MANAGER.list_active()
        return (
            f"# Navicat 状态\n\n"
            f"- 当前连接: `{self._current or '(无)'}`\n"
            f"- 已保存连接: {saved}\n"
            f"- 活动连接: {len(active)} ({', '.join(active) or '-'})\n"
            f"- 数据库: `{self._db or '(未选择)'}`\n"
        )


def _run_sync(coro) -> str:
    """在同步上下文跑协程."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        return asyncio.run(coro)
    # 在已有 loop 中: 用线程
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
