from types import SimpleNamespace
from uuid import uuid4

from internal.entity.tool_inventory_entity import (
    DEFAULT_TOOL_METADATA,
    RiskLevel,
    ToolSourceType,
    normalize_tool_metadata,
)
from internal.entity.tool_pool_entity import ToolSubPoolRegistry
from internal.service.tool_inventory_service import (
    ToolCandidateCollector,
    ToolPolicyFilter,
    ToolRanker,
    CrossPoolToolSubsetBuilder,
)


class _QueryStub:
    def __init__(self, *, all_result=None):
        self._all_result = [] if all_result is None else all_result

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._all_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


def test_normalize_tool_metadata_should_fill_defaults_and_clamp_risk():
    metadata = normalize_tool_metadata({"tool_pool": "web", "risk_level": "danger", "cost_level": "low"})

    assert metadata == {**DEFAULT_TOOL_METADATA, "tool_pool": "web", "cost_level": "low"}


def test_default_tool_metadata_should_include_phase3_fields():
    metadata = normalize_tool_metadata(None)

    assert metadata == {
        "tool_pool": "general",
        "tool_tags": [],
        "capabilities": [],
        "risk_level": "medium",
        "permission_scope": "user",
        "cost_level": "medium",
        "health_status": "healthy",
        "success_rate": 0.0,
        "avg_latency": 0,
        "owner": "system",
        "knowledge_scope": "none",
        "tenant_scope": "default",
        "user_scope": "owner",
        "requires_confirmation": False,
        "allowed_agent_pools": [],
        "enabled": True,
    }


def test_tool_metadata_should_normalize_phase3_boundaries():
    metadata = normalize_tool_metadata({
        "risk_level": "dangerous",
        "permission_scope": "invalid",
        "health_status": "broken",
        "success_rate": 2,
        "avg_latency": -100,
        "enabled": "false",
        "capabilities": ["search", "search", 123],
    })

    assert metadata["risk_level"] == "dangerous"
    assert metadata["permission_scope"] == "user"
    assert metadata["health_status"] == "healthy"
    assert metadata["success_rate"] == 1.0
    assert metadata["avg_latency"] == 0
    assert metadata["enabled"] is False
    assert metadata["capabilities"] == ["search"]


def test_tool_sub_pool_registry_should_return_builtin_pools():
    registry = ToolSubPoolRegistry()

    pools = registry.list_pools()

    assert [pool["name"] for pool in pools] == [
        "general",
        "mcp",
        "api",
        "builtin",
        "knowledge",
        "memory",
        "external_data",
        "system_admin",
    ]


def test_tool_sub_pool_registry_should_keep_visibility_defaults():
    registry = ToolSubPoolRegistry()

    general = registry.get_pool("general")
    system_admin = registry.get_pool("system_admin")

    assert general["visible_to_user"] is True
    assert system_admin["visible_to_user"] is False


def test_tool_sub_pool_registry_should_fallback_unknown_pool_to_general():
    registry = ToolSubPoolRegistry()

    assert registry.get_pool("unknown")["name"] == "general"
    assert registry.normalize_pool_name("unknown") == "general"


def test_candidate_collector_should_merge_api_mcp_builtin_and_knowledge_tools():
    account_id = uuid4()
    api_tool = SimpleNamespace(
        id=uuid4(),
        name="search_orders",
        description="查询订单",
        provider=SimpleNamespace(id=uuid4(), name="ERP", icon="", description="ERP", headers=[]),
        parameters=[],
    )
    mcp_provider = SimpleNamespace(
        id=uuid4(),
        name="github",
        label="GitHub",
        description="GitHub MCP",
        category="code",
        tool_names=["search_repositories"],
        is_public=True,
    )
    knowledge_base = SimpleNamespace(
        id=uuid4(),
        name="系统知识库",
        description="系统资料",
        knowledge_scope="system",
        owner_account_id=None,
        enabled=True,
    )
    builtin_service = SimpleNamespace(
        get_builtin_tools=lambda: [
            {
                "name": "weather",
                "label": "天气",
                "description": "天气工具",
                "category": "search",
                "tools": [{"name": "get_weather", "description": "查天气", "inputs": []}],
            }
        ]
    )
    collector = ToolCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[api_tool]),
            _QueryStub(all_result=[mcp_provider]),
            _QueryStub(all_result=[knowledge_base]),
        ]),
        builtin_tool_service=builtin_service,
    )

    result = collector.collect(account_id)

    assert [item["source_type"] for item in result] == [
        ToolSourceType.API.value,
        ToolSourceType.MCP.value,
        ToolSourceType.BUILTIN.value,
        ToolSourceType.KNOWLEDGE.value,
    ]
    assert result[0]["name"] == "search_orders"
    assert result[0]["provider_id"] == str(api_tool.provider.id)
    assert result[0]["provider_name"] == "ERP"
    assert result[0]["visibility"] == "private"
    assert result[0]["enabled"] is True
    assert result[0]["metadata"]["tool_pool"] == "api"
    assert result[0]["metadata"]["permission_scope"] == "user"
    assert result[1]["provider_name"] == "GitHub"
    assert result[1]["visibility"] == "public"
    assert result[1]["metadata"]["tool_pool"] == "mcp"
    assert result[1]["metadata"]["permission_scope"] == "public"
    assert result[2]["name"] == "get_weather"
    assert result[2]["visibility"] == "system"
    assert result[2]["metadata"]["tool_pool"] == "builtin"
    assert result[2]["metadata"]["owner"] == "system"
    assert result[3]["metadata"]["tool_pool"] == "knowledge"
    assert result[3]["metadata"]["knowledge_scope"] == "system"


