from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

from internal.core.memory.token_buffer_memory import TokenBufferMemory
import internal.core.memory.token_buffer_memory as memory_module


class _FakeMessageQuery:
    def __init__(self, messages):
        self.messages = messages
        self.limit_count = None

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def all(self):
        return self.messages


class _FakeSession:
    def __init__(self, messages):
        self.query_obj = _FakeMessageQuery(messages)

    def query(self, _model):
        return self.query_obj


class _FakeModelInstance:
    def __init__(self):
        self.calls = []

    def convert_to_human_message(self, query, image_urls):
        self.calls.append((query, image_urls))
        return HumanMessage(content=f"human:{query}")


def test_get_history_prompt_messages_should_return_empty_when_conversation_missing():
    memory = TokenBufferMemory(
        db=SimpleNamespace(session=_FakeSession(messages=[])),
        conversation=None,
        model_instance=_FakeModelInstance(),
    )

    assert memory.get_history_prompt_messages() == []


def test_get_history_prompt_messages_should_build_prompt_and_trim(monkeypatch):
    model_instance = _FakeModelInstance()
    raw_messages = [
        SimpleNamespace(query="q2", image_urls=["u2"], answer="a2"),
        SimpleNamespace(query="q1", image_urls=["u1"], answer="a1"),
    ]
    session = _FakeSession(messages=raw_messages)
    memory = TokenBufferMemory(
        db=SimpleNamespace(session=session),
        conversation=SimpleNamespace(id=1),
        model_instance=model_instance,
    )
    captured = {}

    def _fake_trim_messages(messages, max_tokens, token_counter, strategy, start_on, end_on):
        captured["messages"] = messages
        captured["max_tokens"] = max_tokens
        captured["token_counter"] = token_counter
        captured["strategy"] = strategy
        captured["start_on"] = start_on
        captured["end_on"] = end_on
        return ["trimmed"]

    monkeypatch.setattr(memory_module, "trim_messages", _fake_trim_messages)

    result = memory.get_history_prompt_messages(max_token_limit=321, message_limit=2)

    assert result == ["trimmed"]
    assert session.query_obj.limit_count == 2
    assert model_instance.calls == [("q1", ["u1"]), ("q2", ["u2"])]
    assert isinstance(captured["messages"][0], HumanMessage)
    assert isinstance(captured["messages"][1], AIMessage)
    assert captured["max_tokens"] == 321
    assert captured["token_counter"] is model_instance
    assert captured["strategy"] == "last"
    assert captured["start_on"] == "human"
    assert captured["end_on"] == "ai"


def test_build_context_should_assemble_three_layers(monkeypatch):
    memory = TokenBufferMemory(db=SimpleNamespace(), conversation=None, model_instance=None)
    monkeypatch.setattr(memory, "_get_conversation", lambda cid: SimpleNamespace(id=cid, summary="s"))
    monkeypatch.setattr(memory, "extract_recent", lambda cid: [HumanMessage("hi"), AIMessage("yo")])
    monkeypatch.setattr(memory, "get_distant_summary", lambda conv: "远期摘要")
    monkeypatch.setattr(memory, "get_relevant_facts", lambda acc, q: ["事实A", "事实B"])

    context = memory.build_context(uuid4(), "query", SimpleNamespace(id=uuid4()))

    assert set(context.keys()) == {
        "recent_messages", "distant_summary", "relevant_facts", "combined_token_count"
    }
    assert len(context["recent_messages"]) == 2
    assert isinstance(context["recent_messages"][0], HumanMessage)
    assert isinstance(context["recent_messages"][1], AIMessage)
    assert context["distant_summary"] == "远期摘要"
    assert context["relevant_facts"] == ["事实A", "事实B"]
    assert context["combined_token_count"] >= 0


def test_extract_recent_should_query_recent_messages_and_convert():
    raw_messages = [
        SimpleNamespace(query="q2", image_urls=["u2"], answer="a2"),
        SimpleNamespace(query="q1", image_urls=["u1"], answer="a1"),
    ]
    session = _FakeSession(messages=raw_messages)
    model_instance = _FakeModelInstance()
    memory = TokenBufferMemory(
        db=SimpleNamespace(session=session),
        conversation=None,
        model_instance=model_instance,
    )

    result = memory.extract_recent(conversation_id=1)

    assert session.query_obj.limit_count == TokenBufferMemory.RECENT_MESSAGE_LIMIT
    assert len(result) == 4
    assert isinstance(result[0], HumanMessage)
    assert isinstance(result[1], AIMessage)
    assert model_instance.calls == [("q1", ["u1"]), ("q2", ["u2"])]


