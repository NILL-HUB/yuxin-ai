"""视图过滤与策略路由（D1 PolicyRouter 接线，2026-10-04）。

不变量：
1. ``view_names`` 为空/None = 不限视图（与接线前行为一致）；
2. 非空 = 四个召回分支全部受限（TKG 标签谓词 / pgvector memory_type /
   Community 标签 / 图扩展节点标签），不允许任何分支绕过；
3. 非法视图名 fail-closed（不静默退化成全量）；
4. 意图分类只走规则通道（不调 LLM）；异常退化为「不限视图 + 摘要优先」；
5. 对话召回顺序由意图决定：prefer_deep 深检优先（空则摘要兜底），否则摘要优先。
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from internal.model.memory_models import RetrievalOptions, RetrievalResult
from internal.service.memory.retriever import MemoryRetriever

OWNER = str(uuid4())


class _RecResult:
    def __init__(self, records=None):
        self._records = list(records or [])

    def single(self):
        return self._records[0] if self._records else None

    def __iter__(self):
        return iter(self._records)


class _RecSession:
    def __init__(self, records=None):
        self.calls = []
        self._records = list(records or [])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, parameters=None, **binds):
        params = dict(parameters or {})
        params.update(binds)
        self.calls.append((cypher, params))
        return _RecResult(self._records)


class _RecDriver:
    def __init__(self, records=None):
        self.session_obj = None
        self._records = records

    def session(self):
        self.session_obj = _RecSession(self._records)
        return self.session_obj


# 真实形状的摘要样本（有列表项 → digest_has_substance 判为有实质内容）
_REAL_DIGEST = (
    "# 用户记忆摘要" + chr(10)
    + "更新时间：2026-10-05 11:02" + chr(10) + chr(10)
    + "## 用户画像" + chr(10)
    + "- 偏好：喜欢吃苹果；喜欢喝美式咖啡" + chr(10)
)


class _DigestStub:
    def __init__(self, text: str = ""):
        self.text = text
        self.calls = 0

    def get_digest(self, owner_key: str) -> str:
        self.calls += 1
        return self.text


# ---------------------------------------------------------------- 视图解析


class TestResolveViewFilter:
    def test_empty_means_unrestricted(self):
        assert MemoryRetriever._resolve_view_filter([]) is None
        assert MemoryRetriever._resolve_view_filter(None) is None

    def test_single_view_maps_labels_and_pg_types(self):
        labels, pg = MemoryRetriever._resolve_view_filter(["episodes"])
        assert labels == {"Episode"}
        assert pg == {"episode"}

    def test_skills_has_no_pg_types(self):
        labels, pg = MemoryRetriever._resolve_view_filter(["skills"])
        assert labels == {"Skill"}
        assert pg == set()

    def test_unknown_view_is_fail_closed(self):
        labels, pg = MemoryRetriever._resolve_view_filter(["nope"])
        assert labels == set() and pg == set()

    def test_mixed_known_and_unknown_keeps_known(self):
        labels, pg = MemoryRetriever._resolve_view_filter(["episodes", "nope"])
        assert labels == {"Episode"}
        assert pg == {"episode"}


class TestViewLabelClause:
    def test_unrestricted_returns_empty_clause(self):
        assert MemoryRetriever._view_label_clause("node", None) == ""

    def test_restricted_lists_all_labels(self):
        clause = MemoryRetriever._view_label_clause("node", ({"Episode", "Entity"}, set()))
        assert "node:`Episode`" in clause and "node:`Entity`" in clause

    def test_empty_labels_is_never_true(self):
        assert MemoryRetriever._view_label_clause("node", (set(), set())) == "AND false"


class TestNodeInViews:
    def test_unrestricted_allows_all(self):
        assert MemoryRetriever._node_in_views([], None) is True

    def test_matching_label_allowed(self):
        assert (
            MemoryRetriever._node_in_views(["Episode", "MemoryNode"], ({"Episode"}, set()))
            is True
        )

    def test_non_matching_label_rejected(self):
        assert MemoryRetriever._node_in_views(["Entity"], ({"Episode"}, set())) is False

    def test_empty_allow_set_rejects(self):
        assert MemoryRetriever._node_in_views(["Episode"], (set(), set())) is False


# ---------------------------------------------------------------- 四个召回分支


class TestTkgRecallViewFilter:
    def test_cypher_contains_label_predicate(self):
        driver = _RecDriver()
        retriever = MemoryRetriever(neo4j_driver=driver, db=None)
        retriever._tkg_recall("q", OWNER, 10, ({"Episode"}, {"episode"}))

        cypher, _params = driver.session_obj.calls[0]
        assert "node:`Episode`" in cypher

    def test_unrestricted_has_no_label_predicate(self):
        driver = _RecDriver()
        retriever = MemoryRetriever(neo4j_driver=driver, db=None)
        retriever._tkg_recall("q", OWNER, 10, None)

        cypher, _params = driver.session_obj.calls[0]
        assert "node:`" not in cypher

    def test_empty_allow_set_short_circuits(self):
        driver = _RecDriver()
        retriever = MemoryRetriever(neo4j_driver=driver, db=None)
        assert retriever._tkg_recall("q", OWNER, 10, (set(), set())) == []
        assert driver.session_obj is None  # 未触达 Neo4j


class TestVectorRecallViewFilter:
    def test_view_without_pg_rows_short_circuits(self):
        class _BoomDb:
            def __getattr__(self, name):
                raise AssertionError("视图无向量行时不应触达数据库")

        retriever = MemoryRetriever(neo4j_driver=None, db=_BoomDb())
        assert retriever._vector_recall([0.1] * 8, OWNER, 10, ({"Skill"}, set())) == []

    @staticmethod
    def _patch_embedding_router(monkeypatch):
        from internal.service import embedding_table_router as mod

        class _Router:
            def resolve_system_default_dimension(self):
                return 1536

            def ensure_tables_for_dimension(self, dimension):
                return True

            def get_user_memory_table_name(self, dimension):
                return "user_memory_embedding_1536"

        monkeypatch.setattr(
            mod.EmbeddingTableRouter, "get_instance", staticmethod(lambda: _Router())
        )

    def test_memory_type_filter_reaches_sql(self, monkeypatch):
        captured: dict = {}
        self._patch_embedding_router(monkeypatch)

        class _Res:
            def all(self):
                return []

        class _Session:
            def execute(self, sql, params):
                captured["sql"] = str(sql)
                captured["params"] = params
                return _Res()

        class _Db:
            session = _Session()

        retriever = MemoryRetriever(neo4j_driver=None, db=_Db())
        retriever._vector_recall([0.1] * 8, OWNER, 10, ({"Episode"}, {"episode"}))

        assert "um.memory_type IN" in captured["sql"]
        assert captured["params"]["mt_0"] == "episode"

    def test_unrestricted_has_no_type_filter(self, monkeypatch):
        captured: dict = {}
        self._patch_embedding_router(monkeypatch)

        class _Res:
            def all(self):
                return []

        class _Session:
            def execute(self, sql, params):
                captured["sql"] = str(sql)
                captured["params"] = params
                return _Res()

        class _Db:
            session = _Session()

        retriever = MemoryRetriever(neo4j_driver=None, db=_Db())
        retriever._vector_recall([0.1] * 8, OWNER, 10, None)

        assert "um.memory_type" not in captured["sql"]


class TestCommunityRecallViewFilter:
    def test_skips_when_view_excludes_themes(self):
        driver = _RecDriver()
        retriever = MemoryRetriever(neo4j_driver=driver, db=None)
        assert retriever._community_recall("q", OWNER, 10, ({"Episode"}, {"episode"})) == []
        assert driver.session_obj is None  # 未触达 Neo4j

    def test_runs_when_view_includes_themes(self):
        driver = _RecDriver()
        retriever = MemoryRetriever(neo4j_driver=driver, db=None)
        retriever._community_recall("q", OWNER, 10, ({"Community"}, set()))
        assert driver.session_obj is not None


class TestDeepSearchViewConsistency:
    """图扩展节点同样受视图约束（不允许有分支绕过）。"""

    def test_spread_nodes_outside_views_are_dropped(self, monkeypatch):
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        monkeypatch.setattr(
            MemoryRetriever,
            "_tkg_recall",
            lambda self, q, o, k, vf=None, tc=None: [
                RetrievalResult(memory_id="seed", content="种子", score=1.0, source="bm25")
            ],
        )
        monkeypatch.setattr(MemoryRetriever, "_embed_query", lambda self, q: None)
        monkeypatch.setattr(
            MemoryRetriever, "_community_recall", lambda self, q, o, k, vf=None, tc=None: []
        )
        monkeypatch.setattr(
            MemoryRetriever,
            "_graph_spread",
            lambda self, ids, top_k=20, owner_key="": [("entity1", 1.0)],
        )
        monkeypatch.setattr(
            MemoryRetriever,
            "_get_node_data",
            lambda self, node_id, owner_key="": {
                "content": "实体内容",
                "timestamp": datetime.now(UTC),
                "labels": ["Entity", "MemoryNode"],
            },
        )

        results = retriever._system2_deep_search(
            "q", OWNER, RetrievalOptions(top_k=5, view_names=["episodes"])
        )
        assert all(item.memory_id != "entity1" for item in results)

    def test_get_node_data_returns_labels(self):
        driver = _RecDriver(
            records=[
                {
                    "content": "x",
                    "summary": "",
                    "created_at": None,
                    "user_id": None,
                    "labels": ["Episode", "MemoryNode"],
                }
            ]
        )
        retriever = MemoryRetriever(neo4j_driver=driver, db=None)
        data = retriever._get_node_data("n1")
        assert data["labels"] == ["Episode", "MemoryNode"]


# ---------------------------------------------------------------- 检索入口


class TestPreferDeep:
    def test_prefer_deep_skips_digest(self):
        digest = _DigestStub(_REAL_DIGEST)
        retriever = MemoryRetriever(neo4j_driver=None, db=None, digest_manager=digest)

        results = retriever.retrieve("q", OWNER, RetrievalOptions(prefer_deep=True))

        assert results == []
        assert digest.calls == 0  # 未读摘要缓存

    def test_default_still_prefers_digest(self):
        digest = _DigestStub(_REAL_DIGEST)
        retriever = MemoryRetriever(neo4j_driver=None, db=None, digest_manager=digest)

        results = retriever.retrieve("q", OWNER)

        assert len(results) == 1 and results[0].source == "digest_cache"
        assert digest.calls == 1


class TestRoutePolicy:
    @pytest.mark.parametrize(
        "query,intent,views,prefer_deep",
        [
            ("你好", "greeting", ["profile"], False),
            ("上周我做了什么", "temporal", ["episodes"], True),
            ("他是我认识的人吗", "relational", ["relations"], True),
            ("帮我创建一个提醒", "action", ["profile", "skills"], False),
            (
                "回顾一下我的偏好",
                "reflection",
                ["profile", "episodes", "knowledge", "themes"],
                True,
            ),
            ("数据库索引", "factual", ["knowledge"], True),  # 默认 FACTUAL 0.5 → 深检
        ],
    )
    def test_rule_routing(self, query, intent, views, prefer_deep):
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        route = retriever.route_policy(query, OWNER)

        assert route.intent == intent
        assert route.views == views
        assert route.prefer_deep is prefer_deep

    def test_exception_falls_back_to_default_route(self, monkeypatch):
        from internal.service.memory import policy_router as mod

        def _boom(self, query):
            raise RuntimeError("classifier down")

        monkeypatch.setattr(mod.PolicyRouter, "classify_query", _boom)
        retriever = MemoryRetriever(neo4j_driver=None, db=None)

        route = retriever.route_policy("任意查询", OWNER)

        assert route.intent == "unknown"
        assert route.views == []
        assert route.prefer_deep is False


class TestRetrieveForChat:
    @staticmethod
    def _patch_deep(monkeypatch, results, captured):
        def _fake(self, query, owner_key, options):
            captured["views"] = list(options.view_names)
            captured["prefer_deep"] = options.prefer_deep
            return results

        monkeypatch.setattr(MemoryRetriever, "_system2_deep_search", _fake)

    def test_deep_first_for_temporal_and_passes_views(self, monkeypatch):
        captured: dict = {}
        self._patch_deep(
            monkeypatch,
            [RetrievalResult(memory_id="m1", content="片段内容", score=1.0, source="bm25")],
            captured,
        )
        digest = _DigestStub(_REAL_DIGEST)
        retriever = MemoryRetriever(neo4j_driver=None, db=None, digest_manager=digest)

        text = retriever.retrieve_for_chat("上周我做了什么", OWNER, max_chars=500)

        assert text == "片段内容"
        assert captured["views"] == ["episodes"]
        assert captured["prefer_deep"] is True
        assert digest.calls == 0  # 深检优先：未读摘要

    def test_deep_empty_falls_back_to_digest(self, monkeypatch):
        captured: dict = {}
        self._patch_deep(monkeypatch, [], captured)
        digest = _DigestStub(_REAL_DIGEST)
        retriever = MemoryRetriever(neo4j_driver=None, db=None, digest_manager=digest)

        text = retriever.retrieve_for_chat("上周我做了什么", OWNER, max_chars=500)

        assert "用户记忆摘要" in text  # 回退到 Digest
        assert captured["views"] == ["episodes"]

    def test_digest_first_for_greeting(self, monkeypatch):
        captured = {"deep_called": False}

        def _fake(self, query, owner_key, options):
            captured["deep_called"] = True
            return []

        monkeypatch.setattr(MemoryRetriever, "_system2_deep_search", _fake)
        digest = _DigestStub(_REAL_DIGEST)
        retriever = MemoryRetriever(neo4j_driver=None, db=None, digest_manager=digest)

        text = retriever.retrieve_for_chat("你好", OWNER, max_chars=500)

        assert "用户记忆摘要" in text  # GREETING 走摘要
        assert captured["deep_called"] is False  # GREETING 不触发深检

    def test_greeting_without_digest_falls_to_deep(self, monkeypatch):
        captured: dict = {}
        self._patch_deep(
            monkeypatch,
            [RetrievalResult(memory_id="m", content="兜底片段", score=1.0, source="semantic")],
            captured,
        )
        retriever = MemoryRetriever(neo4j_driver=None, db=None, digest_manager=_DigestStub(""))

        text = retriever.retrieve_for_chat("你好", OWNER, max_chars=500)

        assert text == "兜底片段"


# ---------------------------------------------------------------- 时间窗


class TestTimeRangeFilter:
    """``RetrievalOptions.time_range_days`` 必须下推到每个召回分支（不可被接收后忽略）。"""

    def test_cutoff_none_when_unset_or_zero(self):
        assert MemoryRetriever._resolve_time_cutoff(None) is None
        assert MemoryRetriever._resolve_time_cutoff(0) is None

    def test_cutoff_computed_from_days(self):
        cutoff = MemoryRetriever._resolve_time_cutoff(7)
        delta = datetime.now(UTC) - cutoff
        assert 6.9 < delta.total_seconds() / 86400 < 7.1

    def test_tkg_recall_adds_time_predicate(self):
        driver = _RecDriver()
        retriever = MemoryRetriever(neo4j_driver=driver, db=None)
        cutoff = MemoryRetriever._resolve_time_cutoff(3)

        retriever._tkg_recall("q", OWNER, 10, None, cutoff)

        cypher, params = driver.session_obj.calls[0]
        assert "node.created_at" in cypher and "$cutoff" in cypher
        assert params["cutoff"] == cutoff

    def test_tkg_recall_without_cutoff_has_no_predicate(self):
        driver = _RecDriver()
        retriever = MemoryRetriever(neo4j_driver=driver, db=None)

        retriever._tkg_recall("q", OWNER, 10, None, None)

        cypher, params = driver.session_obj.calls[0]
        assert "cutoff" not in cypher
        assert "cutoff" not in params

    def test_community_recall_adds_time_predicate(self):
        driver = _RecDriver()
        retriever = MemoryRetriever(neo4j_driver=driver, db=None)
        cutoff = MemoryRetriever._resolve_time_cutoff(3)

        retriever._community_recall("q", OWNER, 10, None, cutoff)

        cypher, params = driver.session_obj.calls[0]
        assert "node.created_at" in cypher and "$cutoff" in cypher
        assert params["cutoff"] == cutoff

    def test_vector_recall_adds_time_predicate(self, monkeypatch):
        captured: dict = {}
        TestVectorRecallViewFilter._patch_embedding_router(monkeypatch)

        class _Res:
            def all(self):
                return []

        class _Session:
            def execute(self, sql, params):
                captured["sql"] = str(sql)
                captured["params"] = params
                return _Res()

        class _Db:
            session = _Session()

        retriever = MemoryRetriever(neo4j_driver=None, db=_Db())
        cutoff = MemoryRetriever._resolve_time_cutoff(3)
        retriever._vector_recall([0.1] * 8, OWNER, 10, None, cutoff)

        assert "um.created_at >= :cutoff" in captured["sql"]
        assert captured["params"]["cutoff"] == cutoff

    def test_spread_node_older_than_cutoff_is_dropped(self, monkeypatch):
        from datetime import timedelta

        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        monkeypatch.setattr(
            MemoryRetriever,
            "_tkg_recall",
            lambda self, q, o, k, vf=None, tc=None: [
                RetrievalResult(memory_id="seed", content="种子", score=1.0, source="bm25")
            ],
        )
        monkeypatch.setattr(MemoryRetriever, "_embed_query", lambda self, q: None)
        monkeypatch.setattr(
            MemoryRetriever, "_community_recall", lambda self, q, o, k, vf=None, tc=None: []
        )
        monkeypatch.setattr(
            MemoryRetriever,
            "_graph_spread",
            lambda self, ids, top_k=20, owner_key="": [("old1", 1.0)],
        )
        monkeypatch.setattr(
            MemoryRetriever,
            "_get_node_data",
            lambda self, node_id, owner_key="": {
                "content": "很久以前的节点",
                "timestamp": datetime.now(UTC) - timedelta(days=30),
                "labels": ["Episode", "MemoryNode"],
            },
        )

        options = RetrievalOptions(top_k=5, time_range_days=7)
        results = retriever._system2_deep_search("q", OWNER, options)

        assert all(item.memory_id != "old1" for item in results)
