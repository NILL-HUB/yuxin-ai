from unittest.mock import MagicMock, patch
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


def test_execute_flags_blocked_when_marker_present():
    """子代理按约定输出「无法完成：原因」时，结果须标记 blocked 并携带原因。"""
    llm = MagicMock()
    llm.convert_to_human_message.return_value = MagicMock(name="human_message")

    blocked_thought = _make_thought(
        answer="我尝试检索了知识库，但无法完成：缺少该平台的访问凭证。",
        event="agent_message",
    )
    agent = MagicMock()
    agent.stream.return_value = iter([blocked_thought])
    agent_class = MagicMock(return_value=agent)

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=None,
        tools=[],
        llm=llm,
    )

    item = TaskPlanItem(task_id="task-blocked", title="标题", description="描述")
    result = executor.execute(item)

    assert result["blocked"] is True
    assert result["blocking_reason"] == "缺少该平台的访问凭证。"
    assert result["metadata"]["agent_blocked"] is True


def test_execute_does_not_flag_blocked_without_marker():
    llm = MagicMock()
    llm.convert_to_human_message.return_value = MagicMock(name="human_message")

    ok_thought = _make_thought(answer="任务已完成，结果为 42。", event="agent_message")
    agent = MagicMock()
    agent.stream.return_value = iter([ok_thought])
    agent_class = MagicMock(return_value=agent)

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=None,
        tools=[],
        llm=llm,
    )

    item = TaskPlanItem(task_id="task-ok-2", title="标题", description="描述")
    result = executor.execute(item)

    assert result["blocked"] is False
    assert result["blocking_reason"] == ""


def test_detect_blocked_supports_both_colon_styles():
    assert AgentTaskExecutor._detect_blocked("无法完成：缺少工具") == (True, "缺少工具")
    assert AgentTaskExecutor._detect_blocked("无法完成: 缺少工具") == (True, "缺少工具")
    assert AgentTaskExecutor._detect_blocked("一切正常") == (False, "")
    assert AgentTaskExecutor._detect_blocked("") == (False, "")


_LONG_TASK_DESCRIPTION = "请统计上月各渠道转化率并给出可执行的优化建议"


def _executor_with_answer(answer: str) -> AgentTaskExecutor:
    llm = MagicMock()
    llm.convert_to_human_message.return_value = MagicMock(name="human_message")
    thought = _make_thought(answer=answer, event="agent_message")
    agent = MagicMock()
    agent.stream.return_value = iter([thought])
    agent_class = MagicMock(return_value=agent)
    return AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=None,
        tools=[],
        llm=llm,
    )


def test_execute_uses_llm_evaluation_when_result_suspicious():
    """约定标记未命中但结果可疑（回答极短、任务描述具体）时，补一次 LLM 自评。"""
    executor = _executor_with_answer("嗯")
    item = TaskPlanItem(
        task_id="t-sus", title="标题", description=_LONG_TASK_DESCRIPTION
    )

    evaluator_llm = MagicMock()
    evaluator_llm.invoke.return_value = MagicMock(
        content="NOT_COMPLETED\n缺少各渠道转化率数据，未给出优化建议"
    )

    with patch(
        "internal.service.language_model_service.LanguageModelService.get_feature_model",
        return_value=evaluator_llm,
    ), patch(
        "internal.service.system_prompt_library_service.SystemPromptLibraryService.get_prompt_or_default",
        return_value="评审提示词",
    ):
        result = executor.execute(item)

    assert result["blocked"] is True
    assert "缺少各渠道转化率数据" in result["blocking_reason"]
    evaluator_llm.invoke.assert_called_once()


def test_execute_keeps_unblocked_when_evaluator_reports_completed():
    executor = _executor_with_answer("嗯")
    item = TaskPlanItem(
        task_id="t-sus-ok", title="标题", description=_LONG_TASK_DESCRIPTION
    )

    evaluator_llm = MagicMock()
    evaluator_llm.invoke.return_value = MagicMock(content="COMPLETED\n任务已达成")

    with patch(
        "internal.service.language_model_service.LanguageModelService.get_feature_model",
        return_value=evaluator_llm,
    ), patch(
        "internal.service.system_prompt_library_service.SystemPromptLibraryService.get_prompt_or_default",
        return_value="评审提示词",
    ):
        result = executor.execute(item)

    assert result["blocked"] is False
    assert result["blocking_reason"] == ""


