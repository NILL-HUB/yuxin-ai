from datetime import datetime
from uuid import uuid4

from internal.entity.agent_entity import DEFAULT_AGENT_METADATA
from internal.model.app import App, AppAssignment
from internal.service.agent_pool_service import AgentCandidateCollector, AgentPolicyFilter, CrossPoolAgentSubsetBuilder


class _QueryStub:
    def __init__(self, *, all_result=None):
        self._all_result = [] if all_result is None else all_result
        self.filters = []
        self.order_by_args = []

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args):
        self.order_by_args.append(args)
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
            "model_tier": "balanced",
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

    assert [candidate["id"] for candidate in result] == [str(public_app.id), str(assigned_app.id)]
    assert result[0]["source_scope"] == "public"
    assert result[1]["source_scope"] == "assigned"
    assert result[0]["metadata"]["primary_pool"] == "customer_support"


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


def test_subset_builder_should_filter_by_primary_pool_and_sort_priority():
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
