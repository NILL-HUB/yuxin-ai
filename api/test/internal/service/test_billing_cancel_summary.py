from uuid import uuid4

from internal.entity.billing_metering_entity import BillingEventType
from internal.service.billing_metering_service import BillingUsageAggregator


class TestBillingCancelSummary:
    def test_cancelled_event_should_carry_total_credits(self):
        task_id = str(uuid4())
        aggregator = BillingUsageAggregator(task_id=task_id)

        aggregator.started()
        aggregator.model_tokens(
            source_name="assistant_agent",
            input_tokens=100,
            output_tokens=50,
            reason="agent_message",
        )

        cancelled = aggregator.cancelled()
        assert cancelled.event_type == BillingEventType.CANCELLED.value
        assert cancelled.reason == "user_stop"
        assert "total_credits" in cancelled.to_sse()

    def test_cancelled_should_reflect_accumulated_credits(self):
        task_id = str(uuid4())
        aggregator = BillingUsageAggregator(task_id=task_id)

        aggregator.started()
        delta = aggregator.model_tokens(
            source_name="assistant_agent",
            input_tokens=200,
            output_tokens=100,
            reason="agent_message",
        )

        cancelled = aggregator.cancelled()
        assert cancelled.total_credits >= delta.total_credits

    def test_cancelled_should_carry_pending_phases(self):
        task_id = str(uuid4())
        aggregator = BillingUsageAggregator(task_id=task_id)

        aggregator.started()
        aggregator.model_tokens(
            source_name="assistant_agent",
            input_tokens=100,
            output_tokens=50,
            reason="agent_message",
        )

        cancelled = aggregator.cancelled(
            pending_phases=["工具调用", "结果合成"],
        )

        assert cancelled.event_type == BillingEventType.CANCELLED.value
        sse_payload = cancelled.to_sse()
        assert sse_payload["pending_phases"] == ["工具调用", "结果合成"]
        assert sse_payload["total_credits"] == cancelled.total_credits

    def test_final_should_be_distinct_from_cancelled(self):
        task_id = str(uuid4())
        aggregator = BillingUsageAggregator(task_id=task_id)

        aggregator.started()
        aggregator.model_tokens(
            source_name="assistant_agent",
            input_tokens=100,
            output_tokens=50,
            reason="agent_message",
        )

        final = aggregator.final()
        cancelled = aggregator.cancelled()

        assert final.event_type == BillingEventType.FINAL.value
        assert cancelled.event_type == BillingEventType.CANCELLED.value
        assert final.event_type != cancelled.event_type

    def test_stop_chat_should_set_redis_flag(self):
        from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
        from internal.core.agent.entities.agent_entity import InvokeFrom
        from types import SimpleNamespace

        task_id = uuid4()
        account = SimpleNamespace(id=uuid4())

        flag_set = False

        def _set_stop_flag(tid, invoke_from, user_id):
            nonlocal flag_set
            flag_set = True

        original = AgentQueueManager.set_stop_flag
        AgentQueueManager.set_stop_flag = classmethod(
            lambda cls, *args, **kwargs: _set_stop_flag(*args, **kwargs)
        )
        try:
            from internal.service.assistant_agent_service import AssistantAgentService
            AssistantAgentService.stop_chat(task_id, account)
        finally:
            AgentQueueManager.set_stop_flag = original

        assert flag_set is True

    def test_stop_chat_should_cancel_registered_token(self):
        from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
        from internal.entity.cancel_token_entity import CancelToken
        from internal.service.assistant_agent_service import AssistantAgentService
        from types import SimpleNamespace

        task_id = uuid4()
        account = SimpleNamespace(id=uuid4())
        token = CancelToken()
        AssistantAgentService._active_cancel_tokens[str(task_id)] = token

        original = AgentQueueManager.set_stop_flag
        AgentQueueManager.set_stop_flag = classmethod(
            lambda cls, *args, **kwargs: None
        )
        try:
            AssistantAgentService.stop_chat(task_id, account)
        finally:
            AgentQueueManager.set_stop_flag = original
            AssistantAgentService._active_cancel_tokens.pop(str(task_id), None)

        assert token.is_cancelled() is True
