"""工具池治理修复的回归测试。

覆盖本轮巡检修复：
1. 风险等级枚举唯一事实源（RISK_LEVEL_VALUES / SENSITIVE_RISK_LEVEL_VALUES）一致性。
2. ToolPolicyFilter 对 dangerous 工具一律拒绝（不受 allow_confirmation 影响）。
3. Agent 非法 risk_level fail-closed 到最高档（不透传 safe 绕过风险过滤）。
4. AgentPolicyFilter 的 allow_confirmation 语义与 high 风险拦截。
5. CrossPoolAgentSubsetBuilder.build() 真正经过 AgentPolicyFilter（治理链路接通）。
"""
from types import SimpleNamespace
from uuid import UUID

from internal.entity.agent_entity import (
    AGENT_RISK_LEVEL_FALLBACK,
    AgentRiskLevel,
    normalize_agent_metadata,
)
from internal.entity.tool_inventory_entity import (
    RISK_LEVEL_VALUES,
    SENSITIVE_RISK_LEVEL_VALUES,
    RiskLevel,
    normalize_tool_metadata,
)
from internal.service.agent_pool_service import (
    AgentCandidateCollector,
    AgentPolicyFilter,
    CrossPoolAgentSubsetBuilder,
)
from internal.service.tool_inventory_service import ToolPolicyFilter

ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _candidate(tool_id="api_tool:1", *, risk_level="safe", **metadata_overrides):
    metadata = normalize_tool_metadata({"risk_level": risk_level, **metadata_overrides})
    return {"id": tool_id, "name": tool_id, "metadata": metadata}


# ------------------------------------------------------------------ #
#  1. 风险等级枚举唯一事实源                                           #
# ------------------------------------------------------------------ #

def test_risk_level_values_match_runtime_enum():
    """RISK_LEVEL_VALUES 必须与 RiskLevel 枚举逐值对应，且覆盖全部 6 档。"""
    assert RISK_LEVEL_VALUES == (
        "safe", "low", "medium", "high", "sensitive", "dangerous",
    )
    assert set(RISK_LEVEL_VALUES) == {item.value for item in RiskLevel}


def test_sensitive_risk_level_values_are_the_strong_tiers():
    """阶段2 阻断集合必须是 {sensitive, dangerous}。"""
    assert SENSITIVE_RISK_LEVEL_VALUES == frozenset({"sensitive", "dangerous"})


def test_admin_governance_risk_levels_share_single_source():
    """管理端 service / schema 的风险枚举必须来自同一常量（防止再次漂移）。"""
    from internal.schema.admin_tool_governance_schema import RISK_LEVELS as schema_levels
    from internal.service.admin_tool_governance_service import RISK_LEVELS as service_levels

    assert list(service_levels) == list(RISK_LEVEL_VALUES)
    assert list(schema_levels) == list(RISK_LEVEL_VALUES)
    # 历史脏值 critical 必须已不在枚举中
    assert "critical" not in service_levels


# ------------------------------------------------------------------ #
#  2. ToolPolicyFilter：dangerous 一律拒绝                             #
# ------------------------------------------------------------------ #

def test_dangerous_tool_is_rejected_even_with_confirmation():
    """dangerous 工具不可自动挂载——allow_confirmation=True 也不放行。"""
    result = ToolPolicyFilter().filter(
        [_candidate(risk_level="dangerous")],
        account_id=str(ACCOUNT_ID),
        allow_confirmation=True,
    )

    assert result["candidates"] == []
    assert result["filtered_out_tools"][0]["reason"] == "dangerous_tool_not_allowed"


def test_dangerous_tool_is_rejected_without_confirmation():
    result = ToolPolicyFilter().filter(
        [_candidate(risk_level="dangerous")],
        account_id=str(ACCOUNT_ID),
    )

    assert result["candidates"] == []
    assert result["filtered_out_tools"][0]["reason"] == "dangerous_tool_not_allowed"


