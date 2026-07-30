"""ToolNode 扩展 tool_type 测试。

覆盖 P2-3 扩展的 7 种 tool_type 分发逻辑：
- builtin_tool / api_tool: 回归（构造期初始化 _tool，原逻辑不变）
- mcp: 延迟加载 McpToolFactory
- knowledge: 延迟加载 RetrievalService
- skill: 延迟加载 SkillService
- workflow: 嵌套 Workflow + 环检测 + max_depth
- agent_binding: 调用子 App + 环检测 + max_depth
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import VariableEntity
from internal.core.workflow.nodes.start.start_entity import StartNodeData
from internal.core.workflow.nodes.tool.tool_entity import ToolNodeData
from internal.core.workflow.nodes.tool.tool_node import (
    ToolNode,
    MAX_NESTED_DEPTH,
    CALL_STACK_CONFIG_KEY,
)
from internal.exception import FailException, NotFoundException


def _state_with_node_result(node_result):
    return {"inputs": {}, "outputs": {}, "node_results": [node_result]}


def _ref_var(name, ref_node_id, ref_var_name, var_type="string"):
    return VariableEntity(
        name=name,
        type=var_type,
        value={
            "type": "ref",
            "content": {"ref_node_id": ref_node_id, "ref_var_name": ref_var_name},
        },
    )


def _make_node_data(tool_type, *, tool_id="", provider_id="", inputs=None, outputs=None, meta=None, params=None):
    return ToolNodeData(
        id=uuid4(),
        node_type="tool",
        title="tool",
        type=tool_type,
        provider_id=provider_id,
        tool_id=tool_id,
        inputs=inputs or [],
        outputs=outputs or [],
        meta=meta or {},
        params=params or {},
    )


class _InjectorStub:
    """按类名返回预设 service mock 的 injector 桩。"""

    def __init__(self, mappings=None):
        self._mappings = mappings or {}

    def get(self, cls):
        for key, value in self._mappings.items():
            if cls.__name__ == key:
                return value
        return SimpleNamespace()


class TestToolNodeBuiltinApiRegression:
    """回归测试：builtin_tool / api_tool 执行逻辑不变。"""

    def test_builtin_tool_constructs_tool_in_init(self, monkeypatch):
        """builtin_tool 在构造函数中初始化 _tool（向后兼容）。"""
        constructed = {}

        class _BuiltinTool:
            def __init__(self, **kwargs):
                constructed["kwargs"] = kwargs

            def invoke(self, _payload):
                return "builtin-ok"

        class _BuiltinManager:
            def get_tool(self, _provider_id, _tool_id):
                return _BuiltinTool

        class _Injector:
            def get(self, _cls):
                return _BuiltinManager()

        monkeypatch.setattr("app.http.module.injector", _Injector())

        node_data = _make_node_data(
            "builtin_tool",
            provider_id="weather",
            tool_id="get_weather",
            params={"k": 2},
        )
        node = ToolNode(node_data=node_data)

        # 构造期已初始化 _tool，params 传入
        assert constructed["kwargs"] == {"k": 2}
        assert node._tool is not None

        result = node.invoke(_state_with_node_result(
            NodeResult(node_data=StartNodeData(id=uuid4(), node_type="start", title="s", inputs=[]), outputs={})
        ))
        assert result["node_results"][0].outputs["text"] == "builtin-ok"
        assert result["node_results"][0].status == NodeStatus.SUCCEEDED.value

    def test_api_tool_raises_not_found_when_missing(self, monkeypatch):
        """api_tool 工具不存在时抛 NotFoundException（原逻辑）。"""
        class _DbQuery:
            @staticmethod
            def filter(*_args):
                return _DbQuery()

            @staticmethod
            def one_or_none():
                return None

        class _DB:
            session = SimpleNamespace(query=lambda _model: _DbQuery())

        class _Injector:
            def get(self, cls):
                if cls.__name__ == "SQLAlchemy":
                    return _DB()
                return SimpleNamespace()

        monkeypatch.setattr("app.http.module.injector", _Injector())

        node_data = _make_node_data("api_tool", provider_id="p", tool_id="t")
        with pytest.raises(NotFoundException, match="API扩展插件不存在"):
            ToolNode(node_data=node_data)


class TestToolNodeMcp:
    """mcp 工具节点：延迟加载 McpToolFactory。"""

    def test_mcp_node_invokes_mcp_tool(self, monkeypatch):
        """mcp 节点通过 McpToolFactory 加载工具并执行。"""
        invoked = {"binding": None}

        class _McpTool:
            def invoke(self, inputs):
                invoked["inputs"] = inputs
                return "mcp-result"

        class _McpFactoryStub:
            def __init__(self, *args, **kwargs):
                pass

            def get_tools(self, bindings, mcp_tool_snapshots=None):
                invoked["binding"] = bindings[0] if bindings else {}
                return [_McpTool()]

        monkeypatch.setattr(
            "internal.core.tools.mcp_tools.providers.McpToolFactory",
            _McpFactoryStub,
        )

        node_data = _make_node_data(
            "mcp",
            provider_id="github",
            tool_id="create_issue",
            meta={"url": "https://mcp.example.com", "transport": "streamable_http"},
        )
        node = ToolNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})
        assert result["node_results"][0].outputs["text"] == "mcp-result"
        # binding 从 meta + provider_id + tool_id 构建
        assert invoked["binding"]["url"] == "https://mcp.example.com"
        assert invoked["binding"]["provider_key"] == "github"
        assert "create_issue" in invoked["binding"]["tool_names"]

    def test_mcp_node_raises_when_no_tools_loaded(self, monkeypatch):
        """McpToolFactory 返回空工具列表时抛 FailException。"""
        class _McpFactoryStub:
            def __init__(self, *args, **kwargs):
                pass

            def get_tools(self, bindings, mcp_tool_snapshots=None):
                return []

        monkeypatch.setattr(
            "internal.core.tools.mcp_tools.providers.McpToolFactory",
            _McpFactoryStub,
        )

        node_data = _make_node_data("mcp", provider_id="p", tool_id="t")
        node = ToolNode(node_data=node_data)

        with pytest.raises(FailException, match="MCP工具加载失败"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []})


class TestToolNodeSkill:
    """skill 工具节点：延迟加载 SkillService。"""

    def test_skill_node_invokes_skill_tool(self, monkeypatch):
        """skill 节点通过 SkillService 加载技能包工具并执行。"""
        class _SkillTool:
            def invoke(self, inputs):
                return "skill-result"

        skill_service = SimpleNamespace(
            get_langchain_tools_by_skill_bindings=lambda bindings: [_SkillTool()]
        )
        monkeypatch.setattr("app.http.module.injector", _InjectorStub({"SkillService": skill_service}))

        skill_id = str(uuid4())
        node_data = _make_node_data("skill", tool_id=skill_id)
        node = ToolNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})
        assert result["node_results"][0].outputs["text"] == "skill-result"

    def test_skill_node_raises_when_no_tools(self, monkeypatch):
        """SkillService 返回空工具列表时抛 FailException。"""
        skill_service = SimpleNamespace(
            get_langchain_tools_by_skill_bindings=lambda bindings: []
        )
        monkeypatch.setattr("app.http.module.injector", _InjectorStub({"SkillService": skill_service}))

        node_data = _make_node_data("skill", tool_id=str(uuid4()))
        node = ToolNode(node_data=node_data)

        with pytest.raises(FailException, match="技能工具加载失败"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []})


class TestToolNodeWorkflow:
    """workflow 嵌套工具节点：延迟加载 AppConfigService + 环检测。"""

    def test_workflow_node_invokes_nested_workflow(self, monkeypatch):
        """workflow 节点通过 AppConfigService 加载嵌套 Workflow 并执行。"""
        captured = {"config": None}

        class _WorkflowTool:
            def invoke(self, inputs, config=None):
                captured["config"] = config
                return "nested-workflow-result"

        app_config_service = SimpleNamespace(
            get_langchain_tools_by_workflow_ids=lambda ids: [_WorkflowTool()]
        )
        monkeypatch.setattr("app.http.module.injector", _InjectorStub({"AppConfigService": app_config_service}))

        workflow_id = str(uuid4())
        node_data = _make_node_data("workflow", tool_id=workflow_id)
        node = ToolNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})
        assert result["node_results"][0].outputs["text"] == "nested-workflow-result"
        # 嵌套调用时 config 应包含压入 workflow_id 的 call_stack
        nested_config = captured["config"]
        assert nested_config is not None
        assert workflow_id in nested_config["configurable"][CALL_STACK_CONFIG_KEY]

    def test_workflow_node_cycle_detection_blocks_recursion(self, monkeypatch):
        """workflow 自环：workflow_id 已在 call_stack 中时拒绝执行。"""
        app_config_service = SimpleNamespace(
            get_langchain_tools_by_workflow_ids=lambda ids: [SimpleNamespace(invoke=lambda *_a, **_kw: "should-not-reach")]
        )
        monkeypatch.setattr("app.http.module.injector", _InjectorStub({"AppConfigService": app_config_service}))

        workflow_id = str(uuid4())
        node_data = _make_node_data("workflow", tool_id=workflow_id)
        node = ToolNode(node_data=node_data)

        # config 中 call_stack 已含 workflow_id，触发环检测
        config = {"configurable": {CALL_STACK_CONFIG_KEY: [workflow_id]}}
        with pytest.raises(FailException, match="工作流嵌套循环"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []}, config=config)

    def test_workflow_node_max_depth_blocks_recursion(self, monkeypatch):
        """call_stack 长度 >= MAX_NESTED_DEPTH 时拒绝执行。"""
        app_config_service = SimpleNamespace(
            get_langchain_tools_by_workflow_ids=lambda ids: [SimpleNamespace(invoke=lambda *_a, **_kw: "should-not-reach")]
        )
        monkeypatch.setattr("app.http.module.injector", _InjectorStub({"AppConfigService": app_config_service}))

        workflow_id = str(uuid4())
        node_data = _make_node_data("workflow", tool_id=workflow_id)
        node = ToolNode(node_data=node_data)

        # 构造达到深度上限的 call_stack
        full_stack = [str(uuid4()) for _ in range(MAX_NESTED_DEPTH)]
        config = {"configurable": {CALL_STACK_CONFIG_KEY: full_stack}}
        with pytest.raises(FailException, match="工作流嵌套深度超过上限"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []}, config=config)

    def test_workflow_node_raises_when_nested_workflow_missing(self, monkeypatch):
        """嵌套 Workflow 加载失败（未发布/不存在）时抛 FailException。"""
        app_config_service = SimpleNamespace(
            get_langchain_tools_by_workflow_ids=lambda ids: []
        )
        monkeypatch.setattr("app.http.module.injector", _InjectorStub({"AppConfigService": app_config_service}))

        node_data = _make_node_data("workflow", tool_id=str(uuid4()))
        node = ToolNode(node_data=node_data)

        with pytest.raises(FailException, match="嵌套工作流加载失败"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []})


class TestToolNodeAgentBinding:
    """agent_binding 工具节点：延迟加载 AppService + 环检测。"""

    def test_agent_binding_node_invokes_sub_app(self, monkeypatch):
        """agent_binding 节点通过 AppService 调用子 App。"""
        captured = {"config": None, "bindings": None}

        class _AgentTool:
            def invoke(self, inputs, config=None):
                captured["config"] = config
                return "agent-binding-result"

        app_service = SimpleNamespace(
            get_langchain_tools_by_agent_bindings=lambda bindings, **kwargs: (
                captured.__setitem__("bindings", bindings),
                [_AgentTool()],
            )[1]
        )
        monkeypatch.setattr("app.http.module.injector", _InjectorStub({"AppRuntimeService": app_service}))

        target_app_id = str(uuid4())
        node_data = _make_node_data("agent_binding", tool_id=target_app_id)
        node = ToolNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})
        assert result["node_results"][0].outputs["text"] == "agent-binding-result"
        # 传给 AppService 的 binding 含目标 app_id
        assert captured["bindings"][0]["app_id"] == target_app_id
        # 嵌套 config 含压入的 app_id
        assert target_app_id in captured["config"]["configurable"][CALL_STACK_CONFIG_KEY]

    def test_agent_binding_node_cycle_detection_blocks_recursion(self, monkeypatch):
        """agent_binding 自环：app_id 已在 call_stack 中时拒绝执行。"""
        app_service = SimpleNamespace(
            get_langchain_tools_by_agent_bindings=lambda bindings, **kw: [SimpleNamespace(invoke=lambda *_a, **_kw: "no")]
        )
        monkeypatch.setattr("app.http.module.injector", _InjectorStub({"AppService": app_service}))

        target_app_id = str(uuid4())
        node_data = _make_node_data("agent_binding", tool_id=target_app_id)
        node = ToolNode(node_data=node_data)

        config = {"configurable": {CALL_STACK_CONFIG_KEY: [target_app_id]}}
        with pytest.raises(FailException, match="Agent 调用循环"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []}, config=config)

    def test_agent_binding_node_max_depth_blocks_recursion(self, monkeypatch):
        """agent_binding 嵌套深度 >= MAX_NESTED_DEPTH 时拒绝执行。"""
        app_service = SimpleNamespace(
            get_langchain_tools_by_agent_bindings=lambda bindings, **kw: [SimpleNamespace(invoke=lambda *_a, **_kw: "no")]
        )
        monkeypatch.setattr("app.http.module.injector", _InjectorStub({"AppService": app_service}))

        target_app_id = str(uuid4())
        node_data = _make_node_data("agent_binding", tool_id=target_app_id)
        node = ToolNode(node_data=node_data)

        full_stack = [str(uuid4()) for _ in range(MAX_NESTED_DEPTH)]
        config = {"configurable": {CALL_STACK_CONFIG_KEY: full_stack}}
        with pytest.raises(FailException, match="Agent 嵌套深度超过上限"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []}, config=config)


class TestToolNodeKnowledge:
    """knowledge 工具节点：延迟加载 RetrievalService。"""

    def test_knowledge_node_invokes_retrieval(self, monkeypatch):
        """knowledge 节点通过 RetrievalService 构造检索工具并执行。"""
        captured = {"query": None, "kb_ids": None}

        class _RetrievalTool:
            def invoke(self, payload):
                captured["query"] = payload.get("query")
                return "knowledge-result"

        retrieval_service = SimpleNamespace(
            create_knowledge_retrieval_tool=lambda flask_app, knowledge_base_ids, account_id: (
                captured.__setitem__("kb_ids", knowledge_base_ids),
                _RetrievalTool(),
            )[1]
        )
        monkeypatch.setattr("app.http.module.injector", _InjectorStub({"RetrievalService": retrieval_service}))

        kb_id = str(uuid4())
        source_data = StartNodeData(id=uuid4(), node_type="start", title="start", inputs=[])
        previous_result = NodeResult(node_data=source_data, outputs={"query": "什么是RAG"})
        node_data = _make_node_data(
            "knowledge",
            tool_id=kb_id,
            inputs=[_ref_var(name="query", ref_node_id=source_data.id, ref_var_name="query")],
        )
        node = ToolNode(node_data=node_data)

        result = node.invoke(_state_with_node_result(previous_result))
        assert result["node_results"][0].outputs["text"] == "knowledge-result"
        assert captured["query"] == "什么是RAG"
        assert str(captured["kb_ids"][0]) == kb_id


class TestToolNodeCallStackHelpers:
    """环检测辅助函数单测。"""

    def test_get_call_stack_returns_empty_when_no_config(self):
        assert ToolNode._get_call_stack(None) == []
        assert ToolNode._get_call_stack({}) == []
        assert ToolNode._get_call_stack({"configurable": {}}) == []

    def test_get_call_stack_extracts_stack(self):
        config = {"configurable": {CALL_STACK_CONFIG_KEY: ["a", "b", "c"]}}
        assert ToolNode._get_call_stack(config) == ["a", "b", "c"]

    def test_push_call_stack_returns_new_config_without_mutating_original(self):
        original = {"configurable": {CALL_STACK_CONFIG_KEY: ["a"]}}
        new_config = ToolNode._push_call_stack(original, "b")
        # 原 config 不被修改
        assert original["configurable"][CALL_STACK_CONFIG_KEY] == ["a"]
        # 新 config 含压入的 id
        assert new_config["configurable"][CALL_STACK_CONFIG_KEY] == ["a", "b"]

    def test_push_call_stack_handles_empty_config(self):
        new_config = ToolNode._push_call_stack(None, "first")
        assert new_config["configurable"][CALL_STACK_CONFIG_KEY] == ["first"]

    def test_extract_query_from_inputs_prefers_query_key(self):
        assert ToolNode._extract_query_from_inputs({"query": "hello", "other": "x"}) == "hello"

    def test_extract_query_from_inputs_falls_back_to_first_string(self):
        assert ToolNode._extract_query_from_inputs({"name": "world"}) == "world"

    def test_extract_query_from_inputs_returns_empty_when_no_string(self):
        assert ToolNode._extract_query_from_inputs({"count": 5}) == ""
        assert ToolNode._extract_query_from_inputs({}) == ""


class TestToolNodeUnknownTypeFallback:
    """未知 tool_type 兜底（Literal 已约束，但 _dispatch_invoke 有兜底分支）。"""

    def test_empty_tool_type_falls_back_to_tool_invoke(self, monkeypatch):
        """tool_type 为空时走 _tool.invoke（原兼容逻辑），_tool 为 None 时抛 FailException。"""
        node_data = _make_node_data("")
        node = ToolNode(node_data=node_data)
        # _tool 为 None，invoke 会抛 AttributeError，被包装为 FailException
        with pytest.raises(FailException, match="扩展插件执行失败"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []})
