from types import SimpleNamespace

from internal.entity.runtime_tool_entity import CompositeComponentRef
from internal.service.runtime_tool_governance_gate import RuntimeToolGovernanceGate


# ------------------------------------------------------------------ #
#  Stub 工具                                                          #
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


class _StubResolver:
    """覆盖 resolve() 返回预设成员的 CompositeToolResolver 桩。"""

    def __init__(self, members_by_tool_id=None):
        self._members = members_by_tool_id or {}
        self.resolve_calls: list[str] = []

    def resolve(self, tool_id, *, max_depth=8):
        self.resolve_calls.append(tool_id)
        return list(self._members.get(tool_id, []))


def _policy(*, risk_level="low", enabled=True, require_confirmation=False, allowed_pools=None, health_status="healthy"):
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


def _ref(tool_id, source_type="api_tool"):
    return CompositeComponentRef(
        tool_id=tool_id,
        source_type=source_type,
        ref_path="test",
        is_recursive=False,
    )


def _build_gate(session_queries=None, members_by_tool_id=None):
    session = _SessionStub(session_queries)
    db = _DbStub(session)
    resolver = _StubResolver(members_by_tool_id)
    return RuntimeToolGovernanceGate(db=db, composite_tool_resolver=resolver)


# ------------------------------------------------------------------ #
#  测试用例                                                           #
# ------------------------------------------------------------------ #

def test_apply_empty_tools_returns_empty_list():
    gate = _build_gate()

    filtered_tools, audit = gate.apply([])

    assert filtered_tools == []
    assert audit["accepted"] == []
    assert audit["filtered_out"] == []
    assert audit["composite_resolved"] == {}
    assert audit["input_tool_count"] == 0
    assert audit["output_tool_count"] == 0


def test_apply_atomic_safe_tool_passes():
    tool = _tool("search")
    gate = _build_gate(
        session_queries=[_QueryStub(one_result=_policy(risk_level="safe"))],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"search": "api_tool:t1"},
        account_id="account-1",
    )

    assert filtered_tools == [tool]
    assert len(audit["accepted"]) == 1
    assert audit["accepted"][0]["tool_id"] == "api_tool:t1"
    assert audit["filtered_out"] == []
    assert audit["output_tool_count"] == 1


def test_apply_high_risk_tool_filtered_without_confirmation():
    tool = _tool("delete")
    gate = _build_gate(
        session_queries=[
            _QueryStub(one_result=_policy(
                risk_level="high", require_confirmation=True,
            )),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"delete": "api_tool:t2"},
        allow_confirmation=False,
    )

    assert filtered_tools == []
    assert len(audit["filtered_out"]) == 1
    assert audit["filtered_out"][0]["tool_id"] == "api_tool:t2"
    assert audit["filtered_out"][0]["reason"] == "high_risk_requires_confirmation"
    assert audit["accepted"] == []


