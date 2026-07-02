from datetime import datetime
from uuid import uuid4

from internal.entity.agent_entity import DEFAULT_AGENT_METADATA, normalize_agent_metadata
from internal.entity.agent_pool_entity import AgentSubPoolRegistry
from internal.model.app import App, AppAssignment
from internal.service.agent_pool_service import (
    AgentCandidateCollector,
    AgentPolicyFilter,
    AgentRanker,
    CrossPoolAgentSubsetBuilder,
)


class _QueryStub:
    def __init__(self, *, all_result=None):
        self._all_result = [] if all_result is None else all_result
        self.filters = []
        self.order_by_args = []
        self.outerjoin_args = []

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args):
        self.order_by_args.append(args)
        return self

    def outerjoin(self, *args, **kwargs):
        # AgentCandidateCollector.collect() 现在通过 outerjoin LEFT JOIN AgentPoolConfig；
        # stub 不模拟真实 JOIN，仅维持链式调用并把结果（含 App 对象或 (App, AgentPoolConfig) 元组）原样返回。
        self.outerjoin_args.append((args, kwargs))
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


def _app(**kwargs):
    defaults = {
        "id": uuid4(),
        "account_id": uuid4(),
        "name": "客服 Agent",
        "icon": "🤖",
        "description": "处理客服问题",
        "status": "published",
        "is_public": False,
        "agent_metadata": {
            **DEFAULT_AGENT_METADATA,
            "primary_pool": "customer_support",
            "secondary_pools": ["sales"],
            "capabilities": ["faq", "refund"],
            "task_types": ["customer_service"],
            "model_tier": "standard",
            "cost_level": "medium",
            "routing_priority": 20,
            "allowed_tool_categories": ["knowledge", "ticket"],
        },
        "published_at": datetime(2030, 1, 1, 0, 0, 0),
    }
    defaults.update(kwargs)
    return App(**defaults)


def _assignment(app):
    assignment = AppAssignment(
        id=uuid4(),
        app_id=app.id,
        account_id=uuid4(),
        assigned_by=uuid4(),
        status="active",
        assigned_at=datetime(2030, 1, 1, 0, 0, 0),
    )
    assignment.app = app
    return assignment


def test_default_agent_metadata_should_be_stable_when_app_missing_metadata():
    app = _app(agent_metadata=None)

    assert app.normalized_agent_metadata == DEFAULT_AGENT_METADATA


def test_phase2_default_agent_metadata_should_include_routing_fields():
    metadata = normalize_agent_metadata(None)

    assert metadata == {
        "primary_pool": "general",
        "secondary_pools": [],
        "capabilities": [],
        "task_types": [],
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "risk_level": "safe",
        "model_tier": "standard",
        "model_id": "",
        "key_policy": "default",
        "cost_level": "medium",
        "routing_priority": 50,
        "allowed_tool_categories": [],
        "quality_score": 0.5,
        "success_rate": 0.0,
        "latency_p95": 0,
        "max_context_tokens": 0,
        "enabled": True,
    }


def test_agent_metadata_should_normalize_phase2_boundaries():
    metadata = normalize_agent_metadata(
        {
            "risk_level": "dangerous",
            "routing_priority": 2000,
            "quality_score": 5,
            "success_rate": -1,
            "latency_p95": -100,
            "max_context_tokens": "4096",
            "enabled": "false",
            "input_modalities": ["text", "image", "text", 123],
            "output_modalities": ["text", "", None],
        }
    )

    assert metadata["risk_level"] == "safe"
    assert metadata["routing_priority"] == 1000
    assert metadata["quality_score"] == 1.0
    assert metadata["success_rate"] == 0.0
    assert metadata["latency_p95"] == 0
    assert metadata["max_context_tokens"] == 4096
    assert metadata["enabled"] is False
    assert metadata["input_modalities"] == ["text", "image"]
    assert metadata["output_modalities"] == ["text"]


