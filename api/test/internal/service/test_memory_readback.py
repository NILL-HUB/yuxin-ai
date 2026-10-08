"""记忆读回闭环（_start_user_memory_recall → result）单元测试。

契约（2026-10-05 起）：助手链路在会话开始处**启动**召回（守护线程句柄），
在注入点再 ``result()`` 取回——早启动 + 晚 join，把深检抖动藏进下游等待。
本文件覆盖：
- 引擎关闭 / 空 query → 空文本（fail-open）
- System 1（Digest 快路径）命中 → 返回 digest 文本
- System 2（MemoryRetriever 深度检索）命中 → 拼接 top 内容
- 检索异常 / 依赖缺失 → 空文本（fail-open，不影响对话）

契约（2026-10-05 起）：召回返回 ``MemoryRecallOutcome``（文本 + 待确认机密条目 +
确认 id），不再是裸字符串——机密记忆确认卡片需要结构化字段，裸字符串无法承载。
"""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.assistant_agent_service import AssistantAgentService
from internal.service.memory.retriever import RetrievalResult

_TEST_ACCOUNT_ID = str(uuid4())


@contextmanager
def _null_context():
    yield


class _FakeDigestManager:
    def __init__(self, text: str | None):
        self._text = text

    def get_digest(self, _user_id: str) -> str | None:
        return self._text


class _FakeRetriever:
    """替身：不走真实 Neo4j/pgvector，直接按预设返回 System1/System2 结果。"""

    def __init__(self, digest_manager=None, digest_text: str | None = None, results=None):
        self._digest_manager = digest_manager
        self._digest_text = digest_text
        self._results = results or []

    def _system1_fast_path(self, _query: str, _user_id: str) -> str | None:
        if self._digest_manager is not None:
            return self._digest_manager.get_digest(_user_id)
        return self._digest_text

    def retrieve(self, _query: str, _user_id: str, _options=None):
        if self._results == "raise":
            raise RuntimeError("模拟检索故障")
        return self._results

    def retrieve_for_chat(self, query, owner_key, **kwargs):
        """按新契约返回文本并回填 status["withheld"]（无机密条目 → 空列表）。"""
        status = kwargs.get("status")
        if status is not None:
            status["withheld"] = []
        digest = self._system1_fast_path(query, owner_key)
        if digest:
            return digest
        results = self.retrieve(query, owner_key)
        return chr(10).join(
            str(getattr(item, "content", "") or "") for item in results or []
        )


def _service():
    return AssistantAgentService(
        db=SimpleNamespace(session=SimpleNamespace()),
        faiss_service=None,
        conversation_service=None,
        redis_client=None,
    )


def _patch_deps(monkeypatch, *, digest_text=None, results=None, engine_enabled=True):
    """把召回闭包内的依赖替换为替身。"""
    from internal.config import memory_settings as memory_settings_module

    monkeypatch.setattr(
        memory_settings_module.settings,
        "memory_engine_enabled",
        engine_enabled,
    )

    fake_digest = _FakeDigestManager(digest_text)
    fake_retriever = _FakeRetriever(
        digest_manager=fake_digest,
        results=results,
    )

    import app.http.app as app_module
    import app.http.asgi_app as asgi_app

    class _FakeFlaskApp:
        def app_context(self):
            return _null_context()

    monkeypatch.setattr(app_module, "app", _FakeFlaskApp())

    class _FakeConfirmations:
        """确认服务替身：无授权、创建记录返回固定 id。"""

        def authorized_ids(self, _owner_key):
            return frozenset()

        def create(self, *, owner_key, items):
            return "conf-1"

    def _fake_get_service(cls):
        if cls.__name__ == "MemoryReadConfirmationService":
            return _FakeConfirmations()
        return fake_digest

    monkeypatch.setattr(asgi_app, "_get_service", _fake_get_service)

    def _fake_retriever_factory(digest_manager=None):
        # 返回替身，跳过 MemoryRetriever 真实构造
        retriever = _FakeRetriever(digest_manager=digest_manager, results=results)
        retriever._digest_text = digest_text
        return retriever

    monkeypatch.setattr(
        "internal.service.memory.retriever.MemoryRetriever",
        _fake_retriever_factory,
    )
    # 上面直接替换类会在闭包 import 时生效（import 后取模块属性）
    return fake_retriever


class TestRetrieveUserMemoryForChat:
    def test_returns_empty_when_engine_disabled(self, monkeypatch):
        _patch_deps(monkeypatch, digest_text="有记忆", engine_enabled=False)
        service = _service()
        outcome = service._start_user_memory_recall(
            account_id=_TEST_ACCOUNT_ID, query="你好", conversation_id="c1"
        ).result()
        assert outcome.text == ""

    def test_returns_empty_when_query_blank(self, monkeypatch):
        _patch_deps(monkeypatch, digest_text="有记忆", engine_enabled=True)
        service = _service()
        outcome = service._start_user_memory_recall(
            account_id=_TEST_ACCOUNT_ID, query="   ", conversation_id="c1"
        ).result()
        assert outcome.text == ""

    def test_system1_digest_hit_returns_digest(self, monkeypatch):
        _patch_deps(monkeypatch, digest_text="用户喜欢 Python", engine_enabled=True)
        service = _service()
        outcome = service._start_user_memory_recall(
            account_id=_TEST_ACCOUNT_ID, query="帮我写代码", conversation_id="c1"
        ).result(3)
        assert "Python" in outcome.text

    def test_system2_fallback_returns_joined_results(self, monkeypatch):
        _patch_deps(
            monkeypatch,
            digest_text=None,
            results=[
                RetrievalResult(memory_id="m1", content="用户偏好简洁回答", score=0.9),
                RetrievalResult(memory_id="m2", content="上周讨论过部署方案", score=0.8),
            ],
            engine_enabled=True,
        )
        service = _service()
        outcome = service._start_user_memory_recall(
            account_id=_TEST_ACCOUNT_ID, query="有什么偏好", conversation_id="c1"
        ).result(3)
        assert "偏好简洁" in outcome.text
        assert "部署方案" in outcome.text

    def test_fail_open_when_retrieve_raises(self, monkeypatch):
        _patch_deps(monkeypatch, digest_text=None, results="raise", engine_enabled=True)
        service = _service()
        outcome = service._start_user_memory_recall(
            account_id=_TEST_ACCOUNT_ID, query="触发异常", conversation_id="c1"
        ).result(3)
        assert outcome.text == ""
        assert outcome.needs_confirmation is False
