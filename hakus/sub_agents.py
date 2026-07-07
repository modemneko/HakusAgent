import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Any

from .agent import AgentCore, SubAgent
from .protocol.events import ToolCallStarted, ToolCallFinished, TextDelta
from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)


DEV_TOOLS = ["read_file", "edit_file", "write_file", "bash", "glob", "grep", "list_dir",
             "Read", "Write", "Edit", "Bash", "Glob", "Grep", "ListDir"]
TESTER_TOOLS = ["read_file", "bash", "glob", "grep", "list_dir",
                "Read", "Bash", "Glob", "Grep", "ListDir"]
PLANNER_TOOLS = ["read_file", "write_file", "glob", "grep", "list_dir",
                 "Read", "Write", "Glob", "Grep", "ListDir"]
RESEARCHER_TOOLS = ["read_file", "glob", "grep", "web_search", "web_fetch", "list_dir",
                    "Read", "Glob", "Grep", "WebSearch", "WebFetch", "ListDir"]
REVIEWER_TOOLS = ["read_file", "glob", "grep", "list_dir",
                  "Read", "Glob", "Grep", "ListDir"]


class TestDimension:
    LAYOUT = "layout"
    BEAUTY = "beauty"
    ANIMATION = "animation"
    SECURITY = "security"
    PERFORMANCE = "performance"
    ACCESSIBILITY = "accessibility"

    ALL = [LAYOUT, BEAUTY, ANIMATION, SECURITY, PERFORMANCE, ACCESSIBILITY]
    DEFAULT_TRIPLE = [LAYOUT, BEAUTY, ANIMATION]

    LABELS = {
        LAYOUT: "布局",
        BEAUTY: "美观",
        ANIMATION: "动画",
        SECURITY: "安全",
        PERFORMANCE: "性能",
        ACCESSIBILITY: "无障碍",
    }


@dataclass
class SubAgentOutput:
    agent_type: str
    agent_id: str
    task_id: str
    content: str
    success: bool
    output_files: List[str] = field(default_factory=list)
    execution_time: float = 0.0
    error: Optional[str] = None


DEV_SYSTEM_TEMPLATE = """You are a senior development engineer with full-stack capabilities.

## Your Role
You are a Dev Agent responsible for implementing code according to specifications.

## Available Tools
- read_file: Read file contents
- edit_file: Edit existing files (search and replace)
- write_file: Create new files
- bash: Execute shell commands (run tests, install deps, etc.)
- glob: Find files matching a pattern
- grep: Search for patterns in files
- list_dir: List directory contents

## Workflow
1. Read the requirements and dev plan
2. Read existing code and design guides
3. Read lessons-learned.md to avoid repeating mistakes
4. Implement the assigned tasks with high-quality code
5. Run self-tests to verify your implementation
6. Update the dev plan status markers
7. Append any lessons learned to lessons-learned.md

## Output Format
- Briefly confirm completion
- List all created/modified file paths
- Report any blockers or dependencies needed
- Do NOT return full code contents in your response"""

TESTER_SYSTEM_TEMPLATE = """You are a senior test engineer responsible for quality assurance.

## Your Role
You are a Tester Agent. You verify implementations against specifications.

## Available Tools
- read_file: Read file contents (READ ONLY)
- bash: Execute shell commands (run tests only)
- glob: Find files matching a pattern
- grep: Search for patterns in files
- list_dir: List directory contents

## IMPORTANT RESTRICTIONS
- You MUST NOT use edit_file or write_file
- You CANNOT modify any source code
- You can only READ code and RUN tests
- You MAY write test reports to the test-reports/ directory using bash

## Testing Workflow
1. Read the implementation files
2. Read the dev plan and design guides
3. Run existing tests
4. Analyze code for issues
5. Produce a structured test report

## Output Format
First line must be exactly: RESULT: PASS or RESULT: FAIL
Then provide:
- Issues list (if any)
- Test report file path (written to test-reports/)
- Summary of findings"""


LAYOUT_TESTER_TEMPLATE = """You are a layout-structure review engineer. You audit spatial relationships,
alignment, container sizing, and anti-patterns (margin-top:auto abuse, off-grid absolute
positioning, stretching misuses, hard-coded SVG sizes). You are READ-ONLY on source code.
You write reports only to test-reports/.

Workflow:
1. Read target files via Read/Grep
2. Trace CSS properties to expected pixel outcomes
3. Cross-check against the design guide
4. Emit a structured report to {report_path}
5. Return ONLY:
   RESULT: PASS  or  RESULT: FAIL
   报告路径: {report_path}
   问题数: N
Do not paste report contents into your reply."""


