"""B7/C5 memory_schema 单元测试。"""

import pytest

from internal.schema.memory_schema import (
    ConsolidationResp,
    MemoryDigestResp,
    MemoryRetrieveReq,
    MemoryRetrieveResp,
    MemoryWriteResp,
)


class TestMemorySchemas:
    def test_memory_retrieve_resp_should_serialize_results(self):
        """MemoryRetrieveResp 应能序列化 results 列表。"""
        resp = MemoryRetrieveResp()
        data = resp.dump({
            "results": [{"memory_id": "m1", "content": "测试", "score": 0.9}],
            "summary": "摘要",
            "intent": "",
            "retrieval_path": "system2",
            "latency_ms": 12.5,
        })

        assert data["retrieval_path"] == "system2"
        assert data["latency_ms"] == 12.5
        assert len(data["results"]) == 1

    def test_memory_digest_resp_should_serialize(self):
        """MemoryDigestResp 应能序列化 digest 字段。"""
        resp = MemoryDigestResp()
        data = resp.dump({
            "user_id": "u1",
            "digest": "用户偏好摘要。",
            "cached": True,
        })

        assert data["user_id"] == "u1"
        assert data["cached"] is True
        assert "偏好" in data["digest"]

    def test_consolidation_resp_should_serialize_with_task_id(self):
        """ConsolidationResp 应能序列化 task_id（异步模式）。"""
        resp = ConsolidationResp()
        data = resp.dump({
            "user_id": "u1",
            "success": True,
            "total_items": 0,
            "phase_results": {"task_id": "abc-123"},
            "errors": [],
            "task_id": "abc-123",
        })

        assert data["success"] is True
        assert data["task_id"] == "abc-123"
        assert data["errors"] == []

    def test_consolidation_resp_should_serialize_sync_mode(self):
        """ConsolidationResp 应能序列化同步模式（task_id=None）。"""
        resp = ConsolidationResp()
        data = resp.dump({
            "user_id": "u1",
            "success": True,
            "total_items": 5,
            "phase_results": {"episode_to_semantic": {"converted": 3}},
            "errors": [],
            "task_id": None,
        })

        assert data["success"] is True
        assert data["total_items"] == 5
        assert data["task_id"] is None
