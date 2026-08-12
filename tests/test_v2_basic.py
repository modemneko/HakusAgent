"""
HakusAI v2 简单测试
验证基本功能是否正常工作
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


async def test_tool_registry():
    """测试工具注册表"""
    print("测试工具注册表...")
    
    from hakusai_core.v2 import ToolRegistry, create_default_registry
    
    registry = create_default_registry()
    
    # 检查工具数量
    tools = registry.list_tools()
    print(f"  已注册工具数量: {len(tools)}")
    assert len(tools) >= 10, f"工具数量不足，期望 >= 10，实际 {len(tools)}"
    
    # 检查工具名称
    tool_names = registry.list_tool_names()
    print(f"  工具名称: {tool_names}")
    assert "read" in tool_names
    assert "write" in tool_names
    assert "edit" in tool_names
    assert "bash" in tool_names
    
    print("  ✓ 工具注册表测试通过\n")


async def test_agent_factory():
    """测试 Agent 工厂"""
    print("测试 Agent 工厂...")
    
    from hakusai_core.v2 import AgentFactory, create_default_registry
    
    registry = create_default_registry()
    
    # 测试创建 Build Agent
    build_agent = AgentFactory.create("build", tool_registry=registry)
    assert build_agent.name == "build"
    print(f"  Build Agent: {build_agent.name}")
    
    # 测试创建 Plan Agent
    plan_agent = AgentFactory.create("plan", tool_registry=registry)
    assert plan_agent.name == "plan"
    print(f"  Plan Agent: {plan_agent.name}")
    
    # 测试列出 Agent
    agents = AgentFactory.list_agents()
    print(f"  可用 Agent: {agents}")
    assert "build" in agents
    assert "plan" in agents
    
    print("  ✓ Agent 工厂测试通过\n")


async def test_session_store():
    """测试会话存储"""
    print("测试会话存储...")
    
    from hakusai_core.v2 import SessionStore, Message
    from datetime import datetime
    
    # 使用临时数据库
    db_path = "test_session.db"
    store = SessionStore(db_path)
    
    # 创建会话
    session = store.create_session(
        project_id="test-project",
        agent_type="build",
    )
    print(f"  创建会话: {session.id}")
    assert session.id is not None
    
    # 保存消息
    message = Message(
        id="msg_1",
        role="user",
        content="测试消息",
        timestamp=datetime.now(),
    )
    store.save_message(session.id, message)
    print("  保存消息成功")
    
    # 获取会话
    retrieved = store.get_session(session.id)
    assert retrieved is not None
    assert len(retrieved.messages) == 1
    print(f"  获取会话成功，消息数: {len(retrieved.messages)}")
    
    # 清理
    import os
    if os.path.exists(db_path):
        os.remove(db_path)
    
    print("  ✓ 会话存储测试通过\n")


async def test_schema_models():
    """测试 Schema 模型"""
    print("测试 Schema 模型...")
    
    from hakusai_core.v2 import (
        AgentConfig,
        AgentMode,
        Message,
        ToolResult,
        SessionConfig,
    )
    from datetime import datetime
    
    # 测试 AgentConfig
    config = AgentConfig(
        name="test-agent",
        mode=AgentMode.BUILD,
    )
    assert config.name == "test-agent"
    assert config.mode == AgentMode.BUILD
    print("  AgentConfig 测试通过")
    
    # 测试 Message
    message = Message(
        id="msg_1",
        role="user",
        content="测试内容",
        timestamp=datetime.now(),
    )
    assert message.id == "msg_1"
    print("  Message 测试通过")
    
    # 测试 ToolResult
    result = ToolResult(
        success=True,
        output="测试输出",
    )
    assert result.success is True
    print("  ToolResult 测试通过")
    
    print("  ✓ Schema 模型测试通过\n")


async def main():
    """运行所有测试"""
    print("=== HakusAI v2 测试 ===\n")
    
    try:
        await test_tool_registry()
        await test_agent_factory()
        await test_session_store()
        await test_schema_models()
        
        print("=== 所有测试通过！===\n")
        return True
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)