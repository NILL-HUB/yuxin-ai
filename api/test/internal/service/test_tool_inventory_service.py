from types import SimpleNamespace
from uuid import uuid4

from internal.entity.tool_inventory_entity import RiskLevel, ToolSourceType, normalize_tool_metadata
from internal.service.tool_inventory_service import ToolCandidateCollector, ToolPolicyFilter, ToolSubsetBuilder


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

    assert metadata == {
        "tool_pool": "web",
        "tool_tags": [],
        "capabilities": [],
        "risk_level": RiskLevel.MEDIUM.value,
        "cost_level": "low",
        "requires_confirmation": False,
        "allowed_agent_pools": [],
    }


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
    assert result[1]["provider_name"] == "GitHub"
    assert result[2]["name"] == "get_weather"
    assert result[3]["metadata"]["tool_pool"] == "knowledge"


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
    builder = ToolSubsetBuilder(
        collector=ToolCandidateCollector(session=_SessionStub(), builtin_tool_service=SimpleNamespace(get_builtin_tools=lambda: [])),
        policy_filter=ToolPolicyFilter(),
    )

    result = builder.build_subset(tools, tool_pool="knowledge", agent_pool="support")

    assert [item["name"] for item in result["candidates"]] == ["知识检索"]
    assert result["filtered_out_tools"] == []
