from uuid import uuid4

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent


class _QueueStub:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


def _make_manager(task_id):
    manager = AgentQueueManager.__new__(AgentQueueManager)
    manager._terminal_events = {}
    manager._queues = {str(task_id): _QueueStub()}
    manager.stop_listen = lambda *_args, **_kwargs: None
    return manager


def _make_thought(task_id, event_value):
    return AgentThought(
        id=uuid4(),
        task_id=task_id,
        event=event_value,
    )


def test_billing_final_should_not_be_dropped_after_agent_end():
    task_id = uuid4()
    manager = _make_manager(task_id)

    manager.publish(task_id, _make_thought(task_id, QueueEvent.AGENT_END.value))
    manager.publish(task_id, _make_thought(task_id, QueueEvent.BILLING_FINAL.value))

    assert len(manager._queues[str(task_id)].items) == 2


def test_billing_cancelled_should_not_be_dropped_after_stop():
    task_id = uuid4()
    manager = _make_manager(task_id)

    manager.publish(task_id, _make_thought(task_id, QueueEvent.STOP.value))
    manager.publish(task_id, _make_thought(task_id, QueueEvent.BILLING_CANCELLED.value))

    assert len(manager._queues[str(task_id)].items) == 2


def test_billing_summary_should_pass_through_after_terminal():
    task_id = uuid4()
    manager = _make_manager(task_id)

    manager.publish(task_id, _make_thought(task_id, QueueEvent.ERROR.value))
    manager.publish(task_id, _make_thought(task_id, QueueEvent.BILLING_SUMMARY.value))

    assert len(manager._queues[str(task_id)].items) == 2


def test_non_billing_event_should_still_be_dropped_after_terminal():
    task_id = uuid4()
    manager = _make_manager(task_id)

    manager.publish(task_id, _make_thought(task_id, QueueEvent.AGENT_END.value))
    manager.publish(task_id, _make_thought(task_id, QueueEvent.AGENT_MESSAGE.value))

    assert len(manager._queues[str(task_id)].items) == 1


def test_billing_delta_should_be_dropped_after_terminal():
    task_id = uuid4()
    manager = _make_manager(task_id)

    manager.publish(task_id, _make_thought(task_id, QueueEvent.AGENT_END.value))
    manager.publish(task_id, _make_thought(task_id, QueueEvent.BILLING_DELTA.value))

    assert len(manager._queues[str(task_id)].items) == 1