def test_agent_sub_pool_registry_should_return_builtin_pools():
    registry = AgentSubPoolRegistry()

    pools = registry.list_pools()

    assert [pool["name"] for pool in pools] == [
        "general",
        "coding",
        "office",
        "data",
        "research",
        "customer_service",
        "internal_admin",
    ]


def test_agent_sub_pool_registry_should_keep_visibility_defaults():
    registry = AgentSubPoolRegistry()

    general = registry.get_pool("general")
    internal_admin = registry.get_pool("internal_admin")

    assert general["label"] == "通用"
    assert general["visible_to_user"] is True
    assert internal_admin["visible_to_user"] is False


def test_agent_sub_pool_registry_should_fallback_unknown_pool_to_general():
    registry = AgentSubPoolRegistry()

    pool = registry.get_pool("unknown_pool")

    assert pool["name"] == "general"
    assert registry.normalize_pool_name("unknown_pool") == "general"


def test_candidate_collector_should_merge_public_and_assigned_apps_without_duplicates():
    account_id = uuid4()
    public_app = _app(name="公开客服", is_public=True)
    assigned_app = _app(name="分配客服", is_public=False)
    duplicate_assignment = _assignment(public_app)
    assigned_assignment = _assignment(assigned_app)
    collector = AgentCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[public_app]),
            _QueryStub(all_result=[duplicate_assignment, assigned_assignment]),
        ])
    )

    result = collector.collect(account_id)

    app_candidates = [candidate for candidate in result if candidate["source_type"] == "app"]
    assert [candidate["id"] for candidate in app_candidates] == [
        str(public_app.id),
        str(assigned_app.id),
    ]
    assert app_candidates[0]["source_scope"] == "public"
    assert app_candidates[1]["source_scope"] == "assigned"
    assert app_candidates[0]["metadata"]["primary_pool"] == "customer_support"


def test_candidate_collector_should_include_own_apps_and_builtin_agents():
    account_id = uuid4()
    own_app = _app(name="我的编程 Agent", account_id=account_id, is_public=False)
    collector = AgentCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[own_app]),
        ])
    )

    result = collector.collect(account_id)

    assert result[0]["id"] == str(own_app.id)
    assert result[0]["source_scope"] == "own"
    assert result[0]["source_type"] == "app"
    assert result[0]["app_id"] == str(own_app.id)
    assert result[0]["visibility"] == "private"
    assert {candidate["agent_id"] for candidate in result} >= {
        "builtin:lightweight",
        "builtin:strong_reasoning",
        "builtin:deep_thinking",
    }


def test_candidate_collector_should_exclude_draft_and_disabled_apps():
    account_id = uuid4()
    draft = _app(name="草稿", status="draft", is_public=True)
    disabled = _app(
        name="禁用",
        is_public=True,
        agent_metadata={**DEFAULT_AGENT_METADATA, "enabled": False},
    )
    active = _app(name="可用", is_public=True)
    collector = AgentCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[draft, disabled, active]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
        ])
    )

    result = collector.collect(account_id)

    app_names = [
        candidate["name"] for candidate in result if candidate["source_type"] == "app"
    ]
    assert app_names == ["可用"]


def test_candidate_collector_should_recall_by_primary_pool():
    account_id = uuid4()
    coding = _app(
        name="编程 Agent",
        is_public=True,
        agent_metadata={**DEFAULT_AGENT_METADATA, "primary_pool": "coding"},
    )
    office = _app(
        name="办公 Agent",
        is_public=True,
        agent_metadata={**DEFAULT_AGENT_METADATA, "primary_pool": "office"},
    )
    collector = AgentCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[coding, office]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
        ])
    )

    result = collector.collect_by_pools(account_id, ["coding"], query="写前端代码")

    assert [candidate["name"] for candidate in result] == ["编程 Agent"]
    assert result[0]["match_reason"] == "primary_pool:coding"
    assert result[0]["semantic_score"] == 1.0


