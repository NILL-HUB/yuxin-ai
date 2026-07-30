"""Agent 工具检索服务。

Agent 执行子任务时，通过此服务从向量索引中检索合适的工具（MCP/Skill/内置/API）。

设计原则：
1. 四类工具分开检索，避免向量污染（用户明确要求）；
2. 扩K机制：初始 Top-K=3，分数偏低时扩到 K=6 再查一次；
3. 上报机制：扩K后仍无合适工具，返回 needs_escalation=True，由指挥官判断；
4. 指挥官收到上报后，可决定：a) 确实缺能力，回报用户；b) 放宽要求重试。
"""
import logging
from dataclasses import dataclass, field
from typing import Any

from internal.entity.conductor_entity import ConductorAgentTask
from internal.model.resource_vector_index import (
    RESOURCE_TYPE_API_TOOL,
    RESOURCE_TYPE_BUILTIN_TOOL,
    RESOURCE_TYPE_MCP_TOOL,
    RESOURCE_TYPE_SKILL,
)
from internal.service.resource_vector_index_service import ResourceVectorIndexService

logger = logging.getLogger(__name__)


# =========================================================
# 配置常量
# =========================================================

# 初始检索 Top-K
INITIAL_TOP_K = 3
# 扩K后的 Top-K
EXPANDED_TOP_K = 6
# 初始检索的"足够好"分数阈值（高于此值即接受）
GOOD_SCORE_THRESHOLD = 0.55
# 扩K后的"勉强可用"分数阈值（低于此值则上报指挥官）
MIN_SCORE_THRESHOLD = 0.35

# 四类工具资源类型
_TOOL_RESOURCE_TYPES = [
    RESOURCE_TYPE_MCP_TOOL,
    RESOURCE_TYPE_SKILL,
    RESOURCE_TYPE_BUILTIN_TOOL,
    RESOURCE_TYPE_API_TOOL,
]


# =========================================================
# 数据结构
# =========================================================

@dataclass
class ToolCandidate:
    """单个工具候选。"""
    resource_type: str          # mcp_tool/skill/builtin_tool/api_tool
    resource_id: str
    resource_name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    sub_pool: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "sub_pool": self.sub_pool,
            "metadata": dict(self.metadata),
            "score": self.score,
        }


@dataclass
class ToolFindResult:
    """工具检索结果。

    needs_escalation=True 时，表示 Agent 找不到合适工具，需上报指挥官。
    """
    tools: list[ToolCandidate] = field(default_factory=list)
    needs_escalation: bool = False
    reason: str = ""
    expanded: bool = False              # 是否触发了扩K
    best_score: float = 0.0             # 最佳候选分数

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools": [t.to_dict() for t in self.tools],
            "needs_escalation": self.needs_escalation,
            "reason": self.reason,
            "expanded": self.expanded,
            "best_score": self.best_score,
        }


# =========================================================
# Agent 工具检索服务
# =========================================================

class AgentToolFinder:
    """Agent 工具检索服务。

    Agent 执行子任务时调用此服务检索工具。
    四类工具分开检索，避免向量污染；扩K机制保证召回率；上报机制处理缺工具场景。
    """

    def __init__(self, vector_index_service: ResourceVectorIndexService | None = None):
        self._vector_index_service = vector_index_service or ResourceVectorIndexService()

    def find_tools(
        self,
        task: ConductorAgentTask,
        *,
        sub_pool: str | None = None,
    ) -> ToolFindResult:
        """为子任务检索工具。

        Args:
            task: 指挥官分配的子任务
            sub_pool: 可选的子池过滤（如 "coding"），None 则不过滤

        Returns:
            ToolFindResult: 检索结果，needs_escalation=True 时需上报指挥官
        """
        query_text = self._build_query_text(task)
        if not query_text.strip():
            return ToolFindResult(
                needs_escalation=True,
                reason="任务描述为空，无法检索工具",
            )

        # 第一轮：初始 Top-K 检索
        tools, best_score = self._search_all_types(
            query_text, top_k=INITIAL_TOP_K, sub_pool=sub_pool
        )

        if tools and best_score >= GOOD_SCORE_THRESHOLD:
            return ToolFindResult(
                tools=tools,
                needs_escalation=False,
                best_score=best_score,
                expanded=False,
            )

        # 第二轮：扩K检索
        logger.info(
            "Agent 工具检索初始分数偏低 best=%.3f < %.3f, 扩K到 %d",
            best_score, GOOD_SCORE_THRESHOLD, EXPANDED_TOP_K,
        )
        tools, best_score = self._search_all_types(
            query_text, top_k=EXPANDED_TOP_K, sub_pool=sub_pool
        )

        if tools and best_score >= MIN_SCORE_THRESHOLD:
            return ToolFindResult(
                tools=tools,
                needs_escalation=False,
                best_score=best_score,
                expanded=True,
            )

        # 扩K后仍无合适工具，上报指挥官
        return ToolFindResult(
            tools=tools,  # 仍返回最佳候选供指挥官参考
            needs_escalation=True,
            reason=(
                f"扩K检索后仍无合适工具 (best_score={best_score:.3f} < {MIN_SCORE_THRESHOLD}), "
                f"任务所需能力: {task.required_capabilities}"
            ),
            expanded=True,
            best_score=best_score,
        )

    # ── 内部方法 ───────────────────────────────────────────────

    @staticmethod
    def _build_query_text(task: ConductorAgentTask) -> str:
        """构建检索查询文本。

        组合任务标题、描述、所需能力，形成语义检索查询。
        """
        parts = [task.title, task.description]
        if task.required_capabilities:
            parts.append("所需能力: " + " ".join(task.required_capabilities))
        if task.expected_output:
            parts.append("期望输出: " + task.expected_output)
        return "\n".join(p for p in parts if p and p.strip())

    def _search_all_types(
        self,
        query_text: str,
        *,
        top_k: int,
        sub_pool: str | None = None,
    ) -> tuple[list[ToolCandidate], float]:
        """查询四类工具资源，合并结果并返回最佳分数。

        四类分开查询避免向量污染，合并后按分数排序取 Top-K。
        """
        all_candidates: list[ToolCandidate] = []
        best_score = 0.0

        for resource_type in _TOOL_RESOURCE_TYPES:
            try:
                results = self._vector_index_service.search(
                    resource_type=resource_type,
                    query=query_text,
                    top_k=top_k,
                    sub_pool=sub_pool,
                )
            except Exception:
                logger.warning(
                    "工具向量检索失败 type=%s query=%s",
                    resource_type, query_text[:80],
                    exc_info=True,
                )
                continue

            for r in results:
                candidate = ToolCandidate(
                    resource_type=resource_type,
                    resource_id=r.get("resource_id", ""),
                    resource_name=r.get("resource_name", ""),
                    description=r.get("description", ""),
                    capabilities=list(r.get("capabilities") or []),
                    sub_pool=r.get("sub_pool", "general"),
                    metadata=dict(r.get("metadata") or {}),
                    score=float(r.get("score") or 0.0),
                )
                all_candidates.append(candidate)
                if candidate.score > best_score:
                    best_score = candidate.score

        # 合并后按分数降序排序，取 Top-K
        all_candidates.sort(key=lambda c: c.score, reverse=True)
        # 每类最多保留 top_k 个，总数最多 top_k * 2
        capped = all_candidates[: top_k * 2]
        return capped, best_score
