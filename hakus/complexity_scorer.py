"""确定性任务复杂度评分 — 替代启发式关键词路由.

核心设计:
- 多维度评分: 步骤数 / 文件创建 / 多文件协作 / 迭代验证 / 批量关键词
- 确定性: 相同输入始终得到相同分数
- 阈值路由: 低于阈值走 submission_loop, 高于阈值走 Orchestrator
- 用户覆盖: `!` 前缀强制路由到 Orchestrator
"""

import re
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "ORCHESTRATOR_THRESHOLD",
    "ComplexityScore",
    "TaskComplexityScorer",
]

# ============================================================
# Scoring dimensions and their weights
# ============================================================

# Each dimension scores 0-max_points. The total is the sum.
# Threshold: >= ORCHESTRATOR_THRESHOLD → route to Orchestrator.

ORCHESTRATOR_THRESHOLD = 25


@dataclass
class ComplexityScore:
    """复杂度评分结果 — 每个维度的分数和总分."""
    total: int = 0
    multi_step: int = 0       # 多步骤操作 (0-25)
    file_creation: int = 0    # 文件创建/修改 (0-20)
    multi_file: int = 0       # 多文件协作 (0-20)
    iterative: int = 0        # 迭代验证 (0-20)
    batch_keywords: int = 0   # 批量/自动化关键词 (0-15)
    should_orchestrate: bool = False


