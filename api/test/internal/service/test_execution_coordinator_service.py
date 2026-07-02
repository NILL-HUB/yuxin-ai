from internal.entity.cancel_token_entity import CancelToken
from internal.entity.execution_orchestration_entity import (
    TaskPlan,
    TaskPlanItem,
)
from internal.service.execution_coordinator_service import ExecutionCoordinatorService
from internal.service.cost_policy_service import EscalationPolicyService


class FailingExecutor:
    def __init__(self, failing_task_ids=None):
        self.failing_task_ids = set(failing_task_ids or [])

    def execute(self, item):
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

    def execute(self, item):
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

        def execute(self, item):
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
        def execute(self, item):
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
        def execute(self, item):
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


def _metadata_executor(tier="standard", total_tokens=0):
    class _Executor:
        def execute(self, item):
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
    executor = _metadata_executor(tier="standard", total_tokens=0)
    item = _tier_item(
        complexity="complex", balance=float("inf"), budget="high"
    )
    coordinator = ExecutionCoordinatorService(
        executor=executor, escalation_policy_service=EscalationPolicyService()
    )
    plan = _plan("single_agent", [item])

    results = coordinator.execute(plan)

    assert "escalation:standard->strong" in results[0].warnings


def test_escalation_triggers_downgrade():
    executor = _metadata_executor(tier="strong", total_tokens=0)
    item = _tier_item(
        complexity="simple", balance=50.0, budget="high"
    )
    coordinator = ExecutionCoordinatorService(
        executor=executor, escalation_policy_service=EscalationPolicyService()
    )
    plan = _plan("single_agent", [item])

    results = coordinator.execute(plan)

    assert "escalation:strong->cheap" in results[0].warnings


def test_escalation_no_change():
    executor = _metadata_executor(tier="standard", total_tokens=0)
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
