"""D2 MemoryGovernor 单元测试。"""

from uuid import uuid4

import pytest

from internal.service.memory.memory_governor import MemoryGovernor


class TestMemoryGovernorPII:
    def test_filter_email(self):
        governor = MemoryGovernor()
        result = governor.filter_pii("联系我 user@example.com 谢谢")
        assert "[EMAIL_REDACTED]" in result
        assert "user@example.com" not in result

    def test_filter_phone(self):
        governor = MemoryGovernor()
        result = governor.filter_pii("电话 13812345678")
        assert "[PHONE_REDACTED]" in result
        assert "13812345678" not in result

    def test_filter_id_card(self):
        governor = MemoryGovernor()
        result = governor.filter_pii("身份证 110101199001011234")
        assert "[ID_REDACTED]" in result

    def test_filter_bank_card(self):
        governor = MemoryGovernor()
        result = governor.filter_pii("卡号 6222021234567890123")
        assert "[CARD_REDACTED]" in result

    def test_filter_no_pii(self):
        governor = MemoryGovernor()
        result = governor.filter_pii("这是普通文本无 PII")
        assert result == "这是普通文本无 PII"

    def test_filter_empty_content(self):
        governor = MemoryGovernor()
        assert governor.filter_pii("") == ""


class TestMemoryGovernorDelete:
    def test_soft_delete_without_driver(self):
        governor = MemoryGovernor(neo4j_driver=None)
        assert governor.soft_delete_memory("m1", "u1") is False

    def test_hard_delete_without_driver(self):
        governor = MemoryGovernor(neo4j_driver=None)
        assert governor.hard_delete_memory("m1", "u1") is False


class TestMemoryGovernorEdit:
    def test_edit_without_driver(self):
        governor = MemoryGovernor(neo4j_driver=None)
        assert governor.edit_memory("m1", "u1", "新内容") is None


class TestMemoryGovernorGDPR:
    def test_gdpr_delete_without_driver(self):
        governor = MemoryGovernor(neo4j_driver=None)
        stats = governor.gdpr_delete("u1")
        assert isinstance(stats, dict)
        assert stats["neo4j_nodes"] == 0
        assert stats["neo4j_edges"] == 0