def test_apply_composite_effective_risk_is_max_of_members():
    tool = _tool("wf_w1")
    gate = _build_gate(
        # 查询顺序：workflow 自身策略(无) → m1 策略(safe) → m2 策略(high+确认)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(
                risk_level="high", require_confirmation=True,
            )),
        ],
        members_by_tool_id={
            "workflow:w1": [_ref("api_tool:m1"), _ref("api_tool:m2")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_w1": "workflow:w1"},
        allow_confirmation=False,
    )

    # 有效风险 = max(safe, high) = high，且 m2 require_confirmation=True → 被过滤
    assert filtered_tools == []
    assert len(audit["filtered_out"]) == 1
    assert audit["filtered_out"][0]["tool_id"] == "workflow:w1"
    assert audit["filtered_out"][0]["reason"] == "high_risk_requires_confirmation"
    # 组合工具解析审计记录成员链路
    assert "workflow:w1" in audit["composite_resolved"]
    composite = audit["composite_resolved"]["workflow:w1"]
    assert composite["member_count"] == 2
    assert composite["member_tool_ids"] == ["api_tool:m1", "api_tool:m2"]


def test_apply_observe_only_does_not_filter_but_records_audit():
    tool = _tool("delete")
    gate = _build_gate(
        session_queries=[
            _QueryStub(one_result=_policy(
                risk_level="high", require_confirmation=True,
            )),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"delete": "api_tool:t2"},
        allow_confirmation=False,
        observe_only=True,
    )

    # observe_only：工具不被过滤，仍保留
    assert filtered_tools == [tool]
    assert audit["observe_only"] is True
    assert audit["output_tool_count"] == 1
    # 审计仍记录过滤决策
    assert len(audit["filtered_out"]) == 1
    assert audit["filtered_out"][0]["reason"] == "high_risk_requires_confirmation"


def test_apply_tool_id_hints_take_priority_over_name_pattern():
    """name 为 wf_ 前缀（应匹配 workflow），但 hint 提供精确 tool_id，应优先用 hint。"""
    tool = _tool("wf_my_workflow")
    gate = _build_gate(
        # hint 提供的 tool_id 为 workflow:uuid-123，查询其策略(无) + 成员策略(safe)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="safe")),
        ],
        members_by_tool_id={
            "workflow:uuid-123": [_ref("api_tool:m1")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_my_workflow": "workflow:uuid-123"},
    )

    # tool_id 应为 hint 提供的精确值，而非 name 模式匹配的占位值
    assert audit["accepted"][0]["tool_id"] == "workflow:uuid-123"
    assert "workflow:uuid-123" in audit["composite_resolved"]
    # resolver 收到的是 hint 提供的 tool_id
    assert gate.composite_tool_resolver.resolve_calls == ["workflow:uuid-123"]


def test_apply_policy_not_found_degrades_to_defaults():
    tool = _tool("search")
    gate = _build_gate(
        session_queries=[_QueryStub(one_result=None)],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"search": "api_tool:t1"},
    )

    # 无策略记录时降级为默认值（risk_level=medium），medium 不在 {high, sensitive} → 放行
    assert filtered_tools == [tool]
    assert len(audit["accepted"]) == 1


def test_apply_audit_context_structure():
    """验证审计上下文包含全部必需字段且结构正确。"""
    safe_tool = _tool("search")
    risky_tool = _tool("delete")
    gate = _build_gate(
        session_queries=[
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(
                risk_level="sensitive", require_confirmation=True,
            )),
        ],
    )

    filtered_tools, audit = gate.apply(
        [safe_tool, risky_tool],
        tool_id_hints={
            "search": "api_tool:safe",
            "delete": "api_tool:risky",
        },
        account_id="account-1",
        app_id="app-1",
        agent_pool="primary",
        budget_level="medium",
    )

    # 结构断言
    assert set(audit.keys()) >= {
        "accepted", "filtered_out", "composite_resolved",
        "observe_only", "input_tool_count", "output_tool_count",
    }
    assert audit["observe_only"] is False
    assert audit["input_tool_count"] == 2
    assert audit["output_tool_count"] == 1
    assert audit["account_id"] == "account-1"
    assert audit["app_id"] == "app-1"
    assert audit["agent_pool"] == "primary"
    assert audit["budget_level"] == "medium"
    # accepted 结构
    assert audit["accepted"] == [
        {"tool_id": "api_tool:safe", "name": "search"},
    ]
    # filtered_out 结构
    assert audit["filtered_out"] == [
        {
            "tool_id": "api_tool:risky",
            "name": "delete",
            "reason": "high_risk_requires_confirmation",
        },
    ]
    # composite_resolved 结构（原子工具不产生组合解析记录）
    assert audit["composite_resolved"] == {}
    # 返回的工具列表正确
    assert filtered_tools == [safe_tool]


# ------------------------------------------------------------------ #
#  agent_binding 治理测试 (P1-5)                                      #
# ------------------------------------------------------------------ #

def _app(*, is_public=False):
    """构造 App 桩，用于 _is_agent_binding_public_app 的 DB 查询返回。"""
    return SimpleNamespace(is_public=is_public)