class TaskComplexityScorer:
    """基于多维度评分的确定性任务复杂度计算器."""

    # ---- Multi-step signals (0-25) ----
    # Verbs that imply multiple sequential operations
    MULTI_STEP_VERBS_ZH = frozenset({
        "开发", "构建", "搭建", "实现", "设计", "创建", "制作", "编写",
        "写", "做", "部署", "配置", "集成", "重构", "迁移", "优化", "自动化",
    })
    MULTI_STEP_VERBS_EN = frozenset({
        "build", "develop", "create", "implement", "design", "scaffold",
        "deploy", "configure", "integrate", "refactor", "migrate",
        "automate", "generate", "produce", "construct",
    })
    # Connectors that imply sequential steps
    STEP_CONNECTORS = frozenset({
        "然后", "接着", "之后", "再", "并且", "同时", "以及",
        "then", "after", "next", "and then", "followed by",
    })
    # Tech + verb combo: "用 X 写/开发/搭建..." is a very strong signal
    TECH_VERB_PREFIXES_ZH = frozenset({"用", "使用", "借助"})
    # Request patterns: "帮我写...", "请帮我..."
    REQUEST_PREFIXES_ZH = frozenset({"帮我", "请帮我", "给我"})

    # ---- File creation signals (0-20) ----
    PROJECT_NOUNS_ZH = frozenset({
        "项目", "系统", "服务", "应用", "工程", "代码库", "平台",
        "网站", "工具", "框架", "库", "模块",
    })
    PROJECT_NOUNS_EN = frozenset({
        "project", "system", "service", "app", "application",
        "platform", "website", "tool", "framework", "library",
        "module", "codebase", "backend", "frontend", "fullstack",
        "dashboard", "api", "server", "microservice",
    })
    # Adjectives that amplify scope: "完整的系统", "full backend"
    SCOPE_AMPLIFIERS_ZH = frozenset({"完整", "整个", "全套", "全部"})
    SCOPE_AMPLIFIERS_EN = frozenset({"full", "complete", "entire", "whole"})
    FILE_EXTENSIONS = frozenset({
        ".java", ".py", ".go", ".ts", ".js", ".rs", ".kt", ".swift",
        ".cpp", ".c", ".h", ".cs", ".php", ".rb", ".scala", ".vue",
        ".jsx", ".tsx", ".html", ".css",
    })

    # ---- Multi-file signals (0-20) ----
    TECH_STACKS = frozenset({
        "spring boot", "springboot", "flask", "django", "fastapi",
        "express", "nestjs", "react", "vue", "angular", "next.js",
        "nextjs", "nuxt", "svelte", "electron", "tauri", "gin",
        "grpc", "actix", "rocket", "axum", "ktor", "spring cloud",
        "微服务", "microservice", "monorepo", "monorep",
    })
    MULTI_FILE_PATTERNS = frozenset({
        "多个文件", "多文件", "目录结构", "文件结构",
        "multiple files", "file structure", "directory structure",
        "项目结构", "架构",
    })

    # ---- Iterative verification signals (0-20) ----
    ITERATIVE_KEYWORDS = frozenset({
        "测试", "验证", "检查", "审查", "确认", "修正", "修复", "迭代",
        "test", "verify", "validate", "check", "review", "confirm",
        "fix", "iterate", "refine", "improve", "polish",
        "质量", "quality", "pass", "fail",
    })

    # ---- Batch/automation signals (0-15) ----
    BATCH_KEYWORDS = frozenset({
        "批量", "自动化", "全部", "所有", "每个", "逐个", "依次",
        "batch", "automate", "all", "every", "each", "bulk",
        "批量生成", "批量处理", "pipeline", "流水线",
        "幻灯片", "slides", "ppt", "页面",
    })

    def score(self, user_message: str) -> ComplexityScore:
        """计算任务复杂度评分 — 确定性,相同输入始终得到相同分数."""
        text = (user_message or "").strip()
        if not text:
            return ComplexityScore()

        lower = text.lower()
        result = ComplexityScore()

        # 1. Multi-step (0-25)
        result.multi_step = self._score_multi_step(text, lower)

        # 2. File creation (0-20)
        result.file_creation = self._score_file_creation(text, lower)

        # 3. Multi-file (0-20)
        result.multi_file = self._score_multi_file(text, lower)

        # 4. Iterative verification (0-20)
        result.iterative = self._score_iterative(lower)

        # 5. Batch keywords (0-15)
        result.batch_keywords = self._score_batch(lower)

        result.total = (
            result.multi_step
            + result.file_creation
            + result.multi_file
            + result.iterative
            + result.batch_keywords
        )

        # Combo boost: when multiple dimensions light up, the task is
        # almost certainly complex. E.g. "用 spring boot 写个系统" has
        # multi_step + multi_file but low file_creation — the combo
        # boost pushes it over threshold.
        active_dims = sum(1 for d in (
            result.multi_step, result.file_creation,
            result.multi_file, result.iterative, result.batch_keywords,
        ) if d > 0)
        if active_dims >= 3:
            result.total += 15
        elif active_dims >= 2:
            result.total += 12

        result.should_orchestrate = result.total >= ORCHESTRATOR_THRESHOLD

        logger.debug(
            f"Complexity score: {result.total} "
            f"(step={result.multi_step} file={result.file_creation} "
            f"multi={result.multi_file} iter={result.iterative} "
            f"batch={result.batch_keywords}) "
            f"orchestrate={result.should_orchestrate}"
        )
        return result

    def should_orchestrate(self, user_message: str) -> bool:
        """判断是否应路由到 Orchestrator.

        保留 `!` 前缀强制路由作为用户覆盖手段.
        """
        text = (user_message or "").strip()
        if not text:
            return False
        # Explicit override
        if text.startswith("!"):
            return True
        return self.score(user_message).should_orchestrate

    # ---- Per-dimension scoring ----

    def _score_multi_step(self, text: str, lower: str) -> int:
        score = 0
        # Count multi-step verbs
        verb_hits = sum(1 for v in self.MULTI_STEP_VERBS_ZH if v in lower)
        verb_hits += sum(1 for v in self.MULTI_STEP_VERBS_EN if f" {v}" in f" {lower}")
        score += min(verb_hits * 5, 15)
        # Count step connectors
        connector_hits = sum(1 for c in self.STEP_CONNECTORS if c in lower)
        score += min(connector_hits * 5, 10)
        # Tech + verb combo: "用 spring boot 写..." / "with flask build..."
        has_tech = any(t in lower for t in self.TECH_STACKS)
        has_verb = verb_hits > 0
        has_prefix = any(p in lower for p in self.TECH_VERB_PREFIXES_ZH)
        if has_tech and has_verb:
            score += 10  # Strong multi-step signal
        elif has_tech and has_prefix:
            score += 8  # "用 X" without explicit verb still implies project
        # Request prefix + verb: "帮我写...", "请帮我搭建..."
        has_request = any(p in lower for p in self.REQUEST_PREFIXES_ZH)
        if has_request and has_verb:
            score += 5
        return min(score, 25)

    def _score_file_creation(self, text: str, lower: str) -> int:
        score = 0
        # Project nouns
        noun_hits = sum(1 for n in self.PROJECT_NOUNS_ZH if n in lower)
        noun_hits += sum(1 for n in self.PROJECT_NOUNS_EN if f" {n}" in f" {lower}")
        score += min(noun_hits * 7, 14)
        # File extensions mentioned
        ext_hits = sum(1 for e in self.FILE_EXTENSIONS if e in lower)
        score += min(ext_hits * 3, 6)
        # Scope amplifiers: "完整的系统", "full backend"
        if any(a in lower for a in self.SCOPE_AMPLIFIERS_ZH):
            score += 6
        if any(f" {a}" in f" {lower}" for a in self.SCOPE_AMPLIFIERS_EN):
            score += 6
        return min(score, 20)

    def _score_multi_file(self, text: str, lower: str) -> int:
        score = 0
        # Tech stack mentions
        tech_hits = sum(1 for t in self.TECH_STACKS if t in lower)
        score += min(tech_hits * 7, 14)
        # Multi-file patterns
        if any(p in lower for p in self.MULTI_FILE_PATTERNS):
            score += 6
        # Tech stack + verb implies multi-file project
        has_verb = any(v in lower for v in self.MULTI_STEP_VERBS_ZH)
        has_verb_en = any(f" {v}" in f" {lower}" for v in self.MULTI_STEP_VERBS_EN)
        if tech_hits > 0 and (has_verb or has_verb_en):
            score += 6
        return min(score, 20)

    def _score_iterative(self, lower: str) -> int:
        score = 0
        iter_hits = sum(1 for k in self.ITERATIVE_KEYWORDS if k in lower)
        score += min(iter_hits * 4, 12)
        # Multiple test/fix cycles implied
        if "测试" in lower and ("修正" in lower or "修复" in lower):
            score += 8
        if "test" in lower and ("fix" in lower or "refine" in lower):
            score += 8
        return min(score, 20)

    def _score_batch(self, lower: str) -> int:
        score = 0
        batch_hits = sum(1 for k in self.BATCH_KEYWORDS if k in lower)
        score += min(batch_hits * 5, 10)
        # Numbers implying multiple items (e.g., "10页", "5个")
        num_matches = re.findall(r'(\d+)\s*[页个份项模块]', lower)
        for m in num_matches:
            n = int(m)
            if n >= 3:
                score += 5
                break
        return min(score, 15)
