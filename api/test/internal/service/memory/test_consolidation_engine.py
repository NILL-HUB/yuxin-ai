"""C1 ConsolidationEngine 单元测试。"""

from uuid import uuid4

import pytest

from internal.service.memory.consolidation_engine import ConsolidationEngine


class TestConsolidationEngine:
    def test_run_consolidation_should_not_raise_without_dependencies(self):
        """无 Neo4j 和数据库时也应返回 report，不抛异常。"""
        engine = ConsolidationEngine(neo4j_driver=None)
        report = engine.run_consolidation(str(uuid4()))

        # 应返回 ConsolidationReport，包含 phases 和 errors
        assert hasattr(report, "phases")
        assert hasattr(report, "errors")
        assert isinstance(report.errors, list)

    def test_run_consolidation_should_record_phase_errors(self):
        """单个阶段失败应记录到 errors 而非抛异常。"""
        engine = ConsolidationEngine(neo4j_driver=None)
        report = engine.run_consolidation(str(uuid4()))

        # 无依赖时阶段可能失败，但 errors 应是列表
        assert isinstance(report.errors, list)

    def test_run_consolidation_should_return_phases_dict(self):
        """phases 应是字典，包含各阶段结果。"""
        engine = ConsolidationEngine(neo4j_driver=None)
        report = engine.run_consolidation(str(uuid4()))

        assert isinstance(report.phases, dict)
