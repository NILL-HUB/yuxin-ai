from internal.entity.cancel_token_entity import CancelToken
from internal.entity.execution_orchestration_entity import (
    TaskPlan,
    TaskPlanItem,
)
from internal.service.execution_coordinator_service import ExecutionCoordinatorService
from internal.service.cost_policy_service import EscalationPolicyService
from internal.service.subtask_registry_service import SubtaskRegistryService


class FailingExecutor:
    def __init__(self, failing_task_ids=None):
        self.failing_task_ids = set(failing_task_ids or [])

    def execute(self, item, context=None):
        if item.task_id in self.failing_task_ids:
            raise RuntimeError(f"boom:{item.task_id}")
        return {
            "agent_id": f"agent-{item.agent_pool}",
            "task_id": item.task_id,
            "answer": f"answer:{item.title}",
            "confidence": 0.8,
        }


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, item, context=None):
        self.calls.append(item.task_id)
        return {
            "agent_id": f"agent-{item.agent_pool}",
            "task_id": item.task_id,
            "answer": f"answer:{item.title}",
            "confidence": 0.8,
        }


def _plan(execution_mode, items):
    return TaskPlan(
        original_query="query",
        execution_mode=execution_mode,
        reason="test",
        items=items,
    )


def _item(task_id, order=0, depends_on=None, pool="general"):
    return TaskPlanItem(
        task_id=task_id,
        title=task_id,
        description=task_id,
        agent_pool=pool,
        depends_on=depends_on or [],
        execution_order=order,
    )


def test_execution_coordinator_should_run_direct_answer():
    executor = FakeExecutor()
    coordinator = ExecutionCoordinatorService(executor=executor)
    plan = _plan("direct_answer", [_item("task-1")])

    results = coordinator.execute(plan)

    assert executor.calls == ["task-1"]
    assert len(results) == 1
    assert results[0].answer == "answer:task-1"


def test_execution_coordinator_should_run_single_agent_only_once():
    executor = FakeExecutor()
    coordinator = ExecutionCoordinatorService(executor=executor)
    plan = _plan("single_agent", [_item("task-1"), _item("task-2")])

    results = coordinator.execute(plan)

    assert executor.calls == ["task-1"]
    assert len(results) == 1


def test_execution_coordinator_should_run_parallel_tasks():
    executor = FakeExecutor()
    coordinator = ExecutionCoordinatorService(executor=executor)
    plan = _plan(
        "multi_agent_parallel", [_item("task-1"), _item("task-2")]
    )

    results = coordinator.execute(plan)

    assert set(executor.calls) == {"task-1", "task-2"}
    assert len(executor.calls) == 2
    assert [result.task_id for result in results] == ["task-1", "task-2"]


def test_execution_coordinator_should_run_serial_tasks_by_order():
    executor = FakeExecutor()
    coordinator = ExecutionCoordinatorService(executor=executor)
    plan = _plan(
        "multi_agent_serial",
        [_item("task-2", order=2), _item("task-1", order=1)],
    )

    coordinator.execute(plan)

    assert executor.calls == ["task-1", "task-2"]


def test_execution_coordinator_should_run_deep_thinking_with_stage_warnings():
    executor = FakeExecutor()
    coordinator = ExecutionCoordinatorService(executor=executor)
    plan = _plan(
        "deep_thinking", [_item("research"), _item("analysis", order=1)]
    )

    results = coordinator.execute(plan)

    assert executor.calls == ["research", "analysis"]
    assert results[0].warnings == ["deep_thinking_stage:research"]


def test_execution_coordinator_should_isolate_single_agent_failure():
    coordinator = ExecutionCoordinatorService(executor=FailingExecutor({"task-1"}))
    results = coordinator.execute(_plan("single_agent", [_item("task-1")]))

    assert len(results) == 1
    assert results[0].answer == ""
    assert results[0].errors == ["agent_execution_failed"]
    assert results[0].warnings == ["fallback:task_failed"]


def test_execution_coordinator_should_return_partial_results_when_some_fail():
    coordinator = ExecutionCoordinatorService(executor=FailingExecutor({"task-2"}))
    results = coordinator.execute(
        _plan("multi_agent_parallel", [_item("task-1"), _item("task-2")])
    )

    assert [result.task_id for result in results] == ["task-1", "task-2"]
    assert results[0].answer == "answer:task-1"
    assert results[1].errors == ["agent_execution_failed"]


