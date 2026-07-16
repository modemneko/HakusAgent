import argparse
import asyncio
import os
import sys
import warnings

# Warning/print suppression is now in hakus/__init__.py (loaded first)
# These are just backups in case __init__.py is bypassed
warnings.filterwarnings("ignore")
os.environ.setdefault("TORCHAUDIO_USE_FFMPEG", "0")

from utils.config import BASE_CONFIG
from utils.logger import get_logger, quiet_console_loggers
from .agent import AgentCore
from .permission import PermissionMode
from .memory import ProjectMemory
from .plan_mode import PlanManager
from .hooks import HookRegistry, HookChain, setup_default_hooks
from .session_store import load_last_session, save_last_session, restore_latest_checkpoint

logger = get_logger(__name__)


def _quiet_logging() -> None:
    """Claude Code 风格: 控制台只显示状态/进度, 详细日志写入 ~/.hakus/logs/hakusai.log."""
    quiet_console_loggers()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="hakusai",
        description="HakusAI - AI 智能终端助手",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="模型选择 (deepseek, qwen, gemini, glm, mimo, ollama)",
    )
    parser.add_argument(
        "--permission", "-p",
        type=str,
        choices=["ask", "bypass", "danger_auto", "auto"],
        default="ask",
        help="权限模式 (default: ask). 'ask'=每次危险操作都确认; "
             "'bypass'/'danger_auto'/'auto'=全部放行(仅受严格策略保护)",
    )
    parser.add_argument(
        "--voice", "-v",
        action="store_true",
        default=False,
        help="启用语音模式",
    )
    parser.add_argument(
        "--task", "-t",
        type=str,
        default=None,
        help="直接启动后台任务",
    )
    parser.add_argument(
        "--workdir", "-w",
        type=str,
        default=None,
        help="工作目录",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=0,
        help="最大 Agent 迭代次数 (default: 从配置文件读取，默认100)",
    )
    parser.add_argument(
        "--print", "-e",
        type=str,
        default=None,
        help="一次性查询后退出（非交互模式）",
    )
    parser.add_argument(
        "--continue", "-c",
        action="store_true",
        default=False,
        dest="continue_session",
        help="恢复上一次会话",
    )
    parser.add_argument(
        "--version", "-V",
        action="store_true",
        default=False,
        help="显示版本号",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        default=False,
        help="初始化用户配置文件 (~/.hakus/config.yaml)",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        default=False,
        help="进入 Plan 模式 (先制定计划再执行)",
    )
    parser.add_argument(
        "--add-dir",
        type=str,
        action="append",
        default=None,
        help="添加额外可访问的目录 (可多次使用)",
    )
    return parser.parse_args()


