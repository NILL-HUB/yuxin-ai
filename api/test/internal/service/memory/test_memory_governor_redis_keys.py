"""治理侧 Redis 清理键必须与实际写入键一致（C3）。

实测缺陷：`_clear_user_cache` 白名单写 `digest:{uid}`，
实际键为 `memory:digest:{uid}`（前缀来自 settings.digest.cache_key_prefix），
导致清理恒 miss。
"""
from uuid import uuid4


class _RecordingRedis:
    def __init__(self):
        self.deleted = []
        self.scanned = []

    def delete(self, *keys):
        self.deleted.extend(keys)

    def keys(self, pattern):
        self.scanned.append(pattern)
        return []


def _governor(redis_client):
    from internal.service.memory.memory_governor import MemoryGovernor

    gov = MemoryGovernor.__new__(MemoryGovernor)
    gov._get_redis = lambda: redis_client  # type: ignore[method-assign]
    return gov


def test_clear_user_cache_deletes_real_digest_key():
    from internal.config.memory_settings import settings

    account_id = uuid4()
    redis = _RecordingRedis()
    gov = _governor(redis)

    gov._clear_user_cache(str(account_id))

    expected_digest_key = f"{settings.digest.cache_key_prefix}{account_id}"
    assert expected_digest_key in redis.deleted, (
        "清理键必须与 digest_manager._cache_key 产物一致，否则 Digest 缓存删不掉"
    )
    assert f"digest:{account_id}" not in redis.deleted, "不得再使用缺前缀的旧键"


def test_clear_user_cache_covers_skill_pool_and_stats_keys():
    account_id = uuid4()
    redis = _RecordingRedis()
    gov = _governor(redis)

    gov._clear_user_cache(str(account_id))

    assert f"skill:pool:{account_id}" in redis.deleted
    assert f"skill:stats:{account_id}" in redis.deleted


def test_clear_user_cache_drops_orphan_profile_key():
    """`profile:{uid}` 无任何写入方（画像走 Neo4j），为死键，应移除以免误导。"""
    account_id = uuid4()
    redis = _RecordingRedis()
    gov = _governor(redis)

    gov._clear_user_cache(str(account_id))

    assert f"profile:{account_id}" not in redis.deleted