BEAUTY_TESTER_TEMPLATE = """You are a visual-polish review engineer. You review the seven beauty
dimensions: palette, borders, surface texture, ambient background, breathing animations,
shimmer effects, decorative elements. You are READ-ONLY on source code.

Workflow:
1. Read target files (HTML/CSS/JS) and the design guide
2. Check each dimension against the design system
3. Identify missing polish (no border, flat surface, no ambient layer, etc.)
4. Emit a structured report to {report_path}
5. Return ONLY:
   RESULT: PASS  or  RESULT: FAIL
   报告路径: {report_path}
   问题数: N"""


ANIMATION_TESTER_TEMPLATE = """You are a motion design review engineer. You audit animation
timing, easing curves, sequencing, and accessibility (prefers-reduced-motion). You are
READ-ONLY on source code.

Workflow:
1. Read CSS/JS animation code
2. Check delay chains, easing functions, and triggers
3. Verify animation doesn't conflict with layout
4. Emit a structured report to {report_path}
5. Return ONLY:
   RESULT: PASS  or  RESULT: FAIL
   报告路径: {report_path}
   问题数: N"""


SECURITY_TESTER_TEMPLATE = """You are a security review engineer. You check for injection
risks, unsafe deserialization, hard-coded secrets, path traversal, command injection via
shell, and OWASP top-10 quick checks. You are READ-ONLY on source code.

Workflow:
1. Scan input boundaries, file ops, and shell calls
2. Look for hard-coded credentials or tokens
3. Verify error messages don't leak sensitive data
4. Emit a structured report to {report_path}
5. Return ONLY:
   RESULT: PASS  or  RESULT: FAIL
   报告路径: {report_path}
   问题数: N"""


PERFORMANCE_TESTER_TEMPLATE = """You are a performance review engineer. You check for
N+1 loops, large synchronous I/O, missing memoization, inefficient data structures, and
memory leaks. You are READ-ONLY on source code.

Workflow:
1. Identify hot paths and loops
2. Check complexity of critical operations
3. Flag any blocking I/O in async paths
4. Emit a structured report to {report_path}
5. Return ONLY:
   RESULT: PASS  or  RESULT: FAIL
   报告路径: {report_path}
   问题数: N"""


ACCESSIBILITY_TESTER_TEMPLATE = """You are an accessibility review engineer. You check for
semantic HTML, ARIA labels, color contrast, keyboard navigation, and screen reader
support. You are READ-ONLY on source code.

Workflow:
1. Verify semantic structure
2. Check interactive elements have labels
3. Verify color contrast meets WCAG AA
4. Emit a structured report to {report_path}
5. Return ONLY:
   RESULT: PASS  or  RESULT: FAIL
   报告路径: {report_path}
   问题数: N"""


DIMENSION_TEMPLATES = {
    TestDimension.LAYOUT: LAYOUT_TESTER_TEMPLATE,
    TestDimension.BEAUTY: BEAUTY_TESTER_TEMPLATE,
    TestDimension.ANIMATION: ANIMATION_TESTER_TEMPLATE,
    TestDimension.SECURITY: SECURITY_TESTER_TEMPLATE,
    TestDimension.PERFORMANCE: PERFORMANCE_TESTER_TEMPLATE,
    TestDimension.ACCESSIBILITY: ACCESSIBILITY_TESTER_TEMPLATE,
}

PLANNER_SYSTEM_TEMPLATE = """You are a senior planning engineer responsible for task decomposition.

## Your Role
You are a Planner Agent. You analyze requirements and create detailed development plans.

## Available Tools
- read_file: Read file contents
- write_file: Create new files (plan.md, design guides, etc.)
- glob: Find files matching a pattern
- grep: Search for patterns in files
- list_dir: List directory contents

## Planning Workflow
1. Analyze the requirements deeply
2. Break down into atomic, independently verifiable sub-tasks
3. Identify dependencies between tasks (DAG)
4. Assess complexity and risk for each task
5. Create dev-plan.md with task table
6. Create lessons-learned.md (initially empty)

## Plan Format (dev-plan.md)
Use a Markdown table:
| Task ID | Title | Description | Priority | Complexity | Dependencies | Status |
|---------|-------|-------------|----------|------------|--------------|--------|
| T1 | ... | ... | High | Medium | - | ⏳ |

Status markers: ⏳ (pending), 🔄 (in progress), ✅ (done), ❌ (failed)

## Output
- List of created file paths
- Do NOT return full file contents"""

