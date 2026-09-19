"""admin / Agent 主体记忆召回（ADMIN-P3c-2）。

不变量：
1. 主体键必须是 `admin:{admin_uuid}[:{agent_uuid}]`（不得退化成 for_user）；
2. 召回是增强项：引擎关闭/异常/超时一律返回空串（fail-open），绝不抛出。
"""
from uuid import uuid4

import pytest


def test_returns_empty_when_engine_disabled(monkeypatch):
    from internal.config.memory_settings import settings as memory_settings
    from internal.service.memory import admin_memory_recall

    monkeypatch.setattr(memory_settings, "memory_engine_enabled", False, raising=False)
    assert admin_memory_recall.recall_admin_agent_memory_for_chat(
        admin_user_id=uuid4(), query="hi"
    ) == ""


def test_empty_query_returns_empty():
    from internal.service.memory import admin_memory_recall

    assert admin_memory_recall.recall_admin_agent_memory_for_chat(
        admin_user_id=uuid4(), query="   "
    ) == ""


def test_owner_key_is_admin_scoped(monkeypatch):
    """判别性：主体键必须是 admin 形态（含 agent 时三级）。"""
    from internal.service.memory import admin_memory_recall
    from internal.entity.memory_owner_entity import MemoryOwnerKey

    admin_id, agent_id = uuid4(), uuid4()
    captured = {}

    def _fake_deep(*, owner_key, query):
        captured["owner_key"] = owner_key
        return "召回文本"

    monkeypatch.setattr(
        admin_memory_recall, "_retrieve_digest", lambda *, owner_key, query: ""
    )
    monkeypatch.setattr(admin_memory_recall, "_retrieve_deep", _fake_deep)

    text = admin_memory_recall.recall_admin_agent_memory_for_chat(
        admin_user_id=admin_id, agent_id=agent_id, query="我的偏好"
    )

    assert text == "召回文本"
    assert captured["owner_key"] == MemoryOwnerKey.for_admin(
        admin_id, agent_id=agent_id
    ).to_key()
    assert captured["owner_key"].startswith("admin:")


def test_admin_level_key_has_no_agent_segment(monkeypatch):
    """管理员级（无 agent）主体键是两级 admin:{uuid}。"""
    from internal.service.memory import admin_memory_recall

    admin_id = uuid4()
    captured = {}

    monkeypatch.setattr(
        admin_memory_recall, "_retrieve_digest", lambda *, owner_key, query: ""
    )
    monkeypatch.setattr(
        admin_memory_recall,
        "_retrieve_deep",
        lambda *, owner_key, query: captured.setdefault("owner_key", owner_key) or "",
    )

    admin_memory_recall.recall_admin_agent_memory_for_chat(
        admin_user_id=admin_id, query="hi"
    )

    assert captured["owner_key"] == f"admin:{admin_id}"
    assert captured["owner_key"].count(":") == 1


def test_exception_is_swallowed_returns_empty(monkeypatch):
    """召回异常必须 fail-open（不得让 admin 对话挂掉）。"""
    from internal.service.memory import admin_memory_recall

    def _boom(*args, **kwargs):
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(admin_memory_recall, "_retrieve_digest", _boom)

    assert admin_memory_recall.recall_admin_agent_memory_for_chat(
        admin_user_id=uuid4(), query="hi"
    ) == ""
