"""
HakusAI v2 使用示例
展示如何使用新的架构
"""

import asyncio
from hakusai_core.v2 import (
    # Schema
    AgentConfig,
    AgentMode,
    Message,
    ToolResult,
    
    # Tools
    ToolRegistry,
    ToolExecutor,
    create_default_registry,
    
    # Agent
    BaseAgent,
    BuildAgent,
    PlanAgent,
    AgentFactory,
    
    # Session
    SessionStore,
    
    # Models
    ClientFactory,
    LLMClient,
)


async def example_basic_usage():
    """基础使用示例"""
    print("=== HakusAI v2 基础使用示例 ===\n")
    
    # 1. 创建工具注册表
    print("1. 创建工具注册表...")
    registry = create_default_registry()
    print(f"   已注册 {len(registry.list_tools())} 个工具")
    print(f"   工具列表: {registry.list_tool_names()}\n")
    
    # 2. 使用工具
    print("2. 使用工具读取文件...")
    result = await registry.execute("read", {
        "filePath": "README.md",
    })
    print(f"   结果: {'成功' if result.success else '失败'}")
    if result.success:
        print(f"   内容预览: {result.output[:100]}...")
    print()
    
    # 3. 创建 Agent
    print("3. 创建 Build Agent...")
    agent = AgentFactory.create(
        "build",
        tool_registry=registry,
    )
    print(f"   Agent 名称: {agent.name}")
    print(f"   Agent 模式: {agent.mode}")
    print(f"   系统提示词: {agent.get_system_prompt()[:100]}...")
    print()
    
    # 4. 执行任务
    print("4. 执行任务...")
    # result = await agent.execute("读取 README.md 文件")
    # print(f"   结果: {result}")
    print()


async def example_session_management():
    """会话管理示例"""
    print("=== 会话管理示例 ===\n")
    
    # 1. 创建会话存储
    print("1. 创建会话存储...")
    store = SessionStore("example.db")
    
    # 2. 创建新会话
    print("2. 创建新会话...")
    session = store.create_session(
        project_id="my-project",
        agent_type="build",
        model_provider="openai",
        model_name="gpt-4",
    )
    print(f"   会话 ID: {session.id}")
    print(f"   项目 ID: {session.config.project_id}")
    print()
    
    # 3. 保存消息
    print("3. 保存消息...")
    from datetime import datetime
    message = Message(
        id="msg_1",
        role="user",
        content="你好，请帮我读取 README.md 文件",
        timestamp=datetime.now(),
    )
    store.save_message(session.id, message)
    print("   消息已保存")
    print()
    
    # 4. 获取会话
    print("4. 获取会话...")
    retrieved_session = store.get_session(session.id)
    if retrieved_session:
        print(f"   会话消息数: {len(retrieved_session.messages)}")
    print()
    
    # 清理
    import os
    if os.path.exists("example.db"):
        os.remove("example.db")


async def example_agent_types():
    """Agent 类型示例"""
    print("=== Agent 类型示例 ===\n")
    
    # 创建工具注册表
    registry = create_default_registry()
    
    # 列出所有 Agent 类型
    print("可用的 Agent 类型:")
    for agent_type in AgentFactory.list_agents():
        print(f"  - {agent_type}")
    print()
    
    # 创建不同类型的 Agent
    for agent_type in AgentFactory.list_agents():
        agent = AgentFactory.create(agent_type, tool_registry=registry)
        print(f"{agent_type} Agent:")
        print(f"  名称: {agent.name}")
        print(f"  模式: {agent.mode}")
        print(f"  提示词: {agent.get_system_prompt()[:50]}...")
        print()


async def main():
    """主函数"""
    print("HakusAI v2 示例程序\n")
    
    await example_basic_usage()
    await example_session_management()
    await example_agent_types()
    
    print("示例完成！")


if __name__ == "__main__":
    asyncio.run(main())