import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from internal.entity.cancel_token_entity import CancelToken
from internal.service.executors.multi_agent_executor import MultiAgentExecutor
from internal.service.subtask_registry_service import SubtaskRegistryService


def _parse_payload(sse_event):
    return json.loads(sse_event.split("data:", 1)[1].strip())


def _conv():
    return SimpleNamespace(id=uuid4())


def _msg():
    return SimpleNamespace(id=uuid4())


def _routing_decision():
    return {
        "execution_mode": "multi_agent_parallel",
        "reason": "多领域任务",
        "task_plan_summary": {
            "aggregation_strategy": "concat",
            "agents": [
                {
                    "task_id": "t1",
                    "title": "任务一",
                    "description": "分析数据",
                    "agent_pool": "data",
                    "depends_on": [],
                    "execution_order": 0,
                    "timeout_seconds": 30,
                },
                {
                    "task_id": "t2",
                    "title": "任务二",
                    "description": "撰写报告",
                    "agent_pool": "writing",
                    "depends_on": ["t1"],
                    "execution_order": 1,
                },
            ],
        },
    }


def _fake_task_executor(mock_class, answers):
    fake = MagicMock()

    def _execute(item):
        answer = answers.get(item.task_id, "")
        return {
            "agent_id": item.task_id,
            "task_id": item.task_id,
            "answer": answer,
            "confidence": 1.0,
            "sources": [],
            "tool_calls": [],
            "warnings": [],
            "errors": [],
            "cost": {},
            "metadata": {
                "token_usage": {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
                "latency": 0.1,
            },
        }

    fake.execute.side_effect = _execute
    mock_class.return_value = fake
    return fake


class TestMultiAgentExecutor:
    def test_summarize_uses_llm_synthesis(self):
        captured = {}

        class _FakeLLM:
            def invoke(self, messages):
                captured["messages"] = messages
                return SimpleNamespace(content="综合结论：已完成分析与报告")

        executor = MultiAgentExecutor(
            agent_class=MagicMock(),
            llm=_FakeLLM(),
        )
        decision = _routing_decision()
        decision["task_plan_summary"]["aggregation_strategy"] = "summarize"

        with patch(
            "internal.service.executors.multi_agent_executor.AgentTaskExecutor"
        ) as mock_class:
            _fake_task_executor(mock_class, {"t1": "数据分析完成", "t2": "报告撰写完成"})
            events = list(executor.execute(
                query="任务",
                conversation=_conv(),
                message=_msg(),
                execution_mode="multi_agent_parallel",
                routing_decision=decision,
            ))

        final_messages = [
            _parse_payload(e) for e in events
            if e.startswith("event: agent_message")
        ]
        assert final_messages[0]["answer"] == "综合结论：已完成分析与报告"
        assert len(captured["messages"]) == 2

    def test_summarize_falls_back_to_concat(self):
        class _BrokenLLM:
            def invoke(self, messages):
                raise RuntimeError("llm down")

        executor = MultiAgentExecutor(
            agent_class=MagicMock(),
            llm=_BrokenLLM(),
        )
        decision = _routing_decision()
        decision["task_plan_summary"]["aggregation_strategy"] = "summarize"

        with patch(
            "internal.service.executors.multi_agent_executor.AgentTaskExecutor"
        ) as mock_class:
            _fake_task_executor(mock_class, {"t1": "数据分析完成", "t2": "报告撰写完成"})
            events = list(executor.execute(
                query="任务",
                conversation=_conv(),
                message=_msg(),
                execution_mode="multi_agent_parallel",
                routing_decision=decision,
            ))

        final_messages = [
            _parse_payload(e) for e in events
            if e.startswith("event: agent_message")
        ]
        assert "数据分析完成" in final_messages[0]["answer"]
        assert "报告撰写完成" in final_messages[0]["answer"]

    def test_registers_cancel_token(self):
        registry = MagicMock()
        cancel_token = CancelToken()
        executor = MultiAgentExecutor(
            agent_class=MagicMock(),
            llm=MagicMock(),
            subtask_registry=registry,
            cancel_token=cancel_token,
        )
        message = _msg()

        with patch(
            "internal.service.executors.multi_agent_executor.AgentTaskExecutor"
        ) as mock_class:
            fake = MagicMock()
            fake.execute.return_value = {
                "agent_id": "t1",
                "task_id": "t1",
                "answer": "完成",
                "errors": [],
                "metadata": {},
            }
            mock_class.return_value = fake
            list(executor.execute(
                query="任务",
                conversation=_conv(),
                message=message,
                execution_mode="multi_agent_parallel",
                routing_decision=_routing_decision(),
            ))

        registry.register_cancel_token.assert_called_once_with(str(message.id), cancel_token)

    def test_emits_subtask_events_and_registers_snapshot(self):
        registry = SubtaskRegistryService()
        executor = MultiAgentExecutor(
            agent_class=MagicMock(),
            llm=MagicMock(),
            subtask_registry=registry,
        )
        message = _msg()

        with patch(
            "internal.service.executors.multi_agent_executor.AgentTaskExecutor"
        ) as mock_class:
            _fake_task_executor(mock_class, {"t1": "数据分析完成", "t2": "报告撰写完成"})
            events = list(executor.execute(
                query="完成分析和报告",
                conversation=_conv(),
                message=message,
                execution_mode="multi_agent_parallel",
                routing_decision=_routing_decision(),
            ))

        assert events[0].startswith("event: subtask_started")
        plan = _parse_payload(events[0])
        assert plan["task_count"] == 2
        assert [item["task_id"] for item in plan["items"]] == ["t1", "t2"]
        assert plan["items"][0]["timeout_seconds"] == 30

        running = [
            _parse_payload(e) for e in events
            if e.startswith("event: subtask_running")
        ]
        assert [item["task_id"] for item in running] == ["t1", "t2"]
        assert all(item["status"] == "running" for item in running)

        completed = [
            _parse_payload(e) for e in events
            if e.startswith("event: subtask_completed")
        ]
        assert [item["task_id"] for item in completed] == ["t1", "t2"]
        assert all(item["status"] == "completed" for item in completed)

        final_messages = [
            _parse_payload(e) for e in events
            if e.startswith("event: agent_message")
        ]
        assert len(final_messages) == 1
        assert "数据分析完成" in final_messages[0]["answer"]
        assert "报告撰写完成" in final_messages[0]["answer"]

        assert events[-1].startswith("event: agent_end")
        snapshot = registry.snapshot(str(message.id))
        assert snapshot is not None
        assert snapshot["task_count"] == 2
        assert all(item["status"] == "completed" for item in snapshot["items"])
        assert all(item["last_activity_at"] > 0 for item in snapshot["items"])

    def test_failed_subtask_is_reported_and_skipped_in_answer(self):
        registry = SubtaskRegistryService()
        executor = MultiAgentExecutor(
            agent_class=MagicMock(),
            llm=MagicMock(),
            subtask_registry=registry,
        )
        message = _msg()

        def _failing_execute(item):
            if item.task_id == "t2":
                return {
                    "agent_id": item.task_id,
                    "task_id": item.task_id,
                    "answer": "",
                    "errors": ["agent_execution_failed"],
                    "confidence": 0,
                }
            return {
                "agent_id": item.task_id,
                "task_id": item.task_id,
                "answer": "任务一完成",
                "confidence": 1.0,
                "errors": [],
                "metadata": {},
            }

        with patch(
            "internal.service.executors.multi_agent_executor.AgentTaskExecutor"
        ) as mock_class:
            fake = MagicMock()
            fake.execute.side_effect = _failing_execute
            mock_class.return_value = fake
            events = list(executor.execute(
                query="任务",
                conversation=_conv(),
                message=message,
                execution_mode="multi_agent_parallel",
                routing_decision=_routing_decision(),
            ))

        completed = [
            _parse_payload(e) for e in events
            if e.startswith("event: subtask_completed")
        ]
        by_id = {item["task_id"]: item for item in completed}
        assert by_id["t2"]["status"] == "failed"
        assert by_id["t2"]["errors"] == ["agent_execution_failed"]

        final_messages = [
            _parse_payload(e) for e in events
            if e.startswith("event: agent_message")
        ]
        assert "任务一完成" in final_messages[0]["answer"]
        assert "任务二" not in final_messages[0]["answer"]

        snapshot = registry.snapshot(str(message.id))
        status_by_id = {item["task_id"]: item["status"] for item in snapshot["items"]}
        assert status_by_id == {"t1": "completed", "t2": "failed"}
