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


def test_clear_user_cache_follows_configured_prefix(monkeypatch):
    """清理键必须**跟随配置**（settings.digest.cache_key_prefix），而非硬编码字面量。

    先前用例的期望值也由同一 settings 反推，无法区分「跟随配置」与「硬编码了当前默认值」。
    这里把前缀改成哨兵值：若实现硬编码 `memory:digest:`，本用例必失败。
    """
    from internal.config.memory_settings import settings

    monkeypatch.setattr(settings.digest, "cache_key_prefix", "sentinel:digest:")

    account_id = uuid4()
    redis = _RecordingRedis()
    gov = _governor(redis)

    gov._clear_user_cache(str(account_id))

    assert f"sentinel:digest:{account_id}" in redis.deleted
    assert f"memory:digest:{account_id}" not in redis.deleted


def test_clear_user_cache_scopes_admin_owner_key():
    """admin 主体键：清理键的主体片段必须是完整 owner_key（不得退化成裸 user_id）。"""
    admin_id = uuid4()
    redis = _RecordingRedis()
    gov = _governor(redis)

    gov._clear_user_cache(f"admin:{admin_id}")

    assert f"skill:pool:admin:{admin_id}" in redis.deleted
    assert f"skill:stats:admin:{admin_id}" in redis.deleted
    assert f"skill:pool:{admin_id}" not in redis.deleted, "不得误删裸主体形态的键"


class _FakeKeysRedis(_RecordingRedis):
    """`keys(pattern)` 按预置键集返回命中的键（用 fnmatch 语义模拟 glob）。"""

    def __init__(self, existing):
        super().__init__()
        self._existing = list(existing)

    def keys(self, pattern):
        import fnmatch

        self.scanned.append(pattern)
        return [k for k in self._existing if fnmatch.fnmatchcase(k, pattern)]


def test_clear_all_user_cache_hits_every_owner_scoped_key():
    """GDPR 全量清理必须覆盖各类含主体键的 Redis 键。

    覆盖：尾部主体键（digest / skill:pool / skill:stats / nudge:prompt /
    bms:access_count / memory:agent_curated:quota）与中部主体键
    （nudge:stats:{owner}:{conv} / seed:{owner}:{name}）。
    """
    account_id = uuid4()
    owner = str(account_id)
    existing = [
        f"memory:digest:{owner}",
        f"skill:pool:{owner}",
        f"skill:stats:{owner}",
        f"nudge:prompt:{owner}",
        f"nudge:stats:{owner}:conv1",
        f"seed:{owner}:代码审查",
        f"bms:access_count:{owner}",
        f"memory:agent_curated:quota:{owner}",
    ]
    other = str(uuid4())
    existing.append(f"memory:digest:{other}")

    redis = _FakeKeysRedis(existing)
    gov = _governor(redis)

    gov._clear_all_user_cache(owner)

    for key in existing[:-1]:
        assert key in redis.deleted, f"{key} 必须被清理"
    assert f"memory:digest:{other}" not in redis.deleted, "不得误删他人主体的键"


def test_clear_all_user_cache_returns_zero_without_redis():
    gov = _governor(None)
    assert gov._clear_all_user_cache(str(uuid4())) == 0


def test_clear_all_user_cache_dedupes_count():
    """缺口十一：同一键被两个模式命中时，计数不得重复。

    ``memory:digest:{owner}`` 同时匹配 ``*:{owner}``（尾部主体键）与精确前缀
    ``memory:digest:{owner}``。``delete(*keys)`` 幂等，故清理正确性不受影响，
    但 ``len(keys)`` 会把它计两次，使 stats["redis_keys"] 偏大。
    """
    account_id = uuid4()
    digest_key = f"memory:digest:{account_id}"

    class _Redis:
        def keys(self, pattern):
            if pattern == f"*:{account_id}":
                return [digest_key, f"skill:pool:{account_id}"]
            if pattern == f"*:{account_id}:*":
                return []
            # 精确前缀模式
            return [digest_key]

        def delete(self, *keys):
            return len(keys)

    gov = _governor(_Redis())

    count = gov._clear_all_user_cache(str(account_id))

    assert count == 2, "distinct 键为 2（digest + skill:pool），不得重复计数"