def test_sensitive_tool_passes_when_confirmation_allowed():
    """sensitive 工具在获得确认后可挂载（与 dangerous 区分）。"""
    result = ToolPolicyFilter().filter(
        [_candidate(risk_level="sensitive", requires_confirmation=True)],
        account_id=str(ACCOUNT_ID),
        allow_confirmation=True,
    )

    assert len(result["candidates"]) == 1


def test_low_and_medium_risk_tools_pass():
    result = ToolPolicyFilter().filter(
        [
            _candidate("api_tool:low", risk_level="low"),
            _candidate("api_tool:medium", risk_level="medium"),
        ],
        account_id=str(ACCOUNT_ID),
    )

    assert {c["id"] for c in result["candidates"]} == {"api_tool:low", "api_tool:medium"}


# ------------------------------------------------------------------ #
#  3. Agent 非法风险值 fail-closed                                     #
# ------------------------------------------------------------------ #

def test_unknown_agent_risk_level_fails_closed_to_highest():
    """非法/高危语义值（如 dangerous）不得降级为 safe，必须落到最高档。"""
    metadata = normalize_agent_metadata({"risk_level": "dangerous"})

    assert metadata["risk_level"] == AGENT_RISK_LEVEL_FALLBACK
    assert metadata["risk_level"] == AgentRiskLevel.HIGH.value


def test_agent_risk_level_fallback_is_not_lowest():
    """兜底值不得是 safe（否则构成越权缺口）。"""
    assert AGENT_RISK_LEVEL_FALLBACK != AgentRiskLevel.SAFE.value


def test_valid_agent_risk_levels_are_preserved():
    for level in (AgentRiskLevel.SAFE, AgentRiskLevel.MEDIUM, AgentRiskLevel.HIGH):
        assert normalize_agent_metadata({"risk_level": level.value})["risk_level"] == level.value


# ------------------------------------------------------------------ #
#  4. AgentPolicyFilter：high 风险与 allow_confirmation                #
# ------------------------------------------------------------------ #

def _app(*, status="published", is_public=True, risk_level="safe", enabled=True):
    return SimpleNamespace(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="测试 Agent",
        icon="",
        description="",
        status=status,
        is_public=is_public,
        agent_metadata={"risk_level": risk_level, "enabled": enabled},
        normalized_agent_metadata=normalize_agent_metadata(
            {"risk_level": risk_level, "enabled": enabled}
        ),
    )


def _raw_candidate(app, source_scope="public"):
    return {"app": app, "source_scope": source_scope, "metadata": app.normalized_agent_metadata}


def test_high_risk_agent_rejected_without_confirmation():
    app = _app(risk_level="high")
    result = AgentPolicyFilter().filter([_raw_candidate(app)])

    assert result["candidates"] == []
    assert result["filtered_out_agents"][0]["reason"] == "risk_level_requires_confirmation"


def test_high_risk_agent_passes_with_confirmation():
    app = _app(risk_level="high")
    result = AgentPolicyFilter().filter([_raw_candidate(app)], allow_confirmation=True)

    assert len(result["candidates"]) == 1


# ------------------------------------------------------------------ #
#  5. build() 真正经过 AgentPolicyFilter（治理链路接通）               #
# ------------------------------------------------------------------ #

def test_build_routes_candidates_through_policy_filter():
    """CrossPoolAgentSubsetBuilder.build() 必须过滤掉 high 风险 Agent。

    历史实现直接序列化候选、完全绕过 AgentPolicyFilter，导致治理失效。
    """
    high_risk = _app(risk_level="high")
    safe_app = _app(risk_level="safe")
    safe_app.id = UUID("33333333-3333-3333-3333-333333333333")

    collector = SimpleNamespace(
        collect_raw=lambda _account_id: [_raw_candidate(high_risk), _raw_candidate(safe_app)]
    )
    builder = CrossPoolAgentSubsetBuilder(
        collector=collector,
        policy_filter=AgentPolicyFilter(),
    )

    result = builder.build(ACCOUNT_ID)

    names = [c["name"] for c in result["candidates"]]
    assert names == ["测试 Agent"]
    # high 风险 Agent 被过滤且带原因
    assert result["filtered_out_agents"][0]["reason"] == "risk_level_requires_confirmation"


