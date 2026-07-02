from types import SimpleNamespace
from uuid import uuid4

from internal.entity.runtime_tool_entity import CompositeComponentRef
from internal.service.composite_tool_resolver import CompositeToolResolver


class _QueryStub:
    """支持 filter().one_or_none() / filter().all() 链式调用的查询桩。"""

    def __init__(self, *, all_result=None, one_result=None):
        self._all_result = [] if all_result is None else all_result
        self._one_result = one_result

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def one_or_none(self):
        return self._one_result

    def all(self):
        return self._all_result


class _SessionStub:
    """按调用顺序依次返回预设查询结果的会话桩。"""

    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


def _make_app(app_id, *, is_public=False, app_config=None):
    return SimpleNamespace(id=app_id, is_public=is_public, app_config=app_config)


def _make_workflow(workflow_id, *, graph=None):
    return SimpleNamespace(id=workflow_id, graph=graph or {})


def _make_config(**overrides):
    defaults = {
        "tools": [],
        "mcp_bindings": [],
        "skills": [],
        "workflows": [],
        "agent_bindings": [],
        "app_dataset_joins": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_resolve_atomic_builtin_tool_returns_empty():
    resolver = CompositeToolResolver(session=_SessionStub())

    result = resolver.resolve("builtin:weather:get_weather")

    assert result == []


def test_resolve_atomic_api_tool_returns_empty():
    resolver = CompositeToolResolver(session=_SessionStub())

    result = resolver.resolve("api_tool:abc-123")

    assert result == []


def test_resolve_atomic_mcp_tool_returns_empty():
    resolver = CompositeToolResolver(session=_SessionStub())

    result = resolver.resolve("mcp:provider-1:tool-name")

    assert result == []


def test_resolve_atomic_knowledge_tool_returns_empty():
    resolver = CompositeToolResolver(session=_SessionStub())

    result = resolver.resolve("knowledge:dataset-1")

    assert result == []


def test_resolve_skill_returns_empty():
    """skill 不是组合工具，不递归展开。"""
    resolver = CompositeToolResolver(session=_SessionStub())

    result = resolver.resolve("skill:skill-1")

    assert result == []


def test_resolve_workflow_extracts_tool_and_dataset_nodes():
    dataset_id = uuid4()
    workflow_id = uuid4()
    graph = {
        "nodes": [
            {
                "node_type": "tool",
                "tool_type": "builtin_tool",
                "provider_id": "weather",
                "tool_id": "get_weather",
            },
            {
                "node_type": "tool",
                "tool_type": "api_tool",
                "provider_id": "erp-provider",
                "tool_id": "search_orders",
            },
            {
                "node_type": "dataset_retrieval",
                "dataset_ids": [str(dataset_id)],
            },
            {
                "node_type": "llm",
            },
        ],
        "edges": [],
    }
    session = _SessionStub([_QueryStub(one_result=_make_workflow(workflow_id, graph=graph))])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"workflow:{workflow_id}")

    assert [ref.tool_id for ref in result] == [
        "builtin:weather:get_weather",
        "api_tool:search_orders",
        f"knowledge:{dataset_id}",
    ]
    assert [ref.source_type for ref in result] == ["builtin", "api_tool", "knowledge"]
    assert [ref.is_recursive for ref in result] == [False, False, False]
    assert result[0].ref_path == "workflow.nodes[0].tool"
    assert result[1].ref_path == "workflow.nodes[1].tool"
    assert result[2].ref_path == "workflow.nodes[2].dataset_retrieval"


def test_resolve_workflow_skips_unknown_node_types():
    workflow_id = uuid4()
    graph = {
        "nodes": [
            {"node_type": "code"},
            {"node_type": "http_request"},
            {"node_type": "if_else"},
        ],
        "edges": [],
    }
    session = _SessionStub([_QueryStub(one_result=_make_workflow(workflow_id, graph=graph))])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"workflow:{workflow_id}")

    assert result == []


def test_resolve_workflow_returns_empty_when_workflow_not_found():
    workflow_id = uuid4()
    session = _SessionStub([_QueryStub(one_result=None)])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"workflow:{workflow_id}")

    assert result == []


