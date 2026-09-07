from unittest.mock import MagicMock
from uuid import uuid4

from langchain_core.tools import Tool

from internal.core.agent.entities.agent_entity import AgentConfig
from internal.entity.execution_orchestration_entity import TaskPlanItem
from internal.service.agent_task_executor import AgentTaskExecutor


def test_execute_success_returns_expected_dict():
    human_message = MagicMock(name="human_message")
    llm = MagicMock()
    llm.convert_to_human_message.return_value = human_message

    # 使用 spec=AgentThought 让 MagicMock 在访问未定义字段时返回更合理的行为，
    # 同时显式设置数字字段为 0，避免 MagicMock 在 max() 聚合时触发 TypeError
    thought1 = MagicMock()
    thought1.answer = "中间答案"
    thought1.event = "agent_message"
    thought1.total_token_count = 0
    thought1.total_price = 0.0
    thought1.latency = 0.0
    thought2 = MagicMock()
    thought2.answer = "最终答案"
    thought2.event = "agent_message"
    thought2.total_token_count = 0
    thought2.total_price = 0.0
    thought2.latency = 0.0
    thought3 = MagicMock()
    thought3.answer = ""
    thought3.event = "agent_end"
    thought3.total_token_count = 0
    thought3.total_price = 0.0
    thought3.latency = 0.0

    agent = MagicMock()
    agent.stream.return_value = iter([thought1, thought2, thought3])

    agent_class = MagicMock(return_value=agent)

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config={"k": "v"},
        tools=["tool1"],
        llm=llm,
        history=[],
        query="备用查询",
    )

    item = TaskPlanItem(task_id="task-1", title="标题", description="任务描述")
    result = executor.execute(item)

    agent_class.assert_called_once_with(llm=llm, agent_config={"k": "v"})
    llm.convert_to_human_message.assert_called_once_with("任务描述", [])

    stream_input = agent.stream.call_args.args[0]
    assert stream_input["messages"] == [human_message]
    assert stream_input["history"] == []
    assert stream_input["long_term_memory"] == ""
    assert stream_input["user_memory"] == ""

    # 验证关键字段：answer 累加所有 AGENT_MESSAGE 事件（流式分片拼接），agent_end 不影响
    assert result["agent_id"] == "task-1"
    assert result["task_id"] == "task-1"
    assert result["answer"] == "中间答案最终答案"
    assert result["confidence"] == 1.0
    assert result["sources"] == []
    assert result["tool_calls"] == []
    assert result["warnings"] == []
    assert result["errors"] == []
    # cost 字段在 token_count=0 时仍包含默认结构
    assert result["cost"]["total_tokens"] == 0
    assert result["cost"]["total_price"] == 0.0
    # metadata 包含 title / agent_thoughts / token_usage / latency
    assert result["metadata"]["title"] == "标题"
    assert "agent_thoughts" in result["metadata"]
    assert "token_usage" in result["metadata"]
    assert "latency" in result["metadata"]


def test_execute_exception_returns_error_dict_without_raising():
    agent_class = MagicMock(side_effect=RuntimeError("boom"))
    llm = MagicMock()

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=None,
        tools=[],
        llm=llm,
    )

    item = TaskPlanItem(task_id="task-2", title="标题2", description="描述2")
    result = executor.execute(item)

    assert result == {
        "agent_id": "",
        "task_id": "task-2",
        "answer": "",
        "errors": ["agent_execution_failed"],
        "warnings": [],
        "confidence": 0,
    }


def test_execute_filters_tools_per_item_when_agent_config_provided():
    tool_search = Tool(name="search", description="search tool", func=lambda x: x)
    tool_browser = Tool(name="browser", description="browser tool", func=lambda x: x)

    agent_config = AgentConfig(user_id=uuid4(), tools=[tool_search, tool_browser])

    agent = MagicMock()
    agent.stream.return_value = iter([])
    agent_class = MagicMock(return_value=agent)

    llm = MagicMock()
    llm.convert_to_human_message.return_value = MagicMock(name="human_message")

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=agent_config,
        tools=[tool_search, tool_browser],
        llm=llm,
    )

    item = TaskPlanItem(task_id="task-3", title="子任务", description="只搜索", tools=["search"])
    executor.execute(item)

    called_config = agent_class.call_args.kwargs["agent_config"]
    assert [getattr(t, "name", None) for t in called_config.tools] == ["search"]


def test_execute_keeps_full_tools_when_item_has_no_tools():
    tool_search = Tool(name="search", description="search tool", func=lambda x: x)
    tool_browser = Tool(name="browser", description="browser tool", func=lambda x: x)

    agent_config = AgentConfig(user_id=uuid4(), tools=[tool_search, tool_browser])

    agent = MagicMock()
    agent.stream.return_value = iter([])
    agent_class = MagicMock(return_value=agent)

    llm = MagicMock()
    llm.convert_to_human_message.return_value = MagicMock(name="human_message")

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=agent_config,
        tools=[tool_search, tool_browser],
        llm=llm,
    )

    item = TaskPlanItem(task_id="task-4", title="子任务", description="无工具限制")
    executor.execute(item)

    called_config = agent_class.call_args.kwargs["agent_config"]
    assert called_config is agent_config


