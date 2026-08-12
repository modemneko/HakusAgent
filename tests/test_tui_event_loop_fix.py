"""
验证 _run_async_in_fresh_loop 在 TUI 事件循环上下文中的行为。

模拟场景：TUI 的 run_stream() 是一个 async 方法，
已运行在事件循环中。slash 命令 /orchestrate 触发 _start_orchestrator()，
原实现使用 asyncio.new_event_loop() 触发 "Cannot run the event loop
while another loop is running"。修复后通过子线程隔离事件循环。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def tui_main():
    """模拟 TUI 自身的事件循环"""
    from hakus.tui import HakusTUI
    from unittest.mock import MagicMock

    agent = MagicMock()
    agent._model_type = "deepseek"
    agent._permission.mode.value = "auto"
    agent._context.working_dir = os.getcwd()
    agent._tool_registry = MagicMock()
    agent._tool_registry.get.return_value = None
    agent.get_checkpoints.return_value = []

    tui = HakusTUI.__new__(HakusTUI)
    tui._agent = agent
    tui._session = MagicMock()
    tui._console = None

    async def fake_coro(x):
        await asyncio.sleep(0.05)
        return f"coro_result_for_{x}"

    loop = asyncio.get_running_loop()
    print(f"主事件循环 id: {id(loop)}")
    print(f"当前是否有事件循环在跑: {asyncio.get_running_loop() is not None}")

    result = tui._run_async_in_fresh_loop(fake_coro, "hello")
    print(f"_run_async_in_fresh_loop 返回: {result}")
    assert result == "coro_result_for_hello", f"unexpected: {result}"

    async def failing_coro():
        raise ValueError("test error")

    try:
        tui._run_async_in_fresh_loop(failing_coro)
    except ValueError as e:
        print(f"异常正确传递: {e}")
    else:
        raise AssertionError("应当抛出异常")

    print("OK TUI event loop isolation verified")


def main():
    asyncio.run(tui_main())


if __name__ == "__main__":
    main()