def _init_components(args: argparse.Namespace) -> AgentCore:
    model_type = args.model or BASE_CONFIG.get("DEFAULT_MODEL", "opencode")

    permission_mode = PermissionMode(args.permission)

    working_dir = args.workdir or os.getcwd()
    if not os.path.isdir(working_dir):
        logger.warning(f"Working directory does not exist: {working_dir}, using cwd")
        working_dir = os.getcwd()

    session_id = None
    if getattr(args, "continue_session", False):
        last = load_last_session()
        if last:
            session_id = last.get("session_id")
            if not args.workdir and last.get("working_dir") and os.path.isdir(last["working_dir"]):
                working_dir = last["working_dir"]
            logger.info(f"Continuing session: {session_id}")
        else:
            logger.warning("--continue requested but no previous session found")

    # 从配置文件读取 Agent 配置，命令行参数优先
    agent_config = BASE_CONFIG.get("agent", {})
    max_iterations = args.max_iterations or agent_config.get("max_iterations", 100)
    llm_timeout = agent_config.get("llm_timeout", 180)
    tool_timeout = agent_config.get("tool_timeout", 120)
    follow_up_timeout = agent_config.get("follow_up_timeout", 180)
    max_context_tokens = agent_config.get("max_context_tokens", 200000)
    
    logger.info(f"Agent config: max_iterations={max_iterations}, llm_timeout={llm_timeout}s, "
                f"tool_timeout={tool_timeout}s, max_context_tokens={max_context_tokens}")

    agent = AgentCore(
        model_type=model_type,
        permission_mode=permission_mode,
        max_iterations=max_iterations,
        max_context_tokens=max_context_tokens,
        working_dir=working_dir,
        session_id=session_id,
        llm_timeout=llm_timeout,
        tool_timeout=tool_timeout,
        follow_up_timeout=follow_up_timeout,
    )

    try:
        # Auxiliary snake_case tools are already registered by
        # AgentCore.__init__ via ToolRegistry.register_builtin(), so this
        # block is a no-op kept only for backward compat with plugins that
        # may still call register_auxiliary_tools externally.
        from .tools import ToolRegistry
        registry: ToolRegistry = agent._tool_registry
        registry.register_builtin()
        logger.info("Built-in tools registered")
    except Exception as e:
        logger.warning(f"Failed to register built-in tools: {e}")

    try:
        from .dev_tools import register_dev_tools
        n = register_dev_tools(agent._tool_registry)
        logger.info(f"Registered {n} dev tools (Read/Write/Edit/Glob/Grep/Bash/...)")
    except Exception as e:
        logger.warning(f"Failed to register dev tools: {e}")

    try:
        from .db_tools import register_db_tools
        n_db = register_db_tools(agent._tool_registry)
        logger.info(f"Registered {n_db} database tools (Navicat-style)")
    except Exception as e:
        logger.warning(f"Failed to register db tools: {e}")

    if BASE_CONFIG.get("MEMORY_ENABLED", False):
        try:
            from .memory_vector import MemoryManager
            memory = MemoryManager(uid="default")
            agent.set_memory(memory)
            logger.info("Memory manager initialized")
        except ImportError:
            logger.info("Memory manager not available")
        except Exception as e:
            logger.debug(f"Failed to initialize memory: {e}")
    else:
        logger.debug("Memory manager disabled by config (memory.enabled=false)")

    project_memory = ProjectMemory(working_dir)
    memory_content = project_memory.load()
    if memory_content:
        logger.info(f"Loaded project memory: {len(project_memory.list_loaded())} file(s)")

    plan_manager = PlanManager()

    hook_registry = HookRegistry()
    setup_default_hooks(hook_registry)
    hook_chain = HookChain(hook_registry)

    try:
        from .orchestrator import Orchestrator, OrchestratorConfig
        # Use the user's current project directory as workspace so
        # files are written where the user expects them, not in ~/.hakus/
        workspace_dir = working_dir
        orchestrator = Orchestrator(
            root_agent=agent,
            workspace_dir=workspace_dir,
            config=OrchestratorConfig(
                batch_size=int(BASE_CONFIG.get("ORCHESTRATOR_BATCH_SIZE", 5)),
                max_fix_rounds=int(BASE_CONFIG.get("ORCHESTRATOR_MAX_FIX_ROUNDS", 5)),
                use_multi_dim_test=bool(BASE_CONFIG.get("ORCHESTRATOR_MULTI_DIM", True)),
            ),
        )
        agent._orchestrator = orchestrator
        logger.info(
            f"Orchestrator ready (multi-dim={orchestrator._config.use_multi_dim_test}, "
            f"dims={orchestrator._config.test_dimensions})"
        )
    except Exception as e:
        logger.warning(f"Failed to initialize orchestrator: {e}")
        agent._orchestrator = None

    system_prompt_parts = [
        "You are HakusAI, an AI-powered development assistant that lives in the terminal.",
        "You have access to a complete set of development tools:",
        "- File ops: Read, Write, Edit, MultiEdit, Glob, Grep, Tree",
        "- Shell: Bash, PowerShell, BashOutput",
        "- Web: WebFetch, WebSearch",
        "- Tasks: TodoWrite, AskUserQuestion",
        "- Git: GitStatus, GitDiff, GitCommit, GitLog",
        "",
        "CRITICAL GUIDELINES:",
        "1. **Use specialized tools first** - For file operations, ALWAYS prefer Read/Edit/Write/Glob/Grep",
        "   over cat/sed/grep/find shell commands. Use Bash only when shell-specific.",
        "2. **Read before Edit** - Always Read a file before using Edit. The Edit tool's old_string",
        "   must be unique - if not, use replace_all or provide more context.",
        "3. **Plan complex tasks** - For non-trivial work, use the Plan workflow (enter plan mode,",
        "   output a plan, then execute).",
        "4. **Be concise and accurate** - Don't over-explain. Focus on solving the user's problem.",
        "5. **Project memory** - .hakus.md / CLAUDE.md files contain project conventions. Read them",
        "   when working in a project for the first time.",
        "",
        "When asked to do development work, follow this loop:",
        "1. Use Glob/Grep to understand the codebase",
        "2. Use Read to examine relevant files",
        "3. Use TodoWrite to track progress",
        "4. Use Edit/Write to make changes",
        "5. Use Bash to test (build/run tests)",
        "6. Use Git to commit when done",
        "",
        "---",
        "## 多智能体协同硬约束 (Orchestrator Mode)",
        "当用户使用 `/orchestrate <requirement>` 触发协同时，你必须遵守：",
        "1. **只编排不干活** — 不要直接编辑代码，所有修改委托给 DevAgent",
        "2. **失败重测只 resume 失败维度**（layout/beauty/animation/security/...）",
        "3. **保持上下文整洁** — 不读子 agent 的产出文件内容，只接收路径和 PASS/FAIL",
        "4. **时间戳格式**: yymmdd hhmm（如 260602 1430）",
        "5. **测试并发上限 = 3**，按维度精准 resume，不重建通过的维度",
    ]

    if memory_content:
        system_prompt_parts.append("")
        system_prompt_parts.append("---")
        system_prompt_parts.append(memory_content)

    system_prompt = chr(10).join(system_prompt_parts)
    agent.set_system_prompt(system_prompt)
    agent.update_dynamic_context("working_dir", working_dir)

    agent._project_memory = project_memory
    agent._plan_manager = plan_manager
    agent._hook_registry = hook_registry
    agent._hook_chain = hook_chain

    try:
        agent._checkpoint.load(agent._session_id)
        logger.info(f"Checkpoints loaded for session: {agent._session_id}")
        if getattr(args, "continue_session", False):
            if restore_latest_checkpoint(agent):
                logger.info("Previous conversation context restored")
    except Exception:
        pass

    return agent


