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

    注：统一存储端口 ``upload_bytes_without_record(filename, content, mime_type,
    folder)`` 只接收**文件名**与 folder，``archive`` 当前只上传 basename
    （folder="memory-cold"），故 owner 路径片段暂未真正落到对象路径——
    这是端口的既有约束，已在模块 docstring 披露（见 test_module_documents_unwired_status）。
    本用例锁定可观测事实：admin 键可被解析、归档不抛错、且域名不变。
    """
    from internal.config.memory_settings import settings
    from internal.model.memory_models import ColdStorageEntry
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    admin_id = uuid4()
    mgr = ColdStorageManager.__new__(ColdStorageManager)
    captured = {}

    class _Storage:
        def upload_bytes_without_record(self, filename, content, folder):
            captured["filename"] = filename
            captured["folder"] = folder
            return "url"

    mgr._get_storage_service = lambda: _Storage()
    mgr._config = settings.cold_storage

    entry = ColdStorageEntry(
        node_id=uuid4(), user_id=f"admin:{admin_id}", content="c"
    )
    url = mgr.archive(entry)

    assert url == "url"
    assert captured["filename"].endswith(".json.gz")
    assert captured["folder"] == "memory-cold"


def test_archive_user_basename_unchanged():
    """用户主体：归档 basename 与历史逐字节一致（零变化）。"""
    from internal.config.memory_settings import settings
    from internal.model.memory_models import ColdStorageEntry
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    node_id = uuid4()
    mgr = ColdStorageManager.__new__(ColdStorageManager)
    captured = {}

    class _Storage:
        def upload_bytes_without_record(self, filename, content, folder):
            captured["filename"] = filename
            return "url"

    mgr._get_storage_service = lambda: _Storage()
    mgr._config = settings.cold_storage

    mgr.archive(
        ColdStorageEntry(node_id=node_id, user_id=str(uuid4()), content="c")
    )

    assert captured["filename"] == f"{node_id}.json.gz"


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
