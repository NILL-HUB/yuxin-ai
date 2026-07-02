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


def _policy(*, risk_level="low", enabled=True, require_confirmation=False, allowed_pools=None):
    """构造 ToolGovernancePolicy 桩。"""
    return SimpleNamespace(
        risk_level=risk_level,
        enabled=enabled,
        require_confirmation=require_confirmation,
        allowed_pools=allowed_pools or [],
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
