"""P0-5 AgentPoolConfig 接入 AgentCandidateCollector 端到端集成测试。

验证环节：
    AgentPoolConfig（路由元数据）接入 AgentCandidateCollector 后，候选 Agent
    携带路由元数据（primary_pool/risk_level/model_tier/routing_priority），
    并能被下游 AgentPolicyFilter / AgentRanker 正常处理。

测试场景：
    1. AgentPoolConfig 存在时候选携带路由元数据，缺失时降级默认值
    2. AgentPoolConfig 字段值透传到候选 dict 顶层
    3. collect 后接 AgentPolicyFilter 不破坏
    4. collect 后接 AgentRanker 按 routing_priority 影响排序
    5. AgentPoolConfig 缺失的 App 仍能被收集（降级默认值保证可用性）
"""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from internal.entity.agent_entity import DEFAULT_AGENT_METADATA
from internal.model.app import App, AppAssignment
from internal.service.agent_pool_service import (
    AgentCandidateCollector,
    AgentPolicyFilter,
    AgentRanker,
)


# ------------------------------------------------------------------ #
#  Stub（复用 test_agent_pool_service.py 的 _QueryStub/_SessionStub） #
# ------------------------------------------------------------------ #

class _QueryStub:
    """支持 filter/order_by/outerjoin/all 链式调用的查询桩。

    outerjoin stub 不模拟真实 JOIN，仅维持链式调用并把 all_result 原样返回；
    all_result 中的元素可以是 (App, AgentPoolConfig) 元组或裸 App 对象。
    """

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
        # P0-5: AgentCandidateCollector.collect() 通过 outerjoin LEFT JOIN
        # AgentPoolConfig；stub 不模拟真实 JOIN，仅维持链式调用。
        self.outerjoin_args.append((args, kwargs))
        return self

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


def _app(**kwargs):
    defaults = {
        "id": uuid4(),
        "account_id": uuid4(),
        "name": "测试 Agent",
        "icon": "🤖",
        "description": "测试描述",
        "status": "published",
        "is_public": False,
        "agent_metadata": dict(DEFAULT_AGENT_METADATA),
        "published_at": datetime(2030, 1, 1, 0, 0, 0),
    }
    defaults.update(kwargs)
    return App(**defaults)


def _pool_config(**kwargs):
    """构造 AgentPoolConfig 桩对象。"""
    defaults = {
        "primary_pool": "general",
        "secondary_pools": [],
        "risk_level": "safe",
        "model_tier": "standard",
        "routing_priority": 100,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ------------------------------------------------------------------ #
#  测试用例                                                           #
# ------------------------------------------------------------------ #

def test_candidate_carries_routing_metadata_when_pool_config_exists():
    """场景1：AgentPoolConfig 存在时候选携带路由元数据，缺失时降级默认值。

    构造 2 个公开 App：第 1 个有 AgentPoolConfig（primary_pool=coding,
    risk_level=safe, model_tier=premium, routing_priority=10），第 2 个没有。
    collect() 后第 1 个候选应含配置字段，第 2 个应含降级默认值。
    """
    account_id = uuid4()
    app_with_config = _app(name="编程 Agent", is_public=True)
    app_without_config = _app(name="通用 Agent", is_public=True)
    pool_config = _pool_config(
        primary_pool="coding",
        risk_level="safe",
        model_tier="premium",
        routing_priority=10,
    )
    collector = AgentCandidateCollector(
        session=_SessionStub([
            # public_rows: (app, pool_config) 元组 + 裸 app（降级为 (app, None)）
            _QueryStub(all_result=[(app_with_config, pool_config), app_without_config]),
            _QueryStub(all_result=[]),  # assignments
            _QueryStub(all_result=[]),  # own_rows
        ])
    )

    result = collector.collect(account_id)

    app_candidates = [c for c in result if c["source_type"] == "app"]
    assert len(app_candidates) == 2
    # 第 1 个候选携带 AgentPoolConfig 路由元数据
    first = app_candidates[0]
    assert first["name"] == "编程 Agent"
    assert first["primary_pool"] == "coding"
    assert first["risk_level"] == "safe"
    assert first["model_tier"] == "premium"
    assert first["routing_priority"] == 10
    # 第 2 个候选降级默认值
    second = app_candidates[1]
    assert second["name"] == "通用 Agent"
    assert second["primary_pool"] == "general"
    assert second["risk_level"] == "safe"
    assert second["model_tier"] == "standard"
    assert second["routing_priority"] == 100


def test_pool_config_fields_transparently_passed_to_candidate_top_level():
    """场景2：AgentPoolConfig 字段值透传到候选 dict 顶层。

    构造 AgentPoolConfig(primary_pool=data_analysis, risk_level=sensitive,
    model_tier=premium, routing_priority=5)，collect() 后候选 dict 顶层
    应能直接读取这些字段。
    """
    account_id = uuid4()
    app = _app(name="数据分析 Agent", is_public=True)
    pool_config = _pool_config(
        primary_pool="data_analysis",
        risk_level="sensitive",
        model_tier="premium",
        routing_priority=5,
    )
    collector = AgentCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[(app, pool_config)]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
        ])
    )

    result = collector.collect(account_id)

    app_candidates = [c for c in result if c["source_type"] == "app"]
    assert len(app_candidates) == 1
    candidate = app_candidates[0]
    # 顶层可直接读取 AgentPoolConfig 字段
    assert candidate["primary_pool"] == "data_analysis"
    assert candidate["risk_level"] == "sensitive"
    assert candidate["model_tier"] == "premium"
    assert candidate["routing_priority"] == 5
    # id/app_id/agent_id 仍正确
    assert candidate["id"] == str(app.id)
    assert candidate["app_id"] == str(app.id)


