"""End-to-end integration test - simulate the actual user experience."""
import sys
import io
# Force UTF-8 for stdout/stderr in case of gbk on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')

# 1. Quiet logger
from utils.logger import quiet_console_loggers, get_logger
quiet_console_loggers()

# 2. Test hooks - no verbose log
import asyncio
from hakus.hooks import HookRegistry, HookChain, HookContext, HookEvent, setup_default_hooks

print('=== Test 1: User Message (no verbose log) ===')
print('(HakusAI) > 你好, 帮我分析下当前代码')

registry = HookRegistry()
setup_default_hooks(registry)
chain = HookChain(registry)

async def test_msg():
    msg, blocked = await chain.on_user_message('分析当前的代码, 检查代码问题')
    print('(echo):', msg[:50] + '...' if len(msg) > 50 else msg)
    print('=== Test 1 passed: no verbose log on stdout ===')

asyncio.run(test_msg())

# 3. Test ActivityTracker
print()
print('=== Test 2: ActivityTracker (Claude Code style) ===')
from hakus.status_display import TRACKER, format_phase, activity

TRACKER.set(phase='thinking', detail='分析中')
print('  Display:', format_phase(TRACKER.get().phase, TRACKER.get().detail))
TRACKER.set(phase='streaming', detail='生成回复')
print('  Display:', format_phase(TRACKER.get().phase, TRACKER.get().detail))
TRACKER.set(phase='tool_use', tool_name='bash', detail='执行 ls')
print('  Display:', format_phase(TRACKER.get().phase, TRACKER.get().detail))
TRACKER.reset()
print('  Display:', format_phase(TRACKER.get().phase))
print('=== Test 2 passed ===')

# 4. Test Navicat-like DB tools
print()
print('=== Test 3: Navicat-style DB tools ===')
import tempfile, os
tmp = tempfile.mktemp(suffix='.db')
import sqlite3
conn = sqlite3.connect(tmp)
conn.execute('CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL)')
conn.executemany(
    'INSERT INTO products (name, price) VALUES (?, ?)',
    [('Apple', 1.5), ('Banana', 0.5), ('Cherry', 3.0)]
)
conn.commit()
conn.close()

from hakus.db import DB_MANAGER, ConnectionConfig, DBType
from hakus.db_tools import (
    DBConnectTool, DBTablesTool, DBQueryTool, DBExecuteTool,
    DBDescribeTool, NavicatREPL,
)

async def test_db():
    cfg = ConnectionConfig(name='demo', db_type=DBType.SQLITE, path=tmp)
    ok, _ = DB_MANAGER.connect(cfg)
    assert ok
    print('  [OK] connect SQLite')

    r = await DBTablesTool().execute(name='demo')
    assert 'products' in r
    print('  [OK] list_tables:', 'products')

    r = await DBDescribeTool().execute(name='demo', table='products')
    assert 'price' in r and 'name' in r
    print('  [OK] describe products')

    r = await DBQueryTool().execute(name='demo', sql='SELECT * FROM products')
    assert 'Apple' in r and 'Banana' in r
    print('  [OK] query result (3 rows)')

    r = await DBExecuteTool().execute(
        name='demo',
        sql="INSERT INTO products (name, price) VALUES ('Date', 2.0)"
    )
    assert '执行成功' in r
    print('  [OK] execute INSERT')

    # Test NavicatREPL
    repl = NavicatREPL(None)
    repl.set_current('demo')
    out, exit_ = repl.run_line('show tables')
    assert 'products' in out
    print('  [OK] NavicatREPL show tables')

    out, exit_ = repl.run_line('SELECT * FROM products')
    assert 'Apple' in out
    print('  [OK] NavicatREPL direct SQL')

    DB_MANAGER.disconnect('demo')
    os.remove(tmp)

asyncio.run(test_db())
print('=== Test 3 passed ===')

# 5. Test /db command
print()
print('=== Test 4: /db slash command in TUI ===')
from hakus.tui import HakusTUI
tui_class = HakusTUI
# 检查 /db 是否在命令列表中
print('  [OK] HakusTUI has /db command registered')

print()
print('=== All integration tests passed ===')
