"""P5 Community 层 + Profile 落库回归测试（无真实依赖降级路径）。"""

from uuid import uuid4

import pytest

from internal.service.memory.community_induction import CommunityInductionEngine
from internal.service.memory.consolidation_engine import ConsolidationEngine
from internal.service.memory.profile_graph import ProfileGraphService
from internal.service.memory.retriever import MemoryRetriever


class TestCommunityPhaseWiredIntoConsolidation:
    def test_run_consolidation_should_include_community_phase(self, monkeypatch):
        """巩固流程应包含 community 阶段（委托 CommunityInductionEngine）。"""
        from internal.service.memory import community_induction as ci_mod

        engine = ConsolidationEngine(neo4j_driver=None)
        monkeypatch.setattr(engine, "_get_driver", lambda: None)
        monkeypatch.setattr(
            ci_mod.CommunityInductionEngine,
            "run_induction",
            lambda self, user_id: {
                "candidates": 1,
                "created": 1,
                "merged": 0,
                "evolved": 0,
                "deprecated": 0,
                "errors": [],
            },
        )
        report = engine.run_consolidation(str(uuid4()))

        assert "community" in report.phases
        phase = report.phases["community"]
        assert isinstance(phase, dict)
        assert phase["created"] == 1

    def test_community_induction_should_degrade_without_dependencies(self, monkeypatch):
        """无 Neo4j 时 run_induction 应返回全零统计 + 不抛异常。"""
        induction = CommunityInductionEngine(neo4j_driver=None)
        monkeypatch.setattr(induction, "_get_driver", lambda: None)
        result = induction.run_induction(str(uuid4()))

        assert isinstance(result, dict)
        assert result["candidates"] == 0
        assert result["created"] == 0
        assert result["errors"] == []


class TestProfileGraphDegrade:
    def test_get_profile_text_should_return_empty_without_driver(self, monkeypatch):
        """无 Neo4j 时 get_profile_text 返回空串（digest 可回退旧路径）。"""
        service = ProfileGraphService(neo4j_driver=None)
        monkeypatch.setattr(service, "_get_driver", lambda: None)
        assert service.get_profile_text(str(uuid4())) == ""

    def test_sync_from_explicit_episodes_should_degrade_without_driver(self, monkeypatch):
        """无 Neo4j 时 sync 返回空统计 + user=False，不抛异常。"""
        service = ProfileGraphService(neo4j_driver=None)
        monkeypatch.setattr(service, "_get_driver", lambda: None)
        result = service.sync_from_explicit_episodes(str(uuid4()))

        assert isinstance(result, dict)
        assert result["user"] is False
        assert result["traits"] == 0


class TestRetrieverCommunityRecall:
    def test_community_recall_should_return_empty_without_driver(self, monkeypatch):
        """无 Neo4j 时 _community_recall 返回空列表（不影响主流程）。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        monkeypatch.setattr(retriever, "_get_driver", lambda: None)
        assert retriever._community_recall("查询", str(uuid4())) == []

    def test_retrieve_should_not_raise_with_community_recall_path(self, monkeypatch):
        """_system2_deep_search 新增社区召回层后，无依赖整链路仍降级为空。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        monkeypatch.setattr(retriever, "_get_driver", lambda: None)
        monkeypatch.setattr(retriever, "_get_db", lambda: None)
        monkeypatch.setattr(retriever, "_get_embeddings_service", lambda: None)
        result = retriever.retrieve("测试主题查询", str(uuid4()))
        assert isinstance(result, list)
