import logging
logger = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol

from internal.entity.cancel_token_entity import CancelToken
from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
    TaskPlan,
    TaskPlanItem,
)
from internal.entity.orchestrator_entity import ExecutionMode


_SINGLE_SHOT_MODES = {
    ExecutionMode.DIRECT_ANSWER.value,
    ExecutionMode.SINGLE_AGENT.value,
    ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value,
    ExecutionMode.REJECT_OR_CONFIRM.value,
    "blocked",
}

_PARALLEL_MODES = {
    ExecutionMode.MULTI_AGENT.value,
    ExecutionMode.MULTI_AGENT_PARALLEL.value,
}

_MAX_PARALLEL_WORKERS = 8


class TaskExecutor(Protocol):
    def execute(self, item: TaskPlanItem) -> dict:
        pass


class ExecutionCoordinatorService:
    def __init__(
        self,
        executor: TaskExecutor,
        cancel_token: CancelToken | None = None,
        event_logger=None,
        escalation_policy_service=None,
    ):
        self.executor = executor
        self.cancel_token = cancel_token or CancelToken()
        self.event_logger = event_logger
        self.escalation_policy_service = escalation_policy_service

    def execute(self, plan: TaskPlan, routing_log_id=None) -> list[OrchestratedAgentResult]:
        results = self._run_plan(plan)
        self._emit_agent_completed(routing_log_id, results)
        return results

    def _run_plan(self, plan: TaskPlan) -> list[OrchestratedAgentResult]:
        if not plan.items:
            return []
        if plan.execution_mode in _SINGLE_SHOT_MODES:
            return [self._safe_execute_item(plan.items[0], plan.execution_mode)]
        if plan.execution_mode in _PARALLEL_MODES:
            return self._run_parallel(plan)
        return self._run_sequential(plan)

    def _run_parallel(self, plan: TaskPlan) -> list[OrchestratedAgentResult]:
        items = list(plan.items)
        results_by_id: dict[str, OrchestratedAgentResult] = {}
        completed_ids: set[str] = set()
        remaining = items
        while remaining:
            if self.cancel_token.is_cancelled():
                break
            ready, remaining = self._split_ready(remaining, completed_ids)
            if not ready:
                ready, remaining = remaining, []
            wave_results = self._run_wave(ready, plan.execution_mode)
            for task_id, result in wave_results.items():
                results_by_id[task_id] = result
                completed_ids.add(task_id)
        if not results_by_id:
            return []
        ordered = self._ordered_items(items)
        results = [results_by_id[item.task_id] for item in ordered if item.task_id in results_by_id]
        return self._apply_global_fallback(results)

    def _run_wave(
        self, items: list[TaskPlanItem], execution_mode: str
    ) -> dict[str, OrchestratedAgentResult]:
        if len(items) == 1:
            item = items[0]
            return {item.task_id: self._safe_execute_item(item, execution_mode)}
        results: dict[str, OrchestratedAgentResult] = {}
        max_workers = min(len(items), _MAX_PARALLEL_WORKERS)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self._safe_execute_item, item, execution_mode): item
                for item in items
            }
            for future in as_completed(future_map):
                item = future_map[future]
                try:
                    results[item.task_id] = future.result()
                except Exception:
                    results[item.task_id] = self._failure_result(item)
        return results

    def _run_sequential(self, plan: TaskPlan) -> list[OrchestratedAgentResult]:
        items = self._topological_sort(plan.items)
        results: list[OrchestratedAgentResult] = []
        for item in items:
            if self.cancel_token.is_cancelled():
                break
            results.append(self._safe_execute_item(item, plan.execution_mode))
        if not results:
            return []
        return self._apply_global_fallback(results)

    @staticmethod
    def _split_ready(remaining, completed_ids):
        ready = []
        rest = []
        for item in remaining:
            if all(dep in completed_ids for dep in item.depends_on):
                ready.append(item)
            else:
                rest.append(item)
        return ready, rest

    @staticmethod
    def _ordered_items(items) -> list:
        return sorted(items, key=lambda item: (item.execution_order, item.task_id))

    @staticmethod
    def _topological_sort(items) -> list:
        item_by_id = {item.task_id: item for item in items}
        resolved: set[str] = set()
        ordered: list[TaskPlanItem] = []

        def _visit(item, visiting):
            if item.task_id in resolved or item.task_id in visiting:
                return
            visiting.add(item.task_id)
            for dep_id in item.depends_on:
                dep = item_by_id.get(dep_id)
                if dep is not None:
                    _visit(dep, visiting)
            visiting.discard(item.task_id)
            resolved.add(item.task_id)
            ordered.append(item)

        for item in sorted(items, key=lambda i: (i.execution_order, i.task_id)):
            _visit(item, set())
        return ordered

    @staticmethod
    def _apply_global_fallback(results) -> list:
        if results and all(result.errors for result in results):
            return [ExecutionCoordinatorService._global_fallback_result()]
        return results

    def _emit_agent_completed(self, routing_log_id, results) -> None:
        if self.event_logger is None or routing_log_id is None:
            return
        try:
            self.event_logger.log_event(
                "agent_completed",
                routing_log_id,
                {
                    "result_count": len(results),
                    "failed_count": sum(1 for r in results if r.errors),
                },
            )
        except Exception:
            logger.warning("记录 agent_completed 事件失败", exc_info=True)

    def _safe_execute_item(
        self, item: TaskPlanItem, execution_mode: str
    ) -> OrchestratedAgentResult:
        try:
            return self._execute_item(item, execution_mode)
        except Exception:
            return self._failure_result(item)

    def _execute_item(
        self, item: TaskPlanItem, execution_mode: str
    ) -> OrchestratedAgentResult:
        result = OrchestratedAgentResult.from_dict(self.executor.execute(item))
        if execution_mode == ExecutionMode.DEEP_THINKING.value:
            result.warnings.append(f"deep_thinking_stage:{item.task_id}")
        if self.escalation_policy_service is not None:
            self._check_escalation(result, item)
        return result

    def _check_escalation(
        self, result: OrchestratedAgentResult, item: TaskPlanItem
    ) -> None:
        try:
            metadata = getattr(result, "metadata", None) or {}
            token_count = metadata.get("token_usage", {}).get("total_tokens", 0)
            current_tier = metadata.get("tier", "2")
            task_complexity = getattr(item, "complexity", "simple")
            balance_credits = getattr(item, "balance_credits", float("inf"))
            budget_level = getattr(item, "budget_level", "medium")
            final_tier = self.escalation_policy_service.resolve_tier(
                current_tier=current_tier,
                token_count=token_count,
                task_complexity=task_complexity,
                balance_credits=balance_credits,
                budget_level=budget_level,
            )
            if final_tier != current_tier:
                result.warnings.append(f"escalation:{current_tier}->{final_tier}")
        except Exception:
            logger.warning("EscalationPolicy 检查失败", exc_info=True)

    @staticmethod
    def _failure_result(item: TaskPlanItem) -> OrchestratedAgentResult:
        return OrchestratedAgentResult(
            agent_id="",
            task_id=item.task_id,
            answer="",
            confidence=0,
            warnings=["fallback:task_failed"],
            errors=["agent_execution_failed"],
        )

    @staticmethod
    def _global_fallback_result() -> OrchestratedAgentResult:
        return OrchestratedAgentResult(
            agent_id="",
            task_id="fallback",
            answer="当前任务暂时无法完成，请稍后重试或缩小任务范围。",
            confidence=0,
            warnings=["fallback:all_agents_failed"],
            errors=["agent_execution_failed"],
        )