def test_candidate_collector_should_exclude_disabled_and_unhealthy_tools():
    account_id = uuid4()
    disabled_api_tool = SimpleNamespace(
        id=uuid4(),
        name="disabled_api",
        description="禁用 API",
        provider=SimpleNamespace(id=uuid4(), name="ERP"),
        parameters=[],
        metadata={"enabled": False},
    )
    unhealthy_mcp_provider = SimpleNamespace(
        id=uuid4(),
        name="broken_mcp",
        label="Broken MCP",
        description="异常 MCP",
        category="mcp",
        tool_names=["broken_tool"],
        is_public=True,
        metadata={"health_status": "unhealthy"},
    )
    disabled_knowledge_base = SimpleNamespace(
        id=uuid4(),
        name="禁用知识库",
        description="禁用",
        knowledge_scope="system",
        owner_account_id=None,
        enabled=False,
    )
    builtin_service = SimpleNamespace(
        get_builtin_tools=lambda: [
            {
                "name": "unsafe",
                "label": "不可用",
                "description": "不可用工具",
                "category": "builtin",
                "metadata": {"enabled": False},
                "tools": [{"name": "disabled_builtin", "description": "禁用", "inputs": []}],
            }
        ]
    )
    collector = ToolCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[disabled_api_tool]),
            _QueryStub(all_result=[unhealthy_mcp_provider]),
            _QueryStub(all_result=[disabled_knowledge_base]),
        ]),
        builtin_tool_service=builtin_service,
    )

    assert collector.collect(account_id) == []


def test_candidate_collector_should_collect_external_data_tools():
    account_id = uuid4()
    external_data_source = SimpleNamespace(
        id=uuid4(),
        source_type="notion",
        source_name="我的Notion",
        knowledge_base_id=uuid4(),
        owner_account_id=account_id,
        authorization_status="granted",
    )
    builtin_service = SimpleNamespace(get_builtin_tools=lambda: [])
    collector = ToolCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[external_data_source]),
        ]),
        builtin_tool_service=builtin_service,
    )

    result = collector.collect(account_id)

    external_candidates = [
        c for c in result if c["metadata"]["tool_pool"] == "external_data"
    ]
    assert len(external_candidates) == 1
    candidate = external_candidates[0]
    assert candidate["name"] == "external_data_retrieval"
    assert candidate["metadata"]["risk_level"] == RiskLevel.LOW.value
    assert candidate["metadata"]["tool_pool"] == "external_data"
    assert candidate["provider_name"] == "我的Notion"


def test_candidate_collector_should_skip_external_data_without_knowledge_base():
    account_id = uuid4()
    external_data_source = SimpleNamespace(
        id=uuid4(),
        source_type="github",
        source_name="我的GitHub",
        knowledge_base_id=None,
        owner_account_id=account_id,
        authorization_status="granted",
    )
    builtin_service = SimpleNamespace(get_builtin_tools=lambda: [])
    collector = ToolCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[external_data_source]),
        ]),
        builtin_tool_service=builtin_service,
    )

    result = collector.collect(account_id)

    assert [
        c for c in result if c["metadata"]["tool_pool"] == "external_data"
    ] == []


def _candidate(name: str, metadata: dict) -> dict:
    return {"id": name, "name": name, "metadata": normalize_tool_metadata(metadata)}


def test_policy_filter_should_return_phase3_rejection_reasons():
    candidates = [
        _candidate("disabled", {"enabled": False}),
        _candidate("unhealthy", {"health_status": "unhealthy"}),
        _candidate(
            "private",
            {"permission_scope": "user", "user_scope": "owner", "owner": "other"},
        ),
        _candidate("system", {"permission_scope": "system"}),
        _candidate(
            "knowledge",
            {"tool_pool": "knowledge", "user_scope": "owner", "owner": "other"},
        ),
        _candidate("high-risk", {"risk_level": "high", "requires_confirmation": True}),
        _candidate("high-cost", {"cost_level": "high"}),
        _candidate("pool-denied", {"allowed_agent_pools": ["coding"], "cost_level": "low"}),
    ]

    result = ToolPolicyFilter().filter(
        candidates,
        account_id="current",
        agent_pool="office",
        budget_level="low",
        allow_confirmation=False,
    )

    assert [item["reason"] for item in result["filtered_out_tools"]] == [
        "tool_disabled",
        "tool_unhealthy",
        "user_scope_denied",
        "permission_scope_denied",
        "knowledge_scope_denied",
        "high_risk_requires_confirmation",
        "cost_level_exceeds_budget",
        "agent_pool_not_allowed",
    ]
    assert result["candidates"] == []