def test_resolve_agent_binding_private_app_recursively_expands():
    app1_id = uuid4()
    app2_id = uuid4()
    workflow_id = uuid4()
    # app2 的配置：含一个 builtin 工具
    app2_config = _make_config(
        tools=[{"type": "builtin_tool", "provider_id": "search", "tool_id": "web_search"}],
    )
    # app1 的配置：含 api_tool + mcp + skill + dataset + workflow + agent_binding
    app1_config = _make_config(
        tools=[{"type": "api_tool", "provider_id": "erp", "tool_id": "search_orders"}],
        mcp_bindings=[{"name": "github", "provider_key": "gh-key"}],
        skills=[{"skill_id": "code-review"}],
        app_dataset_joins=[SimpleNamespace(dataset_id=uuid4())],
        workflows=[str(workflow_id)],
        agent_bindings=[{"app_id": str(app2_id)}],
    )
    workflow_graph = {
        "nodes": [
            {
                "node_type": "tool",
                "tool_type": "builtin_tool",
                "provider_id": "weather",
                "tool_id": "get_weather",
            },
        ],
        "edges": [],
    }
    # 查询顺序：App(app1) -> Workflow(w1) -> App(app2)
    session = _SessionStub([
        _QueryStub(one_result=_make_app(app1_id, is_public=False, app_config=app1_config)),
        _QueryStub(one_result=_make_workflow(workflow_id, graph=workflow_graph)),
        _QueryStub(one_result=_make_app(app2_id, is_public=False, app_config=app2_config)),
    ])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"agent_binding:{app1_id}")

    tool_ids = [ref.tool_id for ref in result]
    # app1 直接成员
    assert "api_tool:search_orders" in tool_ids
    assert "mcp:gh-key" in tool_ids
    assert "skill:code-review" in tool_ids
    assert any(tid.startswith("knowledge:") for tid in tool_ids)
    # workflow 成员引用 + 递归展开后的 builtin 工具
    assert f"workflow:{workflow_id}" in tool_ids
    assert "builtin:weather:get_weather" in tool_ids
    # agent_binding 成员引用 + 递归展开后的 builtin 工具
    assert f"agent_binding:{app2_id}" in tool_ids
    assert "builtin:search:web_search" in tool_ids
    # workflow 成员标记 is_recursive=True，原子工具标记 False
    workflow_ref = next(ref for ref in result if ref.tool_id == f"workflow:{workflow_id}")
    assert workflow_ref.is_recursive is True
    api_ref = next(ref for ref in result if ref.tool_id == "api_tool:search_orders")
    assert api_ref.is_recursive is False


def test_resolve_agent_binding_public_app_returns_empty():
    app_id = uuid4()
    app = _make_app(app_id, is_public=True, app_config=_make_config())
    session = _SessionStub([_QueryStub(one_result=app)])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"agent_binding:{app_id}")

    assert result == []


def test_resolve_agent_binding_returns_empty_when_app_not_found():
    app_id = uuid4()
    session = _SessionStub([_QueryStub(one_result=None)])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"agent_binding:{app_id}")

    assert result == []


def test_resolve_agent_binding_returns_empty_when_no_app_config():
    app_id = uuid4()
    app = _make_app(app_id, is_public=False, app_config=None)
    session = _SessionStub([_QueryStub(one_result=app)])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"agent_binding:{app_id}")

    assert result == []


def test_resolve_agent_binding_cycle_does_not_infinite_recurse():
    """两个私有 App 通过 agent_bindings 互相引用，visited 集合应阻断循环。"""
    app1_id = uuid4()
    app2_id = uuid4()
    app1_config = _make_config(agent_bindings=[{"app_id": str(app2_id)}])
    app2_config = _make_config(agent_bindings=[{"app_id": str(app1_id)}])
    # 查询顺序：App(app1) -> App(app2)，app2 对 app1 的引用命中 visited 不再查
    session = _SessionStub([
        _QueryStub(one_result=_make_app(app1_id, is_public=False, app_config=app1_config)),
        _QueryStub(one_result=_make_app(app2_id, is_public=False, app_config=app2_config)),
    ])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"agent_binding:{app1_id}")

    tool_ids = [ref.tool_id for ref in result]
    # app1 引用 app2，app2 引用 app1（被 visited 阻断，不再展开）
    assert f"agent_binding:{app2_id}" in tool_ids
    assert f"agent_binding:{app1_id}" in tool_ids
    # 不会无限递归：只产生 2 个引用
    assert len(result) == 2


