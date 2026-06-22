from unittest.mock import MagicMock

from internal.entity.execution_orchestration_entity import TaskPlan
from internal.service.executors.task_decomposer import (
    TaskDecomposer,
    TaskPlanItemModel,
    TaskPlanModel,
)


def _build_decomposer(plan_model=None, invoke_side_effect=None):
    language_model_service = MagicMock()
    cheap_llm = MagicMock()
    structured = MagicMock()
    if invoke_side_effect is not None:
        structured.invoke.side_effect = invoke_side_effect
    else:
        structured.invoke.return_value = plan_model
    cheap_llm.with_structured_output.return_value = structured
    language_model_service.get_cheap_chat_model.return_value = cheap_llm
    return TaskDecomposer(language_model_service=language_model_service), structured


class TestTaskPlanItemModel:
    def test_defaults_are_empty(self):
        item = TaskPlanItemModel(name="t", description="d")
        assert item.depends_on == []
        assert item.agent_id is None
        assert item.tools == []

    def test_accepts_full_payload(self):
        item = TaskPlanItemModel(
            name="research",
            description="调研",
            depends_on=["prep"],
            agent_id="agent-1",
            tools=["search", "browser"],
        )
        assert item.depends_on == ["prep"]
        assert item.agent_id == "agent-1"
        assert item.tools == ["search", "browser"]


class TestTaskPlanModel:
    def test_defaults(self):
        plan = TaskPlanModel()
        assert plan.items == []
        assert plan.aggregation_strategy == "concat"
        assert plan.needs_decomposition is False

    def test_full_payload(self):
        plan = TaskPlanModel(
            items=[
                TaskPlanItemModel(name="a", description="d1"),
                TaskPlanItemModel(name="b", description="d2", depends_on=["a"]),
            ],
            aggregation_strategy="summarize",
            needs_decomposition=True,
        )
        assert len(plan.items) == 2
        assert plan.items[1].depends_on == ["a"]
        assert plan.aggregation_strategy == "summarize"
        assert plan.needs_decomposition is True


class TestTaskDecomposer:
    def test_decompose_simple_task_returns_single_item(self):
        plan_model = TaskPlanModel(
            items=[TaskPlanItemModel(name="回答", description="直接回答用户问题")],
            needs_decomposition=False,
        )
        decomposer, _ = _build_decomposer(plan_model=plan_model)
        plan = decomposer.decompose("你好", [], [])

        assert isinstance(plan, TaskPlan)
        assert len(plan.items) == 1
        assert plan.items[0].task_id == "subtask_1"
        assert plan.items[0].title == "回答"
        assert plan.items[0].execution_order == 0
        assert plan.aggregation_strategy == "concat"
        assert plan.execution_mode == "multi_agent_parallel"

    def test_decompose_complex_task_returns_multiple_items_with_deps(self):
        plan_model = TaskPlanModel(
            items=[
                TaskPlanItemModel(
                    name="市场调研",
                    description="调研市场",
                    agent_id="agent-1",
                    tools=["search"],
                ),
                TaskPlanItemModel(
                    name="竞品分析",
                    description="分析竞品",
                    agent_id="agent-2",
                    tools=["search"],
                ),
                TaskPlanItemModel(
                    name="综合报告",
                    description="汇总报告",
                    depends_on=["市场调研", "竞品分析"],
                    agent_id="agent-3",
                    tools=[],
                ),
            ],
            aggregation_strategy="best_of",
            needs_decomposition=True,
        )
        decomposer, _ = _build_decomposer(plan_model=plan_model)
        plan = decomposer.decompose("帮我分析市场、竞品并出报告", [], [])

        assert len(plan.items) == 3
        assert [item.task_id for item in plan.items] == [
            "subtask_1",
            "subtask_2",
            "subtask_3",
        ]
        assert [item.execution_order for item in plan.items] == [0, 1, 2]
        assert plan.items[0].agent_id == "agent-1"
        assert plan.items[0].tools == ["search"]
        assert plan.items[2].depends_on == ["subtask_1", "subtask_2"]
        assert plan.aggregation_strategy == "best_of"

    def test_decompose_llm_failure_falls_back_to_single_task(self):
        decomposer, _ = _build_decomposer(invoke_side_effect=RuntimeError("llm down"))
        plan = decomposer.decompose("复杂任务", [], [])

        assert len(plan.items) == 1
        assert plan.items[0].task_id == "subtask_1"
        assert plan.items[0].description == "复杂任务"
        assert plan.aggregation_strategy == "concat"

    def test_decompose_empty_items_falls_back(self):
        plan_model = TaskPlanModel(items=[], needs_decomposition=False)
        decomposer, _ = _build_decomposer(plan_model=plan_model)
        plan = decomposer.decompose("空", [], [])
        assert len(plan.items) == 1
        assert plan.items[0].task_id == "subtask_1"

    def test_decompose_invalid_strategy_normalizes_to_concat(self):
        plan_model = TaskPlanModel(
            items=[TaskPlanItemModel(name="t", description="d")],
            aggregation_strategy="weird_strategy",
        )
        decomposer, _ = _build_decomposer(plan_model=plan_model)
        plan = decomposer.decompose("q", [], [])
        assert plan.aggregation_strategy == "concat"

    def test_decompose_prompt_includes_agents_and_tools(self):
        plan_model = TaskPlanModel(
            items=[TaskPlanItemModel(name="t", description="d")]
        )
        decomposer, structured = _build_decomposer(plan_model=plan_model)
        decomposer.decompose(
            "帮我调研",
            [{"agent_id": "agent-1", "name": "调研Agent", "description": "做市场调研"}],
            [{"name": "search", "description": "联网搜索"}],
        )

        prompt = structured.invoke.call_args.args[0]
        assert "调研Agent" in prompt
        assert "agent-1" in prompt
        assert "search" in prompt
        assert "联网搜索" in prompt

    def test_decompose_carries_aggregation_strategy_through(self):
        for strategy in ("concat", "summarize", "best_of"):
            plan_model = TaskPlanModel(
                items=[TaskPlanItemModel(name="t", description="d")],
                aggregation_strategy=strategy,
            )
            decomposer, _ = _build_decomposer(plan_model=plan_model)
            plan = decomposer.decompose("q", [], [])
            assert plan.aggregation_strategy == strategy