def test_execution_coordinator_should_return_global_fallback_when_all_fail():
    coordinator = ExecutionCoordinatorService(
        executor=FailingExecutor({"task-1", "task-2"})
    )
    results = coordinator.execute(
        _plan("multi_agent_parallel", [_item("task-1"), _item("task-2")])
    )

    assert len(results) == 1
    assert results[0].task_id == "fallback"
    assert results[0].answer == "当前任务暂时无法完成，请稍后重试或缩小任务范围。"
    assert results[0].warnings == ["fallback:all_agents_failed"]
    assert results[0].errors == ["agent_execution_failed"]


def test_cancel_token_should_stop_remaining_iterations():
    executor = FakeExecutor()
    cancel_token = CancelToken()
    coordinator = ExecutionCoordinatorService(
        executor=executor, cancel_token=cancel_token
    )
    plan = _plan("multi_agent_serial", [_item("task-1", order=1), _item("task-2", order=2)])

    cancel_token.cancel()
    results = coordinator.execute(plan)

    assert executor.calls == []
    assert results == []


def test_cancel_token_should_break_mid_execution_when_cancelled_between_items():
    class _CancellingExecutor:
        def __init__(self, cancel_token):
            self.cancel_token = cancel_token
            self.calls = []

        def execute(self, item, context=None):
            self.calls.append(item.task_id)
            if item.task_id == "task-1":
                self.cancel_token.cancel()
            return {
                "agent_id": f"agent-{item.agent_pool}",
                "task_id": item.task_id,
                "answer": f"answer:{item.title}",
                "confidence": 0.8,
            }

    cancel_token = CancelToken()
    executor = _CancellingExecutor(cancel_token)
    coordinator = ExecutionCoordinatorService(
        executor=executor, cancel_token=cancel_token
    )
    plan = _plan(
        "multi_agent_serial", [_item("task-1", order=1), _item("task-2", order=2)]
    )

    results = coordinator.execute(plan)

    assert executor.calls == ["task-1"]
    assert [result.task_id for result in results] == ["task-1"]


def test_cancel_token_reset_should_allow_reuse():
    token = CancelToken()
    assert token.is_cancelled() is False
    token.cancel()
    assert token.is_cancelled() is True
    token.reset()
    assert token.is_cancelled() is False


def test_parallel_execution_should_run_items_concurrently():
    import threading

    barrier = threading.Barrier(2, timeout=2)
    completed = []

    class _BarrierExecutor:
        def execute(self, item, context=None):
            barrier.wait()
            completed.append(item.task_id)
            return {
                "agent_id": f"agent-{item.agent_pool}",
                "task_id": item.task_id,
                "answer": f"answer:{item.title}",
                "confidence": 0.8,
            }

    coordinator = ExecutionCoordinatorService(executor=_BarrierExecutor())
    plan = _plan("multi_agent_parallel", [_item("task-1"), _item("task-2")])

    results = coordinator.execute(plan)

    assert set(completed) == {"task-1", "task-2"}
    assert len(results) == 2
    assert all(not result.errors for result in results)


def test_sequential_execution_should_respect_depends_on_ordering():
    calls = []

    class _RecordingExecutor:
        def execute(self, item, context=None):
            calls.append(item.task_id)
            return {
                "agent_id": f"agent-{item.agent_pool}",
                "task_id": item.task_id,
                "answer": f"answer:{item.title}",
                "confidence": 0.8,
            }

    coordinator = ExecutionCoordinatorService(executor=_RecordingExecutor())
    plan = _plan(
        "multi_agent_sequential",
        [
            _item("task-1", order=2),
            _item("task-2", order=1, depends_on=["task-1"]),
            _item("task-3", order=0, depends_on=["task-2"]),
        ],
    )

    coordinator.execute(plan)

    assert calls == ["task-1", "task-2", "task-3"]