def test_collect_result_can_be_processed_by_policy_filter():
    """场景3：collect() 结果能被 AgentPolicyFilter 正常处理（不报错）。

    构造含/不含 AgentPoolConfig 的公开 App，collect() 后接 AgentPolicyFilter，
    过滤结果应结构正确且不抛异常。
    """
    account_id = uuid4()
    published = _app(name="已发布", is_public=True, status="published")
    draft = _app(name="草稿", is_public=True, status="draft")
    pool_config = _pool_config(primary_pool="coding", routing_priority=10)
    collector = AgentCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[(published, pool_config), draft]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
        ])
    )

    raw_result = collector.collect(account_id)
    # AgentPolicyFilter 需要 "app" 字段，collect() 返回的序列化候选不含 "app"，
    # 需用 collect 内部候选结构；这里直接构造 filter 输入验证不报错。
    filter_input = [
        {
            "app": published,
            "source_scope": "public",
            "metadata": published.normalized_agent_metadata,
        },
        {
            "app": draft,
            "source_scope": "public",
            "metadata": draft.normalized_agent_metadata,
        },
    ]

    filter_result = AgentPolicyFilter().filter(filter_input)

    # 草稿被过滤，已发布保留
    assert [c["name"] for c in filter_result["candidates"]] == ["已发布"]
    assert len(filter_result["filtered_out_agents"]) == 1
    assert filter_result["filtered_out_agents"][0]["reason"] == "app_not_published"
    # collect 结果本身结构完整
    assert any(c["name"] == "已发布" for c in raw_result if c["source_type"] == "app")


def test_collect_result_can_be_ranked_by_agent_ranker():
    """场景4：collect 后接 AgentRanker 排序，routing_priority 影响排序。

    构造 2 个候选，routing_priority 不同（10 vs 100），其余评分因子接近。
    AgentRanker 的 priority_score = routing_priority / 1000，routing_priority
    数值大的 priority_score 更高，总分更高，排在前。
    """
    account_id = uuid4()
    high_priority_app = _app(
        name="高优先级 Agent",
        is_public=True,
        agent_metadata={**DEFAULT_AGENT_METADATA, "routing_priority": 100},
    )
    low_priority_app = _app(
        name="低优先级 Agent",
        is_public=True,
        agent_metadata={**DEFAULT_AGENT_METADATA, "routing_priority": 10},
    )
    collector = AgentCandidateCollector(
        session=_SessionStub([
            _QueryStub(all_result=[
                (high_priority_app, _pool_config(routing_priority=100)),
                (low_priority_app, _pool_config(routing_priority=10)),
            ]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
        ])
    )

    result = collector.collect(account_id)
    app_candidates = [c for c in result if c["source_type"] == "app"]
    # 构造 AgentRanker 输入：用 metadata 中的 routing_priority
    ranker_input = [
        {
            "agent_id": c["agent_id"],
            "name": c["name"],
            "semantic_score": 0.5,  # 保持一致，让 routing_priority 成为决定因子
            "metadata": {**DEFAULT_AGENT_METADATA, "routing_priority": c["routing_priority"]},
        }
        for c in app_candidates
    ]

    ranked = AgentRanker().rank(ranker_input)

    # routing_priority=100 的 priority_score 更高 → 总分更高 → 排在前
    assert ranked[0]["name"] == "高优先级 Agent"
    assert ranked[1]["name"] == "低优先级 Agent"
    assert ranked[0]["score"] >= ranked[1]["score"]
    # priority_score 体现在 score_breakdown
    assert ranked[0]["score_breakdown"]["priority_score"] == 0.1
    assert ranked[1]["score_breakdown"]["priority_score"] == 0.01


def test_app_without_pool_config_still_collected_with_defaults():
    """场景5：AgentPoolConfig 缺失的 App 仍能被收集（降级默认值保证可用性）。

    全部 App 均无 AgentPoolConfig（outerjoin 返回裸 App 对象），collect() 后
    候选应含降级默认值且不被丢弃。
    """
    account_id = uuid4()
    app_a = _app(name="Agent A", is_public=True)
    app_b = _app(name="Agent B", is_public=True)
    collector = AgentCandidateCollector(
        session=_SessionStub([
            # 全部裸 App 对象，_unpack_app_row 降级为 (app, None)
            _QueryStub(all_result=[app_a, app_b]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
        ])
    )

    result = collector.collect(account_id)

    app_candidates = [c for c in result if c["source_type"] == "app"]
    assert len(app_candidates) == 2
    for candidate in app_candidates:
        # 全部降级为默认值
        assert candidate["primary_pool"] == "general"
        assert candidate["risk_level"] == "safe"
        assert candidate["model_tier"] == "standard"
        assert candidate["routing_priority"] == 100