def test_execute_injects_upstream_results_into_query():
    agent = MagicMock()
    agent.stream.return_value = iter([])
    agent_class = MagicMock(return_value=agent)
    llm = MagicMock()

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=None,
        tools=[],
        llm=llm,
        query="备用查询",
    )
    item = TaskPlanItem(task_id="task-5", title="下游", description="基于上游写报告")
    executor.execute(
        item,
        context={
            "upstream_results": {
                "task-4": {
                    "answer": "上游分析结果",
                }
            }
        },
    )

    query = llm.convert_to_human_message.call_args.args[0]
    assert "上游分析结果" in query
    assert "基于上游写报告" in query


def test_token_usage_uses_agent_thought_tokens():
    llm = MagicMock()
    llm.convert_to_human_message.return_value = MagicMock(name="human_message")

    thought = MagicMock()
    thought.answer = "最终答案"
    thought.event = "agent_message"
    thought.total_token_count = 120
    thought.total_price = 0.001
    thought.latency = 1.0

    agent = MagicMock()
    agent.stream.return_value = iter([thought])
    agent_class = MagicMock(return_value=agent)

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=None,
        tools=[],
        llm=llm,
    )

    item = TaskPlanItem(task_id="task-6", title="标题", description="描述")
    result = executor.execute(item)

    assert result["metadata"]["token_usage"]["total_tokens"] == 120
    assert result["metadata"]["token_usage"]["prompt_tokens"] == 120
    assert result["metadata"]["token_usage"]["completion_tokens"] == 0


def _make_thought(answer: str = "", event: str = "agent_message", tool_name: str = "", token_count: int = 0, observation: str = ""):
    thought = MagicMock()
    thought.answer = answer
    thought.event = event
    thought.total_token_count = token_count
    thought.total_price = 0.0
    thought.latency = 0.0
    thought.thought = ""
    thought.observation = observation
    thought.tool = tool_name
    thought.tool_input = {}
    thought.id = None
    return thought


def test_execute_replays_once_when_llm_failure_no_side_effect():
    """LLM 中断（无 answer、无工具调用）时继承上下文续跑一次。"""
    llm = MagicMock()
    llm.convert_to_human_message.return_value = MagicMock(name="human_message")

    # 第一次执行：LLM 中断（ERROR 终态事件后流结束，无 answer）
    error_thought = _make_thought(event="error", answer="")
    # 第二次执行：成功产出答案
    ok_thought = _make_thought(answer="恢复后的答案", event="agent_message")

    agent = MagicMock()
    agent.stream.side_effect = [iter([error_thought]), iter([ok_thought])]
    agent_class = MagicMock(return_value=agent)

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=None,
        tools=[],
        llm=llm,
        history=[MagicMock()],
    )

    item = TaskPlanItem(task_id="task-replay", title="标题", description="描述")
    result = executor.execute(item)

    assert agent_class.call_count == 2
    assert result["answer"] == "恢复后的答案"
    # 两次执行的输入上下文一致（继承全部上下文续跑）
    first_input = agent.stream.call_args_list[0].args[0]
    second_input = agent.stream.call_args_list[1].args[0]
    assert first_input["history"] == second_input["history"]


def test_execute_does_not_replay_when_tool_called():
    """已调用过工具（有副作用）时不续跑。"""
    llm = MagicMock()
    llm.convert_to_human_message.return_value = MagicMock(name="human_message")

    # 已调用工具 search 但最终失败（无 answer）
    tool_thought = _make_thought(event="agent_action", tool_name="search", observation="tool result")
    error_thought = _make_thought(event="error", answer="")
    agent = MagicMock()
    agent.stream.return_value = iter([tool_thought, error_thought])
    agent_class = MagicMock(return_value=agent)

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=None,
        tools=[],
        llm=llm,
    )

    item = TaskPlanItem(task_id="task-tool", title="标题", description="描述")
    result = executor.execute(item)

    # 只执行一次（不续跑，避免工具副作用重复）
    assert agent_class.call_count == 1
    # 工具调用已被记录（证明存在副作用信号，故不续跑）
    assert result["tool_calls"] and result["tool_calls"][0]["name"] == "search"


def test_execute_does_not_replay_on_success():
    """正常成功（有 answer）不续跑。"""
    llm = MagicMock()
    llm.convert_to_human_message.return_value = MagicMock(name="human_message")

    ok_thought = _make_thought(answer="正常答案", event="agent_message")
    agent = MagicMock()
    agent.stream.return_value = iter([ok_thought])
    agent_class = MagicMock(return_value=agent)

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=None,
        tools=[],
        llm=llm,
    )

    item = TaskPlanItem(task_id="task-ok", title="标题", description="描述")
    result = executor.execute(item)

    assert agent_class.call_count == 1
    assert result["answer"] == "正常答案"
