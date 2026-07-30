"""WorkflowToolAdapter / Workflow 运行时单元测试。

旧版基于 LangGraph 的 Workflow 已废弃，统一采用 GraphEngine 执行。
本测试覆盖 WorkflowToolAdapter 的公共 API：
- _build_args_schema: 从 start 节点构建输入参数
- _run / stream: 委托 GraphEngine 执行
- Workflow 向后兼容（继承 WorkflowToolAdapter）
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import BaseModel

from internal.core.workflow.entities.node_entity import NodeType
from internal.core.workflow.workflow import Workflow, WorkflowToolAdapter


def _start_node(node_id):
    return SimpleNamespace(id=node_id, node_type=NodeType.START.value, inputs=[])


def _end_node(node_id):
    return SimpleNamespace(id=node_id, node_type=NodeType.END.value, outputs=[])


def test_workflow_tool_adapter_build_args_schema_should_build_required_and_optional_fields():
    """_build_args_schema 应从 start 节点的 inputs 构建动态 BaseModel。"""
    start_inputs = [
        SimpleNamespace(name="query", type="string", required=True, description="search query"),
        SimpleNamespace(name="top_k", type="int", required=False, description="top k"),
    ]
    workflow_config = SimpleNamespace(
        nodes=[SimpleNamespace(node_type=NodeType.START.value, inputs=start_inputs)],
        name="wf",
        description="desc",
        account_id=uuid4(),
    )

    model_cls = WorkflowToolAdapter._build_args_schema(workflow_config)
    fields = model_cls.model_fields

    assert set(fields.keys()) == {"query", "top_k"}
    assert fields["query"].is_required() is True


def test_workflow_class_is_subclass_of_adapter():
    """Workflow 应继承 WorkflowToolAdapter 以保持向后兼容。"""
    assert issubclass(Workflow, WorkflowToolAdapter)


def test_workflow_tool_adapter_init_should_set_name_and_description(monkeypatch):
    """WorkflowToolAdapter.__init__ 应正确设置 name/description/workflow_config。"""
    class _DummySchema(BaseModel):
        pass

    monkeypatch.setattr(
        "internal.core.workflow.workflow.WorkflowToolAdapter._build_args_schema",
        classmethod(lambda cls, _cfg: _DummySchema),
    )

    config = SimpleNamespace(
        name="wf_demo",
        description="demo",
        nodes=[],
        edges=[],
        account_id=uuid4(),
    )
    adapter = WorkflowToolAdapter(workflow_config=config)

    assert adapter.name == "wf_demo"
    assert adapter.description == "demo"
    assert adapter._workflow_config is config


def test_workflow_tool_adapter_run_should_delegate_to_graph_engine(monkeypatch):
    """_run 应委托 GraphEngine.execute 并返回 end 节点输出。"""
    captured_events = []

    class _FakePool:
        def get_node_output(self, node_id, var_name=None):
            return {"answer": "ok"}

    class _FakeEngine:
        def __init__(self, **kwargs):
            self.variable_pool = _FakePool()

        def execute(self, inputs):
            captured_events.append(inputs)
            yield {"event": "workflow_started", "data": {"inputs": inputs}}
            yield {"event": "workflow_finished", "data": {"status": "succeeded"}}

    monkeypatch.setattr(
        "internal.core.workflow.workflow.GraphEngine",
        lambda **kw: _FakeEngine(),
    )

    config = SimpleNamespace(
        name="wf",
        description="d",
        nodes=[_start_node(uuid4()), _end_node(uuid4())],
        edges=[],
        account_id=uuid4(),
    )
    adapter = WorkflowToolAdapter.__new__(WorkflowToolAdapter)
    adapter._workflow_config = config

    result = WorkflowToolAdapter._run(adapter, query="hi")

    assert result == {"answer": "ok"}
    assert captured_events == [{"query": "hi"}]


def test_workflow_tool_adapter_stream_should_yield_graph_engine_events(monkeypatch):
    """stream 应 yield GraphEngine 的事件。"""
    class _FakeEngine:
        def __init__(self, **kwargs):
            pass

        def execute(self, inputs):
            yield {"event": "workflow_started", "data": {"inputs": inputs}}
            yield {"event": "node_started", "data": {"node_id": "1"}}
            yield {"event": "workflow_finished", "data": {"status": "succeeded"}}

    monkeypatch.setattr(
        "internal.core.workflow.workflow.GraphEngine",
        lambda **kw: _FakeEngine(),
    )

    config = SimpleNamespace(
        name="wf",
        description="d",
        nodes=[_start_node(uuid4()), _end_node(uuid4())],
        edges=[],
        account_id=uuid4(),
    )
    adapter = WorkflowToolAdapter.__new__(WorkflowToolAdapter)
    adapter._workflow_config = config

    events = list(WorkflowToolAdapter.stream(adapter, {"query": "hi"}))

    assert len(events) == 3
    assert events[0]["event"] == "workflow_started"
    assert events[1]["event"] == "node_started"
    assert events[2]["event"] == "workflow_finished"


def test_workflow_tool_adapter_extract_end_outputs_should_return_empty_when_no_end_node():
    """无 end 节点时 _extract_end_outputs 应返回空 dict。"""
    config = SimpleNamespace(
        nodes=[_start_node(uuid4())],
        edges=[],
    )
    adapter = WorkflowToolAdapter.__new__(WorkflowToolAdapter)
    adapter._workflow_config = config

    class _FakePool:
        pass

    result = WorkflowToolAdapter._extract_end_outputs(adapter, _FakePool())
    assert result == {}


def test_workflow_init_should_warn_deprecation(monkeypatch, caplog):
    """Workflow.__init__ 应记录废弃警告。"""
    class _DummySchema(BaseModel):
        pass

    monkeypatch.setattr(
        "internal.core.workflow.workflow.WorkflowToolAdapter._build_args_schema",
        classmethod(lambda cls, _cfg: _DummySchema),
    )

    config = SimpleNamespace(
        name="wf_deprecated",
        description="d",
        nodes=[],
        edges=[],
        account_id=uuid4(),
    )

    import logging
    with caplog.at_level(logging.WARNING, logger="internal.core.workflow.workflow"):
        workflow = Workflow(workflow_config=config)

    assert workflow.name == "wf_deprecated"
    assert any("废弃" in record.message for record in caplog.records)