def test_execute_keeps_unblocked_when_evaluator_unavailable():
    """自评不可用（无模型）时保持原判定，不误报阻塞。"""
    executor = _executor_with_answer("嗯")
    item = TaskPlanItem(
        task_id="t-sus-na", title="标题", description=_LONG_TASK_DESCRIPTION
    )

    with patch(
        "internal.service.language_model_service.LanguageModelService.get_feature_model",
        return_value=None,
    ):
        result = executor.execute(item)

    assert result["blocked"] is False
    assert result["blocking_reason"] == ""


def test_execute_skips_llm_evaluation_for_trivial_task():
    """任务描述很短（trivial）时不触发自评，避免无谓的 LLM 调用。"""
    executor = _executor_with_answer("嗯")
    item = TaskPlanItem(task_id="t-trivial", title="标题", description="输出 hello")

    with patch(
        "internal.service.language_model_service.LanguageModelService.get_feature_model",
        return_value=None,
    ) as mock_get_model:
        result = executor.execute(item)

    assert result["blocked"] is False
    mock_get_model.assert_not_called()


def test_request_more_tools_tool_delegates_to_provider():
    from internal.core.agent.meta_tools.request_more_tools import (
        REQUEST_MORE_TOOLS_NAME,
        build_request_more_tools_tool,
    )

    calls = []

    def _provider(query, reason):
        calls.append((query, reason))
        return "已追加 2 个工具：a、b"

    tool = build_request_more_tools_tool(_provider)

    assert tool.name == REQUEST_MORE_TOOLS_NAME
    assert tool.invoke({"query": "企业信息", "reason": "缺数据"}) == "已追加 2 个工具：a、b"
    assert calls == [("企业信息", "缺数据")]


def test_request_more_tools_tool_handles_provider_failure():
    from internal.core.agent.meta_tools.request_more_tools import (
        build_request_more_tools_tool,
    )

    def _boom(query, reason):
        raise RuntimeError("boom")

    tool = build_request_more_tools_tool(_boom)

    assert "申请追加工具失败" in tool.invoke({"query": "x"})


def test_attach_meta_tools_appends_requested_tools_to_agent():
    """执行中申请到的工具写回 agent.agent_config.tools（后续轮次即生效）。"""
    from langchain_core.tools import StructuredTool

    from internal.core.agent.entities.agent_entity import AgentConfig
    from internal.core.agent.meta_tools.request_more_tools import REQUEST_MORE_TOOLS_NAME

    new_tool = StructuredTool.from_function(
        func=lambda x="": "ok", name="web_search", description="搜索"
    )
    holder: dict = {}

    def _provider(query, reason, current_tools):
        holder["current_names"] = [getattr(t, "name", "") for t in current_tools]
        return "已追加 1 个工具：web_search。", [new_tool]

    class _AgentClass:
        def __init__(self, llm=None, agent_config=None):
            self.agent_config = agent_config
            holder["agent"] = self

        def stream(self, _input):
            meta = next(
                t for t in self.agent_config.tools if t.name == REQUEST_MORE_TOOLS_NAME
            )
            holder["meta_result"] = meta.invoke({"query": "搜索", "reason": ""})
            return iter([])

    executor = AgentTaskExecutor(
        agent_class=_AgentClass,
        agent_config=AgentConfig(user_id=uuid4()),
        tools=[],
        llm=MagicMock(),
        extra_tool_provider=_provider,
    )
    item = TaskPlanItem(task_id="t-meta", title="标题", description="描述")

    executor.execute(item)

    names = [t.name for t in holder["agent"].agent_config.tools]
    assert REQUEST_MORE_TOOLS_NAME in names
    assert "web_search" in names
    assert "已追加 1 个工具" in holder["meta_result"]
    # provider 拿到的 current_tools 已包含元工具自身
    assert REQUEST_MORE_TOOLS_NAME in holder["current_names"]


def test_attach_meta_tools_skipped_without_provider():
    """未注入 provider 时不挂载元工具，保持原工具列表。"""
    from internal.core.agent.entities.agent_entity import AgentConfig

    holder: dict = {}

    class _AgentClass:
        def __init__(self, llm=None, agent_config=None):
            self.agent_config = agent_config

        def stream(self, _input):
            holder["tools"] = list(self.agent_config.tools)
            return iter([])

    executor = AgentTaskExecutor(
        agent_class=_AgentClass,
        agent_config=AgentConfig(user_id=uuid4()),
        tools=[],
        llm=MagicMock(),
    )
    item = TaskPlanItem(task_id="t-no-meta", title="标题", description="描述")

    executor.execute(item)

    assert holder["tools"] == []