def test_candidate_collector_should_recall_by_secondary_pool_and_capability():
    account_id = uuid4()
    multi_pool = _app(
        name="图文 Agent",
        is_public=True,
        agent_metadata={
            **DEFAULT_AGENT_METADATA,
            "primary_pool": "office",
            "secondary_pools": ["coding"],
            "capabilities": ["frontend"],
        },
    )
    collector = AgentCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[multi_pool]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
        ])
    )

    result = collector.collect_by_pools(account_id, ["coding"], query="前端页面")

    assert [candidate["name"] for candidate in result] == ["图文 Agent"]
    assert result[0]["match_reason"] == "capability:frontend"
    assert result[0]["semantic_score"] == 0.85


def test_candidate_collector_should_use_general_as_backup():
    account_id = uuid4()
    general = _app(
        name="通用 Agent",
        is_public=True,
        agent_metadata={**DEFAULT_AGENT_METADATA, "primary_pool": "general"},
    )
    collector = AgentCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[general]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
        ])
    )

    result = collector.collect_by_pools(account_id, ["coding"], query="写前端代码")

    assert [candidate["name"] for candidate in result] == ["通用 Agent"]
    assert result[0]["match_reason"] == "backup_pool:general"
    assert result[0]["semantic_score"] == 0.2


def test_candidate_collector_should_deduplicate_and_keep_highest_signal():
    account_id = uuid4()
    agent = _app(
        name="全能前端 Agent",
        is_public=True,
        agent_metadata={
            **DEFAULT_AGENT_METADATA,
            "primary_pool": "coding",
            "secondary_pools": ["office"],
            "capabilities": ["frontend"],
            "task_types": ["frontend"],
        },
    )
    collector = AgentCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[agent]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
        ])
    )

    result = collector.collect_by_pools(account_id, ["coding", "office"], query="前端")

    assert len(result) == 1
    assert result[0]["name"] == "全能前端 Agent"
    assert result[0]["match_reason"] == "primary_pool:coding"
    assert result[0]["semantic_score"] == 1.0


def test_policy_filter_should_exclude_unpublished_and_unassigned_candidates():
    published = _app(name="可用", status="published", is_public=True)
    draft = _app(name="草稿", status="draft", is_public=True)
    private_unassigned = _app(name="未授权", status="published", is_public=False)
    candidates = [
        {"app": published, "source_scope": "public", "metadata": published.normalized_agent_metadata},
        {"app": draft, "source_scope": "public", "metadata": draft.normalized_agent_metadata},
        {"app": private_unassigned, "source_scope": "private", "metadata": private_unassigned.normalized_agent_metadata},
    ]

    result = AgentPolicyFilter().filter(candidates)

    assert [candidate["name"] for candidate in result["candidates"]] == ["可用"]
    assert result["filtered_out_agents"] == [
        {"id": str(draft.id), "name": "草稿", "reason": "app_not_published"},
        {"id": str(private_unassigned.id), "name": "未授权", "reason": "app_not_authorized"},
    ]


