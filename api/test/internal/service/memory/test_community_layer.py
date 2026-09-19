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


class TestCommunityInductionCutoffBinding:
    """缺口六（ADMIN-P3c-4）：Entity 聚合分支的 `$cutoff` 必须绑定。

    修复前 `session.run(cypher_groups, {**owner.neo4j_props()})` 缺 cutoff →
    真图 ParameterMissing 被吞 → groups 恒空 → Entity 聚合候选永远为空。
    """

    def test_entity_group_branch_binds_cutoff(self, monkeypatch):
        """Entity 聚合 Cypher 的 run 绑定必须含 cutoff（与 SemanticMemory 分支对齐）。"""
        from uuid import uuid4

        from internal.entity.memory_owner_entity import MemoryOwnerKey
        from internal.service.memory import community_induction as ci_mod

        captured_binds = {}

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def run(self, cypher, parameters=None, **binds):
                params = dict(parameters or {})
                params.update(binds)
                captured_binds.setdefault(len(captured_binds), (cypher, params))
                return iter([])  # 无记录

        class _Driver:
            def session(self):
                return _Session()

        engine = CommunityInductionEngine(neo4j_driver=_Driver())
        owner_key = str(uuid4())

        # 不吞异常、不依赖真图：直接调用 _collect_eligible，捕获 session.run 绑定
        monkeypatch.setattr(
            ci_mod.CommunityInductionEngine,
            "_compute_age_days",
            lambda self, ts: 0,
        )
        engine._collect_eligible(owner_key)

        # 第二个 run 是 Entity 聚合分支（第一个是 SemanticMemory）
        assert len(captured_binds) == 2
        _, entity_binds = captured_binds[1]
        assert "cutoff" in entity_binds, "Entity 聚合分支必须绑定 $cutoff（缺口六）"
        assert "user_id" in entity_binds or "admin_user_id" in entity_binds

    def test_entity_branch_cutoff_isoformat_matches_semantic_branch(self, monkeypatch):
        """两个分支的 cutoff 值一致（同一时间点，ISO 格式）。"""
        from uuid import uuid4

        from internal.service.memory import community_induction as ci_mod

        captured_binds = {}

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def run(self, cypher, parameters=None, **binds):
                params = dict(parameters or {})
                params.update(binds)
                captured_binds.setdefault(len(captured_binds), params)
                return iter([])

        class _Driver:
            def session(self):
                return _Session()

        engine = CommunityInductionEngine(neo4j_driver=_Driver())
        monkeypatch.setattr(
            ci_mod.CommunityInductionEngine,
            "_compute_age_days",
            lambda self, ts: 0,
        )
        engine._collect_eligible(str(uuid4()))

        assert captured_binds[0]["cutoff"] == captured_binds[1]["cutoff"]
