import logging
import time
logger = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Protocol

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

_ESCALATION_ENABLED_CODE = "escalation_enabled"


def resolve_escalation_policy_service():
    """按 billing_config 开关「escalation_enabled」决定是否生产注入 EscalationPolicyService。

    规则：
    - billing_config 中 code='escalation_enabled' 且 value_numeric >= 1 -> 返回 EscalationPolicyService()
    - 未配置 / value_numeric < 1 / 查询失败（数据库不可用等）-> None（默认关闭，保持现状）
    """
    try:
        from internal.extension.database_extension import db
        from internal.model.billing import BillingConfig
        from internal.service.cost_policy_service import EscalationPolicyService

        row = (
            db.session.query(BillingConfig)
            .filter(BillingConfig.code == _ESCALATION_ENABLED_CODE)
            .one_or_none()
        )
        if row is None:
            return None
        if float(row.value_numeric or 0) >= 1:
            return EscalationPolicyService()
        return None
    except Exception:
        return None


class TaskExecutor(Protocol):
    def execute(self, item: TaskPlanItem, context: dict | None = None) -> dict:
        pass


class ExecutionCoordinatorService:
    def __init__(
        self,
        executor: TaskExecutor,
        cancel_token: CancelToken | None = None,
        event_logger=None,
        escalation_policy_service=None,
        subtask_registry=None,
        request_id: str = "",
        plan_repairer: Callable[[str, list[dict]], TaskPlan | None] | None = None,
    ):
        self.executor = executor
        self.cancel_token = cancel_token or CancelToken()
        self.event_logger = event_logger
        self.escalation_policy_service = escalation_policy_service
        self.subtask_registry = subtask_registry
        self.request_id = request_id
        self.plan_repairer = plan_repairer

    def execute(
        self,
        plan: TaskPlan,
        routing_log_id=None,
        request_id: str = "",
        resume: bool = False,
    ) -> list[OrchestratedAgentResult]:
        effective_request_id = request_id or self.request_id or str(routing_log_id or "")
        self.request_id = effective_request_id
        if (
            not resume
            and self.subtask_registry is not None
            and effective_request_id
        ):
            try:
                self.subtask_registry.register_plan(
                    request_id=effective_request_id,
                    execution_mode=plan.execution_mode,
                    original_query=plan.original_query,
                    items=plan.items,
                )
            except Exception:
                logger.warning("注册子任务计划失败", exc_info=True)
        initial_results = {}
        if resume and self.subtask_registry is not None and effective_request_id:
            try:
                snapshot = self.subtask_registry.snapshot(effective_request_id)
                if snapshot:
                    initial_results = self._results_from_snapshot(plan, snapshot)
                elif self.subtask_registry is not None:
                    self.subtask_registry.register_plan(
                        request_id=effective_request_id,
                        execution_mode=plan.execution_mode,
                        original_query=plan.original_query,
                        items=plan.items,
                    )
            except Exception:
                logger.warning("读取子任务快照失败，忽略 resume", exc_info=True)
        results = self._run_plan(plan, initial_results=initial_results)
        if self.plan_repairer is not None and self._has_failures(results):
            try:
                failures = [
                    result.to_user_safe_dict()
                    for result in results
                    if result.errors
                ]
                repaired = self.plan_repairer(plan.original_query, failures)
                if repaired is not None and repaired.items:
                    results = self._run_plan(repaired, initial_results={})
            except Exception:
                logger.warning("计划修复失败，保留原结果", exc_info=True)
        self._emit_agent_completed(routing_log_id, results)
        return results

    @staticmethod
    def _has_failures(results: list[OrchestratedAgentResult]) -> bool:
        return any(result.errors for result in results)

    def _run_plan(
        self,
        plan: TaskPlan,
        initial_results: dict[str, OrchestratedAgentResult] | None = None,
    ) -> list[OrchestratedAgentResult]:
        initial_results = initial_results or {}
        if not plan.items:
            return []
        if plan.execution_mode in _SINGLE_SHOT_MODES:
            if plan.items[0].task_id in initial_results:
                return [initial_results[plan.items[0].task_id]]
            return [self._safe_execute_item(plan.items[0], plan.execution_mode)]
        if plan.execution_mode in _PARALLEL_MODES:
            return self._run_parallel(plan, initial_results=initial_results)
        return self._run_sequential(plan, initial_results=initial_results)

    def _run_parallel(
        self,
        plan: TaskPlan,
        initial_results: dict[str, OrchestratedAgentResult] | None = None,
    ) -> list[OrchestratedAgentResult]:
        items = list(plan.items)
        results_by_id: dict[str, OrchestratedAgentResult] = dict(initial_results or {})
        completed_ids: set[str] = set(results_by_id)
        failed_ids: set[str] = {
            task_id
            for task_id, result in results_by_id.items()
            if result.errors
        }
        remaining = [
            item for item in items
            if item.task_id not in results_by_id
        ]
        while remaining:
            if self.cancel_token.is_cancelled():
                break
            ready, remaining, skipped = self._split_ready(
                remaining,
                completed_ids,
                failed_ids,
            )
            for item in skipped:
                result = self._dependency_failed_result(item)
                results_by_id[item.task_id] = result
                completed_ids.add(item.task_id)
                failed_ids.add(item.task_id)
            if not ready:
                if not remaining:
                    continue
                ready, remaining = remaining, []
            if not ready:
                continue
            wave_results = self._run_wave(
                ready,
                plan.execution_mode,
                self._build_context_map(items, results_by_id),
            )
            for task_id, result in wave_results.items():
                results_by_id[task_id] = result
                completed_ids.add(task_id)
                if result.errors:
                    failed_ids.add(task_id)
        if not results_by_id:
            return []
        ordered = self._ordered_items(items)
        results = [results_by_id[item.task_id] for item in ordered if item.task_id in results_by_id]
        return self._apply_global_fallback(results)

    def _run_wave(
        self,
        items: list[TaskPlanItem],
        execution_mode: str,
        context_map: dict[str, dict] | None = None,
    ) -> dict[str, OrchestratedAgentResult]:
        context_map = context_map or {}
        if len(items) == 1:
            item = items[0]
            return {
                item.task_id: self._safe_execute_item(
                    item,
                    execution_mode,
                    context_map.get(item.task_id),
                )
            }
        results: dict[str, OrchestratedAgentResult] = {}
        max_workers = min(len(items), _MAX_PARALLEL_WORKERS)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    self._safe_execute_item,
                    item,
                    execution_mode,
                    context_map.get(item.task_id),
                ): item
                for item in items
            }
            for future in as_completed(future_map):
                item = future_map[future]
                try:
                    results[item.task_id] = future.result()
                except Exception:
                    results[item.task_id] = self._failure_result(item)
        return results

    def _run_sequential(
        self,
        plan: TaskPlan,
        initial_results: dict[str, OrchestratedAgentResult] | None = None,
    ) -> list[OrchestratedAgentResult]:
        items = self._topological_sort(plan.items)
        results: list[OrchestratedAgentResult] = list(
            (initial_results or {}).values()
        )
        results_by_id: dict[str, OrchestratedAgentResult] = dict(initial_results or {})
        failed_ids: set[str] = {
            task_id
            for task_id, result in results_by_id.items()
            if result.errors
        }
        for item in items:
            if item.task_id in results_by_id:
                continue
            if self.cancel_token.is_cancelled():
                break
            if any(dep in failed_ids for dep in item.depends_on):
                result = self._dependency_failed_result(item)
                results.append(result)
                results_by_id[item.task_id] = result
                failed_ids.add(item.task_id)
                continue
            result = self._safe_execute_item(
                item,
                plan.execution_mode,
                self._build_upstream_context(item, results_by_id),
            )
            results.append(result)
            results_by_id[item.task_id] = result
            if result.errors:
                failed_ids.add(item.task_id)
        if not results_by_id:
            return []
        ordered = self._ordered_items(items)
        ordered_results = [
            results_by_id[item.task_id]
            for item in ordered
            if item.task_id in results_by_id
        ]
        return self._apply_global_fallback(ordered_results)

    @staticmethod
    def _results_from_snapshot(
        plan: TaskPlan,
        snapshot: dict,
    ) -> dict[str, OrchestratedAgentResult]:
        by_id = {item.task_id: item for item in plan.items}
        results = {}
        for raw in snapshot.get("items") or []:
            task_id = str(raw.get("task_id") or "")
            item = by_id.get(task_id)
            if item is None:
                continue
            status = str(raw.get("status") or "pending")
            errors = list(raw.get("errors") or [])
            if status == "pending" or status == "running":
                continue
            if status == "failed" or errors:
                results[task_id] = ExecutionCoordinatorService._dependency_failed_result(item)
                results[task_id].errors = errors or ["resumed_failed"]
                results[task_id].warnings = ["resumed:failed"]
            else:
                results[task_id] = OrchestratedAgentResult(
                    agent_id=item.task_id,
                    task_id=item.task_id,
                    answer=str(raw.get("answer_preview") or ""),
                    confidence=0,
                    warnings=["resumed:completed"],
                    errors=[],
                )
        return results

    @staticmethod
    def _build_context_map(
        items: list[TaskPlanItem],
        results_by_id: dict[str, OrchestratedAgentResult],
    ) -> dict[str, dict]:
        return {
            item.task_id: ExecutionCoordinatorService._build_upstream_context(
                item,
                results_by_id,
            )
            for item in items
        }

    @staticmethod
    def _build_upstream_context(
        item: TaskPlanItem,
        results_by_id: dict[str, OrchestratedAgentResult],
    ) -> dict:
        upstream = {
            task_id: results_by_id[task_id].to_user_safe_dict()
            for task_id in item.depends_on
            if task_id in results_by_id
        }
        return {"upstream_results": upstream} if upstream else {}

    @staticmethod
    def _split_ready(remaining, completed_ids, failed_ids=None):
        failed_ids = failed_ids or set()
        ready = []
        rest = []
        skipped = []
        for item in remaining:
            if any(dep in failed_ids for dep in item.depends_on):
                skipped.append(item)
            elif all(dep in completed_ids for dep in item.depends_on):
                ready.append(item)
            else:
                rest.append(item)
        return ready, rest, skipped

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
        self,
        item: TaskPlanItem,
        execution_mode: str,
        context: dict | None = None,
    ) -> OrchestratedAgentResult:
        attempts = max(int(item.retry_count or 0), 0) + 1
        result = None
        for attempt in range(attempts):
            try:
                self._mark_running(item)
                result = self._execute_item_with_timeout(item, execution_mode, context)
                self._mark_completed(item, result)
                if not result.errors:
                    return result
            except Exception:
                result = self._failure_result(item)
                self._mark_completed(item, result)
            if attempt < attempts - 1:
                interval = max(float(item.retry_interval or 0), 0.0)
                if interval > 0:
                    time.sleep(interval)
        if result is None:
            result = self._failure_result(item)
        if attempts > 1 and result.errors:
            result.warnings.append(f"retried:{attempts - 1}")
        return result

    def _execute_item_with_timeout(
        self,
        item: TaskPlanItem,
        execution_mode: str,
        context: dict | None = None,
    ) -> OrchestratedAgentResult:
        timeout = max(float(item.timeout_seconds or 0), 0.0)
        if timeout <= 0:
            return self._execute_item(item, execution_mode, context)
        # 软超时：返回失败结果让协调器继续，但不强杀正在执行的 Agent/工具线程。
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._execute_item, item, execution_mode, context)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            executor.shutdown(wait=False, cancel_futures=True)
            return self._timeout_result(item, timeout)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _timeout_result(
        item: TaskPlanItem,
        timeout: float,
    ) -> OrchestratedAgentResult:
        return OrchestratedAgentResult(
            agent_id="",
            task_id=item.task_id,
            answer="",
            confidence=0,
            warnings=["fallback:task_timeout"],
            errors=["agent_execution_timeout"],
        )

    def _mark_running(self, item: TaskPlanItem) -> None:
        if self.subtask_registry is None or not self.request_id:
            return
        try:
            self.subtask_registry.mark_running(self.request_id, item.task_id)
        except Exception:
            logger.warning("标记子任务 running 失败", exc_info=True)

    def _mark_completed(self, item: TaskPlanItem, result: OrchestratedAgentResult) -> None:
        if self.subtask_registry is None or not self.request_id:
            return
        try:
            self.subtask_registry.mark_completed(
                self.request_id,
                item.task_id,
                answer_preview=result.answer,
                errors=result.errors or None,
            )
        except Exception:
            logger.warning("标记子任务 completed 失败", exc_info=True)

    def _execute_item(
        self,
        item: TaskPlanItem,
        execution_mode: str,
        context: dict | None = None,
    ) -> OrchestratedAgentResult:
        result = OrchestratedAgentResult.from_dict(
            self.executor.execute(item, context=context)
        )
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
    def _dependency_failed_result(item: TaskPlanItem) -> OrchestratedAgentResult:
        return OrchestratedAgentResult(
            agent_id="",
            task_id=item.task_id,
            answer="",
            confidence=0,
            warnings=["fallback:dependency_failed"],
            errors=["dependency_failed"],
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
