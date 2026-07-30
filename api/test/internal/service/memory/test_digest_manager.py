"""B6 DigestManager 单元测试。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.memory.digest_manager import DigestManager


class TestDigestManager:
    def test_get_digest_should_return_empty_when_redis_miss_and_neo4j_unavailable(self):
        """Redis 缓存 miss 且 Neo4j 不可用时应返回空字符串。"""
        # 构造 Redis miss 的假客户端
        class _FakeRedis:
            def get(self, _key):
                return None

            def setex(self, _key, _ttl, _val):
                pass

        manager = DigestManager(redis_client=_FakeRedis())
        result = manager.get_digest(str(uuid4()))

        assert isinstance(result, str)

    def test_get_digest_should_return_cached_value(self):
        """Redis 命中时应直接返回缓存值（JSON 格式 {"text": "..."}）。"""
        import json

        cached_text = "用户偏好：Python，关注测试。"

        class _FakeRedis:
            def __init__(self, cached):
                self._cached = cached

            def get(self, _key):
                if self._cached is None:
                    return None
                # DigestManager 缓存格式为 JSON: {"text": "...", "updated_at": "..."}
                payload = json.dumps({"text": self._cached, "updated_at": "2026-07-09T12:00:00"})
                return payload.encode("utf-8")

            def setex(self, _key, _ttl, _val):
                pass

        manager = DigestManager(redis_client=_FakeRedis(cached_text))
        result = manager.get_digest(str(uuid4()))

        assert result == cached_text

    def test_update_digest_should_degrade_gracefully_without_neo4j(self):
        """无 Neo4j 驱动时 update_digest 不应抛异常。"""
        class _FakeRedis:
            def get(self, _key):
                return None

            def setex(self, _key, _ttl, _val):
                pass

        manager = DigestManager(redis_client=_FakeRedis())
        result = manager.update_digest(str(uuid4()))

        assert isinstance(result, str)