def test_policy_filter_should_explain_phase2_policy_rejections():
    account_id = uuid4()
    private_app = _app(name="私有", is_public=False)
    internal_admin = _app(
        name="审计",
        is_public=True,
        agent_metadata={**DEFAULT_AGENT_METADATA, "primary_pool": "internal_admin"},
    )
    disabled = _app(
        name="禁用",
        is_public=True,
        agent_metadata={**DEFAULT_AGENT_METADATA, "enabled": False},
    )
    high_risk = _app(
        name="高风险",
        is_public=True,
        agent_metadata={**DEFAULT_AGENT_METADATA, "risk_level": "high"},
    )
    high_cost = _app(
        name="高成本",
        is_public=True,
        agent_metadata={**DEFAULT_AGENT_METADATA, "cost_level": "high"},
    )
    image_unsupported = _app(
        name="不支持图片",
        is_public=True,
        agent_metadata={
            **DEFAULT_AGENT_METADATA,
            "input_modalities": ["text"],
            "cost_level": "low",
        },
    )
    tool_denied = _app(
        name="工具受限",
        is_public=True,
        agent_metadata={
            **DEFAULT_AGENT_METADATA,
            "input_modalities": ["text", "image"],
            "cost_level": "low",
            "allowed_tool_categories": ["knowledge"],
        },
    )
    candidates = [
        {"app": private_app, "source_scope": "private", "metadata": private_app.normalized_agent_metadata},
        {"app": internal_admin, "source_scope": "public", "metadata": internal_admin.normalized_agent_metadata},
        {"app": disabled, "source_scope": "public", "metadata": disabled.normalized_agent_metadata},
        {"app": high_risk, "source_scope": "public", "metadata": high_risk.normalized_agent_metadata},
        {"app": high_cost, "source_scope": "public", "metadata": high_cost.normalized_agent_metadata},
        {"app": image_unsupported, "source_scope": "public", "metadata": image_unsupported.normalized_agent_metadata},
        {"app": tool_denied, "source_scope": "public", "metadata": tool_denied.normalized_agent_metadata},
    ]

    result = AgentPolicyFilter().filter(
        candidates,
        account_id=account_id,
        requested_pool="internal_admin",
        input_modalities=["image"],
        budget_level="low",
        required_tool_categories=["browser"],
    )

    assert [item["reason"] for item in result["filtered_out_agents"]] == [
        "app_not_authorized",
        "pool_not_visible",
        "agent_disabled",
        "risk_level_requires_confirmation",
        "cost_level_exceeds_budget",
        "input_modality_not_supported",
        "tool_category_not_allowed",
    ]


def test_policy_filter_should_accept_candidate_when_phase2_policy_allows():
    app = _app(
        name="可用图片 Agent",
        is_public=True,
        agent_metadata={
            **DEFAULT_AGENT_METADATA,
            "primary_pool": "office",
            "input_modalities": ["text", "image"],
            "allowed_tool_categories": ["browser"],
            "cost_level": "low",
        },
    )

    result = AgentPolicyFilter().filter(
        [{"app": app, "source_scope": "public", "metadata": app.normalized_agent_metadata}],
        requested_pool="office",
        input_modalities=["image"],
        budget_level="low",
        required_tool_categories=["browser"],
    )

    assert result["filtered_out_agents"] == []
    assert result["candidates"][0]["name"] == "可用图片 Agent"


def test_agent_ranker_should_rank_by_capability_and_semantic_score():
    high = {
        "agent_id": "agent-high",
        "name": "高匹配",
        "semantic_score": 0.9,
        "metadata": {**DEFAULT_AGENT_METADATA, "capabilities": ["frontend"]},
    }
    low = {
        "agent_id": "agent-low",
        "name": "低匹配",
        "semantic_score": 0.4,
        "metadata": {**DEFAULT_AGENT_METADATA, "capabilities": []},
    }

    result = AgentRanker().rank([low, high], required_capabilities=["frontend"])

    assert [candidate["agent_id"] for candidate in result] == ["agent-high", "agent-low"]
    assert result[0]["score_breakdown"]["capability_score"] == 1.0
    assert result[0]["score"] > result[1]["score"]


def test_agent_ranker_should_penalize_high_cost_and_high_latency():
    cheap = {
        "agent_id": "cheap",
        "name": "低成本",
        "semantic_score": 0.8,
        "metadata": {
            **DEFAULT_AGENT_METADATA,
            "cost_level": "low",
            "latency_p95": 100,
            "quality_score": 0.8,
        },
    }
    expensive = {
        "agent_id": "expensive",
        "name": "高成本",
        "semantic_score": 0.8,
        "metadata": {
            **DEFAULT_AGENT_METADATA,
            "cost_level": "high",
            "latency_p95": 3000,
            "quality_score": 0.8,
        },
    }

    result = AgentRanker().rank([expensive, cheap])

    assert [candidate["agent_id"] for candidate in result] == ["cheap", "expensive"]
    assert result[0]["score_breakdown"]["cost_score"] == 1.0
    assert result[1]["score_breakdown"]["cost_score"] == 0.2