def test_agent_binding_tool_identified_as_composite():
    """agent_binding 工具通过 tool_id_hints 被识别为组合工具并展开成员。"""
    app_id = "11111111-1111-1111-1111-111111111111"
    runtime_name = f"agent_app_{app_id.replace('-', '')}"
    tool = _tool(runtime_name)
    gate = _build_gate(
        # 查询顺序：agent_binding 策略(无) → App(私有) → 成员 m1 策略(safe)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_app(is_public=False)),
            _QueryStub(one_result=_policy(risk_level="safe")),
        ],
        members_by_tool_id={
            f"agent_binding:{app_id}": [_ref("api_tool:m1")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={runtime_name: f"agent_binding:{app_id}"},
    )

    # 工具被识别为组合工具，resolver 收到 hint 提供的精确 tool_id
    assert gate.composite_tool_resolver.resolve_calls == [f"agent_binding:{app_id}"]
    # safe 成员 → 有效风险 safe → 放行
    assert filtered_tools == [tool]
    assert audit["accepted"][0]["tool_id"] == f"agent_binding:{app_id}"
    # 审计记录组合工具展开
    assert f"agent_binding:{app_id}" in audit["composite_resolved"]
    composite = audit["composite_resolved"][f"agent_binding:{app_id}"]
    assert composite["composite_resolved"] is True
    assert composite["member_count"] == 1
    assert composite["member_tool_ids"] == ["api_tool:m1"]


def test_agent_binding_private_app_effective_risk_is_max_of_members():
    """私有 App agent_binding：有效风险等级取成员 max，高风险+确认 → 被过滤。"""
    app_id = "22222222-2222-2222-2222-222222222222"
    runtime_name = f"agent_app_{app_id.replace('-', '')}"
    tool = _tool(runtime_name)
    gate = _build_gate(
        # 查询顺序：agent_binding 策略(无) → App(私有) → m1(safe) → m2(high+确认)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_app(is_public=False)),
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(
                risk_level="high", require_confirmation=True,
            )),
        ],
        members_by_tool_id={
            f"agent_binding:{app_id}": [
                _ref("api_tool:m1"), _ref("api_tool:m2"),
            ],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={runtime_name: f"agent_binding:{app_id}"},
        allow_confirmation=False,
    )

    # 有效风险 = max(safe, high) = high，且 m2 require_confirmation=True → 被过滤
    assert filtered_tools == []
    assert len(audit["filtered_out"]) == 1
    assert audit["filtered_out"][0]["tool_id"] == f"agent_binding:{app_id}"
    assert audit["filtered_out"][0]["reason"] == "high_risk_requires_confirmation"
    composite = audit["composite_resolved"][f"agent_binding:{app_id}"]
    assert composite["composite_resolved"] is True
    assert composite["member_count"] == 2
    assert composite["member_tool_ids"] == ["api_tool:m1", "api_tool:m2"]


