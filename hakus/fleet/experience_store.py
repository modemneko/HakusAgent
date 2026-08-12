"""经验库 — 替代 PARL 的"学习"能力.

HakusAI 用 API 无法做真正的 RL 训练，但可以：
  1. 记录每次任务的拆解策略、并行度、成功率
  2. 下次任务前查询相似任务的最优策略
  3. 逐步积累"什么任务适合怎么拆"的经验

持久化路径: ~/.hakus/fleet_experience.json
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Strategy:
    """一次任务的执行策略."""
    expert_count: int = 0
    expert_roles: List[str] = field(default_factory=list)
    parallelism: int = 10
    avg_timeout: int = 300

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Strategy":
        return cls(
            expert_count=d.get("expert_count", 0),
            expert_roles=d.get("expert_roles", []),
            parallelism=d.get("parallelism", 10),
            avg_timeout=d.get("avg_timeout", 300),
        )


@dataclass
class TaskPattern:
    """一类任务的经验模式."""
    pattern_id: str
    keywords: List[str] = field(default_factory=list)
    category: str = "unknown"
    optimal_strategy: Optional[Strategy] = None
    total_runs: int = 0
    success_count: int = 0
    avg_time: float = 0.0
    avg_tokens: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_runs if self.total_runs > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "keywords": self.keywords,
            "category": self.category,
            "optimal_strategy": self.optimal_strategy.to_dict() if self.optimal_strategy else None,
            "total_runs": self.total_runs,
            "success_count": self.success_count,
            "avg_time": self.avg_time,
            "avg_tokens": self.avg_tokens,
            "history": self.history[-20:],  # 只保留最近 20 条
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TaskPattern":
        return cls(
            pattern_id=d.get("pattern_id", ""),
            keywords=d.get("keywords", []),
            category=d.get("category", "unknown"),
            optimal_strategy=Strategy.from_dict(d["optimal_strategy"]) if d.get("optimal_strategy") else None,
            total_runs=d.get("total_runs", 0),
            success_count=d.get("success_count", 0),
            avg_time=d.get("avg_time", 0.0),
            avg_tokens=d.get("avg_tokens", 0),
            history=d.get("history", []),
        )


class ExperienceStore:
    """经验库 — 持久化任务策略和执行结果."""

    def __init__(self, persist_path: Optional[str] = None):
        if persist_path is None:
            config_dir = Path(os.environ.get("HAKUS_HOME") or os.path.expanduser("~/.hakus"))
            config_dir.mkdir(parents=True, exist_ok=True)
            persist_path = str(config_dir / "fleet_experience.json")
        self._path = persist_path
        self._patterns: Dict[str, TaskPattern] = {}
        self._load()

    def _load(self) -> None:
        """从磁盘加载经验库."""
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for pid, pdata in data.get("patterns", {}).items():
                    self._patterns[pid] = TaskPattern.from_dict(pdata)
                logger.info(f"ExperienceStore loaded {len(self._patterns)} patterns from {self._path}")
        except Exception as e:
            logger.warning(f"Failed to load experience store: {e}")

    def _save(self) -> None:
        """持久化到磁盘."""
        try:
            data = {
                "version": "1.0",
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "patterns": {pid: p.to_dict() for pid, p in self._patterns.items()},
            }
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save experience store: {e}")

    def _match_pattern(self, task_description: str) -> Optional[TaskPattern]:
        """通过关键词匹配任务模式."""
        task_lower = task_description.lower()
        best_match: Optional[TaskPattern] = None
        best_score = 0
        for pattern in self._patterns.values():
            score = sum(1 for kw in pattern.keywords if kw.lower() in task_lower)
            if score > best_score:
                best_score = score
                best_match = pattern
        return best_match if best_score > 0 else None

    def _generate_pattern_id(self, task_description: str) -> str:
        """根据任务描述生成 pattern_id."""
        import hashlib
        # 取前 100 字符的 hash 作为 ID 基础
        h = hashlib.md5(task_description[:100].encode()).hexdigest()[:8]
        return f"pattern_{h}"

    def _extract_keywords(self, task_description: str) -> List[str]:
        """从任务描述中提取关键词."""
        # 简单的关键词提取：检测常见技术栈
        tech_keywords = [
            "html", "css", "javascript", "typescript", "react", "vue", "angular",
            "three.js", "webgl", "shader", "glsl", "canvas",
            "python", "flask", "fastapi", "django", "pytest",
            "node", "express", "npm",
            "sql", "database", "redis",
            "docker", "kubernetes",
            "api", "rest", "graphql",
            "测试", "重构", "bug", "修复", "实现",
            "前端", "后端", "全栈",
            "认证", "授权", "jwt",
            "数据可视化", "仪表盘",
            "粒子", "动画", "物理",
        ]
        task_lower = task_description.lower()
        return [kw for kw in tech_keywords if kw in task_lower]

    def lookup(self, task_description: str) -> Optional[Strategy]:
        """查找相似任务的最优策略."""
        pattern = self._match_pattern(task_description)
        if pattern and pattern.optimal_strategy and pattern.success_rate > 0.3:
            logger.info(
                f"ExperienceStore hit: pattern={pattern.pattern_id} "
                f"success_rate={pattern.success_rate:.0%} "
                f"strategy={pattern.optimal_strategy.expert_count} experts"
            )
            return pattern.optimal_strategy
        return None

    def record(
        self,
        task_description: str,
        strategy: Strategy,
        success: bool,
        elapsed: float,
        tokens: int,
    ) -> None:
        """记录一次任务的执行结果，更新经验库."""
        pid = self._generate_pattern_id(task_description)
        keywords = self._extract_keywords(task_description)

        if pid not in self._patterns:
            self._patterns[pid] = TaskPattern(
                pattern_id=pid,
                keywords=keywords,
                category=self._categorize(task_description),
            )

        pattern = self._patterns[pid]
        # 更新关键词（合并）
        for kw in keywords:
            if kw not in pattern.keywords:
                pattern.keywords.append(kw)

        # 更新统计
        old_total = pattern.total_runs
        pattern.total_runs += 1
        if success:
            pattern.success_count += 1
        # 滑动平均
        pattern.avg_time = (pattern.avg_time * old_total + elapsed) / pattern.total_runs
        pattern.avg_tokens = (pattern.avg_tokens * old_total + tokens) / pattern.total_runs

        # 记录历史
        pattern.history.append({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "success": success,
            "elapsed": round(elapsed, 1),
            "tokens": tokens,
            "expert_count": strategy.expert_count,
            "parallelism": strategy.parallelism,
        })

        # 更新最优策略（只记录成功的策略）
        if success and (
            pattern.optimal_strategy is None
            or elapsed < pattern.avg_time * 1.2  # 比平均快就更新
        ):
            pattern.optimal_strategy = strategy

        self._save()
        logger.info(
            f"ExperienceStore recorded: pattern={pid} success={success} "
            f"total_runs={pattern.total_runs} success_rate={pattern.success_rate:.0%}"
        )

    def _categorize(self, task_description: str) -> str:
        """简单分类任务."""
        task_lower = task_description.lower()
        if any(kw in task_lower for kw in ["bug", "修复", "fix", "error"]):
            return "bugfix"
        if any(kw in task_lower for kw in ["实现", "implement", "create", "创建"]):
            return "feature"
        if any(kw in task_lower for kw in ["重构", "refactor"]):
            return "refactor"
        if any(kw in task_lower for kw in ["three.js", "webgl", "shader", "粒子"]):
            return "graphics"
        return "general"

    def get_stats(self) -> Dict[str, Any]:
        """获取经验库统计信息."""
        return {
            "total_patterns": len(self._patterns),
            "total_runs": sum(p.total_runs for p in self._patterns.values()),
            "avg_success_rate": (
                sum(p.success_rate for p in self._patterns.values()) / len(self._patterns)
                if self._patterns else 0
            ),
            "patterns": [
                {
                    "id": p.pattern_id,
                    "category": p.category,
                    "keywords": p.keywords[:5],
                    "runs": p.total_runs,
                    "success_rate": round(p.success_rate, 2),
                    "avg_time": round(p.avg_time, 1),
                }
                for p in self._patterns.values()
            ],
        }
