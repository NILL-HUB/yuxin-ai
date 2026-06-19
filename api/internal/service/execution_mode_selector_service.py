from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel


class ExecutionModeSelectorService:
    def select(
        self,
        *,
        risk_level: str = RiskLevel.SAFE.value,
        needs_deep_thinking: bool = False,
        deep_thinking_requested: bool = False,
        needs_multi_agent: bool = False,
        needs_tools: bool = False,
        needs_agent: bool = False,
        available_pool_count: int = 0,
        image_count: int = 0,
        preliminary_mode: str = ExecutionMode.DIRECT_ANSWER.value,
    ) -> str:
        if risk_level == RiskLevel.HIGH.value:
            return ExecutionMode.REJECT_OR_CONFIRM.value
        if needs_deep_thinking or deep_thinking_requested:
            return ExecutionMode.DEEP_THINKING.value
        if needs_multi_agent:
            if available_pool_count > 1:
                return ExecutionMode.MULTI_AGENT_PARALLEL.value
            return ExecutionMode.MULTI_AGENT_SEQUENTIAL.value
        if image_count > 0 and needs_agent:
            return ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value
        if needs_tools and needs_agent:
            return ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value
        if needs_agent:
            return ExecutionMode.SINGLE_AGENT.value
        return preliminary_mode