def test_resolve_agent_binding_self_cycle_does_not_infinite_recurse():
    """agent_binding 引用自身，visited 集合应阻断循环：成员引用被记录但不再展开。"""
    app_id = uuid4()
    config = _make_config(agent_bindings=[{"app_id": str(app_id)}])
    session = _SessionStub([_QueryStub(one_result=_make_app(app_id, is_public=False, app_config=config))])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"agent_binding:{app_id}")

    # 自引用的成员 ref 被记录，但递归展开时命中 visited 返回空，不会无限递归
    assert len(result) == 1
    assert result[0].tool_id == f"agent_binding:{app_id}"
    assert result[0].is_recursive is True


def test_resolve_depth_limit_blocks_recursion():
    """max_depth=1 时根 agent_binding 展开，但嵌套 workflow 不再展开。"""
    app_id = uuid4()
    workflow_id = uuid4()
    workflow_graph = {
        "nodes": [
            {
                "node_type": "tool",
                "tool_type": "builtin_tool",
                "provider_id": "weather",
                "tool_id": "get_weather",
            },
        ],
        "edges": [],
    }
    config = _make_config(workflows=[str(workflow_id)])
    session = _SessionStub([
        _QueryStub(one_result=_make_app(app_id, is_public=False, app_config=config)),
    ])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"agent_binding:{app_id}", max_depth=1)

    # depth=0 展开 agent_binding，发现 workflow 成员引用
    # depth=1 >= max_depth=1，workflow 不再展开，故无 builtin 工具
    tool_ids = [ref.tool_id for ref in result]
    assert tool_ids == [f"workflow:{workflow_id}"]
    assert result[0].is_recursive is True


def test_resolve_depth_limit_zero_returns_empty():
    """max_depth=0 时根节点立即命中深度限制，返回空列表。"""
    app_id = uuid4()
    config = _make_config(workflows=[str(uuid4())])
    session = _SessionStub([
        _QueryStub(one_result=_make_app(app_id, is_public=False, app_config=config)),
    ])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"agent_binding:{app_id}", max_depth=0)

    assert result == []


def test_resolve_depth_limit_allows_one_more_level():
    """max_depth=2 时 agent_binding(depth0) + workflow(depth1) 均展开，workflow 内工具可见。"""
    app_id = uuid4()
    workflow_id = uuid4()
    workflow_graph = {
        "nodes": [
            {
                "node_type": "tool",
                "tool_type": "builtin_tool",
                "provider_id": "weather",
                "tool_id": "get_weather",
            },
        ],
        "edges": [],
    }
    config = _make_config(workflows=[str(workflow_id)])
    session = _SessionStub([
        _QueryStub(one_result=_make_app(app_id, is_public=False, app_config=config)),
        _QueryStub(one_result=_make_workflow(workflow_id, graph=workflow_graph)),
    ])
    resolver = CompositeToolResolver(session=session)

    result = resolver.resolve(f"agent_binding:{app_id}", max_depth=2)

    tool_ids = [ref.tool_id for ref in result]
    assert f"workflow:{workflow_id}" in tool_ids
    assert "builtin:weather:get_weather" in tool_ids


def test_resolve_invalid_tool_id_returns_empty():
    """无冒号分隔的 tool_id 无法解析出 source_type，返回空。"""
    resolver = CompositeToolResolver(session=_SessionStub())

    assert resolver.resolve("invalid-tool-id") == []


def test_resolve_invalid_workflow_uuid_returns_empty():
    """workflow 的 entity_id 非合法 UUID 时返回空。"""
    resolver = CompositeToolResolver(session=_SessionStub())

    result = resolver.resolve("workflow:not-a-uuid")

    assert result == []


def test_resolve_invalid_agent_binding_uuid_returns_empty():
    """agent_binding 的 entity_id 非合法 UUID 时返回空。"""
    resolver = CompositeToolResolver(session=_SessionStub())

    result = resolver.resolve("agent_binding:not-a-uuid")

    assert result == []
