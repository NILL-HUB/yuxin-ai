from internal.service.pool_intent_resolver_service import PoolIntentResolver


def test_pool_intent_resolver_should_match_coding_pool():
    result = PoolIntentResolver().resolve("帮我写一个前端页面并修复 bug")

    assert result["matched_pools"] == ["coding"]
    assert result["pool_reasons"] == [
        {"pool": "coding", "reason": "keyword:前端"}
    ]


def test_pool_intent_resolver_should_match_data_pool():
    result = PoolIntentResolver().resolve("分析销售数据并生成 SQL 报表")

    assert result["matched_pools"] == ["data"]
    assert result["pool_reasons"] == [
        {"pool": "data", "reason": "keyword:数据"}
    ]


def test_pool_intent_resolver_should_match_multiple_pools():
    result = PoolIntentResolver().resolve("帮我 P 图并写前端页面")

    assert result["matched_pools"] == ["office", "coding"]
    assert result["pool_reasons"] == [
        {"pool": "office", "reason": "keyword:P 图"},
        {"pool": "coding", "reason": "keyword:前端"},
    ]


def test_pool_intent_resolver_should_fallback_to_general():
    result = PoolIntentResolver().resolve("你好，随便聊聊")

    assert result["matched_pools"] == ["general"]
    assert result["pool_reasons"] == [
        {"pool": "general", "reason": "fallback:general"}
    ]


def test_pool_intent_resolver_should_keep_internal_admin_match():
    result = PoolIntentResolver().resolve("帮我审计系统权限和运维配置")

    assert result["matched_pools"] == ["internal_admin"]
    assert result["pool_reasons"] == [
        {"pool": "internal_admin", "reason": "keyword:审计"}
    ]
