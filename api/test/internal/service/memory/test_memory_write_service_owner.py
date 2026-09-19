"""记忆写入的 owner 透传（ADMIN-P3c-2）。

不变量：
1. 传入 owner_key 时，三层决策后的 ledger_writer 调用必须带上它（否则 admin
   写路径退化成 for_user / 空主体——P3c-1 的断链点）；
2. 不传 owner_key 时（用户端既有路径）行为不变。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import MemoryOwnerKey


class _SpyLedger:
    def __init__(self):
        self.calls = []

    def write_full_path(self, **kw):
        self.calls.append(("full", kw))
        return {"status": "full"}

    def write_summary_path(self, **kw):
        self.calls.append(("summary", kw))
        return {"status": "summary"}

    def write_stats_path(self, **kw):
        self.calls.append(("stats", kw))
        return {"status": "stats"}


def _service(ledger):
    """构造短路到 FULL 路径的 MemoryWriteService（聚焦 owner 透传）。"""
    from internal.model.memory_models import WritePath
    from internal.service.memory.memory_write_service import MemoryWriteService

    svc = MemoryWriteService.__new__(MemoryWriteService)
    svc.ledger_writer = ledger

    class _Det:
        is_explicit = False
        category = None
        polarity = None
        confidence = 0.0
        fallback_used = False
        subject = None

    class _Conflict:
        conflict_detected = False
        conflict_type = None
        resolved_count = 0
        superseded_ids = []

    class _Salience:
        write_path = WritePath.FULL
        total_score = 0.9

    svc.explicit_detector = type("D", (), {"detect": lambda self, e: _Det()})()
    svc.conflict_resolver = type("R", (), {"resolve": lambda self, e, d: _Conflict()})()
    svc.salience_scorer = type(
        "S", (), {"score": lambda self, e, explicitness=None: _Salience()}
    )()
    svc.entity_extractor = type(
        "E",
        (),
        {
            "extract_entities_and_relations": lambda self, c, max_entities=None: ([], []),
            "generate_summary": lambda self, c: "",
        },
    )()
    svc.embeddings_service = type(
        "M", (), {"embeddings": type("X", (), {"embed_query": lambda self, t: [0.1]})()}
    )()
    return svc


def _event(user_id="ignored"):
    from internal.model.memory_models import EventSource, MemoryEvent

    return MemoryEvent(content="内容", source=EventSource.SYSTEM_OBSERVATION, user_id=user_id)


def test_write_from_event_passes_owner_key(monkeypatch):
    from internal.config.memory_settings import settings

    monkeypatch.setattr(settings, "memory_engine_enabled", True, raising=False)
    ledger = _SpyLedger()
    svc = _service(ledger)
    admin_id = uuid4()

    svc.write_from_event(_event(), owner_key=MemoryOwnerKey.for_admin(admin_id))

    assert ledger.calls, "必须下推到 ledger_writer"
    _kind, kw = ledger.calls[0]
    assert kw["owner_key"] == MemoryOwnerKey.for_admin(admin_id)
    assert kw["owner_key"].owner_type.value == "admin"


def test_write_from_event_without_owner_key_keeps_legacy(monkeypatch):
    from internal.config.memory_settings import settings

    monkeypatch.setattr(settings, "memory_engine_enabled", True, raising=False)
    ledger = _SpyLedger()
    svc = _service(ledger)

    svc.write_from_event(_event(str(uuid4())))

    _kind, kw = ledger.calls[0]
    assert kw.get("owner_key") is None, "用户端既有路径不得被强行注入 admin 键"


def test_write_admin_conversation_uses_admin_key(monkeypatch):
    """便捷入口必须构造 admin 主体键（含 agent 时两级隔离）。"""
    from internal.config.memory_settings import settings
    from internal.entity.memory_owner_entity import MemoryOwnerKey as MOK

    monkeypatch.setattr(settings, "memory_engine_enabled", True, raising=False)
    ledger = _SpyLedger()
    svc = _service(ledger)
    admin_id, agent_id = uuid4(), uuid4()

    svc.write_admin_conversation(
        admin_user_id=admin_id,
        agent_id=agent_id,
        query="记住我偏好简洁",
        ai_response="好的",
        conversation_id="conv-1",
    )

    _kind, kw = ledger.calls[0]
    assert kw["owner_key"] == MOK.for_admin(admin_id, agent_id=agent_id)


def test_write_admin_conversation_skips_without_response(monkeypatch):
    from internal.config.memory_settings import settings

    monkeypatch.setattr(settings, "memory_engine_enabled", True, raising=False)
    ledger = _SpyLedger()
    svc = _service(ledger)

    result = svc.write_admin_conversation(
        admin_user_id=uuid4(), query="q", ai_response="", conversation_id="c"
    )

    assert result is None
    assert ledger.calls == []
