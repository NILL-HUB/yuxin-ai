"""P0-2 CompositeToolResolver + P1-1 部分阻断策略 + P1-5 agent_binding 差异 端到端集成测试。

验证环节：
    CompositeToolResolver 递归解析组合工具成员，RuntimeToolGovernanceGate 基于成员
    计算有效风险等级（max）并应用部分阻断策略。agent_binding 区分私有 App（递归展开）
    与公开 App（A2A 黑盒）。

测试场景：
    1. workflow 组合工具端到端（resolve 返回 3 成员，gate 有效风险 = max 成员）
    2. 部分阻断策略端到端（dangerous/sensitive/safe 成员不同结果）
    3. agent_binding 私有 App 递归展开成员
    4. agent_binding 公开 App 黑盒（resolve 返回空，gate 审计标记 blackbox）
    5. 循环引用防护（A→B→A 不无限递归）
"""

from types import SimpleNamespace
from uuid import uuid4

from internal.entity.runtime_tool_entity import CompositeComponentRef
from internal.service.composite_tool_resolver import CompositeToolResolver
from internal.service.runtime_tool_governance_gate import RuntimeToolGovernanceGate


# ------------------------------------------------------------------ #
#  Stub                                                               #
# ------------------------------------------------------------------ #

class _QueryStub:
    """支持 filter().one_or_none() / filter().all() 链式调用的查询桩。"""

    def __init__(self, *, one_result=None, all_result=None):
        self._one_result = one_result
        self._all_result = [] if all_result is None else all_result

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


class _DbStub:
    """db.session 链式调用桩。"""

    def __init__(self, session):
        self.session = session


def _policy(*, risk_level="low", enabled=True, require_confirmation=False,
            allowed_pools=None, health_status="healthy"):
    """构造 ToolGovernancePolicy 桩。"""
    return SimpleNamespace(
        risk_level=risk_level,
        enabled=enabled,
        require_confirmation=require_confirmation,
        allowed_pools=allowed_pools or [],
        health_status=health_status,
    )


def _tool(name, description="", metadata=None):
    """构造 BaseTool 桩。"""
    return SimpleNamespace(name=name, description=description, metadata=metadata)


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


def _build_gate_with_real_resolver(gate_session_queries, resolver_session_queries):
    """构造使用真实 CompositeToolResolver 的 RuntimeToolGovernanceGate。

    gate_session_queries: gate 的 db.session 查询序列（策略 + App 公开性查询）
    resolver_session_queries: CompositeToolResolver 的 session 查询序列（Workflow/App）
    """
    gate_session = _SessionStub(gate_session_queries)
    db = _DbStub(gate_session)
    resolver_session = _SessionStub(resolver_session_queries)
    resolver = CompositeToolResolver(session=resolver_session)
    return RuntimeToolGovernanceGate(db=db, composite_tool_resolver=resolver)


# ------------------------------------------------------------------ #
#  测试用例                                                           #
# ------------------------------------------------------------------ #

