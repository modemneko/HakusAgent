"""
HakusAI 增强功能使用示例
展示如何集成超时、重试、循环控制、恢复等功能
"""

import asyncio
from typing import AsyncIterator, Dict, Any

# 导入增强模块
from hakus.timeout import TimeoutManager, TimeoutConfig, TimeoutLevel
from hakus.improved_loop import ImprovedAgentLoop, AgentLoopConfig
from hakus.recovery import RecoveryManager, SessionSnapshot
from hakus.enhanced_agent import EnhancedAgent, EnhancedAgentConfig


async def example_basic_timeout():
    """基础超时示例"""
    print("=== 基础超时示例 ===\n")
    
    # 创建超时管理器
    config = TimeoutConfig(
        tool_timeout=30.0,
        provider_timeout=60.0,
        chunk_timeout=10.0,
    )
    manager = TimeoutManager(config)
    
    # 示例：带超时的操作
    async def slow_operation():
        await asyncio.sleep(5)
        return "操作完成"
    
    try:
        result = await manager.with_timeout(
            slow_operation(),
            timeout=2.0,
            level=TimeoutLevel.TOOL,
            operation="慢操作",
        )
        print(f"结果: {result}")
    except Exception as e:
        print(f"超时: {e}")
    
    print()


async def example_retry_mechanism():
    """重试机制示例"""
    print("=== 重试机制示例 ===\n")
    
    from hakus.timeout import RetryManager
    
    manager = RetryManager()
    
    # 模拟失败的操作
    attempt = 0
    
    async def failing_operation():
        nonlocal attempt
        attempt += 1
        if attempt < 3:
            raise ConnectionError(f"连接失败 (尝试 {attempt})")
        return "成功!"
    
    # 带重试的执行
    for i in range(3):
        try:
            result = await failing_operation()
            print(f"成功: {result}")
            break
        except Exception as e:
            if manager.is_retryable(e):
                delay = manager.calculate_delay(i + 1)
                print(f"可重试错误: {e}, 等待 {delay:.1f}s...")
                await asyncio.sleep(min(delay, 1.0))  # 缩短演示时间
            else:
                print(f"不可重试错误: {e}")
                break
    
    print()


async def example_doom_loop_detection():
    """Doom Loop 检测示例"""
    print("=== Doom Loop 检测示例 ===\n")
    
    from hakus.improved_loop import DoomLoopDetector
    
    detector = DoomLoopDetector(window_size=3, threshold=3)
    
    # 模拟工具调用
    calls = [
        ("read_file", {"path": "/some/file.txt"}),
        ("edit_file", {"path": "/some/file.txt", "content": "new"}),
        ("read_file", {"path": "/some/file.txt"}),  # 重复
        ("edit_file", {"path": "/some/file.txt", "content": "new"}),  # 重复
        ("read_file", {"path": "/some/file.txt"}),  # 重复 - 应该检测到
    ]
    
    for tool_name, tool_input in calls:
        detector.record(tool_name, tool_input)
        is_loop, loop_tool = detector.is_loop_detected()
        
        if is_loop:
            print(f"  检测到 Doom Loop! 工具: {loop_tool}")
            detector.reset()
        else:
            print(f"  正常调用: {tool_name}")
    
    print()


async def example_context_monitoring():
    """上下文监控示例"""
    print("=== 上下文监控示例 ===\n")
    
    from hakus.improved_loop import ContextMonitor
    
    monitor = ContextMonitor(max_tokens=10000, threshold=0.7)
    
    # 模拟上下文增长
    token_counts = [1000, 3000, 5000, 7000, 8000, 9500]
    
    for tokens in token_counts:
        monitor.update(tokens)
        usage = monitor.get_usage_percentage()
        warning = monitor.is_overflow_warning()
        critical = monitor.is_overflow_critical()
        
        status = "正常"
        if critical:
            status = "临界溢出!"
        elif warning:
            status = "警告"
        
        print(f"  Token: {tokens}, 使用率: {usage:.1%}, 状态: {status}")
    
    print()


async def example_session_recovery():
    """会话恢复示例"""
    print("=== 会话恢复示例 ===\n")
    
    import tempfile
    import os
    
    # 使用临时数据库
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "recovery.db")
        manager = RecoveryManager(db_path)
        
        # 创建会话快照
        snapshot = SessionSnapshot(
            session_id="test_session",
            iteration=5,
            messages=[
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好!"},
            ],
            tool_states={},
            context_tokens=1000,
            timestamp=1234567890.0,
        )
        
        # 保存快照
        snapshot_id = manager.save_snapshot(snapshot)
        print(f"  保存快照: {snapshot_id}")
        
        # 加载快照
        loaded = manager.load_snapshot(snapshot_id)
        if loaded:
            print(f"  加载快照: 迭代 {loaded.iteration}, 消息数 {len(loaded.messages)}")
        
        # 获取最新快照
        latest = manager.get_latest_snapshot("test_session")
        if latest:
            print(f"  最新快照: 迭代 {latest.iteration}")
    
    print()


async def example_enhanced_agent():
    """增强 Agent 示例"""
    print("=== 增强 Agent 示例 ===\n")
    
    # 创建增强 Agent 配置
    config = EnhancedAgentConfig(
        llm_timeout=60.0,
        tool_timeout=30.0,
        max_iterations=10,
        soft_stop_threshold=8,
        max_retries=2,
    )
    
    agent = EnhancedAgent(config)
    
    # 模拟 LLM 调用
    async def mock_llm_call(messages, system_prompt_suffix="", **kwargs):
        await asyncio.sleep(0.1)
        return {
            "content": f"这是 LLM 响应 (迭代 {agent.agent_loop.current_iteration})",
            "tool_calls": [],
        }
    
    # 模拟工具执行
    async def mock_tool_executor(tool_name, tool_input):
        await asyncio.sleep(0.1)
        return {"result": f"{tool_name} 执行完成"}
    
    # 运行
    messages = [{"role": "user", "content": "测试任务"}]
    
    events = []
    async for event in agent.run_with_enhancements(
        messages=messages,
        llm_caller=mock_llm_call,
        tool_executor=mock_tool_executor,
        session_id="demo_session",
    ):
        events.append(event)
        if event.get("type") in ["turn_completed", "loop_stopped"]:
            print(f"  {event.get('type')}: {event.get('reason', event.get('content', ''))}")
            break
    
    # 显示状态
    status = agent.get_status()
    print(f"  最终状态: 迭代 {status['iteration']}, 软停止 {status['soft_stopped']}")
    
    print()


async def main():
    """运行所有示例"""
    print("HakusAI 增强功能示例\n")
    
    await example_basic_timeout()
    await example_retry_mechanism()
    await example_doom_loop_detection()
    await example_context_monitoring()
    await example_session_recovery()
    await example_enhanced_agent()
    
    print("所有示例完成!")


if __name__ == "__main__":
    asyncio.run(main())