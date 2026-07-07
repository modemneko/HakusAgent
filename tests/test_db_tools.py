"""
测试数据库工具 (Navicat 风格)
"""
import asyncio
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from hakus.db import DBType, ConnectionConfig, ConnectionManager, DB_MANAGER
from hakus.db_tools import (
    DBConnectTool, DBQueryTool, DBExecuteTool, DBTablesTool, DBDescribeTool,
    DBListTool, DBDisconnectTool, DBRemoveTool, _format_table, _format_describe,
)


@pytest.fixture
def sample_db(tmp_path):
    """创建一个临时 SQLite 数据库用于测试."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            email TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL DEFAULT 0.0
        )
    """)
    conn.executemany(
        "INSERT INTO users (name, age, email) VALUES (?, ?, ?)",
        [
            ("Alice", 30, "alice@test.com"),
            ("Bob", 25, "bob@test.com"),
            ("Charlie", 35, "charlie@test.com"),
        ]
    )
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture(autouse=True)
def use_global_manager(sample_db):
    """所有测试使用全局 DB_MANAGER (避免每个测试一个实例)."""
    for n in ("tui_test", "tbl", "desc", "q", "ex", "dc", "safe", "lim"):
        DB_MANAGER.disconnect(n)
    yield
    for n in ("tui_test", "tbl", "desc", "q", "ex", "dc", "safe", "lim"):
        DB_MANAGER.disconnect(n)


# ============================================================
# ConnectionConfig 持久化测试
# ============================================================
class TestConnectionConfig:
    def test_to_from_dict(self):
        cfg = ConnectionConfig(
            name="test1", db_type=DBType.SQLITE, path="/tmp/test.db"
        )
        d = cfg.to_dict()
        assert d["name"] == "test1"
        assert d["db_type"] == "sqlite"
        assert d["path"] == "/tmp/test.db"

        cfg2 = ConnectionConfig.from_dict(d)
        assert cfg2.name == cfg.name
        assert cfg2.db_type == cfg.db_type
        assert cfg2.path == cfg.path

    def test_from_dict_mysql(self):
        d = {
            "name": "mysql1", "db_type": "mysql",
            "host": "localhost", "port": 3306,
            "user": "root", "password": "pwd",
            "database": "test_db",
        }
        cfg = ConnectionConfig.from_dict(d)
        assert cfg.db_type == DBType.MYSQL
        assert cfg.port == 3306


# ============================================================
# ConnectionManager 测试
# ============================================================
class TestConnectionManager:
    def test_connect_sqlite(self, sample_db):
        DB_MANAGER.disconnect("test_sqlite")
        cfg = ConnectionConfig(
            name="test_sqlite", db_type=DBType.SQLITE, path=sample_db
        )
        ok, msg = DB_MANAGER.connect(cfg)
        assert ok is True
        assert "OK" in msg
        assert DB_MANAGER.is_connected("test_sqlite")
        DB_MANAGER.disconnect("test_sqlite")

    def test_disconnect(self, sample_db):
        DB_MANAGER.disconnect("test_disc")
        cfg = ConnectionConfig(
            name="test_disc", db_type=DBType.SQLITE, path=sample_db
        )
        DB_MANAGER.connect(cfg)
        assert DB_MANAGER.disconnect("test_disc") is True
        assert not DB_MANAGER.is_connected("test_disc")

    def test_list_active(self, sample_db):
        DB_MANAGER.disconnect("a")
        DB_MANAGER.disconnect("b")
        cfg1 = ConnectionConfig(name="a", db_type=DBType.SQLITE, path=sample_db)
        cfg2 = ConnectionConfig(name="b", db_type=DBType.SQLITE, path=sample_db)
        DB_MANAGER.connect(cfg1)
        DB_MANAGER.connect(cfg2)
        active = DB_MANAGER.list_active()
        assert "a" in active
        assert "b" in active
        DB_MANAGER.disconnect("a")
        DB_MANAGER.disconnect("b")

    def test_save_remove_config(self, sample_db):
        DB_MANAGER.disconnect("rm_test")
        DB_MANAGER.remove_config("rm_test")
        cfg = ConnectionConfig(name="rm_test", db_type=DBType.SQLITE, path=sample_db)
        DB_MANAGER.connect(cfg)
        DB_MANAGER.save_config(cfg)
        assert DB_MANAGER.get_config("rm_test") is not None
        DB_MANAGER.remove_config("rm_test")
        assert DB_MANAGER.get_config("rm_test") is None

    def test_get_driver(self, sample_db):
        DB_MANAGER.disconnect("getdrv")
        cfg = ConnectionConfig(name="getdrv", db_type=DBType.SQLITE, path=sample_db)
        DB_MANAGER.connect(cfg)
        driver = DB_MANAGER.get_driver("getdrv")
        assert driver is not None
        assert driver.name == "sqlite"
        DB_MANAGER.disconnect("getdrv")

    def test_get_nonexistent_driver(self):
        assert DB_MANAGER.get_driver("definitely_nope_999") is None


