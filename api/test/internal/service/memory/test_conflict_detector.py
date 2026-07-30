"""C2 ConflictDetector 单元测试。"""

from uuid import uuid4

import pytest

from internal.service.memory.conflict_detector import ConflictDetector


class TestConflictDetector:
    def test_detect_should_degrade_without_neo4j(self):
        """无 Neo4j 驱动时应降级返回空结果。"""
        detector = ConflictDetector(neo4j_driver=None)
        result = detector.detect(str(uuid4()))

        # 应返回字典，包含 conflicts 列表
        assert isinstance(result, dict)
        # 无驱动时 conflicts 应为空或降级
        if "conflicts" in result:
            assert isinstance(result["conflicts"], list)

    def test_detect_should_not_raise_on_invalid_user_id(self):
        """无效用户 ID 不应抛异常。"""
        detector = ConflictDetector(neo4j_driver=None)
        result = detector.detect("")

        assert isinstance(result, dict)