# ------------------------------------------------------------------ #
#  5.1 collect_raw() 必须保留 app 对象（防止重复定义再次覆盖）          #
# ------------------------------------------------------------------ #

class _CollectorQueryStub:
    """最小查询桩：仅维持链式调用并返回预设行。"""

    def __init__(self, all_result=None):
        self._all_result = [] if all_result is None else all_result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def outerjoin(self, *args, **kwargs):
        return self

    def all(self):
        return self._all_result


class _CollectorSessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _CollectorQueryStub()


def test_collect_raw_must_preserve_app_object():
    """AgentCandidateCollector.collect_raw() 必须保留 app 对象。

    历史缺陷：collect_raw() 在类中被**重复定义**，后一个定义退化为 collect() 的
    简单转发（序列化结果不含 app 键），覆盖了保留 app 对象的正确实现。后果是
    build() 拿到的候选 `candidate.get("app")` 恒为 None，AgentPolicyFilter 因
    `if app is None: accepted.append(candidate)` 而**无条件放行全部候选**，
    pool_not_visible / risk_level / cost_level 等硬过滤全部静默失效。

    注意：本用例刻意使用**真实 collector**而非桩——既有用例用桩注入
    collect_raw 恰好掩盖了该缺陷，因此这里必须覆盖真实实现。

    内置候选（_builtin_candidates）按设计不含 app 键，由 AgentPolicyFilter 透传，
    因此这里只断言「App 候选」保留了 app 对象。
    """
    app = _app(risk_level="high")
    collector = AgentCandidateCollector(
        session=_CollectorSessionStub([_CollectorQueryStub([app])])
    )

    raw = collector.collect_raw(ACCOUNT_ID)

    app_candidates = [candidate for candidate in raw if candidate.get("app") is not None]
    assert len(app_candidates) == 1, "App 候选必须出现在 collect_raw() 结果中"
    assert app_candidates[0]["app"] is app, (
        "collect_raw() 必须保留 app 对象，否则 AgentPolicyFilter 会无条件放行全部候选"
    )


def test_collect_raw_feeds_policy_filter_end_to_end():
    """真实 collector → 真实 filter 端到端：high 风险 Agent 必须被拒。

    与 test_build_routes_candidates_through_policy_filter 的区别：该用例的桩
    collector 直接产出合规候选，无法发现 collect_raw 被覆盖；本用例串起真实
    链路，使「治理链路静默断开」可被测试捕获。
    """
    app = _app(risk_level="high")
    collector = AgentCandidateCollector(
        session=_CollectorSessionStub([_CollectorQueryStub([app])])
    )

    result = AgentPolicyFilter().filter(collector.collect_raw(ACCOUNT_ID))

    # high 风险 App 必须被过滤且带原因（内置候选无 app 键，按设计透传）
    assert result["filtered_out_agents"][0]["reason"] == "risk_level_requires_confirmation"
    assert all(
        candidate.get("app") is not app for candidate in result["candidates"]
    ), "被拒的 high 风险 App 不得出现在通过列表中"


def test_build_subset_forwards_allow_confirmation():
    """build_subset 必须把 allow_confirmation 透传给 policy_filter。"""
    high_risk = _app(risk_level="high")
    builder = CrossPoolAgentSubsetBuilder(
        collector=SimpleNamespace(),
        policy_filter=AgentPolicyFilter(),
    )

    result = builder.build_subset([_raw_candidate(high_risk)], allow_confirmation=True)

    assert len(result["candidates"]) == 1
    assert result["filtered_out_agents"] == []