def test_parallel_execution_should_sort_results_deterministically():
    executor = FakeExecutor()
    coordinator = ExecutionCoordinatorService(executor=executor)
    plan = _plan(
        "multi_agent_parallel",
        [_item("task-3", order=0), _item("task-1", order=0), _item("task-2", order=0)],
    )

    results = coordinator.execute(plan)

    assert set(executor.calls) == {"task-1", "task-2", "task-3"}
    assert [result.task_id for result in results] == ["task-1", "task-2", "task-3"]


def test_parallel_execution_should_skip_tasks_whose_dependency_failed():
    executor = FailingExecutor({"task-1"})
    coordinator = ExecutionCoordinatorService(executor=executor)
    plan = _plan(
        "multi_agent_parallel",
        [
            _item("task-1", order=0),
            _item("task-2", order=1, depends_on=["task-1"]),
            _item("task-3", order=2),
        ],
    )

    results = coordinator.execute(plan)

    by_id = {result.task_id: result for result in results}
    assert by_id["task-1"].errors == ["agent_execution_failed"]
    assert by_id["task-2"].errors == ["dependency_failed"]
    assert by_id["task-3"].answer == "answer:task-3"


def test_sequential_execution_should_skip_tasks_whose_dependency_failed():
    executor = FailingExecutor({"task-1"})
    coordinator = ExecutionCoordinatorService(executor=executor)
    plan = _plan(
        "multi_agent_sequential",
        [
            _item("task-1", order=0),
            _item("task-2", order=1, depends_on=["task-1"]),
            _item("task-3", order=2),
        ],
    )

    results = coordinator.execute(plan)

    by_id = {result.task_id: result for result in results}
    assert by_id["task-1"].errors == ["agent_execution_failed"]
    assert by_id["task-2"].errors == ["dependency_failed"]
    assert by_id["task-3"].answer == "answer:task-3"


def test_sequential_execution_should_pass_upstream_output_to_downstream():
    calls = []

    class _ContextExecutor:
        def execute(self, item, context=None):
            calls.append((item.task_id, context or {}))
            return {
                "agent_id": f"agent-{item.agent_pool}",
                "task_id": item.task_id,
                "answer": f"answer:{item.title}",
                "confidence": 0.8,
            }

    coordinator = ExecutionCoordinatorService(executor=_ContextExecutor())
    plan = _plan(
        "multi_agent_sequential",
        [
            _item("task-1", order=0),
            _item("task-2", order=1, depends_on=["task-1"]),
        ],
    )

    coordinator.execute(plan)

    by_id = {task_id: context for task_id, context in calls}
    assert by_id["task-1"] == {}
    assert by_id["task-2"]["upstream_results"]["task-1"]["answer"] == "answer:task-1"


def test_parallel_execution_should_pass_upstream_output_between_waves():
    calls = []

    class _ContextExecutor:
        def execute(self, item, context=None):
            calls.append((item.task_id, context or {}))
            return {
                "agent_id": f"agent-{item.agent_pool}",
                "task_id": item.task_id,
                "answer": f"answer:{item.title}",
                "confidence": 0.8,
            }

    coordinator = ExecutionCoordinatorService(executor=_ContextExecutor())
    plan = _plan(
        "multi_agent_parallel",
        [
            _item("task-1", order=0),
            _item("task-2", order=1, depends_on=["task-1"]),
        ],
    )

    coordinator.execute(plan)

    by_id = {task_id: context for task_id, context in calls}
    assert by_id["task-1"] == {}
    assert by_id["task-2"]["upstream_results"]["task-1"]["answer"] == "answer:task-1"


def test_execution_coordinator_should_retry_failed_task_when_configured():
    calls = []

    class _RetryExecutor:
        def execute(self, item, context=None):
            calls.append(item.task_id)
            if len(calls) == 1:
                raise RuntimeError("first attempt failed")
            return {
                "agent_id": "agent",
                "task_id": item.task_id,
                "answer": "retry-success",
                "confidence": 0.8,
            }

    item = _item("task-1")
    item.retry_count = 1
    coordinator = ExecutionCoordinatorService(executor=_RetryExecutor())

    results = coordinator.execute(_plan("single_agent", [item]))

    assert len(calls) == 2
    assert results[0].answer == "retry-success"