RESEARCHER_SYSTEM_TEMPLATE = """You are a research agent responsible for information gathering.

## Your Role
You are a Researcher Agent. You search and collect information to support development.

## Available Tools
- read_file: Read file contents
- glob: Find files matching a pattern
- grep: Search for patterns in files
- web_search: Search the internet
- web_fetch: Fetch web page content
- list_dir: List directory contents

## Research Workflow
1. Understand what information is needed
2. Search the codebase for existing implementations
3. Search the web for relevant documentation and best practices
4. Synthesize findings into a structured report
5. Save the report to doc/research-report.md

## Output
- Summary of findings
- Key references and links
- Report file path"""


class BaseSubAgent:
    max_iterations: int = 15  # Subclasses override
    llm_timeout: float = 120.0  # Subclasses override

    def __init__(self, parent: AgentCore, agent_type: str, allowed_tools: List[str],
                 system_template: str):
        self._parent = parent
        self._agent_type = agent_type
        self._allowed_tools = allowed_tools
        self._system_template = system_template
        self._sub_agent: Optional[SubAgent] = None
        self._agent_id: Optional[str] = None
        self._output_files: List[str] = []
        self._created_at: str = datetime.now().isoformat()

    @property
    def agent_type(self) -> str:
        return self._agent_type

    @property
    def agent_id(self) -> Optional[str]:
        return self._agent_id

    @property
    def completed(self) -> bool:
        return self._sub_agent is not None and self._sub_agent.completed

    @property
    def result(self) -> Optional[str]:
        if self._sub_agent is not None:
            return self._sub_agent.result
        return None

    def _build_task_prompt(self, task_description: str, context: Dict[str, Any]) -> str:
        parts = [f"## Task\n{task_description}"]
        if context.get("workspace_dir"):
            parts.append(f"\n## Working Directory\n{context['workspace_dir']}")
        if context.get("plan_file"):
            parts.append(f"\n## Plan File\n{context['plan_file']}")
        if context.get("lessons_file"):
            parts.append(f"\n## Lessons Learned\n{context['lessons_file']}")
        if context.get("input_files"):
            files = "\n".join(f"- {f}" for f in context["input_files"])
            parts.append(f"\n## Input Files\n{files}")
        if context.get("test_reports_dir"):
            parts.append(f"\n## Test Reports Directory\n{context['test_reports_dir']}")
        if context.get("extra_instructions"):
            parts.append(f"\n## Additional Instructions\n{context['extra_instructions']}")
        return "\n".join(parts)

    async def create(self, task_description: str, context: Optional[Dict[str, Any]] = None) -> str:
        ctx = context or {}
        prompt = self._build_task_prompt(task_description, ctx)
        self._sub_agent = SubAgent(
            parent=self._parent,
            task=prompt,
            max_depth=self.max_iterations,
            allowed_tools=self._allowed_tools,
            llm_timeout=self.llm_timeout,
        )
        # Set working_dir from context so tools write to the workspace
        if ctx.get("workspace_dir"):
            self._sub_agent._context.working_dir = ctx["workspace_dir"]
        system_prompt = self._resolve_system_prompt()
        self._sub_agent._context.set_static_system_prompt(system_prompt)
        self._agent_id = f"{self._agent_type}_{int(time.time())}"
        logger.info(f"SubAgent created: {self._agent_id} (type: {self._agent_type})")
        return self._agent_id

    def _resolve_system_prompt(self) -> str:
        md_prompt = load_prompt_from_markdown(self._agent_type)
        if md_prompt:
            return f"{md_prompt}\n\n---\n\n{self._system_template}"
        return self._system_template

    async def stream_run(self, timeout: int = 600) -> AsyncIterator["AgentEvent"]:
        """Async generator that yields AgentEvent protocol events during execution.

        Subclasses can override to emit more specific progress messages.
        """
        from .protocol.events import AgentEvent

        if self._sub_agent is None:
            yield ToolCallStarted(name=self._agent_type)
            yield ToolCallFinished(
                name=self._agent_type,
                success=False,
                result="Agent not created",
            )
            return

        yield ToolCallStarted(name=self._agent_type)
        yield TextDelta(text="Starting task...")

        start = time.time()
        try:
            yield TextDelta(text="Executing...")
            result = await self._sub_agent.run()
            elapsed = time.time() - start
            yield ToolCallFinished(
                name=self._agent_type,
                success=True,
                result=result or "",
                duration=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"SubAgent {self._agent_id} failed: {e}")
            yield ToolCallFinished(
                name=self._agent_type,
                success=False,
                result=str(e),
                duration=elapsed,
            )

    async def run(self, timeout: int = 600) -> SubAgentOutput:
        final_output = None
        async for event in self.stream_run(timeout=timeout):
            if isinstance(event, ToolCallFinished):
                final_output = SubAgentOutput(
                    agent_type=self._agent_type,
                    agent_id=self._agent_id or "",
                    task_id="",
                    content=event.result or "",
                    success=event.success,
                    execution_time=event.duration,
                )
        if final_output is None:
            final_output = SubAgentOutput(
                agent_type=self._agent_type,
                agent_id=self._agent_id or "",
                task_id="",
                content="",
                success=False,
                error="No output from stream_run",
            )
        return final_output

    async def resume(self, new_task: str, context: Optional[Dict[str, Any]] = None) -> None:
        if self._sub_agent is None:
            logger.warning(f"Cannot resume agent {self._agent_id}: not created")
            return
        ctx = context or {}
        prompt = self._build_task_prompt(new_task, ctx)
        self._sub_agent._context.add_message("user", prompt)
        self._sub_agent._completed = False
        self._sub_agent._result = None
        logger.info(f"SubAgent resumed: {self._agent_id}")


