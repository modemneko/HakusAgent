"""
HakusAI 数据库工具集 (Navicat 风格)

支持数据库类型:
  - sqlite  : SQLite (本地文件, 无需额外依赖)
  - mysql   : MySQL / MariaDB (需要 pymysql)
  - postgres: PostgreSQL (需要 psycopg2-binary)
  - mssql   : SQL Server (需要 pymssql, 可选)
  - mongo   : MongoDB (需要 pymongo, 可选)

核心功能:
  - 连接管理 (connect / disconnect / list / test)
  - 数据库浏览 (list_databases / list_tables / describe_table)
  - SQL 执行 (execute / query)
  - 数据操作 (insert / update / delete)
  - 导入/导出 (export_csv / import_csv)
  - 模式管理 (create_table / drop_table / backup)
  - 持久化: ~/.hakus/connections.json (Claude Code 风格: 配置文件不外露)
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# 配置 & 状态
# ============================================================
HAKUS_HOME = Path(os.path.expanduser("~")) / ".hakus"
CONNECTIONS_FILE = HAKUS_HOME / "connections.json"
HAKUS_HOME.mkdir(parents=True, exist_ok=True)


class DBType(str, Enum):
    SQLITE = "sqlite"
    MYSQL = "mysql"
    POSTGRES = "postgres"
    MSSQL = "mssql"
    MONGO = "mongo"


@dataclass
class ConnectionConfig:
    name: str
    db_type: DBType
    host: str = "localhost"
    port: int = 0
    user: str = ""
    password: str = ""
    database: str = ""
    path: str = ""  # for sqlite
    options: Dict[str, Any] = field(default_factory=dict)
    saved_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "db_type": self.db_type.value,
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "path": self.path,
            "options": self.options,
            "saved_at": self.saved_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConnectionConfig":
        return cls(
            name=d["name"],
            db_type=DBType(d.get("db_type", "sqlite")),
            host=d.get("host", "localhost"),
            port=d.get("port", 0),
            user=d.get("user", ""),
            password=d.get("password", ""),
            database=d.get("database", ""),
            path=d.get("path", ""),
            options=d.get("options", {}),
            saved_at=d.get("saved_at", time.time()),
        )


# ============================================================
# Driver 抽象
# ============================================================
class DBDriver:
    """统一数据库驱动接口."""

    name: str = ""

    def test(self) -> Tuple[bool, str]:
        return True, "OK"

    def execute(self, sql: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def fetch_all(self, sql: str, params: Optional[Tuple] = None) -> Tuple[List[str], List[List[Any]]]:
        raise NotImplementedError

    def list_databases(self) -> List[str]:
        return []

    def list_tables(self, database: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    def describe_table(self, table: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SQLiteDriver(DBDriver):
    name = "sqlite"

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None

    def _ensure(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def test(self) -> Tuple[bool, str]:
        try:
            self._ensure().execute("SELECT 1").fetchone()
            return True, f"OK (file={self.path})"
        except Exception as e:
            return False, f"FAIL: {e}"

    def execute(self, sql: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._ensure()
            cur = conn.cursor()
            cur.execute(sql, params or ())
            affected = cur.rowcount
            lastrowid = cur.lastrowid
            conn.commit()
        return [{"affected_rows": affected, "last_row_id": lastrowid}]

    def fetch_all(self, sql: str, params: Optional[Tuple] = None) -> Tuple[List[str], List[List[Any]]]:
        with self._lock:
            conn = self._ensure()
            cur = conn.cursor()
            cur.execute(sql, params or ())
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = [list(r) for r in cur.fetchall()]
        return cols, rows

    def list_tables(self, database: Optional[str] = None) -> List[str]:
        cols, rows = self.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [r[0] for r in rows]

    def describe_table(self, table: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = f"PRAGMA table_info({_quote_ident(table, 'sqlite')})"
        _, rows = self.fetch_all(sql)
        result = []
        for r in rows:
            result.append({
                "column": r[1],
                "type": r[2],
                "nullable": not bool(r[3]),
                "default": r[4],
                "primary_key": bool(r[5]),
            })
        return result

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def _quote_ident(name: str, db_type: str) -> str:
    if db_type == "sqlite":
        return '"' + name.replace('"', '""') + '"'
    if db_type in ("mysql", "mssql"):
        return "`" + name.replace("`", "``") + "`"
    if db_type == "postgres":
        return '"' + name.replace('"', '""') + '"'
    return name


# ============================================================
# 连接管理
# ============================================================
class ConnectionManager:
    """统一的连接管理 + 持久化."""

    def __init__(self) -> None:
        self._connections: Dict[str, DBDriver] = {}
        self._configs: Dict[str, ConnectionConfig] = {}
        self._lock = threading.RLock()
        self._load_saved()

    def _load_saved(self) -> None:
        if not CONNECTIONS_FILE.exists():
            return
        try:
            data = json.loads(CONNECTIONS_FILE.read_text(encoding="utf-8"))
            for d in data:
                cfg = ConnectionConfig.from_dict(d)
                self._configs[cfg.name] = cfg
        except Exception as e:
            logger.warning(f"加载保存的连接失败: {e}")

    def _save(self) -> None:
        try:
            data = [c.to_dict() for c in self._configs.values()]
            CONNECTIONS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"保存连接失败: {e}")

    # ---------- 连接配置 ----------
    def save_config(self, cfg: ConnectionConfig) -> None:
        with self._lock:
            cfg.saved_at = time.time()
            self._configs[cfg.name] = cfg
            self._save()

    def remove_config(self, name: str) -> bool:
        with self._lock:
            if name in self._configs:
                del self._configs[name]
                self.disconnect(name)
                self._save()
                return True
            return False

    def list_configs(self) -> List[ConnectionConfig]:
        with self._lock:
            return list(self._configs.values())

    def get_config(self, name: str) -> Optional[ConnectionConfig]:
        with self._lock:
            return self._configs.get(name)

    # ---------- 连接 ----------
    def connect(self, cfg: ConnectionConfig) -> Tuple[bool, str]:
        with self._lock:
            if cfg.name in self._connections:
                return True, "已连接"
            try:
                driver = self._create_driver(cfg)
                ok, msg = driver.test()
                if not ok:
                    return False, msg
                self._connections[cfg.name] = driver
                self.save_config(cfg)
                return True, msg
            except Exception as e:
                return False, f"连接失败: {e}"

    def disconnect(self, name: str) -> bool:
        with self._lock:
            drv = self._connections.pop(name, None)
            if drv is not None:
                try:
                    drv.close()
                except Exception:
                    pass
                return True
            return False

    def is_connected(self, name: str) -> bool:
        with self._lock:
            return name in self._connections

    def get_driver(self, name: str) -> Optional[DBDriver]:
        with self._lock:
            return self._connections.get(name)

    def list_active(self) -> List[str]:
        with self._lock:
            return list(self._connections.keys())

    def _create_driver(self, cfg: ConnectionConfig) -> DBDriver:
        if cfg.db_type == DBType.SQLITE:
            return SQLiteDriver(cfg.path or ":memory:")
        if cfg.db_type == DBType.MYSQL:
            try:
                import pymysql
            except ImportError as e:
                raise RuntimeError(f"MySQL 驱动未安装 (pip install pymysql): {e}")
            return _MySQLDriver(cfg)
        if cfg.db_type == DBType.POSTGRES:
            try:
                import psycopg2
            except ImportError as e:
                raise RuntimeError(f"PostgreSQL 驱动未安装 (pip install psycopg2-binary): {e}")
            return _PostgresDriver(cfg)
        if cfg.db_type == DBType.MSSQL:
            try:
                import pymssql
            except ImportError as e:
                raise RuntimeError(f"MSSQL 驱动未安装 (pip install pymssql): {e}")
            return _MSSQLDriver(cfg)
        if cfg.db_type == DBType.MONGO:
            try:
                import pymongo
            except ImportError as e:
                raise RuntimeError(f"MongoDB 驱动未安装 (pip install pymongo): {e}")
            return _MongoDriver(cfg)
        raise ValueError(f"不支持的数据库类型: {cfg.db_type}")


# 延迟导入的占位, 仅在用户实际连接时尝试
class _MySQLDriver(DBDriver):
    name = "mysql"

    def __init__(self, cfg: ConnectionConfig):
        import pymysql
        self.cfg = cfg
        self._conn = pymysql.connect(
            host=cfg.host, port=cfg.port or 3306,
            user=cfg.user, password=cfg.password,
            database=cfg.database or None,
            autocommit=True, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def execute(self, sql, params=None):
        with self._conn.cursor() as cur:
            cur.execute(sql, params or ())
            return [{"affected_rows": cur.rowcount, "last_row_id": cur.lastrowid}]

    def fetch_all(self, sql, params=None):
        with self._conn.cursor() as cur:
            cur.execute(sql, params or ())
            desc = cur.description or []
            cols = [d[0] for d in desc]
            data = [list(r.values()) for r in cur.fetchall()]
        return cols, data

    def list_databases(self):
        _, rows = self.fetch_all("SHOW DATABASES")
        return [r[0] for r in rows]

    def list_tables(self, database=None):
        db = database or self.cfg.database
        if db:
            self.execute(f"USE `{db}`")
        _, rows = self.fetch_all("SHOW TABLES")
        return [r[0] for r in rows]

    def describe_table(self, table, database=None):
        db = database or self.cfg.database
        if db:
            self.execute(f"USE `{db}`")
        cols, rows = self.fetch_all(f"DESCRIBE `{table}`")
        result = []
        for r in rows:
            result.append({
                "column": r[0], "type": r[1], "nullable": r[2] == "YES",
                "default": r[4], "primary_key": r[3] == "PRI",
            })
        return result

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


class _PostgresDriver(DBDriver):
    name = "postgres"

    def __init__(self, cfg: ConnectionConfig):
        import psycopg2.extras
        self.cfg = cfg
        self._conn = psycopg2.connect(
            host=cfg.host, port=cfg.port or 5432,
            user=cfg.user, password=cfg.password,
            dbname=cfg.database or "postgres",
        )

    def execute(self, sql, params=None):
        with self._conn.cursor() as cur:
            cur.execute(sql, params or ())
            affected = cur.rowcount
            self._conn.commit()
            return [{"affected_rows": affected, "last_row_id": None}]

    def fetch_all(self, sql, params=None):
        with self._conn.cursor() as cur:
            cur.execute(sql, params or ())
            desc = cur.description or []
            cols = [d[0] for d in desc]
            rows = [list(r) for r in cur.fetchall()]
        return cols, rows

    def list_databases(self):
        cols, rows = self.fetch_all("SELECT datname FROM pg_database WHERE datistemplate=false")
        return [r[0] for r in rows]

    def list_tables(self, database=None):
        _, rows = self.fetch_all(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        return [r[0] for r in rows]

    def describe_table(self, table, database=None):
        _, rows = self.fetch_all(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name=%s ORDER BY ordinal_position",
            (table,),
        )
        result = []
        for r in rows:
            result.append({
                "column": r[0], "type": r[1], "nullable": r[2] == "YES",
                "default": r[3], "primary_key": False,
            })
        return result

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


class _MSSQLDriver(DBDriver):
    name = "mssql"

    def __init__(self, cfg: ConnectionConfig):
        import pymssql
        self.cfg = cfg
        self._conn = pymssql.connect(
            server=cfg.host, port=cfg.port or 1433,
            user=cfg.user, password=cfg.password,
            database=cfg.database or "master",
        )

    def execute(self, sql, params=None):
        with self._conn.cursor() as cur:
            cur.execute(sql, params or ())
            affected = cur.rowcount
            self._conn.commit()
            return [{"affected_rows": affected, "last_row_id": None}]

    def fetch_all(self, sql, params=None):
        with self._conn.cursor() as cur:
            cur.execute(sql, params or ())
            desc = cur.description or []
            cols = [d[0] for d in desc]
            rows = [list(r) for r in cur.fetchall()]
        return cols, rows

    def list_databases(self):
        _, rows = self.fetch_all("SELECT name FROM sys.databases ORDER BY name")
        return [r[0] for r in rows]

    def list_tables(self, database=None):
        _, rows = self.fetch_all(
            "SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE' "
            "ORDER BY table_name"
        )
        return [r[0] for r in rows]

    def describe_table(self, table, database=None):
        _, rows = self.fetch_all(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name=%s "
            "ORDER BY ordinal_position",
            (table,),
        )
        result = []
        for r in rows:
            result.append({
                "column": r[0], "type": r[1], "nullable": r[2] == "YES",
                "default": r[3], "primary_key": False,
            })
        return result

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


class _MongoDriver(DBDriver):
    name = "mongo"

    def __init__(self, cfg: ConnectionConfig):
        import pymongo
        self.cfg = cfg
        uri = cfg.options.get("uri") or (
            f"mongodb://{cfg.user}:{cfg.password}@{cfg.host}:{cfg.port or 27017}/"
        )
        self._client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._db_name = cfg.database or None

    def _db(self):
        if self._db_name is None:
            raise RuntimeError("请先选择数据库 (use_database)")
        return self._client[self._db_name]

    def execute(self, command, params=None):
        # MongoDB 不支持 SQL, command 应是 {"op": ..., "coll": ..., "doc": ...}
        if isinstance(command, str):
            try:
                command = json.loads(command)
            except Exception:
                raise RuntimeError("MongoDB command 必须是 JSON 字符串或 dict")
        op = command.get("op")
        coll = self._db()[command["coll"]]
        if op == "insert":
            r = coll.insert_one(command.get("doc", {}))
            return [{"affected_rows": 1, "last_row_id": str(r.inserted_id)}]
        if op == "insert_many":
            r = coll.insert_many(command.get("docs", []))
            return [{"affected_rows": len(r.inserted_ids)}]
        if op == "update":
            r = coll.update_one(command["filter"], command["update"])
            return [{"affected_rows": r.modified_count}]
        if op == "delete":
            r = coll.delete_one(command["filter"])
            return [{"affected_rows": r.deleted_count}]
        raise RuntimeError(f"未知 MongoDB op: {op}")

    def fetch_all(self, command, params=None):
        if isinstance(command, str):
            command = json.loads(command)
        coll = self._db()[command["coll"]]
        cur = coll.find(command.get("filter", {}))
        cur = cur.skip(command.get("skip", 0)).limit(command.get("limit", 100))
        rows = []
        for d in cur:
            d["_id"] = str(d.get("_id"))
            rows.append([json.dumps(d, default=str)])
        return ["doc"], rows

    def list_databases(self):
        return self._client.list_database_names()

    def list_tables(self, database=None):
        if database:
            self._db_name = database
        return self._db().list_collection_names()

    def describe_table(self, table, database=None):
        sample = self._db()[table].find_one()
        if not sample:
            return []
        result = []
        for k, v in sample.items():
            result.append({
                "column": k, "type": type(v).__name__,
                "nullable": True, "default": None, "primary_key": k == "_id",
            })
        return result

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass


# ============================================================
# 全局实例
# ============================================================
DB_MANAGER = ConnectionManager()