def test_execution_coordinator_should_mark_retried_failure_when_exhausted():
    class _AlwaysFailingExecutor:
        def execute(self, item, context=None):
            raise RuntimeError("always fails")

    item = _item("task-1")
    item.retry_count = 1
    coordinator = ExecutionCoordinatorService(executor=_AlwaysFailingExecutor())

    results = coordinator.execute(_plan("single_agent", [item]))

    assert results[0].errors == ["agent_execution_failed"]
    assert "retried:1" in results[0].warnings


def test_execution_coordinator_should_timeout_slow_task():
    import time

    class _SlowExecutor:
        def execute(self, item, context=None):
            time.sleep(0.2)
            return {
                "agent_id": "agent",
                "task_id": item.task_id,
                "answer": "too-late",
                "confidence": 0.8,
            }

    item = _item("task-1")
    item.timeout_seconds = 0.05
    coordinator = ExecutionCoordinatorService(executor=_SlowExecutor())

    results = coordinator.execute(_plan("single_agent", [item]))

    assert results[0].errors == ["agent_execution_timeout"]
    assert results[0].warnings == ["fallback:task_timeout"]


def test_execution_coordinator_should_not_timeout_fast_task():
    executor = FakeExecutor()
    item = _item("task-1")
    item.timeout_seconds = 5.0
    coordinator = ExecutionCoordinatorService(executor=executor)

    results = coordinator.execute(_plan("single_agent", [item]))

    assert results[0].answer == "answer:task-1"


def test_execution_coordinator_should_resume_from_snapshot():
    registry = SubtaskRegistryService(_force_memory=True)
    plan = _plan(
        "multi_agent_sequential",
        [
            _item("task-1", order=0),
            _item("task-2", order=1, depends_on=["task-1"]),
        ],
    )
    registry.register_plan(
        request_id="req-1",
        execution_mode="multi_agent_sequential",
        original_query="query",
        items=plan.items,
    )
    registry.mark_completed(
        "req-1",
        "task-1",
        answer_preview="done",
    )

    calls = []

    class _RecordingExecutor:
        def execute(self, item, context=None):
            calls.append(item.task_id)
            return {
                "agent_id": f"agent-{item.agent_pool}",
                "task_id": item.task_id,
                "answer": f"answer:{item.title}",
                "confidence": 0.8,
            }

    coordinator = ExecutionCoordinatorService(
        executor=_RecordingExecutor(),
        subtask_registry=registry,
    )

    results = coordinator.execute(plan, request_id="req-1", resume=True)

    assert calls == ["task-2"]
    assert [result.task_id for result in results] == ["task-1", "task-2"]
    assert results[0].warnings == ["resumed:completed"]


def test_execution_coordinator_should_repair_plan_when_failures_exist():
    calls = []

    class _Executor:
        def execute(self, item, context=None):
            calls.append(item.task_id)
            if item.task_id == "task-1":
                raise RuntimeError("original failed")
            return {
                "agent_id": "agent",
                "task_id": item.task_id,
                "answer": f"answer:{item.title}",
                "confidence": 0.8,
            }

    def _repairer(original_query, failures):
        return _plan(
            "single_agent",
            [_item("repaired-task")],
        )

    coordinator = ExecutionCoordinatorService(
        executor=_Executor(),
        plan_repairer=_repairer,
    )
    plan = _plan("single_agent", [_item("task-1")])

    results = coordinator.execute(plan)

    assert calls == ["task-1", "repaired-task"]
    assert results[0].answer == "answer:repaired-task"


def test_execution_coordinator_should_keep_original_results_when_repairer_returns_none():
    calls = []

    class _FailingExecutor:
        def execute(self, item, context=None):
            calls.append(item.task_id)
            raise RuntimeError("failed")

    coordinator = ExecutionCoordinatorService(
        executor=_FailingExecutor(),
        plan_repairer=lambda original_query, failures: None,
    )
    plan = _plan("single_agent", [_item("task-1")])

    results = coordinator.execute(plan)

    assert calls == ["task-1"]
    assert results[0].errors == ["agent_execution_failed"]