def test_agent_binding_public_app_skips_member_resolution():
    """公开 App agent_binding：不展开成员，用 app_id 层级策略，审计标记黑盒。"""
    app_id = "33333333-3333-3333-3333-333333333333"
    runtime_name = f"agent_app_{app_id.replace('-', '')}"
    tool = _tool(runtime_name)
    gate = _build_gate(
        # 查询顺序：agent_binding 策略(medium, 无确认) → App(公开)
        session_queries=[
            _QueryStub(one_result=_policy(risk_level="medium")),
            _QueryStub(one_result=_app(is_public=True)),
        ],
        members_by_tool_id={
            # 即使预设了成员，公开 App 也不应调用 resolver
            f"agent_binding:{app_id}": [_ref("api_tool:m1")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={runtime_name: f"agent_binding:{app_id}"},
        allow_confirmation=False,
    )

    # 公开 App 不调用 CompositeToolResolver
    assert gate.composite_tool_resolver.resolve_calls == []
    # app_id 层级策略 medium + 无确认 → 放行
    assert filtered_tools == [tool]
    assert audit["accepted"][0]["tool_id"] == f"agent_binding:{app_id}"
    # 审计标记公开 App 黑盒
    composite = audit["composite_resolved"][f"agent_binding:{app_id}"]
    assert composite["composite_resolved"] is False
    assert composite["reason"] == "public_app_a2a_blackbox"
    assert composite["member_count"] == 0
    assert composite["member_tool_ids"] == []


def test_agent_binding_default_governance_metadata():
    """agent_binding 无策略记录时降级为显式默认治理元数据。"""
    gate = _build_gate(
        session_queries=[_QueryStub(one_result=None)],
    )

    metadata = gate._load_governance_metadata(
        "agent_binding:default-app-1", "agent_binding"
    )

    assert metadata["risk_level"] == "medium"
    assert metadata["permission_scope"] == "user"
    assert metadata["requires_confirmation"] is False
    assert metadata["enabled"] is True
    assert metadata["cost_level"] == "medium"
    assert metadata["tool_pool"] == "agent_binding"


# ------------------------------------------------------------------ #
#  block_sensitive_only 渐进式启用测试 (P1-2 阶段2)                    #
# ------------------------------------------------------------------ #

def test_apply_block_sensitive_only_blocks_sensitive_tool():
    """阶段2：sensitive 风险+确认 工具被阻断。"""
    tool = _tool("purge")
    gate = _build_gate(
        session_queries=[
            _QueryStub(one_result=_policy(
                risk_level="sensitive", require_confirmation=True,
            )),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"purge": "api_tool:s1"},
        allow_confirmation=False,
        observe_only=False,
        block_sensitive_only=True,
    )

    assert filtered_tools == []
    assert audit["observe_only"] is False
    assert audit["block_sensitive_only"] is True
    assert len(audit["filtered_out"]) == 1


def test_apply_block_sensitive_only_blocks_dangerous_tool():
    """阶段2：被 ToolPolicyFilter 过滤的 dangerous 风险工具被阻断。

    注意：ToolPolicyFilter 仅对 {HIGH, SENSITIVE}+确认要求过滤，dangerous 工具
    需经其他原因（如 enabled=False）被过滤后，block_sensitive_only 才会因
    risk_level=dangerous ∈ {sensitive, dangerous} 保持阻断。
    """
    tool = _tool("nuke")
    gate = _build_gate(
        session_queries=[
            _QueryStub(one_result=_policy(
                risk_level="dangerous", enabled=False, require_confirmation=True,
            )),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"nuke": "api_tool:d1"},
        allow_confirmation=False,
        observe_only=False,
        block_sensitive_only=True,
    )

    assert filtered_tools == []
    assert audit["filtered_out"][0]["reason"] == "tool_disabled"


def test_apply_block_sensitive_only_passes_high_risk_tool():
    """阶段2：high 风险工具即便被 ToolPolicyFilter 过滤也放行（仅 sensitive/dangerous 阻断）。"""
    tool = _tool("delete")
    gate = _build_gate(
        session_queries=[
            _QueryStub(one_result=_policy(
                risk_level="high", require_confirmation=True,
            )),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"delete": "api_tool:h1"},
        allow_confirmation=False,
        observe_only=False,
        block_sensitive_only=True,
    )

    # high 不在 {sensitive, dangerous} → 放行（即便 ToolPolicyFilter 因确认要求过滤它）
    assert filtered_tools == [tool]
    # 审计仍记录 ToolPolicyFilter 的过滤决策
    assert len(audit["filtered_out"]) == 1
    assert audit["filtered_out"][0]["reason"] == "high_risk_requires_confirmation"


def test_apply_block_sensitive_only_passes_safe_and_medium_tools():
    """阶段2：safe/medium 风险工具放行。"""
    safe_tool = _tool("search")
    medium_tool = _tool("update")
    gate = _build_gate(
        session_queries=[
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(risk_level="medium")),
        ],
    )

    filtered_tools, audit = gate.apply(
        [safe_tool, medium_tool],
        tool_id_hints={
            "search": "api_tool:safe",
            "update": "api_tool:med",
        },
        observe_only=False,
        block_sensitive_only=True,
    )

    assert filtered_tools == [safe_tool, medium_tool]


def test_apply_observe_only_overrides_block_sensitive_only():
    """observe_only=True 时 block_sensitive_only 不生效，全部工具保留。"""
    tool = _tool("purge")
    gate = _build_gate(
        session_queries=[
            _QueryStub(one_result=_policy(
                risk_level="sensitive", require_confirmation=True,
            )),
        ],
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"purge": "api_tool:s1"},
        allow_confirmation=False,
        observe_only=True,
        block_sensitive_only=True,
    )

    # observe_only 优先：不阻断
    assert filtered_tools == [tool]
    assert audit["observe_only"] is True
    assert audit["block_sensitive_only"] is True


def test_apply_block_sensitive_only_mixed_safe_and_sensitive():
    """阶段2：混合工具列表，仅 sensitive/dangerous 被阻断，其余放行。"""
    safe_tool = _tool("search")
    sensitive_tool = _tool("purge")
    high_tool = _tool("delete")
    gate = _build_gate(
        session_queries=[
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(
                risk_level="sensitive", require_confirmation=True,
            )),
            _QueryStub(one_result=_policy(
                risk_level="high", require_confirmation=True,
            )),
        ],
    )

    filtered_tools, audit = gate.apply(
        [safe_tool, sensitive_tool, high_tool],
        tool_id_hints={
            "search": "api_tool:safe",
            "purge": "api_tool:sens",
            "delete": "api_tool:high",
        },
        allow_confirmation=False,
        observe_only=False,
        block_sensitive_only=True,
    )

    # safe 放行、sensitive 阻断、high 放行
    assert filtered_tools == [safe_tool, high_tool]
    assert audit["output_tool_count"] == 2
    assert audit["input_tool_count"] == 3


