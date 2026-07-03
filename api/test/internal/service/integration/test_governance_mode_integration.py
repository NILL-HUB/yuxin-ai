"""P1-2 三阶段渐进式启用 端到端集成测试。

验证环节：
    GovernanceModeResolver 根据 OrchestrationFeatureFlag 解析当前治理模式（阶段1/2/3），
    build_governance_context() 构建治理上下文，RuntimeToolGovernanceGate.apply() 按阶段
    应用不同过滤策略。

测试场景：
    1. 阶段1 observe_only：只观测不阻断
    2. 阶段2 block_sensitive：仅 sensitive/dangerous 阻断
    3. 阶段3 block_all：全量过滤
    4. 优先级：block_all > block_sensitive > observe_only
    5. 降级：查询异常时降级为阶段1
    6. build_governance_context overrides 透传
"""

from types import SimpleNamespace

from internal.entity.orchestration_feature_flag_entity import (
    POOL_GOVERNANCE_FLAG_BLOCK_ALL,
    POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE,
    POOL_GOVERNANCE_FLAG_OBSERVE_ONLY,
    POOL_GOVERNANCE_MODE_BLOCK_ALL,
    POOL_GOVERNANCE_MODE_BLOCK_SENSITIVE,
    POOL_GOVERNANCE_MODE_OBSERVE_ONLY,
)
from internal.service.governance_mode_resolver import GovernanceModeResolver
from internal.service.runtime_tool_governance_gate import RuntimeToolGovernanceGate


# ------------------------------------------------------------------ #
#  Stub                                                               #
# ------------------------------------------------------------------ #

class _FlagQueryStub:
    """支持 filter(...).all() 的 feature flag 查询桩。"""

    def __init__(self, all_result=None):
        self._all_result = all_result or []

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._all_result


class _PolicyQueryStub:
    """支持 filter(...).one_or_none() 的策略查询桩。"""

    def __init__(self, *, one_result=None):
        self._one_result = one_result

    def filter(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self._one_result


class _FlagSessionStub:
    """feature flag 会话桩：query 返回预设的 flag 列表。"""

    def __init__(self, flags):
        self._flags = flags

    def query(self, *_args, **_kwargs):
        return _FlagQueryStub(all_result=self._flags)


class _PolicySessionStub:
    """策略会话桩：按调用顺序依次返回预设查询结果。"""

    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _PolicyQueryStub(one_result=None)


class _SessionRaisesStub:
    """query() 直接抛异常的会话桩，用于验证降级路径。"""

    def query(self, *_args, **_kwargs):
        raise RuntimeError("table missing")


class _DbStub:
    def __init__(self, session):
        self.session = session


class _StubResolver:
    """覆盖 resolve() 返回空的 CompositeToolResolver 桩（原子工具测试用）。"""

    def resolve(self, tool_id, *, max_depth=8):
        return []


def _flag(code, enabled):
    return SimpleNamespace(code=code, enabled=enabled)


def _policy(*, risk_level="low", enabled=True, require_confirmation=False,
            allowed_pools=None, health_status="healthy"):
    return SimpleNamespace(
        risk_level=risk_level,
        enabled=enabled,
        require_confirmation=require_confirmation,
        allowed_pools=allowed_pools or [],
        health_status=health_status,
    )


def _tool(name, description="", metadata=None):
    return SimpleNamespace(name=name, description=description, metadata=metadata)


def _mode_resolver(flags):
    """构造 GovernanceModeResolver，flags 为 feature flag 列表。"""
    session = _FlagSessionStub(flags)
    return GovernanceModeResolver(db=_DbStub(session))


def _gate(policy_queries=None):
    """构造 RuntimeToolGovernanceGate（用 _StubResolver，原子工具测试）。"""
    session = _PolicySessionStub(policy_queries)
    db = _DbStub(session)
    return RuntimeToolGovernanceGate(db=db, composite_tool_resolver=_StubResolver())


# ------------------------------------------------------------------ #
#  测试用例                                                           #
# ------------------------------------------------------------------ #

def test_stage1_observe_only_does_not_filter_but_records_audit():
    """场景1：阶段1 observe_only - 只观测不阻断。

    mock OBSERVE_ONLY=True, BLOCK_SENSITIVE=False, BLOCK_ALL=False。
    resolve_mode() 返回 observe_only=True；gate.apply(observe_only=True) 对
    sensitive 工具不阻断，只记录审计。
    """
    resolver = _mode_resolver([
        _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, True),
        _flag(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, False),
        _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, False),
    ])

    mode = resolver.resolve_mode()
    assert mode["mode"] == POOL_GOVERNANCE_MODE_OBSERVE_ONLY
    assert mode["observe_only"] is True

    ctx = resolver.build_governance_context()
    assert ctx["observe_only"] is True

    # gate.apply observe_only=True 对 sensitive 工具不阻断
    tool = _tool("purge")
    gate = _gate([
        _PolicyQueryStub(one_result=_policy(
            risk_level="sensitive", require_confirmation=True,
        )),
    ])
    filtered_tools, audit = gate.apply(
        [tool],
        tool_id_hints={"purge": "api_tool:s1"},
        allow_confirmation=False,
        observe_only=True,
    )

    assert filtered_tools == [tool]
    assert audit["observe_only"] is True
    # 审计仍记录过滤决策
    assert len(audit["filtered_out"]) == 1
    assert audit["filtered_out"][0]["reason"] == "high_risk_requires_confirmation"