def _metadata_executor(tier="standard", total_tokens=0):
    class _Executor:
        def execute(self, item, context=None):
            return {
                "agent_id": "a",
                "task_id": item.task_id,
                "answer": f"answer:{item.title}",
                "confidence": 0.8,
                "metadata": {
                    "tier": tier,
                    "token_usage": {"total_tokens": total_tokens},
                },
            }

    return _Executor()


def _tier_item(task_id="task-1", complexity=None, balance=None, budget=None):
    item = _item(task_id)
    if complexity is not None:
        item.complexity = complexity
    if balance is not None:
        item.balance_credits = balance
    if budget is not None:
        item.budget_level = budget
    return item


def test_escalation_triggers_upgrade():
    executor = _metadata_executor(tier="2", total_tokens=0)
    item = _tier_item(
        complexity="complex", balance=float("inf"), budget="high"
    )
    coordinator = ExecutionCoordinatorService(
        executor=executor, escalation_policy_service=EscalationPolicyService()
    )
    plan = _plan("single_agent", [item])

    results = coordinator.execute(plan)

    assert "escalation:2->3" in results[0].warnings


def test_escalation_triggers_downgrade():
    executor = _metadata_executor(tier="3", total_tokens=0)
    item = _tier_item(
        complexity="simple", balance=50.0, budget="high"
    )
    coordinator = ExecutionCoordinatorService(
        executor=executor, escalation_policy_service=EscalationPolicyService()
    )
    plan = _plan("single_agent", [item])

    results = coordinator.execute(plan)

    assert "escalation:3->1" in results[0].warnings


def test_escalation_no_change():
    executor = _metadata_executor(tier="2", total_tokens=0)
    item = _tier_item(
        complexity="medium", balance=float("inf"), budget="medium"
    )
    coordinator = ExecutionCoordinatorService(
        executor=executor, escalation_policy_service=EscalationPolicyService()
    )
    plan = _plan("single_agent", [item])

    results = coordinator.execute(plan)

    assert not any(w.startswith("escalation:") for w in results[0].warnings)


def test_no_escalation_service():
    executor = FakeExecutor()
    coordinator = ExecutionCoordinatorService(executor=executor)
    plan = _plan("single_agent", [_item("task-1")])

    results = coordinator.execute(plan)

    assert len(results) == 1
    assert results[0].answer == "answer:task-1"
    assert not any(w.startswith("escalation:") for w in results[0].warnings)


def _patch_billing_config_enabled(monkeypatch, row):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from internal.extension import database_extension

    session = MagicMock()
    session.query.return_value.filter.return_value.one_or_none.return_value = row
    monkeypatch.setattr(database_extension, "db", SimpleNamespace(session=session))


def test_resolve_escalation_policy_service_injects_when_enabled(monkeypatch):
    from types import SimpleNamespace

    from internal.service.cost_policy_service import EscalationPolicyService
    from internal.service.execution_coordinator_service import (
        resolve_escalation_policy_service,
    )

    _patch_billing_config_enabled(
        monkeypatch,
        SimpleNamespace(code="escalation_enabled", value_numeric=1),
    )

    svc = resolve_escalation_policy_service()

    assert svc is not None
    assert isinstance(svc, EscalationPolicyService)


def test_resolve_escalation_policy_service_none_when_unconfigured(monkeypatch):
    from internal.service.execution_coordinator_service import (
        resolve_escalation_policy_service,
    )

    _patch_billing_config_enabled(monkeypatch, None)

    assert resolve_escalation_policy_service() is None


def test_resolve_escalation_policy_service_none_when_query_fails(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from internal.extension import database_extension
    from internal.service.execution_coordinator_service import (
        resolve_escalation_policy_service,
    )

    session = MagicMock()
    session.query.side_effect = RuntimeError("db unavailable")
    monkeypatch.setattr(database_extension, "db", SimpleNamespace(session=session))

    assert resolve_escalation_policy_service() is None


def test_resolve_escalation_policy_service_none_when_disabled(monkeypatch):
    from types import SimpleNamespace

    from internal.service.execution_coordinator_service import (
        resolve_escalation_policy_service,
    )

    _patch_billing_config_enabled(
        monkeypatch,
        SimpleNamespace(code="escalation_enabled", value_numeric=0),
    )

    assert resolve_escalation_policy_service() is None