def test_agent_ranker_should_use_priority_and_name_as_stable_tiebreaker():
    beta = {
        "agent_id": "beta",
        "name": "Beta",
        "semantic_score": 0.5,
        "metadata": {**DEFAULT_AGENT_METADATA, "routing_priority": 100},
    }
    alpha = {
        "agent_id": "alpha",
        "name": "Alpha",
        "semantic_score": 0.5,
        "metadata": {**DEFAULT_AGENT_METADATA, "routing_priority": 100},
    }

    result = AgentRanker().rank([beta, alpha])

    assert [candidate["agent_id"] for candidate in result] == ["alpha", "beta"]


def test_cross_pool_subset_builder_should_output_selected_backup_and_filtered():
    selected = {
        "agent_id": "office-a",
        "name": "办公 A",
        "pool": "office",
        "metadata": {**DEFAULT_AGENT_METADATA, "primary_pool": "office"},
        "semantic_score": 0.9,
    }
    selected_2 = {
        "agent_id": "coding-a",
        "name": "编程 A",
        "pool": "coding",
        "metadata": {**DEFAULT_AGENT_METADATA, "primary_pool": "coding"},
        "semantic_score": 0.9,
    }
    backup = {
        "agent_id": "general-a",
        "name": "通用 A",
        "pool": "general",
        "metadata": {**DEFAULT_AGENT_METADATA, "primary_pool": "general"},
        "semantic_score": 0.2,
    }
    filtered = {"agent_id": "draft-a", "name": "草稿", "reason": "app_not_published"}
    builder = CrossPoolAgentSubsetBuilder(
        collector=None,
        policy_filter=None,
        ranker=AgentRanker(),
    )

    result = builder.build_subset_from_candidates(
        [selected, selected_2, backup],
        matched_pools=["office", "coding"],
        filtered_out_agents=[filtered],
        max_agent_count=2,
        per_pool_limit=1,
    )

    assert [item["agent_id"] for item in result["selected_agents"]] == [
        "office-a",
        "coding-a",
    ]
    assert [item["agent_id"] for item in result["backup_agents"]] == ["general-a"]
    assert result["filtered_out_agents"] == [filtered]
    assert result["matched_agent_pools"] == ["office", "coding"]
    assert result["selection_reason"] == "matched pools: office,coding"


def test_cross_pool_subset_builder_should_respect_max_agent_count():
    high = _app(name="高优先级", agent_metadata={**DEFAULT_AGENT_METADATA, "primary_pool": "sales", "routing_priority": 100})
    low = _app(name="低优先级", agent_metadata={**DEFAULT_AGENT_METADATA, "primary_pool": "sales", "routing_priority": 10})
    other = _app(name="其它池", agent_metadata={**DEFAULT_AGENT_METADATA, "primary_pool": "support", "routing_priority": 200})
    builder = CrossPoolAgentSubsetBuilder(
        collector=AgentCandidateCollector(session=_SessionStub()),
        policy_filter=AgentPolicyFilter(),
    )

    result = builder.build_subset(
        [
            {"app": low, "source_scope": "public", "metadata": low.normalized_agent_metadata},
            {"app": high, "source_scope": "public", "metadata": high.normalized_agent_metadata},
            {"app": other, "source_scope": "public", "metadata": other.normalized_agent_metadata},
        ],
        primary_pool="sales",
    )

    assert [candidate["name"] for candidate in result["candidates"]] == ["高优先级", "低优先级"]