def test_get_distant_summary_should_return_empty_when_within_recent_limit(monkeypatch):
    memory = TokenBufferMemory(db=SimpleNamespace(), conversation=None, model_instance=None)
    conversation = SimpleNamespace(id=1, summary="摘要", distant_summaries=[])
    monkeypatch.setattr(memory, "_count_conversation_messages", lambda cid: TokenBufferMemory.RECENT_MESSAGE_LIMIT)

    assert memory.get_distant_summary(conversation) == ""


def test_get_distant_summary_should_combine_segments_when_exceeding_recent_limit(monkeypatch):
    memory = TokenBufferMemory(db=SimpleNamespace(), conversation=None, model_instance=None)
    conversation = SimpleNamespace(
        id=1, summary="最新摘要", distant_summaries=["早期段1", "早期段2"]
    )
    monkeypatch.setattr(memory, "_count_conversation_messages", lambda cid: TokenBufferMemory.RECENT_MESSAGE_LIMIT + 5)

    result = memory.get_distant_summary(conversation)

    assert "早期段1" in result
    assert "早期段2" in result
    assert "最新摘要" in result


def test_get_relevant_facts_should_recall_via_user_memory_service(monkeypatch):
    memory = TokenBufferMemory(db=SimpleNamespace(), conversation=None, model_instance=None)
    account = SimpleNamespace(id=uuid4())
    captured = {}

    class _FakeUserMemoryService:
        def __init__(self, db=None):
            pass

        def recall_relevant_memories(self, acc, query, top_k=5):
            captured["account"] = acc
            captured["query"] = query
            captured["top_k"] = top_k
            return [{"content": "偏好Python"}, {"content": "关注测试"}, {"other": "x"}]

    monkeypatch.setattr(
        "internal.service.scoped_knowledge_service.UserMemoryService",
        _FakeUserMemoryService,
    )

    result = memory.get_relevant_facts(account, "最近在做什么")

    assert result == ["偏好Python", "关注测试"]
    assert captured["top_k"] == 5
    assert captured["query"] == "最近在做什么"
    assert captured["account"] is account


def test_get_relevant_facts_should_degrade_to_empty_when_recall_fails(monkeypatch):
    memory = TokenBufferMemory(db=SimpleNamespace(), conversation=None, model_instance=None)
    account = SimpleNamespace(id=uuid4())

    class _FailingUserMemoryService:
        def __init__(self, db=None):
            pass

        def recall_relevant_memories(self, acc, query, top_k=5):
            raise RuntimeError("向量服务不可用")

    monkeypatch.setattr(
        "internal.service.scoped_knowledge_service.UserMemoryService",
        _FailingUserMemoryService,
    )

    assert memory.get_relevant_facts(account, "query") == []


def test_get_total_token_budget_should_use_model_max_tokens():
    memory = TokenBufferMemory(
        db=SimpleNamespace(),
        conversation=None,
        model_instance=SimpleNamespace(max_tokens=10000),
    )

    assert memory._get_total_token_budget() == int(10000 * TokenBufferMemory.CONTEXT_TOKEN_RATIO)


def test_get_total_token_budget_should_fallback_to_default_when_model_max_tokens_missing():
    memory = TokenBufferMemory(
        db=SimpleNamespace(),
        conversation=None,
        model_instance=None,
        language_model_service=None,
    )

    assert memory._get_total_token_budget() == int(
        TokenBufferMemory.DEFAULT_MODEL_MAX_TOKENS * TokenBufferMemory.CONTEXT_TOKEN_RATIO
    )


def test_build_context_should_allocate_recent_budget_as_remaining(monkeypatch):
    memory = TokenBufferMemory(
        db=SimpleNamespace(),
        conversation=None,
        model_instance=SimpleNamespace(max_tokens=10000),
    )
    monkeypatch.setattr(memory, "_get_conversation", lambda cid: SimpleNamespace(id=cid, summary="", distant_summaries=[]))
    monkeypatch.setattr(memory, "extract_recent", lambda cid: [])
    monkeypatch.setattr(memory, "get_distant_summary", lambda conv: "")
    monkeypatch.setattr(memory, "get_relevant_facts", lambda acc, q: [])

    total_budget = memory._get_total_token_budget()
    context = memory.build_context(uuid4(), "query", SimpleNamespace(id=uuid4()))

    assert total_budget == int(10000 * 0.3)
    assert context["combined_token_count"] == 0
    assert context["recent_messages"] == []
    assert context["distant_summary"] == ""


def test_truncate_facts_to_budget_should_drop_facts_exceeding_budget():
    memory = TokenBufferMemory(db=SimpleNamespace(), conversation=None, model_instance=None)
    long_fact = "事实" * 200

    result = memory._truncate_facts_to_budget([long_fact, "短事实"], max_tokens=50)

    assert "短事实" not in result or len(result) <= 2
    assert isinstance(result, list)