class DevAgent(BaseSubAgent):
    max_iterations = 15
    llm_timeout = 120.0

    def __init__(self, parent: AgentCore):
        super().__init__(
            parent=parent,
            agent_type="dev",
            allowed_tools=DEV_TOOLS,
            system_template=DEV_SYSTEM_TEMPLATE,
        )

    async def create(self, task_description: str, context: Optional[Dict[str, Any]] = None) -> str:
        ctx = context or {}
        if ctx.get("lessons_file"):
            extra = f"\n\nIMPORTANT: Read {ctx['lessons_file']} first to avoid repeating past mistakes."
            ctx.setdefault("extra_instructions", "")
            ctx["extra_instructions"] += extra
        return await super().create(task_description, ctx)

    async def stream_run(self, timeout: int = 600) -> AsyncIterator["AgentEvent"]:
        from .protocol.events import AgentEvent

        if self._sub_agent is None:
            yield ToolCallStarted(name=self._agent_type)
            yield ToolCallFinished(
                name=self._agent_type,
                success=False,
                result="Agent not created",
            )
            return

        yield ToolCallStarted(name=self._agent_type)
        yield TextDelta(text="Reading requirements and dev plan...")
        yield TextDelta(text="Reading lessons-learned.md...")

        start = time.time()
        try:
            yield TextDelta(text="Implementing code...")
            result = await self._sub_agent.run()
            elapsed = time.time() - start

            yield TextDelta(text="Running self-tests...")
            yield TextDelta(text="Development complete")
            yield ToolCallFinished(
                name=self._agent_type,
                success=True,
                result=result or "",
                duration=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"SubAgent {self._agent_id} failed: {e}")
            yield ToolCallFinished(
                name=self._agent_type,
                success=False,
                result=str(e),
                duration=elapsed,
            )


