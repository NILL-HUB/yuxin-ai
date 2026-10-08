"""用户侧长期记忆召回（对话前注入 ``user_memory``）。

不变量：
1. 主体键必须是 ``for_user`` 形态（裸 UUID，不得退化成 admin:...）；
2. 召回是增强项：引擎关闭/异常/超时一律返回空结果（fail-open），绝不抛出；
3. 路由与视图限定（意图 → 视图子集 → 摘要/深检顺序）由
   ``MemoryRetriever.retrieve_for_chat`` 统一决定，本模块只构造主体键并透传。
"""
from uuid import uuid4

from internal.entity.memory_recall_entity import MemoryRecallOutcome


def test_returns_empty_when_engine_disabled(monkeypatch):
    from internal.config.memory_settings import settings as memory_settings
    from internal.service.memory import user_memory_recall

    monkeypatch.setattr(memory_settings, "memory_engine_enabled", False, raising=False)
    assert (
        user_memory_recall.recall_user_memory_for_chat(account_id=uuid4(), query="hi").text
        == ""
    )


def test_empty_query_returns_empty():
    from internal.service.memory import user_memory_recall

    assert (
        user_memory_recall.recall_user_memory_for_chat(account_id=uuid4(), query="   ").text
        == ""
    )


def test_owner_key_is_user_scoped(monkeypatch):
    """判别性：主体键必须是 for_user 形态（裸 UUID）。"""
    from internal.entity.memory_owner_entity import MemoryOwnerKey
    from internal.service.memory import user_memory_recall

    account_id = uuid4()
    captured = {}

    def _fake_text(*, owner_key, query, max_chars):
        captured["owner_key"] = owner_key
        return MemoryRecallOutcome(text="召回文本")

    monkeypatch.setattr(user_memory_recall, "_retrieve_memory", _fake_text)

    outcome = user_memory_recall.recall_user_memory_for_chat(
        account_id=account_id, query="我的偏好"
    )

    assert outcome.text == "召回文本"
    assert captured["owner_key"] == MemoryOwnerKey.for_user(account_id).to_key()
    assert not captured["owner_key"].startswith("admin:")


def test_char_budget_derived_from_max_tokens(monkeypatch):
    """max_tokens 按 4 字符/token 换算，下限 500。"""
    from internal.service.memory import user_memory_recall

    captured = {}

    def _fake_text(*, owner_key, query, max_chars):
        captured["max_chars"] = max_chars
        return MemoryRecallOutcome()

    monkeypatch.setattr(user_memory_recall, "_retrieve_memory", _fake_text)

    user_memory_recall.recall_user_memory_for_chat(
        account_id=uuid4(), query="q", max_tokens=1500
    )
    assert captured["max_chars"] == 6000

    user_memory_recall.recall_user_memory_for_chat(
        account_id=uuid4(), query="q", max_tokens=10
    )
    assert captured["max_chars"] == 500


def test_exception_is_swallowed_returns_empty(monkeypatch):
    """召回异常必须 fail-open（不得让对话挂掉）。"""
    from internal.service.memory import user_memory_recall

    def _boom(*args, **kwargs):
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(user_memory_recall, "_retrieve_memory", _boom)

    assert (
        user_memory_recall.recall_user_memory_for_chat(account_id=uuid4(), query="hi").text
        == ""
    )
