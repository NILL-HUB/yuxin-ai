from dataclasses import dataclass

from injector import inject

from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel, RoutingDecision


@inject
@dataclass
class TaskClassifierService:
    HIGH_RISK_KEYWORDS = (
        "删除数据库",
        "清空数据库",
        "删除所有",
        "清空所有",
        "drop table",
        "truncate",
        "rm -rf",
        "删库",
    )
    TOOL_KEYWORDS = (
        "查询",
        "搜索",
        "查一下",
        "天气",
        "股票",
        "联网",
        "下载",
        "生成文件",
        "整理成表格",
        "调用",
    )
    AGENT_KEYWORDS = (
        "智能体",
        "agent",
        "Agent",
        "使用",
        "交给",
        "让",
    )
    VERTICAL_HINTS = (
        "护肤",
        "法务",
        "财务",
        "招聘",
        "客服",
        "运营",
        "投研",
        "代码",
        "设计",
    )

    def classify(self, query: str) -> RoutingDecision:
        normalized = (query or "").strip()
        lowered = normalized.lower()
        if self._contains_any(normalized, self.HIGH_RISK_KEYWORDS) or self._contains_any(
            lowered, self.HIGH_RISK_KEYWORDS
        ):
            return RoutingDecision(
                intent="high_risk_operation",
                complexity="complex",
                execution_mode=ExecutionMode.REJECT_OR_CONFIRM.value,
                needs_tools=False,
                needs_agent=False,
                recommended_model_tier="strong",
                risk_level=RiskLevel.HIGH.value,
                reason="用户请求包含高风险操作，需要拒绝或二次确认",
            )
        if self._looks_like_vertical_agent_task(normalized):
            return RoutingDecision(
                intent="vertical_agent_task",
                complexity="medium",
                execution_mode=ExecutionMode.SINGLE_AGENT.value,
                needs_tools=True,
                needs_agent=True,
                recommended_model_tier="balanced",
                risk_level=RiskLevel.SAFE.value,
                reason="用户明确要求使用垂直智能体或问题适合路由到单个专业 Agent",
            )
        if self._contains_any(normalized, self.TOOL_KEYWORDS):
            return RoutingDecision(
                intent="tool_task",
                complexity="medium",
                execution_mode=ExecutionMode.SINGLE_AGENT.value,
                needs_tools=True,
                needs_agent=True,
                recommended_model_tier="balanced",
                risk_level=RiskLevel.SAFE.value,
                reason="用户请求需要查询、联网、文件或工具类能力",
            )
        return RoutingDecision(
            intent="general_qa",
            complexity="simple",
            execution_mode=ExecutionMode.DIRECT_ANSWER.value,
            needs_tools=False,
            needs_agent=False,
            recommended_model_tier="cheap",
            risk_level=RiskLevel.SAFE.value,
            reason="用户问题可由基础模型直接回答",
        )

    def _looks_like_vertical_agent_task(self, query: str) -> bool:
        has_agent_hint = self._contains_any(query, self.AGENT_KEYWORDS)
        has_vertical_hint = self._contains_any(query, self.VERTICAL_HINTS)
        return has_agent_hint and has_vertical_hint

    @staticmethod
    def _contains_any(query: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in query for keyword in keywords)