def test_policy_filter_should_accept_allowed_phase3_candidate():
    candidate = _candidate(
        "browser",
        {
            "tool_pool": "mcp",
            "risk_level": "medium",
            "cost_level": "low",
            "allowed_agent_pools": ["office"],
            "permission_scope": "user",
            "owner": "current",
        },
    )

    result = ToolPolicyFilter().filter(
        [candidate],
        account_id="current",
        agent_pool="office",
        budget_level="low",
        allow_confirmation=False,
    )

    assert result["filtered_out_tools"] == []
    assert result["candidates"][0]["id"] == "browser"


def test_policy_filter_should_exclude_high_risk_when_confirmation_not_allowed():
    safe_tool = {
        "id": str(uuid4()),
        "name": "search",
        "metadata": normalize_tool_metadata({"risk_level": RiskLevel.SAFE.value}),
    }
    high_risk_tool = {
        "id": str(uuid4()),
        "name": "delete_user",
        "metadata": normalize_tool_metadata({"risk_level": RiskLevel.HIGH.value, "requires_confirmation": True}),
    }

    result = ToolPolicyFilter().filter([safe_tool, high_risk_tool], allow_confirmation=False)

    assert [item["name"] for item in result["candidates"]] == ["search"]
    assert result["filtered_out_tools"] == [
        {"id": high_risk_tool["id"], "name": "delete_user", "reason": "high_risk_requires_confirmation"}
    ]


def test_tool_ranker_should_rank_by_capability_success_health_cost_and_latency():
    fast = _candidate(
        "fast",
        {
            "capabilities": ["search"],
            "success_rate": 0.9,
            "health_status": "healthy",
            "cost_level": "low",
            "avg_latency": 100,
        },
    )
    slow = _candidate(
        "slow",
        {
            "capabilities": [],
            "success_rate": 0.5,
            "health_status": "degraded",
            "cost_level": "high",
            "avg_latency": 3000,
        },
    )

    result = ToolRanker().rank([slow, fast], required_capabilities=["search"])

    assert [item["id"] for item in result] == ["fast", "slow"]
    assert result[0]["score_breakdown"]["capability_score"] == 1.0
    assert result[0]["score"] > result[1]["score"]


def test_subset_builder_should_output_selected_backup_and_filtered_tools():
    selected = _candidate(
        "selected",
        {
            "tool_pool": "knowledge",
            "capabilities": ["search"],
            "success_rate": 0.9,
            "cost_level": "low",
        },
    )
    backup = _candidate(
        "backup",
        {
            "tool_pool": "knowledge",
            "capabilities": ["search"],
            "success_rate": 0.7,
            "cost_level": "low",
        },
    )
    filtered = {"id": "unsafe", "name": "unsafe", "reason": "tool_unhealthy"}
    builder = CrossPoolToolSubsetBuilder(
        collector=ToolCandidateCollector(
            session=_SessionStub(),
            builtin_tool_service=SimpleNamespace(get_builtin_tools=lambda: []),
        ),
        policy_filter=ToolPolicyFilter(),
    )

    result = builder.build_ranked_subset(
        [backup, selected],
        filtered_out_tools=[filtered],
        required_capabilities=["search"],
        max_tool_count=1,
    )

    assert [item["id"] for item in result["selected_tools"]] == ["selected"]
    assert [item["id"] for item in result["backup_tools"]] == ["backup"]
    assert result["filtered_out_tools"] == [filtered]
    assert result["selection_reason"] == "ranked_by_capability_success_health_cost_latency"


def test_subset_builder_should_filter_by_pool_and_allowed_agent_pool():
    tools = [
        {
            "id": str(uuid4()),
            "name": "知识检索",
            "metadata": normalize_tool_metadata({"tool_pool": "knowledge", "allowed_agent_pools": ["support"]}),
        },
        {
            "id": str(uuid4()),
            "name": "代码搜索",
            "metadata": normalize_tool_metadata({"tool_pool": "code", "allowed_agent_pools": ["dev"]}),
        },
    ]
    builder = CrossPoolToolSubsetBuilder(
        collector=ToolCandidateCollector(session=_SessionStub(), builtin_tool_service=SimpleNamespace(get_builtin_tools=lambda: [])),
        policy_filter=ToolPolicyFilter(),
    )

    result = builder.build_subset(tools, tool_pool="knowledge", agent_pool="support")

    assert [item["name"] for item in result["candidates"]] == ["知识检索"]
    assert result["filtered_out_tools"] == []