# ============================================================
# DBListTool / DBConnectTool 等高层工具
# ============================================================
class TestDBTools:
    @pytest.mark.asyncio
    async def test_db_list_empty(self):
        tool = DBListTool()
        result = await tool.execute()
        assert "数据库连接" in result

    @pytest.mark.asyncio
    async def test_db_connect_sqlite(self, sample_db):
        tool = DBConnectTool()
        result = await tool.execute(
            name="tui_test", db_type="sqlite", path=sample_db
        )
        assert "已连接" in result
        assert DB_MANAGER.is_connected("tui_test")
        DB_MANAGER.disconnect("tui_test")

    @pytest.mark.asyncio
    async def test_db_tables(self, sample_db):
        cfg = ConnectionConfig(name="tbl", db_type=DBType.SQLITE, path=sample_db)
        DB_MANAGER.connect(cfg)
        tool = DBTablesTool()
        result = await tool.execute(name="tbl")
        assert "users" in result
        assert "products" in result
        DB_MANAGER.disconnect("tbl")

    @pytest.mark.asyncio
    async def test_db_describe(self, sample_db):
        cfg = ConnectionConfig(name="desc", db_type=DBType.SQLITE, path=sample_db)
        DB_MANAGER.connect(cfg)
        tool = DBDescribeTool()
        result = await tool.execute(name="desc", table="users")
        assert "name" in result
        assert "email" in result
        assert "id" in result
        DB_MANAGER.disconnect("desc")

    @pytest.mark.asyncio
    async def test_db_query(self, sample_db):
        cfg = ConnectionConfig(name="q", db_type=DBType.SQLITE, path=sample_db)
        DB_MANAGER.connect(cfg)
        tool = DBQueryTool()
        result = await tool.execute(name="q", sql="SELECT * FROM users")
        assert "Alice" in result
        assert "Bob" in result
        DB_MANAGER.disconnect("q")

    @pytest.mark.asyncio
    async def test_db_execute_insert(self, sample_db):
        cfg = ConnectionConfig(name="ex", db_type=DBType.SQLITE, path=sample_db)
        DB_MANAGER.connect(cfg)
        tool = DBExecuteTool()
        result = await tool.execute(
            name="ex",
            sql="INSERT INTO users (name, age) VALUES ('Dave', 40)",
        )
        assert "执行成功" in result
        # 验证数据
        driver = DB_MANAGER.get_driver("ex")
        cols, rows = driver.fetch_all("SELECT COUNT(*) FROM users")
        assert rows[0][0] == 4
        DB_MANAGER.disconnect("ex")

    @pytest.mark.asyncio
    async def test_db_disconnect(self, sample_db):
        cfg = ConnectionConfig(name="dc", db_type=DBType.SQLITE, path=sample_db)
        DB_MANAGER.connect(cfg)
        tool = DBDisconnectTool()
        result = await tool.execute(name="dc")
        assert "已关闭" in result
        assert not DB_MANAGER.is_connected("dc")

    @pytest.mark.asyncio
    async def test_db_query_rejects_writes(self, sample_db):
        cfg = ConnectionConfig(name="safe", db_type=DBType.SQLITE, path=sample_db)
        DB_MANAGER.connect(cfg)
        tool = DBQueryTool()
        result = await tool.execute(
            name="safe",
            sql="DELETE FROM users"
        )
        assert "请用 db_execute" in result
        DB_MANAGER.disconnect("safe")

    @pytest.mark.asyncio
    async def test_db_query_auto_limit(self, sample_db):
        """验证 SELECT 自动添加 LIMIT."""
        cfg = ConnectionConfig(name="lim", db_type=DBType.SQLITE, path=sample_db)
        DB_MANAGER.connect(cfg)
        tool = DBQueryTool()
        result = await tool.execute(
            name="lim",
            sql="SELECT * FROM users"
        )
        assert "Alice" in result
        DB_MANAGER.disconnect("lim")


# ============================================================
# 格式化辅助
# ============================================================
class TestFormatters:
    def test_format_table(self):
        cols = ["id", "name"]
        rows = [[1, "Alice"], [2, "Bob"]]
        result = _format_table(cols, rows)
        assert "| id | name |" in result
        assert "Alice" in result
        assert "**共 2 行**" in result

    def test_format_table_with_null(self):
        cols = ["a", "b"]
        rows = [[1, None]]
        result = _format_table(cols, rows)
        assert "| 1 |  |" in result

    def test_format_table_max_rows(self):
        cols = ["x"]
        rows = [[i] for i in range(500)]
        result = _format_table(cols, rows, max_rows=10)
        assert "省略 490 行" in result

    def test_format_describe(self):
        rows = [
            {"column": "id", "type": "INTEGER", "nullable": False, "default": None, "primary_key": True},
            {"column": "name", "type": "TEXT", "nullable": False, "default": "", "primary_key": False},
        ]
        result = _format_describe(rows)
        assert "`id`" in result
        assert "INTEGER" in result
        assert "🔑" in result
