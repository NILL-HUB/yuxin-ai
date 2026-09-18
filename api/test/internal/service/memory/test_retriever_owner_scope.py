"""检索分支的主体过滤守卫。

不变量（P3b）：
1. PG 向量分支必须同时约束 `owner_type` 与归属列——只按 owner_account_id 过滤时，
   一旦将来 admin 行的该列被填成某账号，就会跨主体泄漏；
2. 用户主体下 Neo4j 两路的过滤值与改造前逐字节一致。
"""
from uuid import uuid4

from internal.entity.memory_owner_entity import MemoryOwnerKey


class _CapturedSQL:
    """替身 session：记录 SQL 文本与绑定参数，返回空结果。"""

    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((str(sql), params or {}))
        return self

    def all(self):
        return []

    def first(self):
        return None


class _FakeDB:
    def __init__(self):
        self.session = _CapturedSQL()


class _StubRouter:
    """替身向量路由：固定维度、建表必成功、固定表名。"""

    def resolve_system_default_dimension(self):
        return 1536

    def ensure_tables_for_dimension(self, dimension):
        return True

    def get_user_memory_table_name(self, dimension):
        return f"user_memory_embedding_{dimension}"


def test_vector_recall_scopes_by_owner_type(monkeypatch):
    from internal.service.memory.retriever import MemoryRetriever
    from internal.service.embedding_table_router import EmbeddingTableRouter

    monkeypatch.setattr(
        EmbeddingTableRouter,
        "get_instance",
        staticmethod(lambda db=None: _StubRouter()),
    )
    db = _FakeDB()
    retriever = MemoryRetriever(db=db)
    owner_key = MemoryOwnerKey.for_user(uuid4()).to_key()

    retriever._vector_recall(query_embedding=[0.1] * 8, owner_key=owner_key, top_k=3)

    sql_text = " ".join(s for s, _ in db.session.statements)
    assert "owner_type" in sql_text, "向量分支必须约束 owner_type"
    assert "owner_account_id" in sql_text
    # 谓词由 pg_sql_predicate 产出：owner_type 以字面量内联，绑定只含归属列
    assert "owner_type = 'user'" in sql_text, "用户分支须把 owner_type 钉为 'user'"
    bound = db.session.statements[0][1]
    assert "owner_account_id" in bound
    assert "owner_type" not in bound


def test_user_owner_key_round_trips_to_bare_uuid():
    """零变化根基：用户主体键就是裸 UUID。"""
    account_id = uuid4()
    assert MemoryOwnerKey.for_user(account_id).to_key() == str(account_id)


def test_vector_recall_scopes_by_admin_owner(monkeypatch):
    """admin 主体键（无 agent）经向量分支产出管理员级谓词。

    真库因 `owner_account_id NOT NULL` 查不到 admin 行属已登记预期（P3c 写入路径）；
    此处只离线断言谓词生成，不依赖数据。
    """
    from internal.service.memory.retriever import MemoryRetriever
    from internal.service.embedding_table_router import EmbeddingTableRouter

    monkeypatch.setattr(
        EmbeddingTableRouter,
        "get_instance",
        staticmethod(lambda db=None: _StubRouter()),
    )
    db = _FakeDB()
    retriever = MemoryRetriever(db=db)
    admin_id = uuid4()
    owner_key = MemoryOwnerKey.for_admin(admin_id).to_key()

    retriever._vector_recall(query_embedding=[0.1] * 8, owner_key=owner_key, top_k=3)

    sql_text = " ".join(s for s, _ in db.session.statements)
    assert "owner_type = 'admin'" in sql_text, "admin 分支须把 owner_type 钉为 'admin'"
    assert "owner_account_id" not in sql_text, "admin 主体不得按 account 过滤"
    assert "owner_agent_id IS NULL" in sql_text, "管理员级须用 IS NULL 区隔 Agent 级"
    bound = db.session.statements[0][1]
    assert bound["owner_admin_user_id"] == admin_id
    assert "owner_account_id" not in bound
    assert "owner_agent_id" not in bound


def test_vector_recall_scopes_by_admin_agent_owner(monkeypatch):
    """admin + agent 主体键经向量分支产出两级隔离谓词。"""
    from internal.service.memory.retriever import MemoryRetriever
    from internal.service.embedding_table_router import EmbeddingTableRouter

    monkeypatch.setattr(
        EmbeddingTableRouter,
        "get_instance",
        staticmethod(lambda db=None: _StubRouter()),
    )
    db = _FakeDB()
    retriever = MemoryRetriever(db=db)
    admin_id = uuid4()
    agent_id = uuid4()
    owner_key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).to_key()

    retriever._vector_recall(query_embedding=[0.1] * 8, owner_key=owner_key, top_k=3)

    sql_text = " ".join(s for s, _ in db.session.statements)
    assert "owner_type = 'admin'" in sql_text
    assert "owner_agent_id = :owner_agent_id" in sql_text
    assert "IS NULL" not in sql_text
    bound = db.session.statements[0][1]
    assert bound["owner_admin_user_id"] == admin_id
    assert bound["owner_agent_id"] == agent_id


def _make_neo4j_stub():
    """替身 Neo4j：`session.run` 一旦被调用即抛错——非法主体键不得下推 Cypher。"""

    class _StubSession:
        def run(self, cypher, params):
            raise AssertionError("非法主体键不应下推到 Cypher")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _StubDriver:
        def session(self):
            return _StubSession()

    return _StubDriver()


def test_tkg_recall_invalid_owner_key_returns_empty(caplog):
    """非法主体键必须走专用 except：返回 [] 且日志明确指向「非法主体键」，
    而非被通用 except 吞成「检索失败」（后者同样返回 []，无法区分）。"""
    import logging

    from internal.service.memory.retriever import MemoryRetriever

    retriever = MemoryRetriever(neo4j_driver=_make_neo4j_stub())

    with caplog.at_level(logging.WARNING):
        assert retriever._tkg_recall("q", "not-a-uuid", 5) == []

    assert "非法主体键" in caplog.text, "必须走专用 except 分支（否则日志为『检索失败』）"


def test_vector_recall_invalid_owner_key_returns_empty(monkeypatch, caplog):
    """向量分支非法主体键：返回 []、日志含「非法主体键」，且 SQL 未下推。"""
    import logging

    from internal.service.memory.retriever import MemoryRetriever
    from internal.service.embedding_table_router import EmbeddingTableRouter

    monkeypatch.setattr(
        EmbeddingTableRouter,
        "get_instance",
        staticmethod(lambda db=None: _StubRouter()),
    )
    db = _FakeDB()
    retriever = MemoryRetriever(db=db)

    with caplog.at_level(logging.WARNING):
        assert (
            retriever._vector_recall(
                query_embedding=[0.1] * 8, owner_key="not-a-uuid", top_k=3
            )
            == []
        )

    assert "非法主体键" in caplog.text, "必须走专用 except 分支（否则日志为『向量检索失败』）"
    assert db.session.statements == [], "非法主体键不得下推 SQL"


def test_community_recall_invalid_owner_key_returns_empty(caplog):
    """Community 分支非法主体键：返回 [] 且日志含「非法主体键」，
    不得被通用 except 吞成「Community 主题召回失败」。"""
    import logging

    from internal.service.memory.retriever import MemoryRetriever

    retriever = MemoryRetriever(neo4j_driver=_make_neo4j_stub())

    with caplog.at_level(logging.WARNING):
        assert retriever._community_recall("q", "not-a-uuid", 5) == []

    assert "非法主体键" in caplog.text, "必须走专用 except 分支（否则日志为『主题召回失败』）"
