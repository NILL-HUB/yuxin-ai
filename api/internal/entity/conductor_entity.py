"""指挥官（Conductor）决策层核心数据结构。

指挥官是一个强 LLM 入口，负责：
1. 分析用户请求，判断是直接回复还是派发 Agent；
2. 为每个 Agent 子任务匹配合适的模型档位和能力要求；
3. 输出结构化的编排计划（ConductorPlan），由下游执行器执行。

设计原则：
- 计划是纯数据，不携带执行逻辑；
- 计划可被转换为现有的 RoutingDecision，复用现有执行器；
- 硬约束校验在 ConductorService 中执行，校验失败回退到 single_agent。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# =========================================================
# 枚举与常量
# =========================================================

class ConductorMode(str, Enum):
    """指挥官决策的执行模式。

    与现有 ExecutionMode 对齐但精简：
    - DIRECT_ANSWER: 指挥官直接回复（简单任务）
    - SINGLE_AGENT: 派遣单个 Agent
    - MULTI_AGENT_PARALLEL: 多 Agent 并行
    - MULTI_AGENT_SEQUENTIAL: 多 Agent 顺序
    - REJECT_OR_CONFIRM: 拒绝或需澄清
    """
    DIRECT_ANSWER = "direct_answer"
    SINGLE_AGENT = "single_agent"
    MULTI_AGENT_PARALLEL = "multi_agent_parallel"
    MULTI_AGENT_SEQUENTIAL = "multi_agent_sequential"
    REJECT_OR_CONFIRM = "reject_or_confirm"


class AggregationStrategy(str, Enum):
    """多 Agent 结果聚合策略。"""
    CONCAT = "concat"          # 直接拼接
    SUMMARIZE = "summarize"    # 指挥官再综合一次
    BEST_OF = "best_of"        # 取最佳


class ConductorRiskLevel(str, Enum):
    SAFE = "safe"
    MEDIUM = "medium"
    HIGH = "high"


# 硬约束常量
MAX_AGENTS_PER_PLAN = 5
VALID_MODEL_TIERS = {"1", "2", "3"}
VALID_AGENT_POOLS = {
    "general", "coding", "office", "data",
    "research", "customer_service", "internal_admin",
}


# =========================================================
# 数据结构
# =========================================================

@dataclass
class ConductorAgentTask:
    """指挥官分配给单个 Agent 的子任务。

    工具选择不在指挥官层完成——Agent 执行时通过向量索引自行检索工具，
    找不到合适工具时上报指挥官，由指挥官判断是否真的缺能力并决定回报用户。
    """
    task_id: str                              # 任务唯一 ID（t1, t2, ...）
    title: str                                # 子任务标题
    description: str                          # 子任务描述（交给 Agent 的具体指令）
    agent_pool: str = "general"               # Agent 池归属
    required_capabilities: list[str] = field(default_factory=list)  # 能力标签
    model_tier: str = "1"                     # 模型档位 1=轻量 2=标准 3=强模型
    model_id_hint: str | None = None          # 可选：模型 ID 提示（指挥官从摘要中选）
    depends_on: list[str] = field(default_factory=list)  # 依赖的 task_id
    risk_level: str = ConductorRiskLevel.SAFE.value
    expected_output: str = ""                 # 期望输出说明（供 Agent 参考）

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_id": self.task_id,  # 兼容 MultiAgentExecutor 读取的标识符键名
            "title": self.title,
            "description": self.description,
            "agent_pool": self.agent_pool,
            "required_capabilities": list(self.required_capabilities),
            "model_tier": self.model_tier,
            "model_id_hint": self.model_id_hint,
            "depends_on": list(self.depends_on),
            "risk_level": self.risk_level,
            "expected_output": self.expected_output,
        }


@dataclass
class ConductorPlan:
    """指挥官输出的完整编排计划。

    设计为可序列化、可校验、可转换为 RoutingDecision 的纯数据结构。
    """
    execution_mode: str                       # ConductorMode 枚举值
    intent: str                               # 任务意图简述
    complexity: str                           # simple | moderate | complex
    reason: str                               # 决策原因（一句话）

    # direct_answer 模式专用
    direct_answer: str | None = None          # 指挥官直接给出的回复

    # Agent 派发模式专用
    agents: list[ConductorAgentTask] = field(default_factory=list)
    aggregation_strategy: str = AggregationStrategy.SUMMARIZE.value

    # reject_or_confirm 模式专用
    needs_clarification: bool = False
    clarification_question: str | None = None
    reject_reason: str | None = None

    # 元信息
    risk_level: str = ConductorRiskLevel.SAFE.value
    estimated_cost_tier: str = "low"          # low | medium | high
    conductor_model_id: str | None = None     # 实际使用的指挥官模型 ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_mode": self.execution_mode,
            "intent": self.intent,
            "complexity": self.complexity,
            "reason": self.reason,
            "direct_answer": self.direct_answer,
            "agents": [a.to_dict() for a in self.agents],
            "aggregation_strategy": self.aggregation_strategy,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "reject_reason": self.reject_reason,
            "risk_level": self.risk_level,
            "estimated_cost_tier": self.estimated_cost_tier,
            "conductor_model_id": self.conductor_model_id,
        }


# =========================================================
# 缺能力上报决策
# =========================================================

class EscalationAction(str, Enum):
    """指挥官处理 Agent 上报的动作。"""
    RETRY_RELAXED = "retry_relaxed"   # 放宽阈值让 Agent 重试
    REPORT_USER = "report_user"       # 回报用户缺工具/需澄清
    GIVE_UP = "give_up"               # 已重试过仍失败，放弃


@dataclass
class EscalationDecision:
    """指挥官对 Agent 工具检索上报的处理决策。"""
    action: str                              # EscalationAction 枚举值
    message: str | None = None               # 给用户的消息（report_user 时必填）
    reason: str = ""                         # 决策原因
    relaxed_threshold: float | None = None   # 重试时放宽的阈值（retry_relaxed 时必填）

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "message": self.message,
            "reason": self.reason,
            "relaxed_threshold": self.relaxed_threshold,
        }


# =========================================================
# 校验工具
# =========================================================

class ConductorPlanValidator:
    """指挥官计划硬约束校验器。

    所有校验返回 (ok: bool, error: str)，ok=False 时 error 描述失败原因。
    """

    @staticmethod
    def validate(plan: ConductorPlan) -> tuple[bool, str]:
        if plan.execution_mode not in {m.value for m in ConductorMode}:
            return False, f"invalid execution_mode: {plan.execution_mode}"

        # direct_answer: 必须有回复内容，agents 必须为空
        if plan.execution_mode == ConductorMode.DIRECT_ANSWER.value:
            if not plan.direct_answer or not plan.direct_answer.strip():
                return False, "direct_answer mode requires non-empty direct_answer"
            if plan.agents:
                return False, "direct_answer mode must not have agents"
            return True, ""

        # reject_or_confirm: 必须有拒绝原因或澄清问题
        if plan.execution_mode == ConductorMode.REJECT_OR_CONFIRM.value:
            if not plan.reject_reason and not plan.clarification_question:
                return False, "reject_or_confirm mode requires reject_reason or clarification_question"
            return True, ""

        # Agent 派发模式校验
        if not plan.agents:
            return False, f"{plan.execution_mode} mode requires at least one agent"

        if len(plan.agents) > MAX_AGENTS_PER_PLAN:
            return False, f"too many agents: {len(plan.agents)} > {MAX_AGENTS_PER_PLAN}"

        task_ids = {a.task_id for a in plan.agents}
        if len(task_ids) != len(plan.agents):
            return False, "duplicate task_id in agents"

        for agent in plan.agents:
            # 模型档位校验
            if agent.model_tier not in VALID_MODEL_TIERS:
                return False, f"agent {agent.task_id} invalid model_tier: {agent.model_tier}"
            # Agent 池校验
            if agent.agent_pool not in VALID_AGENT_POOLS:
                return False, f"agent {agent.task_id} invalid agent_pool: {agent.agent_pool}"
            # 依赖校验
            for dep in agent.depends_on:
                if dep not in task_ids:
                    return False, f"agent {agent.task_id} depends on unknown task: {dep}"
                if dep == agent.task_id:
                    return False, f"agent {agent.task_id} depends on itself"

        # DAG 无环检测
        ok, err = ConductorPlanValidator._check_acyclic(plan.agents)
        if not ok:
            return False, err

        # multi_agent_parallel 模式不应有依赖
        if plan.execution_mode == ConductorMode.MULTI_AGENT_PARALLEL.value:
            for agent in plan.agents:
                if agent.depends_on:
                    return False, (
                        f"multi_agent_parallel mode agent {agent.task_id} "
                        f"must not have depends_on"
                    )

        return True, ""

    @staticmethod
    def _check_acyclic(agents: list[ConductorAgentTask]) -> tuple[bool, str]:
        """拓扑排序检测依赖图是否有环。"""
        graph: dict[str, list[str]] = {a.task_id: list(a.depends_on) for a in agents}
        visited: dict[str, int] = {a.task_id: 0 for a in agents}  # 0=未访问 1=访问中 2=完成

        def dfs(node: str) -> tuple[bool, str]:
            if visited[node] == 1:
                return False, f"cycle detected at task: {node}"
            if visited[node] == 2:
                return True, ""
            visited[node] = 1
            for dep in graph.get(node, []):
                ok, err = dfs(dep)
                if not ok:
                    return False, err
            visited[node] = 2
            return True, ""

        for task_id in graph:
            if visited[task_id] == 0:
                ok, err = dfs(task_id)
                if not ok:
                    return False, err
        return True, ""
