from internal.entity.execution_orchestration_entity import TaskPlan, TaskPlanItem
from internal.entity.orchestrator_entity import ExecutionMode, RoutingDecision


class TaskPlannerService:
    def plan(self, original_query: str, decision: RoutingDecision) -> TaskPlan:
        if decision.execution_mode == ExecutionMode.REJECT_OR_CONFIRM.value:
            return TaskPlan(
                original_query=original_query,
                execution_mode="blocked",
                reason="reject_or_confirm",
                items=[],
            )
        if decision.execution_mode == "deep_thinking":
            return self._deep_thinking_plan(original_query)
        if decision.execution_mode == ExecutionMode.MULTI_AGENT.value:
            return self._multi_agent_plan(original_query, decision)
        if decision.execution_mode == ExecutionMode.SINGLE_AGENT.value:
            return self._single_agent_plan(original_query, decision)
        return TaskPlan(
            original_query=original_query,
            execution_mode=ExecutionMode.DIRECT_ANSWER.value,
            reason=decision.reason,
            items=[
                TaskPlanItem(
                    task_id="task-1",
                    title=original_query,
                    description=original_query,
                    agent_pool="general",
                )
            ],
        )

    def _single_agent_plan(
        self, original_query: str, decision: RoutingDecision
    ) -> TaskPlan:
        pool = self._selected_agent_pool(decision)
        return TaskPlan(
            original_query=original_query,
            execution_mode=ExecutionMode.SINGLE_AGENT.value,
            reason=decision.reason,
            items=[
                TaskPlanItem(
                    task_id="task-1",
                    title=original_query,
                    description=original_query,
                    agent_pool=pool,
                    required_capabilities=[decision.intent],
                )
            ],
        )

    def _multi_agent_plan(
        self, original_query: str, decision: RoutingDecision
    ) -> TaskPlan:
        pools = self._matched_pools(decision)[: self._max_agent_count(decision)]
        return TaskPlan(
            original_query=original_query,
            execution_mode="multi_agent_parallel",
            reason=decision.reason,
            items=[
                TaskPlanItem(
                    task_id=f"task-{index + 1}",
                    title=f"{pool} task",
                    description=original_query,
                    agent_pool=pool,
                    required_capabilities=[pool],
                    execution_order=index,
                )
                for index, pool in enumerate(pools)
            ],
        )

    @staticmethod
    def _deep_thinking_plan(original_query: str) -> TaskPlan:
        pools = ["research", "analysis", "synthesis"]
        items = []
        for index, pool in enumerate(pools):
            task_id = f"task-{index + 1}"
            depends_on = [items[index - 1].task_id] if index > 0 else []
            items.append(
                TaskPlanItem(
                    task_id=task_id,
                    title=f"{pool} stage",
                    description=original_query,
                    agent_pool=pool,
                    required_capabilities=[pool],
                    depends_on=depends_on,
                    execution_order=index,
                )
            )
        return TaskPlan(
            original_query=original_query,
            execution_mode="deep_thinking",
            reason="deep_thinking",
            items=items,
        )

    @staticmethod
    def _selected_agent_pool(decision: RoutingDecision) -> str:
        subset = decision.agent_subset or {}
        selected_agents = subset.get("selected_agents") or []
        if selected_agents and isinstance(selected_agents[0], dict):
            return selected_agents[0].get("primary_pool") or "general"
        return "general"

    @staticmethod
    def _matched_pools(decision: RoutingDecision) -> list[str]:
        subset = decision.agent_subset or {}
        pools = subset.get("matched_pools") or []
        return pools if pools else ["general"]

    @staticmethod
    def _max_agent_count(decision: RoutingDecision) -> int:
        cost_policy = decision.cost_policy or {}
        try:
            return max(int(cost_policy.get("max_agent_count", 1)), 1)
        except (TypeError, ValueError):
            return 1
