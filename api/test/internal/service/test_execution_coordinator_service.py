from internal.entity.cancel_token_entity import CancelToken
from internal.entity.execution_orchestration_entity import (
    TaskPlan,
    TaskPlanItem,
)
from internal.service.execution_coordinator_service import ExecutionCoordinatorService


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

    assert executor.calls == ["task-1", "task-2"]
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