class TesterAgent(BaseSubAgent):
    max_iterations = 10
    llm_timeout = 120.0

    def __init__(self, parent: AgentCore):
        super().__init__(
            parent=parent,
            agent_type="tester",
            allowed_tools=TESTER_TOOLS,
            system_template=TESTER_SYSTEM_TEMPLATE,
        )

    async def stream_run(self, timeout: int = 600) -> AsyncIterator["AgentEvent"]:
        from .protocol.events import AgentEvent

        if self._sub_agent is None:
            yield ToolCallStarted(name=self._agent_type)
            yield ToolCallFinished(
                name=self._agent_type,
                success=False,
                result="Agent not created",
            )
            return

        yield ToolCallStarted(name=self._agent_type)
        yield TextDelta(text="Reading implementation files...")

        start = time.time()
        try:
            yield TextDelta(text="Running tests...")
            result = await self._sub_agent.run()
            elapsed = time.time() - start

            yield TextDelta(text="Analyzing results...")
            yield TextDelta(text="Writing test report...")
            yield ToolCallFinished(
                name=self._agent_type,
                success=True,
                result=result or "",
                duration=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"SubAgent {self._agent_id} failed: {e}")
            yield ToolCallFinished(
                name=self._agent_type,
                success=False,
                result=str(e),
                duration=elapsed,
            )

    def parse_result(self, output: str) -> Dict[str, Any]:
        result = {"status": "UNKNOWN", "issues": []}
        for line in output.split("\n"):
            stripped = line.strip()
            if stripped.startswith("RESULT:"):
                status = stripped.replace("RESULT:", "").strip().upper()
                result["status"] = status
                break
        lines = output.split("\n")
        in_issues = False
        for line in lines:
            if "issue" in line.lower() and ":" in line:
                in_issues = True
                continue
            if in_issues and line.strip().startswith(("-", "*", "1.", "2.", "3.")):
                issue = line.strip().lstrip("-*0123456789. ").strip()
                if issue:
                    result["issues"].append(issue)
        return result


class DimensionTesterAgent(BaseSubAgent):
    def __init__(self, parent: AgentCore, dimension: str):
        if dimension not in DIMENSION_TEMPLATES:
            raise ValueError(f"Unknown test dimension: {dimension}")
        template = DIMENSION_TEMPLATES[dimension]
        super().__init__(
            parent=parent,
            agent_type=f"tester-{dimension}",
            allowed_tools=TESTER_TOOLS,
            system_template=template,
        )
        self._dimension = dimension

    @property
    def dimension(self) -> str:
        return self._dimension

    async def stream_run(self, timeout: int = 600) -> AsyncIterator["AgentEvent"]:
        from .protocol.events import AgentEvent

        if self._sub_agent is None:
            yield ToolCallStarted(name=self._agent_type)
            yield ToolCallFinished(
                name=self._agent_type,
                success=False,
                result="Agent not created",
            )
            return

        yield ToolCallStarted(name=self._agent_type)
        yield TextDelta(text="Reading implementation files...")

        start = time.time()
        try:
            yield TextDelta(text="Running tests...")
            result = await self._sub_agent.run()
            elapsed = time.time() - start

            yield TextDelta(text="Analyzing results...")
            yield TextDelta(text="Writing test report...")
            yield ToolCallFinished(
                name=self._agent_type,
                success=True,
                result=result or "",
                duration=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"SubAgent {self._agent_id} failed: {e}")
            yield ToolCallFinished(
                name=self._agent_type,
                success=False,
                result=str(e),
                duration=elapsed,
            )

    def parse_result(self, output: str) -> Dict[str, Any]:
        parsed = {
            "status": "UNKNOWN",
            "issues": [],
            "dimension": self._dimension,
            "report_path": "",
            "issue_count": 0,
        }
        for line in output.split("\n"):
            stripped = line.strip()
            if stripped.startswith("RESULT:"):
                parsed["status"] = stripped.replace("RESULT:", "").strip().upper()
            elif "报告路径" in stripped and ":" in stripped:
                parsed["report_path"] = stripped.split(":", 1)[1].strip()
            elif "问题数" in stripped and ":" in stripped:
                try:
                    parsed["issue_count"] = int(stripped.split(":", 1)[1].strip())
                except ValueError:
                    parsed["issue_count"] = 0
        if not parsed["issues"]:
            in_issues = False
            for line in output.split("\n"):
                if "issue" in line.lower() and ":" in line:
                    in_issues = True
                    continue
                if in_issues and line.strip().startswith(("-", "*", "1.", "2.", "3.")):
                    issue = line.strip().lstrip("-*0123456789. ").strip()
                    if issue:
                        parsed["issues"].append(issue)
        return parsed


class LayoutTesterAgent(DimensionTesterAgent):
    def __init__(self, parent: AgentCore):
        super().__init__(parent, TestDimension.LAYOUT)


class BeautyTesterAgent(DimensionTesterAgent):
    def __init__(self, parent: AgentCore):
        super().__init__(parent, TestDimension.BEAUTY)


class AnimationTesterAgent(DimensionTesterAgent):
    def __init__(self, parent: AgentCore):
        super().__init__(parent, TestDimension.ANIMATION)


class SecurityTesterAgent(DimensionTesterAgent):
    def __init__(self, parent: AgentCore):
        super().__init__(parent, TestDimension.SECURITY)