async def _run_one_shot(agent: AgentCore, query: str) -> None:
    print(f"\n> {query}\n")
    response = await agent.process(query)
    if response.content:
        print(response.content)
    print()


def main() -> None:
    # Fix Windows GBK encoding for emoji/Unicode
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    # 版本标识 — 用于确认新代码已加载
    print("=== HakusAI v2 OpenCode Layout ===", file=sys.stderr, flush=True)
    
    args = _parse_args()
    _quiet_logging()

    if args.version:
        print("HakusAI v2.0.0")
        return

    if args.setup:
        from utils.config import init_user_config_from_template, ensure_user_config_dir
        config_dir = ensure_user_config_dir()
        try:
            path = init_user_config_from_template()
            print(f"[OK] 配置文件已生成: {path}")
            print(f"     请编辑该文件填入你的 API Key 和模型配置")
            print(f"     支持的模型商: OpenAI, Anthropic, DeepSeek, Qwen, Gemini, GLM, MiMo, Ollama")
            return
        except FileNotFoundError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)

    try:
        agent = _init_components(args)
    except Exception as e:
        print(f"Failed to initialize: {e}", file=sys.stderr)
        sys.exit(1)

    if args.add_dir:
        for d in args.add_dir:
            d = os.path.abspath(d)
            if os.path.isdir(d):
                agent.update_dynamic_context(f"allowed_dir:{d}", d)
                logger.info(f"Added accessible dir: {d}")

    if args.plan and hasattr(agent, '_plan_manager'):
        agent._plan_manager.enter_plan_mode()

    voice_enabled = args.voice

    try:
        if args.print:
            asyncio.run(_run_one_shot(agent, args.print))
            return

        if args.task:
            # 后台任务：直接用 agent 处理，不启动 TUI
            response = asyncio.run(agent.process(args.task))
            if response.content:
                print(response.content)
            return

        # 启动 TUI v2 (Textual)
        from .tui_v2 import HakusApp
        app = HakusApp(agent, voice_enabled=voice_enabled)
        app.run()

    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            agent._checkpoint.persist(agent._session_id)
            save_last_session(agent._session_id, agent._context.working_dir or os.getcwd())
        except Exception:
            pass


if __name__ == "__main__":
    main()