def test_stage2_block_sensitive_blocks_sensitive_and_passes_safe_medium():
    """场景2：阶段2 block_sensitive - sensitive 阻断，safe/medium 放行。

    mock OBSERVE_ONLY=False, BLOCK_SENSITIVE=True, BLOCK_ALL=False。
    gate.apply 对 sensitive 工具阻断，对 safe/medium 工具放行。
    """
    resolver = _mode_resolver([
        _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, False),
        _flag(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, True),
        _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, False),
    ])

    mode = resolver.resolve_mode()
    assert mode["mode"] == POOL_GOVERNANCE_MODE_BLOCK_SENSITIVE
    assert mode["observe_only"] is False
    assert mode["block_sensitive"] is True

    ctx = resolver.build_governance_context()
    assert ctx["observe_only"] is False
    assert ctx["block_sensitive_only"] is True

    # gate.apply block_sensitive_only=True
    safe_tool = _tool("search")
    sensitive_tool = _tool("purge")
    medium_tool = _tool("update")
    gate = _gate([
        _PolicyQueryStub(one_result=_policy(risk_level="safe")),
        _PolicyQueryStub(one_result=_policy(
            risk_level="sensitive", require_confirmation=True,
        )),
        _PolicyQueryStub(one_result=_policy(risk_level="medium")),
    ])
    filtered_tools, audit = gate.apply(
        [safe_tool, sensitive_tool, medium_tool],
        tool_id_hints={
            "search": "api_tool:safe",
            "purge": "api_tool:sens",
            "update": "api_tool:med",
        },
        allow_confirmation=False,
        observe_only=False,
        block_sensitive_only=True,
    )

    # safe/medium 放行，sensitive 阻断
    assert filtered_tools == [safe_tool, medium_tool]
    assert audit["block_sensitive_only"] is True
    assert audit["output_tool_count"] == 2


def test_stage3_block_all_filters_all_risk_levels():
    """场景3：阶段3 block_all - 全量过滤。

    mock OBSERVE_ONLY=False, BLOCK_SENSITIVE=False, BLOCK_ALL=True。
    gate.apply 全量过滤（high+确认 → 阻断）。
    """
    resolver = _mode_resolver([
        _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, False),
        _flag(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, False),
        _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, True),
    ])

    mode = resolver.resolve_mode()
    assert mode["mode"] == POOL_GOVERNANCE_MODE_BLOCK_ALL
    assert mode["observe_only"] is False
    assert mode["block_sensitive"] is False

    ctx = resolver.build_governance_context()
    assert ctx["observe_only"] is False
    assert ctx["block_sensitive_only"] is False

    # gate.apply observe_only=False, block_sensitive_only=False（阶段3全量过滤）
    safe_tool = _tool("search")
    high_tool = _tool("delete")
    gate = _gate([
        _PolicyQueryStub(one_result=_policy(risk_level="safe")),
        _PolicyQueryStub(one_result=_policy(
            risk_level="high", require_confirmation=True,
        )),
    ])
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

    # high+确认 → 阻断，仅 safe 保留
    assert filtered_tools == [safe_tool]
    assert audit["block_sensitive_only"] is False


def test_priority_block_all_overrides_block_sensitive_and_observe_only():
    """场景4：优先级 - block_all > block_sensitive > observe_only。

    同时 enabled 多个开关，高优先级（block_all）生效。
    """
    resolver = _mode_resolver([
        _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, True),
        _flag(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, True),
        _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, True),
    ])

    mode = resolver.resolve_mode()

    # block_all 优先
    assert mode["mode"] == POOL_GOVERNANCE_MODE_BLOCK_ALL
    assert mode["observe_only"] is False
    assert mode["block_sensitive"] is False
    assert mode["block_all"] is True


def test_degrades_to_stage1_on_db_error():
    """场景5：降级 - 查询异常时降级为阶段1（observe_only=True）。"""
    resolver = GovernanceModeResolver(db=_DbStub(_SessionRaisesStub()))

    mode = resolver.resolve_mode()

    assert mode["mode"] == POOL_GOVERNANCE_MODE_OBSERVE_ONLY
    assert mode["observe_only"] is True
    assert mode["block_sensitive"] is False
    assert mode["block_all"] is False

    ctx = resolver.build_governance_context()
    assert ctx["observe_only"] is True


def test_build_governance_context_overrides_transparent_pass_through():
    """场景6：build_governance_context overrides 透传。

    build_governance_context(account_id="xxx", app_id="yyy") 返回的 context
    含 account_id/app_id。
    """
    resolver = _mode_resolver([
        _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, True),
    ])

    ctx = resolver.build_governance_context(
        account_id="account-xxx",
        app_id="app-yyy",
        agent_pool="primary",
        budget_level="high",
    )

    # 默认字段保留
    assert ctx["observe_only"] is True
    assert ctx["mode"] == POOL_GOVERNANCE_MODE_OBSERVE_ONLY
    # overrides 透传
    assert ctx["account_id"] == "account-xxx"
    assert ctx["app_id"] == "app-yyy"
    assert ctx["agent_pool"] == "primary"
    assert ctx["budget_level"] == "high"