class PerformanceTesterAgent(DimensionTesterAgent):
    def __init__(self, parent: AgentCore):
        super().__init__(parent, TestDimension.PERFORMANCE)


class AccessibilityTesterAgent(DimensionTesterAgent):
    def __init__(self, parent: AgentCore):
        super().__init__(parent, TestDimension.ACCESSIBILITY)


class PlannerAgent(BaseSubAgent):
    max_iterations = 20
    llm_timeout = 180.0

    def __init__(self, parent: AgentCore):
        super().__init__(
            parent=parent,
            agent_type="planner",
            allowed_tools=PLANNER_TOOLS,
            system_template=PLANNER_SYSTEM_TEMPLATE,
        )

    async def stream_run(self, timeout: int = 600) -> AsyncIterator["AgentEvent"]:
        from .protocol.events import AgentEvent

        if self._sub_agent is None:
            yield ToolCallStarted(name=self._agent_type)
            yield ToolCallFinished(
                name=self._agent_type,
                success=False,
                result="Agent not created",
            )
            return

        yield ToolCallStarted(name=self._agent_type)
        yield TextDelta(text="Analyzing requirements...")

        start = time.time()
        try:
            yield TextDelta(text="Breaking down into sub-tasks...")
            result = await self._sub_agent.run()
            elapsed = time.time() - start

            yield TextDelta(text="Creating development plan...")
            yield TextDelta(text="Plan created")
            yield ToolCallFinished(
                name=self._agent_type,
                success=True,
                result=result or "",
                duration=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"SubAgent {self._agent_id} failed: {e}")
            yield ToolCallFinished(
                name=self._agent_type,
                success=False,
                result=str(e),
                duration=elapsed,
            )


class ResearcherAgent(BaseSubAgent):
    max_iterations = 15

    def __init__(self, parent: AgentCore):
        super().__init__(
            parent=parent,
            agent_type="researcher",
            allowed_tools=RESEARCHER_TOOLS,
            system_template=RESEARCHER_SYSTEM_TEMPLATE,
        )


AGENT_TYPE_MAP = {
    "dev": DevAgent,
    "tester": TesterAgent,
    "tester-layout": LayoutTesterAgent,
    "tester-beauty": BeautyTesterAgent,
    "tester-animation": AnimationTesterAgent,
    "tester-security": SecurityTesterAgent,
    "tester-performance": PerformanceTesterAgent,
    "tester-accessibility": AccessibilityTesterAgent,
    "planner": PlannerAgent,
    "researcher": ResearcherAgent,
}


def create_sub_agent(agent_type: str, parent: AgentCore) -> Optional[BaseSubAgent]:
    cls = AGENT_TYPE_MAP.get(agent_type)
    if cls is None:
        logger.error(f"Unknown agent type: {agent_type}")
        return None
    return cls(parent=parent)


def create_dimension_testers(
    parent: AgentCore, dimensions: Optional[List[str]] = None
) -> List[DimensionTesterAgent]:
    if dimensions is None:
        dimensions = TestDimension.DEFAULT_TRIPLE
    testers: List[DimensionTesterAgent] = []
    for d in dimensions:
        cls = AGENT_TYPE_MAP.get(f"tester-{d}")
        if cls is not None:
            testers.append(cls(parent=parent))
    return testers


_PROMPT_DIR = Path(__file__).resolve().parent / "agents"
_PROMPT_FILE_MAP = {
    "dev": "dev.md",
    "planner": "planner.md",
    "researcher": "researcher.md",
    "tester-layout": "tester-layout.md",
    "tester-beauty": "tester-beauty.md",
    "tester-animation": "tester-animation.md",
    "tester-security": "tester-security.md",
    "tester-performance": "tester-performance.md",
    "tester-accessibility": "tester-accessibility.md",
}


def load_prompt_from_markdown(agent_type: str) -> Optional[str]:
    fname = _PROMPT_FILE_MAP.get(agent_type)
    if fname is None:
        return None
    path = _PROMPT_DIR / fname
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if lines and lines[0].strip() == "---":
            end = None
            for i, line in enumerate(lines[1:], start=1):
                if line.strip() == "---":
                    end = i
                    break
            if end is not None:
                text = "\n".join(lines[end + 1 :])
        return text.strip()
    except Exception as e:
        logger.warning(f"Failed to load prompt for {agent_type}: {e}")
        return None
