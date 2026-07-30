"""B2 ColdStorageManager 单元测试。"""

from uuid import uuid4

import pytest

from internal.model.memory_models import ColdStorageEntry
from internal.service.memory.cold_storage_manager import ColdStorageManager


def _make_entry(content: str = "测试冷记忆内容", weight: float = 0.3) -> ColdStorageEntry:
    return ColdStorageEntry(
        node_id=uuid4(),
        user_id=str(uuid4()),
        content=content,
        weight=weight,
        support_count=2,
    )


class TestColdStorageArchive:
    def test_archive_should_return_none_when_cos_unavailable(self):
        """COS 不可用时应返回 None。"""
        manager = ColdStorageManager(cos_client=None, bucket=None)
        entry = _make_entry()

        result = manager.archive(entry)

        assert result is None

    def test_read_archive_should_return_none_when_cos_unavailable(self):
        """COS 不可用时应返回 None。"""
        manager = ColdStorageManager(cos_client=None, bucket=None)
        result = manager.read_archive("nonexistent-key")

        assert result is None

    def test_list_user_archives_should_return_empty_when_cos_unavailable(self):
        """COS 不可用时应返回空列表。"""
        manager = ColdStorageManager(cos_client=None, bucket=None)
        result = manager.list_user_archives(str(uuid4()))

        assert result == []


class TestColdStorageRebuildKey:
    def test_rebuild_key_from_value_should_extract_keywords(self):
        """应从内容中提取关键词作为重建 Key。"""
        manager = ColdStorageManager()
        entry = _make_entry(content="user prefers python programming language")

        result = manager.rebuild_key_from_value(entry)

        # 应返回非空字符串（关键词组合）
        assert result is not None
        assert isinstance(result, str)

    def test_rebuild_key_from_value_should_handle_empty_content(self):
        """空内容应返回 None 或空字符串。"""
        manager = ColdStorageManager()
        entry = _make_entry(content="")

        result = manager.rebuild_key_from_value(entry)

        # 空内容时应降级返回 None 或空字符串
        assert result is None or result == ""


class TestColdStorageGlobalTraverse:
    def test_global_traverse_should_degrade_without_cos(self):
        """COS 不可用时应降级返回零值 RebuildResult。"""
        manager = ColdStorageManager(cos_client=None, bucket=None)
        result = manager.global_traverse(str(uuid4()))

        # RebuildResult 字段：success, rebuilt_count, errors, duration_s
        assert hasattr(result, "success")
        assert hasattr(result, "rebuilt_count")
        assert result.rebuilt_count == 0
        # 不抛异常即可


class TestColdStorageStatisticalMining:
    def test_statistical_mining_should_return_empty_without_cos(self):
        """COS 不可用时应返回空列表。"""
        manager = ColdStorageManager(cos_client=None, bucket=None)
        result = manager.statistical_mining(str(uuid4()))

        assert isinstance(result, list)
        assert result == []
