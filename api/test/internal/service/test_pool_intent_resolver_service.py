from internal.entity.agent_pool_entity import BUILTIN_AGENT_SUB_POOLS, AgentSubPoolRegistry
from internal.service.pool_intent_resolver_service import PoolIntentResolver


def _resolver():
    return PoolIntentResolver(
        registry=AgentSubPoolRegistry(pools=BUILTIN_AGENT_SUB_POOLS)
    )


def test_pool_intent_resolver_should_match_coding_pool():
    result = _resolver().resolve("帮我写一个前端页面并修复 bug")

    assert result["matched_pools"] == ["coding"]
    assert result["pool_reasons"] == [
        {"pool": "coding", "reason": "keyword:前端"}
    ]


def test_pool_intent_resolver_should_match_data_pool():
    result = _resolver().resolve("分析销售数据并生成 SQL 报表")

    assert result["matched_pools"] == ["data"]
    assert result["pool_reasons"] == [
        {"pool": "data", "reason": "keyword:数据"}
    ]


def test_pool_intent_resolver_should_match_multiple_pools():
    result = _resolver().resolve("帮我 P 图并写前端页面")

    assert set(result["matched_pools"]) == {"office", "coding"}
    pool_by_name = {r["pool"]: r["reason"] for r in result["pool_reasons"]}
    assert pool_by_name.get("office") == "keyword:P 图"
    assert pool_by_name.get("coding") == "keyword:前端"


def test_pool_intent_resolver_should_fallback_to_general():
    result = _resolver().resolve("你好，随便聊聊")

    assert result["matched_pools"] == ["general"]
    assert result["pool_reasons"] == [
        {"pool": "general", "reason": "fallback:general"}
    ]


def test_pool_intent_resolver_should_keep_internal_admin_match():
    result = _resolver().resolve("帮我审计系统权限和运维配置")

    assert result["matched_pools"] == ["internal_admin"]
    assert result["pool_reasons"] == [
        {"pool": "internal_admin", "reason": "keyword:审计"}
    ]