def test_workflow_composite_resolve_and_gate_effective_risk_is_max():
    """场景1：workflow 组合工具端到端。

    构造 Workflow，graph 含 2 个 ToolNode（builtin + api_tool）+ 1 个
    DatasetRetrievalNode。CompositeToolResolver.resolve() 返回 3 个
    CompositeComponentRef；RuntimeToolGovernanceGate.apply() 处理该 workflow 工具，
    有效风险等级 = max(成员)。
    """
    workflow_id = uuid4()
    dataset_id = uuid4()
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
                "provider_id": "erp",
                "tool_id": "search_orders",
            },
            {
                "node_type": "dataset_retrieval",
                "dataset_ids": [str(dataset_id)],
            },
        ],
        "edges": [],
    }
    # 先验证 CompositeToolResolver 返回 3 个成员
    resolver = CompositeToolResolver(
        session=_SessionStub([_QueryStub(one_result=_make_workflow(workflow_id, graph=graph))])
    )
    members = resolver.resolve(f"workflow:{workflow_id}")
    assert len(members) == 3
    member_tool_ids = [ref.tool_id for ref in members]
    assert "builtin:weather:get_weather" in member_tool_ids
    assert "api_tool:search_orders" in member_tool_ids
    assert f"knowledge:{dataset_id}" in member_tool_ids

    # 验证 gate 有效风险 = max(safe, medium, safe) = medium → 放行
    tool = _tool("wf_workflow")
    gate = _build_gate_with_real_resolver(
        gate_session_queries=[
            _QueryStub(one_result=None),  # workflow composite policy
            _QueryStub(one_result=_policy(risk_level="safe")),  # builtin member
            _QueryStub(one_result=_policy(risk_level="medium")),  # api_tool member
            _QueryStub(one_result=_policy(risk_level="safe")),  # knowledge member
        ],
        resolver_session_queries=[
            _QueryStub(one_result=_make_workflow(workflow_id, graph=graph)),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_workflow": f"workflow:{workflow_id}"},
    )

    # 有效风险 = max(safe, medium, safe) = medium，medium 不在 {high, sensitive} → 放行
    assert filtered_tools == [tool]
    composite = audit["composite_resolved"][f"workflow:{workflow_id}"]
    assert composite["composite_resolved"] is True
    assert composite["member_count"] == 3
    assert set(composite["member_tool_ids"]) == set(member_tool_ids)


def test_partial_blocking_dangerous_member_blocks_composite():
    """场景2a：部分阻断 - dangerous 成员阻断整个 workflow。"""
    workflow_id = uuid4()
    graph = {
        "nodes": [
            {"node_type": "tool", "tool_type": "api_tool", "tool_id": "safe_op"},
            {"node_type": "tool", "tool_type": "api_tool", "tool_id": "dangerous_op"},
        ],
        "edges": [],
    }
    tool = _tool("wf_dangerous")
    gate = _build_gate_with_real_resolver(
        gate_session_queries=[
            _QueryStub(one_result=None),  # workflow composite policy
            _QueryStub(one_result=_policy(risk_level="safe")),  # safe_op
            _QueryStub(one_result=_policy(risk_level="dangerous")),  # dangerous_op
        ],
        resolver_session_queries=[
            _QueryStub(one_result=_make_workflow(workflow_id, graph=graph)),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_dangerous": f"workflow:{workflow_id}"},
        allow_confirmation=False,
    )

    assert filtered_tools == []
    assert audit["filtered_out"][0]["reason"] == "member_dangerous"
    composite = audit["composite_resolved"][f"workflow:{workflow_id}"]
    assert composite["partial_blocking"]["should_block"] is True
    assert composite["partial_blocking"]["block_reason"] == "member_dangerous"


def test_partial_blocking_sensitive_member_requires_confirmation():
    """场景2b：部分阻断 - sensitive 成员需用户确认，allow_confirmation=False 阻断。"""
    workflow_id = uuid4()
    graph = {
        "nodes": [
            {"node_type": "tool", "tool_type": "api_tool", "tool_id": "safe_op"},
            {"node_type": "tool", "tool_type": "api_tool", "tool_id": "sensitive_op"},
        ],
        "edges": [],
    }
    tool = _tool("wf_sensitive")
    gate = _build_gate_with_real_resolver(
        gate_session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(risk_level="sensitive")),
        ],
        resolver_session_queries=[
            _QueryStub(one_result=_make_workflow(workflow_id, graph=graph)),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_sensitive": f"workflow:{workflow_id}"},
        allow_confirmation=False,
    )

    assert filtered_tools == []
    assert audit["filtered_out"][0]["reason"] == "high_risk_requires_confirmation"
    composite = audit["composite_resolved"][f"workflow:{workflow_id}"]
    assert composite["partial_blocking"]["requires_confirmation"] is True
    assert composite["partial_blocking"]["confirmation_reason"] == "member_sensitive"


def test_partial_blocking_all_safe_members_passes():
    """场景2c：部分阻断 - 全部 safe 成员放行。"""
    workflow_id = uuid4()
    graph = {
        "nodes": [
            {"node_type": "tool", "tool_type": "api_tool", "tool_id": "op1"},
            {"node_type": "tool", "tool_type": "api_tool", "tool_id": "op2"},
        ],
        "edges": [],
    }
    tool = _tool("wf_safe")
    gate = _build_gate_with_real_resolver(
        gate_session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(risk_level="safe")),
        ],
        resolver_session_queries=[
            _QueryStub(one_result=_make_workflow(workflow_id, graph=graph)),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_safe": f"workflow:{workflow_id}"},
        allow_confirmation=False,
    )

    assert filtered_tools == [tool]
    composite = audit["composite_resolved"][f"workflow:{workflow_id}"]
    assert composite["partial_blocking"]["should_block"] is False
    assert composite["partial_blocking"]["requires_confirmation"] is False