def test_apply_stage3_block_all_filters_all_risk_levels():
    """阶段3：observe_only=False + block_sensitive_only=False 全量过滤（向后兼容）。"""
    safe_tool = _tool("search")
    high_tool = _tool("delete")
    gate = _build_gate(
        session_queries=[
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(
                risk_level="high", require_confirmation=True,
            )),
        ],
    )

    filtered_tools, audit = gate.apply(
        [safe_tool, high_tool],
        tool_id_hints={
            "search": "api_tool:safe",
            "delete": "api_tool:high",
        },
        allow_confirmation=False,
        observe_only=False,
        block_sensitive_only=False,
    )

    # 阶段3：high+确认 → 被过滤，仅 safe 保留
    assert filtered_tools == [safe_tool]
    assert audit["block_sensitive_only"] is False


def test_apply_empty_tools_audit_includes_block_sensitive_only_field():
    """空工具列表时 audit_context 仍包含 block_sensitive_only 字段。"""
    gate = _build_gate()

    _filtered, audit = gate.apply(
        [],
        block_sensitive_only=True,
    )

    assert audit["block_sensitive_only"] is True
    assert audit["observe_only"] is False


# ------------------------------------------------------------------ #
#  组合工具部分阻断策略测试 (P1-1 架构文档 10.2.3)                    #
# ------------------------------------------------------------------ #

