"""冷存储归属主体化（ADMIN-P3c-3 / C4）。

不变量：
1. 归档路径片段必须由主体键产出（admin 主体不得退化为裸 uuid 路径）；
2. 回热写回必须按主体属性（admin 节点不得被写裸 user_id）。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import (
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    MemoryOwnerKey,
)


class _Session:
    def __init__(self, sink):
        self._sink = sink

    def run(self, cypher, params=None, **kwargs):
        self._sink.append((cypher, params if params is not None else kwargs))
        return self

    def consume(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Driver:
    def __init__(self):
        self.calls = []

    def session(self):
        return _Session(self.calls)


def test_archive_accepts_admin_key_without_crashing():
    """归档必须能解析 admin 主体键（不再把裸 admin 串当路径/或抛错）。

    ADMIN-P3c-4（C4）：archive 改走 ``upload_local_file(source_path, target_key)``
    保 target_key——对象键 ``{prefix}{owner}/{year}/{month}/{node_id}.json.gz`` 真正
    落盘（此前 upload_bytes_without_record 只收 basename，主体路径丢失）。
    """
    from internal.config.memory_settings import settings
    from internal.model.memory_models import ColdStorageEntry
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    admin_id = uuid4()
    node_id = uuid4()
    mgr = ColdStorageManager.__new__(ColdStorageManager)
    captured = {}

    class _Storage:
        def upload_local_file(self, *, source_path, target_key):
            captured["target_key"] = target_key
            return target_key

        def get_file_url(self, key):
            return f"https://url/{key}"

    mgr._get_storage_service = lambda: _Storage()
    mgr._config = settings.cold_storage

    entry = ColdStorageEntry(node_id=node_id, user_id=f"admin:{admin_id}", content="c")
    url = mgr.archive(entry)

    assert url == f"https://url/{captured['target_key']}"
    assert f"admin:{admin_id}" in captured["target_key"], (
        "对象键必须含 admin 主体路径片段（C4 保 key）"
    )
    assert f"{node_id}.json.gz" in captured["target_key"]


def test_archive_user_basename_unchanged():
    """用户主体：对象键与历史路径语义一致（{prefix}{uuid}/{year}/{month}/{node_id}.json.gz）。"""
    from internal.config.memory_settings import settings
    from internal.model.memory_models import ColdStorageEntry
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    node_id = uuid4()
    account_id = uuid4()
    mgr = ColdStorageManager.__new__(ColdStorageManager)
    captured = {}

    class _Storage:
        def upload_local_file(self, *, source_path, target_key):
            captured["target_key"] = target_key
            return target_key

        def get_file_url(self, key):
            return f"https://url/{key}"

    mgr._get_storage_service = lambda: _Storage()
    mgr._config = settings.cold_storage

    mgr.archive(
        ColdStorageEntry(node_id=node_id, user_id=str(account_id), content="c")
    )

    assert captured["target_key"].startswith(settings.cold_storage.s3_prefix)
    assert str(account_id) in captured["target_key"]
    assert captured["target_key"].endswith(f"{node_id}.json.gz")


def test_archive_owner_cold_nodes_queries_marks_and_archives():
    """C4 接线：archive_owner_cold_nodes 查 cold 节点 → 归档 → 标记 archived_at。"""
    from internal.config.memory_settings import settings
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    class _Storage:
        def upload_local_file(self, *, source_path, target_key):
            return target_key

        def get_file_url(self, key):
            return f"https://url/{key}"

    # 模拟 cold 节点查询返回：两个待归档节点
    cold_records = [
        {"node_id": str(uuid4()), "content": "c1", "weight": 0.1, "cooccurrence_count": 0},
        {"node_id": str(uuid4()), "content": "c2", "weight": 0.2, "cooccurrence_count": 1},
    ]

    class _QueryResult:
        def __init__(self, records):
            self._records = records

        def __iter__(self):
            return iter(self._records)

        def consume(self):
            return self

    class _ArchivingSession:
        def __init__(self, cold_records):
            self._cold_records = cold_records
            self.calls = []

        def run(self, cypher, params=None, **kwargs):
            self.calls.append((cypher, params if params is not None else kwargs))
            if "storage_tier = 'cold'" in cypher:
                return _QueryResult(self._cold_records)
            return _QueryResult([])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _Driver2:
        def __init__(self):
            self.session_obj = _ArchivingSession(cold_records)

        def session(self):
            return self.session_obj

    driver2 = _Driver2()
    mgr2 = ColdStorageManager(neo4j_driver=driver2)
    mgr2._get_storage_service = lambda: _Storage()
    mgr2._config = settings.cold_storage

    account_id = uuid4()
    result = mgr2.archive_owner_cold_nodes(str(account_id))

    assert result["archived"] == 2
    # 归档标记：SET n.archived_at / n.is_active=false 的 Cypher 恰好 2 次
    # （查询自身的 `archived_at IS NULL` 条件不计数）
    mark_cyphers = [c for c, _ in driver2.session_obj.calls if "SET n.archived_at" in c]
    assert len(mark_cyphers) == 2
    # 查询含主体谓词（用户态 user_id）
    query_cyphers = [c for c, _ in driver2.session_obj.calls if "storage_tier = 'cold'" in c]
    assert query_cyphers
    assert "user_id = $user_id" in query_cyphers[0]


def test_archive_owner_cold_nodes_admin_scopes_query():
    """C4：admin 主体的 cold 节点查询按 admin 属性约束。"""
    from internal.config.memory_settings import settings
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    admin_id = uuid4()

    class _Storage:
        def upload_local_file(self, *, source_path, target_key):
            return target_key

        def get_file_url(self, key):
            return key

    class _QueryResult:
        def __init__(self):
            pass

        def __iter__(self):
            return iter([])

    class _Session2:
        def __init__(self):
            self.calls = []

        def run(self, cypher, params=None, **kwargs):
            self.calls.append((cypher, params if params is not None else kwargs))
            return _QueryResult()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _Driver3:
        def __init__(self):
            self.session_obj = _Session2()

        def session(self):
            return self.session_obj

    driver = _Driver3()
    mgr = ColdStorageManager(neo4j_driver=driver)
    mgr._get_storage_service = lambda: _Storage()
    mgr._config = settings.cold_storage

    result = mgr.archive_owner_cold_nodes(f"admin:{admin_id}")

    assert result["archived"] == 0
    query_cyphers = [c for c, _ in driver.session_obj.calls if "storage_tier = 'cold'" in c]
    assert query_cyphers
    assert "admin_user_id = $admin_user_id" in query_cyphers[0]


def test_restore_to_neo4j_admin_writes_admin_props():
    from internal.model.memory_models import ColdStorageEntry
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    driver = _Driver()
    admin_id = uuid4()
    mgr = ColdStorageManager(neo4j_driver=driver)

    mgr._restore_to_neo4j(
        ColdStorageEntry(node_id=uuid4(), user_id=f"admin:{admin_id}", content="c")
    )

    cypher, params = driver.calls[0]
    assert "admin_user_id" in cypher
    assert params["admin_user_id"] == str(admin_id)
    assert params["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL
    assert "user_id" not in params


def test_restore_to_neo4j_user_unchanged():
    from internal.model.memory_models import ColdStorageEntry
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    driver = _Driver()
    account_id = uuid4()
    mgr = ColdStorageManager(neo4j_driver=driver)

    mgr._restore_to_neo4j(
        ColdStorageEntry(node_id=uuid4(), user_id=str(account_id), content="c")
    )

    _cypher, params = driver.calls[0]
    assert params["user_id"] == str(account_id)


def test_module_documents_unwired_status():
    """死模块披露：docstring 必须写明当前无生产调用方（AGENTS.md 诚实披露）。"""
    import pathlib

    src = pathlib.Path(
        "internal/service/memory/cold_storage_manager.py"
    ).read_text(encoding="utf-8")

    assert "无任何生产调用方" in src or "未接入" in src
    assert "list_user_archives" in src