def test_agent_binding_private_app_recursively_expands_members():
    """场景3：agent_binding 私有 App 递归展开成员。

    构造 agent_binding 指向私有 App，目标 AppConfig 含 2 个工具（builtin + api_tool）。
    CompositeToolResolver.resolve("agent_binding:{app_id}") 返回 2 个成员。
    """
    app_id = uuid4()
    app_config = _make_config(
        tools=[
            {"type": "builtin_tool", "provider_id": "search", "tool_id": "web_search"},
            {"type": "api_tool", "tool_id": "fetch_data"},
        ],
    )
    # 先验证 resolver 返回 2 个成员
    resolver = CompositeToolResolver(
        session=_SessionStub([
            _QueryStub(one_result=_make_app(app_id, is_public=False, app_config=app_config)),
        ])
    )
    members = resolver.resolve(f"agent_binding:{app_id}")
    assert len(members) == 2
    member_tool_ids = [ref.tool_id for ref in members]
    assert "builtin:search:web_search" in member_tool_ids
    assert "api_tool:fetch_data" in member_tool_ids

    # 验证 gate 处理 agent_binding 工具（有效风险 = max 成员）
    runtime_name = f"agent_app_{str(app_id).replace('-', '')}"
    tool = _tool(runtime_name)
    gate = _build_gate_with_real_resolver(
        gate_session_queries=[
            _QueryStub(one_result=None),  # agent_binding composite policy
            _QueryStub(one_result=_make_app(app_id, is_public=False)),  # _is_agent_binding_public_app
            _QueryStub(one_result=_policy(risk_level="safe")),  # builtin member
            _QueryStub(one_result=_policy(risk_level="safe")),  # api_tool member
        ],
        resolver_session_queries=[
            _QueryStub(one_result=_make_app(app_id, is_public=False, app_config=app_config)),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={runtime_name: f"agent_binding:{app_id}"},
    )

    # 全部 safe → 放行
    assert filtered_tools == [tool]
    composite = audit["composite_resolved"][f"agent_binding:{app_id}"]
    assert composite["composite_resolved"] is True
    assert composite["member_count"] == 2


def test_agent_binding_public_app_blackbox_skips_member_resolution():
    """场景4：agent_binding 公开 App 黑盒。

    构造 agent_binding 指向公开 App（is_public=True），CompositeToolResolver.resolve
    返回空列表；RuntimeToolGovernanceGate 审计上下文标记 composite_resolved: false,
    reason: "public_app_a2a_blackbox"。
    """
    app_id = uuid4()
    # 先验证 resolver 对公开 App 返回空
    resolver = CompositeToolResolver(
        session=_SessionStub([
            _QueryStub(one_result=_make_app(app_id, is_public=True, app_config=_make_config())),
        ])
    )
    members = resolver.resolve(f"agent_binding:{app_id}")
    assert members == []

    # 验证 gate 审计标记黑盒
    runtime_name = f"agent_app_{str(app_id).replace('-', '')}"
    tool = _tool(runtime_name)
    gate = _build_gate_with_real_resolver(
        gate_session_queries=[
            _QueryStub(one_result=_policy(risk_level="medium")),  # agent_binding composite policy
            _QueryStub(one_result=_make_app(app_id, is_public=True)),  # _is_agent_binding_public_app → True
        ],
        resolver_session_queries=[],  # 公开 App 不调 resolver
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={runtime_name: f"agent_binding:{app_id}"},
        allow_confirmation=False,
    )

    # 公开 App：用 app_id 层级策略 medium → 放行
    assert filtered_tools == [tool]
    composite = audit["composite_resolved"][f"agent_binding:{app_id}"]
    assert composite["composite_resolved"] is False
    assert composite["reason"] == "public_app_a2a_blackbox"
    assert composite["member_count"] == 0
    assert composite["member_tool_ids"] == []


def test_agent_binding_cycle_does_not_infinite_recurse():
    """场景5：循环引用防护（A→B→A 不无限递归）。

    构造 A→B→A 的 agent_binding 循环，CompositeToolResolver.resolve 不无限递归，
    返回部分成员引用（visited 集合阻断循环）。
    """
    app_a_id = uuid4()
    app_b_id = uuid4()
    config_a = _make_config(agent_bindings=[{"app_id": str(app_b_id)}])
    config_b = _make_config(agent_bindings=[{"app_id": str(app_a_id)}])
    resolver = CompositeToolResolver(
        session=_SessionStub([
            _QueryStub(one_result=_make_app(app_a_id, is_public=False, app_config=config_a)),
            _QueryStub(one_result=_make_app(app_b_id, is_public=False, app_config=config_b)),
        ])
    )

    result = resolver.resolve(f"agent_binding:{app_a_id}")

    # 不会无限递归：A 引用 B，B 引用 A（被 visited 阻断），返回 2 个引用
    tool_ids = [ref.tool_id for ref in result]
    assert f"agent_binding:{app_b_id}" in tool_ids
    assert f"agent_binding:{app_a_id}" in tool_ids
    assert len(result) == 2