def test_composite_dangerous_member_blocks_composite():
    """部分阻断：成员含 dangerous → 组合工具整体阻断。"""
    tool = _tool("wf_w1")
    gate = _build_gate(
        # 查询顺序：composite 策略(无) → m1(safe) → m2(dangerous)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(risk_level="dangerous")),
        ],
        members_by_tool_id={
            "workflow:w1": [_ref("api_tool:m1"), _ref("api_tool:m2")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_w1": "workflow:w1"},
        allow_confirmation=False,
    )

    # dangerous 成员 → 整体阻断
    assert filtered_tools == []
    assert len(audit["filtered_out"]) == 1
    assert audit["filtered_out"][0]["tool_id"] == "workflow:w1"
    assert audit["filtered_out"][0]["reason"] == "member_dangerous"
    # 审计记录部分阻断决策
    composite = audit["composite_resolved"]["workflow:w1"]
    assert composite["partial_blocking"]["should_block"] is True
    assert composite["partial_blocking"]["block_reason"] == "member_dangerous"


def test_composite_sensitive_member_requires_confirmation():
    """部分阻断：成员含 sensitive → 组合工具需用户确认。"""
    tool = _tool("wf_w1")
    gate = _build_gate(
        # 查询顺序：composite 策略(无) → m1(safe) → m2(sensitive)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(risk_level="sensitive")),
        ],
        members_by_tool_id={
            "workflow:w1": [_ref("api_tool:m1"), _ref("api_tool:m2")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_w1": "workflow:w1"},
        allow_confirmation=False,
    )

    # sensitive 成员 → 强制需确认，allow_confirmation=False → 阻断
    assert filtered_tools == []
    assert audit["filtered_out"][0]["reason"] == "high_risk_requires_confirmation"
    composite = audit["composite_resolved"]["workflow:w1"]
    assert composite["partial_blocking"]["requires_confirmation"] is True
    assert composite["partial_blocking"]["confirmation_reason"] == "member_sensitive"


def test_composite_disabled_member_blocks_composite():
    """部分阻断：成员含 disabled → 组合工具整体阻断。"""
    tool = _tool("wf_w1")
    gate = _build_gate(
        # 查询顺序：composite 策略(无) → m1(safe) → m2(medium, disabled)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(risk_level="medium", enabled=False)),
        ],
        members_by_tool_id={
            "workflow:w1": [_ref("api_tool:m1"), _ref("api_tool:m2")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_w1": "workflow:w1"},
        allow_confirmation=False,
    )

    # disabled 成员 → 整体阻断（即便组合工具自身 enabled=True）
    assert filtered_tools == []
    assert audit["filtered_out"][0]["reason"] == "member_disabled"
    composite = audit["composite_resolved"]["workflow:w1"]
    assert composite["partial_blocking"]["block_reason"] == "member_disabled"


def test_composite_unhealthy_member_blocks_composite():
    """部分阻断：成员含 unhealthy → 组合工具整体阻断（保守策略）。"""
    tool = _tool("wf_w1")
    gate = _build_gate(
        # 查询顺序：composite 策略(无) → m1(safe) → m2(medium, unhealthy)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(risk_level="medium", health_status="unhealthy")),
        ],
        members_by_tool_id={
            "workflow:w1": [_ref("api_tool:m1"), _ref("api_tool:m2")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_w1": "workflow:w1"},
        allow_confirmation=False,
    )

    # unhealthy 成员 → 整体阻断
    assert filtered_tools == []
    assert audit["filtered_out"][0]["reason"] == "member_unhealthy"
    composite = audit["composite_resolved"]["workflow:w1"]
    assert composite["partial_blocking"]["block_reason"] == "member_unhealthy"


def test_composite_all_safe_members_passes():
    """部分阻断：成员全部 safe → 组合工具正常放行。"""
    tool = _tool("wf_w1")
    gate = _build_gate(
        # 查询顺序：composite 策略(无) → m1(safe) → m2(safe)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="safe")),
            _QueryStub(one_result=_policy(risk_level="safe")),
        ],
        members_by_tool_id={
            "workflow:w1": [_ref("api_tool:m1"), _ref("api_tool:m2")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_w1": "workflow:w1"},
        allow_confirmation=False,
    )

    # 全部 safe → 放行
    assert filtered_tools == [tool]
    assert audit["accepted"][0]["tool_id"] == "workflow:w1"
    assert audit["filtered_out"] == []
    composite = audit["composite_resolved"]["workflow:w1"]
    assert composite["partial_blocking"]["should_block"] is False
    assert composite["partial_blocking"]["requires_confirmation"] is False


def test_composite_double_layer_overlay_takes_stricter_risk():
    """治理策略双层叠加：组合工具层级 medium + 成员层级 high → 有效 high。

    双层叠加（架构文档 10.2.3）：两层策略同时存在时取更严格（max 风险等级）。
    若叠加未生效（仅用 composite 层级 medium），ToolPolicyFilter 不会过滤 medium；
    有效风险为 high + 确认 → 被过滤，证明叠加取了 max(medium, high) = high。
    """
    tool = _tool("wf_w1")
    gate = _build_gate(
        # 查询顺序：composite 策略(medium) → m1(high, 需确认)
        session_queries=[
            _QueryStub(one_result=_policy(risk_level="medium")),
            _QueryStub(one_result=_policy(risk_level="high", require_confirmation=True)),
        ],
        members_by_tool_id={
            "workflow:w1": [_ref("api_tool:m1")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_w1": "workflow:w1"},
        allow_confirmation=False,
    )

    # 双层叠加：max(medium, high) = high + 确认 → 阻断
    assert filtered_tools == []
    assert audit["filtered_out"][0]["reason"] == "high_risk_requires_confirmation"
    # 成员被展开（证明走了双层叠加路径）
    assert audit["composite_resolved"]["workflow:w1"]["member_count"] == 1


def test_observe_only_composite_blocking_does_not_filter():
    """observe_only=True 时部分阻断策略不阻断（只记录审计）。"""
    tool = _tool("wf_w1")
    gate = _build_gate(
        # 查询顺序：composite 策略(无) → m1(dangerous)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="dangerous")),
        ],
        members_by_tool_id={
            "workflow:w1": [_ref("api_tool:m1")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_w1": "workflow:w1"},
        allow_confirmation=False,
        observe_only=True,
    )

    # observe_only：dangerous 成员也不阻断，工具保留
    assert filtered_tools == [tool]
    assert audit["observe_only"] is True
    # 审计仍记录部分阻断决策
    composite = audit["composite_resolved"]["workflow:w1"]
    assert composite["partial_blocking"]["should_block"] is True
    assert composite["partial_blocking"]["block_reason"] == "member_dangerous"


def test_block_sensitive_only_composite_dangerous_still_blocks():
    """block_sensitive_only=True 时组合工具部分阻断策略仍生效（dangerous 成员阻断）。"""
    tool = _tool("wf_w1")
    gate = _build_gate(
        # 查询顺序：composite 策略(无) → m1(dangerous)
        session_queries=[
            _QueryStub(one_result=None),
            _QueryStub(one_result=_policy(risk_level="dangerous")),
        ],
        members_by_tool_id={
            "workflow:w1": [_ref("api_tool:m1")],
        },
    )

    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"wf_w1": "workflow:w1"},
        allow_confirmation=False,
        observe_only=False,
        block_sensitive_only=True,
    )

    # block_sensitive_only 时部分阻断策略仍生效：dangerous 成员 → 阻断
    assert filtered_tools == []
    assert audit["filtered_out"][0]["reason"] == "member_dangerous"
    assert audit["block_sensitive_only"] is True
