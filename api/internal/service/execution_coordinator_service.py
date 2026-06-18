from typing import Protocol

from internal.entity.cancel_token_entity import CancelToken
from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
    TaskPlan,
    TaskPlanItem,
)


class TaskExecutor(Protocol):
    def execute(self, item: TaskPlanItem) -> dict:
        pass


class ExecutionCoordinatorService:
    def __init__(
        self,
        executor: TaskExecutor,
        cancel_token: CancelToken | None = None,
        event_logger=None,
    ):
        self.executor = executor
        self.cancel_token = cancel_token or CancelToken()
        self.event_logger = event_logger

    def execute(self, plan: TaskPlan, routing_log_id=None) -> list[OrchestratedAgentResult]:
        results = self._run_plan(plan)
        self._emit_agent_completed(routing_log_id, results)
        return results

    def _run_plan(self, plan: TaskPlan) -> list[OrchestratedAgentResult]:
        if not plan.items:
            return []
        if plan.execution_mode in {"direct_answer", "single_agent"}:
            return [self._safe_execute_item(plan.items[0], plan.execution_mode)]
        ordered_items = sorted(plan.items, key=lambda item: item.execution_order)
        results: list[OrchestratedAgentResult] = []
        for item in ordered_items:
            if self.cancel_token.is_cancelled():
                break
            results.append(self._safe_execute_item(item, plan.execution_mode))
        if not results:
            return []
        if all(result.errors for result in results):
            return [self._global_fallback_result()]
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
            pass

    def _safe_execute_item(
        self, item: TaskPlanItem, execution_mode: str
    ) -> OrchestratedAgentResult:
        try:
            return self._execute_item(item, execution_mode)
        except Exception:
            return OrchestratedAgentResult(
                agent_id="",
                task_id=item.task_id,
                answer="",
                confidence=0,
                warnings=["fallback:task_failed"],
                errors=["agent_execution_failed"],
            )

    def _execute_item(
        self, item: TaskPlanItem, execution_mode: str
    ) -> OrchestratedAgentResult:
        result = OrchestratedAgentResult.from_dict(self.executor.execute(item))
        if execution_mode == "deep_thinking":
            result.warnings.append(f"deep_thinking_stage:{item.task_id}")
        return result

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
