from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
import json

import pytest
from test.context import TestApp
from langchain_core.messages import HumanMessage, SystemMessage
from werkzeug.datastructures import FileStorage

from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.app_entity import DEFAULT_APP_CONFIG
from internal.entity.conversation_entity import InvokeFrom
from internal.entity.workflow_entity import WorkflowStatus
from internal.exception import FailException, NotFoundException
from internal.model import Account, ApiTool, Message, Workflow
from internal.service.app_config_service import AppConfigService
from internal.service.assistant_agent_service import (
    AssistantAgentService,
    _get_system_knowledge_context,
)
from internal.service.cos_service import CosService
from internal.service.embeddings_service import EmbeddingsService
from internal.service.faiss_service import FaissService
from internal.service.upload_file_service import UploadFileService


@contextmanager
def _null_context():
    yield


class _QueryStub:
    def __init__(self, *, all_result=None):
        self._all_result = all_result if all_result is not None else []

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._all_result

    def get(self, _primary_key):
        return None


class _LockedAccountQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *_args, **_kwargs):
        return self

    def with_for_update(self):
        return self

    def one_or_none(self):
        return self._result


class _AutoCommitContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _ConversationDraft:
    def __init__(self, **kwargs):
        self.id = uuid4()
        self.__dict__.update(kwargs)


class TestAssistantAgentService:
    def _build_service(self):
        return AssistantAgentService(
            db=SimpleNamespace(
                session=SimpleNamespace(
                    query=lambda *_args, **_kwargs: _QueryStub(all_result=[])
                )
            ),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(
                get=lambda key: None,
                setex=lambda key, ttl, value: None,
                scan=lambda cursor, match, count: (0, []),
                delete=lambda *keys: None,
            ),
            public_agent_a2a_service=None,
        )

    def test_schedule_introduction_prewarm_should_skip_in_testing_mode(
        self, app, monkeypatch
    ):
        service = self._build_service()
        thread_calls = []

        class _FakeThread:
            def __init__(self, target=None, daemon=False):
                thread_calls.append(("init", daemon))
                self._target = target

            def start(self):
                thread_calls.append("start")
                if self._target is not None:
                    self._target()

        monkeypatch.setattr(
            "internal.service.assistant_agent_service.Thread", _FakeThread
        )

        with app.app_context():
            service._schedule_introduction_prewarm(uuid4())

        assert thread_calls == []

    def test_schedule_introduction_prewarm_should_warm_cache_when_enabled(
        self, monkeypatch
    ):
        service = self._build_service()
        account_id = uuid4()
        account = SimpleNamespace(id=account_id)
        call_log = []

        class _FakeThread:
            def __init__(self, target=None, daemon=False):
                call_log.append(("thread", daemon))
                self._target = target

            def start(self):
                call_log.append("start")
                if self._target is not None:
                    self._target()

        monkeypatch.setattr(
            "internal.service.assistant_agent_service.Thread", _FakeThread
        )
        monkeypatch.setattr(
            service,
            "get",
            lambda model, pk: account if pk == account_id else None,
        )

        def _generate_introduction(account_arg):
            call_log.append(("generate", account_arg.id))
            yield "chunk"

        monkeypatch.setattr(service, "generate_introduction", _generate_introduction)

        flask_app = TestApp(__name__)
        flask_app.config["TESTING"] = False
        flask_app.config["ASSISTANT_INTRO_PREWARM_ENABLED"] = True

        with flask_app.app_context():
            service._schedule_introduction_prewarm(account_id)

        assert call_log == [
            ("thread", True),
            "start",
            ("generate", account_id),
        ]
        assert (
            str(account_id)
            not in AssistantAgentService._introduction_prewarm_pending
        )

    def test_system_knowledge_context_should_concat_enabled_system_segments(self):
        """启用中的系统知识库文档内容应被注入助手提示词。"""
        from internal.model import KnowledgeBase, KnowledgeDocument, KnowledgeSegment

        fake_base = SimpleNamespace(id=uuid4(), name="身份认知")
        fake_segment = SimpleNamespace(content="当用户问你是什么模型时，请回答你是钰心小钰。")
        fake_segment_two = SimpleNamespace(content="禁止透露底层模型厂商。")

        base_query = SimpleNamespace(
            filter=lambda *_args, **_kwargs: SimpleNamespace(
                all=lambda: [fake_base]
            )
        )
        segment_query = SimpleNamespace(
            join=lambda *_args, **_kwargs: SimpleNamespace(
                filter=lambda *_args, **_kwargs: SimpleNamespace(
                    order_by=lambda *_args, **_kwargs: SimpleNamespace(
                        all=lambda: [fake_segment, fake_segment_two]
                    )
                )
            )
        )
        db = SimpleNamespace(
            session=SimpleNamespace(
                query=lambda model: segment_query if model is KnowledgeSegment else base_query
            )
        )

        context = _get_system_knowledge_context(db)

        assert "钰心小钰" in context
        assert "禁止透露底层模型厂商" in context
        assert context.index("钰心小钰") < context.index("禁止透露底层模型厂商")

    def test_extract_chunk_content_should_support_common_types(self):
        assert AssistantAgentService._extract_chunk_content(None) == ""
        assert AssistantAgentService._extract_chunk_content("hello") == "hello"
        assert (
            AssistantAgentService._extract_chunk_content({"text": "world"}) == "world"
        )
        assert (
            AssistantAgentService._extract_chunk_content(["a", {"text": "b"}]) == "ab"
        )

    def test_contains_markdown_and_ensure_markdown_should_work_for_plain_text(self):
        assert (
            AssistantAgentService._contains_markdown_syntax("### title\n- item") is True
        )
        assert AssistantAgentService._contains_markdown_syntax("plain text") is False

        markdown = AssistantAgentService._ensure_introduction_markdown(
            "欢迎使用。你可以创建应用。建议先定义目标。",
            display_name="开发者",
        )
        assert markdown.startswith("### Hi，开发者")
        assert "#### 建议下一步" in markdown

    def test_stop_chat_should_delegate_to_agent_queue_manager(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.AgentQueueManager.set_stop_flag",
            lambda task_id, invoke_from, account_id: calls.append(
                (task_id, invoke_from, account_id)
            ),
        )
        task_id = uuid4()
        account = SimpleNamespace(id=uuid4())

        AssistantAgentService.stop_chat(task_id, account)

        assert calls[0][0] == task_id
        assert calls[0][2] == account.id

    def test_delete_conversation_should_clear_account_reference(self, monkeypatch):
        from internal.model import Account

        db = SimpleNamespace(
            session=SimpleNamespace(
                query=lambda model: SimpleNamespace(
                    get=lambda pk: None
                ) if model is Account else _QueryStub(all_result=[])
            ),
            auto_commit=lambda: _null_context(),
        )
        service = AssistantAgentService(
            db=db,
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(),
        )
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation_id=uuid4())
        updates = []
        cache_clears = []
        monkeypatch.setattr(
            service,
            "update",
            lambda target, **kwargs: updates.append((target, kwargs)),
        )
        monkeypatch.setattr(
            service,
            "_clear_introduction_cache",
            lambda account_id: cache_clears.append(account_id),
        )

        service.delete_conversation(account)

        assert updates == []
        assert account.assistant_agent_conversation_id is None
        assert cache_clears == [account.id]

    def test_resolve_conversation_id_should_parse_uuid_or_return_none(self):
        conversation_id = uuid4()

        assert AssistantAgentService._resolve_conversation_id("") is None
        assert AssistantAgentService._resolve_conversation_id("   ") is None
        assert (
            AssistantAgentService._resolve_conversation_id(str(conversation_id))
            == conversation_id
        )

    def test_resolve_assistant_agent_conversation_should_return_active_when_id_absent(
        self, monkeypatch
    ):
        service = self._build_service()
        active_conversation = SimpleNamespace(id=uuid4())
        account = SimpleNamespace(
            id=uuid4(),
            assistant_agent_conversation=active_conversation,
        )
        monkeypatch.setattr(
            service,
            "_get_or_create_assistant_agent_conversation",
            lambda target: active_conversation,
        )

        result = service._resolve_assistant_agent_conversation(
            account=account, conversation_id=None
        )

        assert result is active_conversation

    def test_get_or_create_assistant_agent_conversation_should_reuse_valid_pointer(
        self, monkeypatch
    ):
        service = self._build_service()
        account = Account(
            id=uuid4(),
            assistant_agent_conversation_id=uuid4(),
        )
        existing = SimpleNamespace(
            id=account.assistant_agent_conversation_id,
            is_deleted=False,
            created_by=account.id,
            invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
        )
        monkeypatch.setattr(service, "get", lambda *_args, **_kwargs: existing)

        result = service._get_or_create_assistant_agent_conversation(account)

        assert result is existing

    def test_get_or_create_assistant_agent_conversation_should_create_with_row_lock(
        self, app, monkeypatch
    ):
        service = self._build_service()
        account = Account(id=uuid4(), assistant_agent_conversation_id=None)
        locked_account = Account(
            id=account.id,
            assistant_agent_conversation_id=None,
        )
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.Conversation",
            _ConversationDraft,
        )
        added = []
        session = SimpleNamespace(
            query=lambda *_args, **_kwargs: _LockedAccountQuery(locked_account),
            add=added.append,
            flush=lambda: None,
        )
        service.db = SimpleNamespace(
            session=session,
            auto_commit=lambda: _AutoCommitContext(),
        )
        monkeypatch.setattr(service, "get", lambda *_args, **_kwargs: None)

        with app.app_context():
            app.config["ASSISTANT_AGENT_ID"] = str(uuid4())
            result = service._get_or_create_assistant_agent_conversation(account)

        assert result.id is not None
        assert result.created_by == account.id
        assert locked_account.assistant_agent_conversation_id == result.id
        assert added == [result]

    def test_get_or_create_assistant_agent_conversation_should_prefer_locked_pointer(
        self, monkeypatch
    ):
        service = self._build_service()
        account = Account(id=uuid4(), assistant_agent_conversation_id=None)
        existing = SimpleNamespace(
            id=uuid4(),
            is_deleted=False,
            created_by=account.id,
            invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
        )
        locked_account = Account(
            id=account.id,
            assistant_agent_conversation_id=existing.id,
        )
        added = []
        session = SimpleNamespace(
            query=lambda *_args, **_kwargs: _LockedAccountQuery(locked_account),
            add=added.append,
            flush=lambda: None,
        )
        service.db = SimpleNamespace(
            session=session,
            auto_commit=lambda: _AutoCommitContext(),
        )
        monkeypatch.setattr(service, "get", lambda *_args, **_kwargs: existing)

        result = service._get_or_create_assistant_agent_conversation(account)

        assert result is existing
        assert added == []

    def test_update_routing_log_execution_should_persist_actual_results(
        self, monkeypatch
    ):
        service = self._build_service()
        message = SimpleNamespace(
            id=uuid4(),
            answer="完成",
            status="normal",
            total_token_count=10,
            answer_token_count=4,
            message_token_count=6,
            total_price=0.5,
            latency=1.2,
        )
        finalized = []
        service.routing_log_service = SimpleNamespace(
            finalize=lambda routing_log_id, **fields: finalized.append(
                (routing_log_id, fields)
            )
        )
        monkeypatch.setattr(service, "get", lambda _model, _id: message)

        service._update_routing_log_execution(
            message,
            {
                "routing_log_id": str(uuid4()),
                "recommended_model_tier": "cheap",
                "cost_policy": {"allowed": True},
                "agent_subset": {"selected_agents": [{"agent_id": "coding-agent"}]},
            },
            [SimpleNamespace(tool="search", task_id="coding-agent")],
            started_at=0,
        )

        assert len(finalized) == 1
        routing_log_id, fields = finalized[0]
        assert fields["status"] == "success"
        assert fields["cost_summary"]["total_tokens"] == 10
        assert fields["model_selection"]["model_tier"] == "cheap"
        assert fields["tool_pool_hits"] == ["search"]
        assert fields["routing_decision"]["tool_calls"] == ["search"]
        assert fields["routing_decision"]["answer_length"] == 2
        assert fields["agent_pool_hits"] == [{"agent_id": "coding-agent"}]

    def test_load_non_mcp_tool_should_dispatch_skill_source(self, monkeypatch):
        service = self._build_service()
        service.app_config_service = SimpleNamespace()
        skill_tool = SimpleNamespace(name="skill__system_access__execute_shell")
        monkeypatch.setattr(
            service,
            "_load_skill_tools",
            lambda descriptor, account_id="": [skill_tool],
        )
        descriptor = SimpleNamespace(
            source_type="skill",
            tool_id="skill:abc",
            provider_id="abc",
            name="系统访问",
        )

        result = service._load_non_mcp_tool(descriptor, account_id="user-1")

        assert result == [skill_tool]

    def test_resolve_assistant_agent_conversation_should_validate_and_sync(
        self, monkeypatch
    ):
        service = self._build_service()
        account = SimpleNamespace(
            id=uuid4(),
            assistant_agent_conversation_id=uuid4(),
        )
        conversation = SimpleNamespace(
            id=uuid4(),
            created_by=account.id,
            is_deleted=False,
            invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
        )
        monkeypatch.setattr(service, "get", lambda *_args, **_kwargs: conversation)
        updates = []
        monkeypatch.setattr(
            service,
            "update",
            lambda target, **kwargs: updates.append((target, kwargs)),
        )

        result = service._resolve_assistant_agent_conversation(
            account=account,
            conversation_id=conversation.id,
            sync_active=True,
        )

        assert result is conversation
        assert updates == [
            (account, {"assistant_agent_conversation_id": conversation.id})
        ]

    def test_resolve_assistant_agent_conversation_should_not_sync_when_target_already_active(
        self, monkeypatch
    ):
        service = self._build_service()
        conversation_id = uuid4()
        account = SimpleNamespace(
            id=uuid4(),
            assistant_agent_conversation_id=conversation_id,
        )
        conversation = SimpleNamespace(
            id=conversation_id,
            created_by=account.id,
            is_deleted=False,
            invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
        )
        monkeypatch.setattr(service, "get", lambda *_args, **_kwargs: conversation)
        updates = []
        monkeypatch.setattr(
            service,
            "update",
            lambda target, **kwargs: updates.append((target, kwargs)),
        )

        result = service._resolve_assistant_agent_conversation(
            account=account,
            conversation_id=conversation.id,
            sync_active=True,
        )

        assert result is conversation
        assert updates == []

    def test_resolve_assistant_agent_conversation_should_raise_when_invalid(
        self, monkeypatch
    ):
        service = self._build_service()
        account = SimpleNamespace(id=uuid4())
        conversation_id = uuid4()

        monkeypatch.setattr(service, "get", lambda *_args, **_kwargs: None)
        with pytest.raises(NotFoundException):
            service._resolve_assistant_agent_conversation(
                account=account, conversation_id=conversation_id
            )

        invalid_conversation = SimpleNamespace(
            id=conversation_id,
            created_by=uuid4(),
            is_deleted=False,
            invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
        )
        monkeypatch.setattr(
            service, "get", lambda *_args, **_kwargs: invalid_conversation
        )
        with pytest.raises(NotFoundException):
            service._resolve_assistant_agent_conversation(
                account=account, conversation_id=conversation_id
            )

    def test_get_capabilities_should_return_default_text_only_caps_when_service_absent(
        self,
    ):
        service = self._build_service()

        capabilities = service.get_capabilities()

        assert capabilities["requested_model"] == {}
        assert capabilities["effective_model"] == {}
        assert capabilities["image_input"]["enabled"] is False
        assert capabilities["image_input"]["policy"] == "strict"
        assert capabilities["image_output"]["enabled"] is True
        assert capabilities["artifact_output"]["enabled"] is True

    def test_get_capabilities_should_delegate_to_language_model_service(self):
        capture = {}
        expected = {
            "features": ["tool_call", "image_input"],
            "image_input": {"enabled": True},
        }
        service = AssistantAgentService(
            db=SimpleNamespace(
                session=SimpleNamespace(query=lambda *_args, **_kwargs: _QueryStub())
            ),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(),
            language_model_service=SimpleNamespace(
                get_assistant_agent_model_config=lambda: {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                },
                describe_runtime_capabilities=lambda model_config, entrypoint: capture.update(
                    {"model_config": model_config, "entrypoint": entrypoint}
                )
                or expected,
            ),
        )

        capabilities = service.get_capabilities()

        assert capabilities is expected
        assert capture == {
            "model_config": {"provider": "openai", "model": "gpt-4o-mini"},
            "entrypoint": "assistant_agent",
        }

    def test_generate_message_fingerprint_should_create_consistent_hash(self):
        service = AssistantAgentService(
            db=SimpleNamespace(),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(),
        )
        message_ids = ["msg1", "msg2", "msg3"]
        summary = "用户关注AI应用开发"

        fingerprint1 = service._generate_message_fingerprint(message_ids, summary)
        fingerprint2 = service._generate_message_fingerprint(message_ids, summary)

        assert fingerprint1 == fingerprint2
        assert len(fingerprint1) == 32  # MD5 hash length

        # 不同的输入应该产生不同的指纹
        different_fingerprint = service._generate_message_fingerprint(
            ["msg1", "msg2"], summary
        )
        assert fingerprint1 != different_fingerprint

    def test_get_cached_introduction_should_return_none_when_cache_miss(self):
        redis_mock = SimpleNamespace(get=lambda key: None)
        service = AssistantAgentService(
            db=SimpleNamespace(),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=redis_mock,
        )
        account_id = uuid4()
        fingerprint = "abc123"

        result = service._get_cached_introduction(account_id, fingerprint)

        assert result is None

    def test_get_cached_introduction_should_return_data_when_cache_hit(self):
        cached_data = {
            "introduction": "### Hi，开发者\n\n欢迎回来！",
            "suggested_questions_message_id": "msg123",
            "generated_at": "2026-02-28T10:00:00Z",
        }
        redis_mock = SimpleNamespace(
            get=lambda key: json.dumps(cached_data, ensure_ascii=False).encode("utf-8")
        )
        service = AssistantAgentService(
            db=SimpleNamespace(),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=redis_mock,
        )
        account_id = uuid4()
        fingerprint = "abc123"

        result = service._get_cached_introduction(account_id, fingerprint)

        assert result == cached_data
        assert result["introduction"] == "### Hi，开发者\n\n欢迎回来！"

    def test_get_cached_introduction_should_return_none_when_redis_failed(self):
        service = AssistantAgentService(
            db=SimpleNamespace(),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(
                get=lambda _key: (_ for _ in ()).throw(RuntimeError("redis down"))
            ),
        )

        result = service._get_cached_introduction(uuid4(), "fingerprint")

        assert result is None

    def test_set_cached_introduction_should_store_data_with_ttl(self):
        setex_calls = []
        redis_mock = SimpleNamespace(
            setex=lambda key, ttl, value: setex_calls.append((key, ttl, value))
        )
        service = AssistantAgentService(
            db=SimpleNamespace(),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=redis_mock,
        )
        account_id = uuid4()
        fingerprint = "abc123"
        data = {
            "introduction": "### Hi，开发者",
            "suggested_questions_message_id": "msg123",
        }

        service._set_cached_introduction(account_id, fingerprint, data, ttl=3600)

        assert len(setex_calls) == 1
        key, ttl, value = setex_calls[0]
        assert f"assistant_agent:introduction:{account_id}:{fingerprint}" == key
        assert ttl == 3600
        assert json.loads(value) == data

    def test_clear_introduction_cache_should_delete_all_account_caches(self):
        deleted_keys = []
        redis_mock = SimpleNamespace(
            scan=lambda cursor, match, count: (
                (
                    0,
                    [
                        f"assistant_agent:introduction:{uuid4()}:hash1",
                        f"assistant_agent:introduction:{uuid4()}:hash2",
                    ],
                )
                if cursor == 0
                else (0, [])
            ),
            delete=lambda *keys: deleted_keys.extend(keys),
        )
        service = AssistantAgentService(
            db=SimpleNamespace(),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=redis_mock,
        )
        account_id = uuid4()

        service._clear_introduction_cache(account_id)

        assert len(deleted_keys) == 2

    def test_clear_introduction_cache_should_continue_scanning_until_cursor_zero(self):
        deleted_keys = []
        calls = {"count": 0}

        def _scan(cursor, match, count):
            calls["count"] += 1
            if calls["count"] == 1:
                return 1, ["cache-key-1"]
            return 0, ["cache-key-2"]

        service = AssistantAgentService(
            db=SimpleNamespace(),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(
                scan=_scan,
                delete=lambda *keys: deleted_keys.extend(keys),
            ),
        )

        service._clear_introduction_cache(uuid4())

        assert calls["count"] == 2
        assert deleted_keys == ["cache-key-1", "cache-key-2"]

    def test_clear_introduction_cache_should_not_delete_when_scan_returns_empty_keys(
        self,
    ):
        delete_calls = []
        service = AssistantAgentService(
            db=SimpleNamespace(),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(
                scan=lambda cursor, match, count: (0, []),
                delete=lambda *keys: delete_calls.append(keys),
            ),
        )

        service._clear_introduction_cache(uuid4())

        assert delete_calls == []

    def test_clear_introduction_cache_should_swallow_exception_when_scan_failed(self):
        service = AssistantAgentService(
            db=SimpleNamespace(),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(
                scan=lambda **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("scan-failed")
                )
            ),
        )

        service._clear_introduction_cache(uuid4())

    def test_generate_introduction_cache_key_should_follow_pattern(self):
        service = AssistantAgentService(
            db=SimpleNamespace(),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(),
        )
        account_id = uuid4()
        fingerprint = "abc123def456"

        cache_key = service._generate_introduction_cache_key(account_id, fingerprint)

        assert cache_key == f"assistant_agent:introduction:{account_id}:{fingerprint}"
        assert cache_key.startswith("assistant_agent:introduction:")
        assert fingerprint in cache_key

    def test_convert_create_app_to_tool_should_trigger_async_task(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.auto_create_app.delay",
            lambda name, description, account_id: calls.append(
                (name, description, account_id)
            ),
        )
        account_id = uuid4()
        tool = AssistantAgentService.convert_create_app_to_tool(account_id)

        result = tool.invoke(
            {"name": "客服助手", "description": "面向工单场景自动答疑"}
        )

        assert calls == [("客服助手", "面向工单场景自动答疑", account_id)]
        assert "应用名称: 客服助手" in result

    def test_build_assistant_runtime_tools_should_include_global_mcp_bindings(self, monkeypatch):
        service = self._build_service()
        account_id = uuid4()
        expected_bindings = [
            {
                "name": "Global MCP",
                "description": "全局 MCP",
                "transport": "streamable_http",
                "url": "https://mcp.example.com",
                "enabled": True,
                "headers": [],
                "tool_names": [],
                "timeout_seconds": 30,
                "args": [],
                "env": {},
            }
        ]
        captured = {}
        service.public_agent_registry_service = SimpleNamespace(
            convert_public_agent_search_to_tool=lambda: "search-tool"
        )
        service.public_agent_a2a_service = SimpleNamespace(
            convert_public_agent_route_to_tool=lambda _account_id: f"route:{_account_id}"
        )
        service.app_config_service = SimpleNamespace(
            get_langchain_tools_by_mcp_bindings=lambda bindings: captured.update({"bindings": bindings}) or ["mcp-tool"]
        )
        monkeypatch.setattr(
            service,
            "convert_create_app_to_tool",
            lambda _account_id: f"create:{_account_id}",
        )
        # 技能详情/记忆策展工具属于独立模块构建，本测试聚焦 MCP 绑定工具，
        # mock 为固定占位符以匹配当前实现追加工具的次序
        monkeypatch.setattr(
            "internal.service.memory.skill_detail_tool.create_skill_detail_tool",
            lambda **kwargs: "skill-detail-tool",
        )
        monkeypatch.setattr(
            "internal.service.memory.agent_memory_tool.create_agent_memory_tools",
            lambda **kwargs: ["memory-add-tool", "memory-replace-tool", "memory-remove-tool"],
        )

        flask_app = TestApp(__name__)
        flask_app.config["ASSISTANT_MCP_BINDINGS"] = expected_bindings

        with flask_app.app_context():
            tools = service._build_assistant_runtime_tools(account_id)

        assert tools == [
            f"route:{account_id}",
            "search-tool",
            f"create:{account_id}",
            "mcp-tool",
            "skill-detail-tool",
            "memory-add-tool",
            "memory-replace-tool",
            "memory-remove-tool",
        ]
        assert captured["bindings"] == expected_bindings

    def test_get_conversation_messages_with_page_should_delegate_query_and_paginate(
        self, monkeypatch
    ):
        message_1 = SimpleNamespace(id=uuid4())
        message_2 = SimpleNamespace(id=uuid4())
        all_messages = [message_1, message_2]

        class _Query:
            def __init__(self, all_result=None):
                self.filter_calls = []
                self.order_by_calls = []
                self._all_result = all_result if all_result is not None else []

            def filter(self, *args, **_kwargs):
                self.filter_calls.append(args)
                return self

            def order_by(self, *_args, **_kwargs):
                self.order_by_calls.append(_args)
                return self

            def options(self, *_args, **_kwargs):
                return self

            def all(self):
                return self._all_result

        id_query = _Query()
        message_query = _Query(all_result=all_messages)

        class _Session:
            def query(self, model):
                if getattr(model, "key", "") == "id":
                    return id_query
                return message_query

        class _Paginator:
            def __init__(self, db, req):
                self.db = db
                self.req = req
                self.paginate_called = False

            def paginate(self, query):
                self.paginate_called = True
                assert query is id_query
                return [message_1.id, message_2.id]

        monkeypatch.setattr(
            "internal.service.assistant_agent_service.Paginator", _Paginator
        )
        service = AssistantAgentService(
            db=SimpleNamespace(session=_Session()),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(),
        )
        req = SimpleNamespace(
            created_at=SimpleNamespace(
                data=int(datetime(2024, 1, 1, 0, 0, 0).timestamp())
            ),
            conversation_id=SimpleNamespace(data=""),
        )
        account = SimpleNamespace(
            assistant_agent_conversation=SimpleNamespace(id=uuid4())
        )

        messages, paginator = service.get_conversation_messages_with_page(req, account)

        assert messages == all_messages
        assert isinstance(paginator, _Paginator)
        assert paginator.paginate_called is True
        # 包含 4 个固定过滤条件 + 1 个 created_at 条件
        assert len(id_query.filter_calls[0]) == 5
        assert tuple(str(arg) for arg in id_query.order_by_calls[0]) == (
            "message.created_at DESC",
            "message.id DESC",
        )
        assert tuple(str(arg) for arg in message_query.order_by_calls[0]) == (
            "message.created_at DESC",
            "message.id DESC",
        )

    def test_get_conversation_messages_with_page_should_skip_created_at_filter_when_absent(
        self, monkeypatch
    ):
        message = SimpleNamespace(id=uuid4())

        class _Query:
            def __init__(self, all_result=None):
                self.filter_calls = []
                self._all_result = all_result if all_result is not None else []

            def filter(self, *args, **_kwargs):
                self.filter_calls.append(args)
                return self

            def order_by(self, *_args, **_kwargs):
                return self

            def options(self, *_args, **_kwargs):
                return self

            def all(self):
                return self._all_result

        id_query = _Query()
        message_query = _Query(all_result=[message])

        class _Session:
            def query(self, model):
                if getattr(model, "key", "") == "id":
                    return id_query
                return message_query

        class _Paginator:
            def __init__(self, db, req):
                pass

            def paginate(self, query):
                assert query is id_query
                return [message.id]

        monkeypatch.setattr(
            "internal.service.assistant_agent_service.Paginator", _Paginator
        )
        service = AssistantAgentService(
            db=SimpleNamespace(session=_Session()),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(),
        )
        req = SimpleNamespace(
            created_at=SimpleNamespace(data=None),
            conversation_id=SimpleNamespace(data=""),
        )
        account = SimpleNamespace(
            assistant_agent_conversation=SimpleNamespace(id=uuid4())
        )

        messages, _paginator = service.get_conversation_messages_with_page(req, account)

        assert messages == [message]
        assert len(id_query.filter_calls[0]) == 4

    def test_generate_introduction_should_return_first_time_done_when_no_history(self):
        class _Query:
            def __init__(self, rows):
                self._rows = rows

            def filter(self, *_args, **_kwargs):
                return self

            def order_by(self, *_args, **_kwargs):
                return self

            def limit(self, *_args, **_kwargs):
                return self

            def all(self):
                return self._rows

        class _Session:
            def __init__(self):
                self._queries = [_Query([]), _Query([])]

            def query(self, _model):
                return self._queries.pop(0)

        service = AssistantAgentService(
            db=SimpleNamespace(session=_Session()),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(get=lambda key: None),
        )
        account = SimpleNamespace(id=uuid4(), name="新人")

        events = list(service.generate_introduction(account))

        assert len(events) == 1
        assert events[0].startswith("event: intro_done")
        payload = json.loads(events[0].split("data:", 1)[1].strip())
        assert payload["is_first_time"] is True
        assert payload["content"] == ""
        assert payload["message_id"] == ""

    def test_generate_introduction_should_stream_chunks_and_emit_markdown_done(
        self, monkeypatch
    ):
        latest_message = SimpleNamespace(id=uuid4(), query="你好", answer="你好呀")

        class _Query:
            def __init__(self, rows):
                self._rows = rows

            def filter(self, *_args, **_kwargs):
                return self

            def order_by(self, *_args, **_kwargs):
                return self

            def limit(self, *_args, **_kwargs):
                return self

            def all(self):
                return self._rows

        class _Session:
            def __init__(self):
                self._queries = [
                    _Query([latest_message]),
                    _Query([("历史偏好：关注自动化测试",)]),
                ]

            def query(self, _model):
                return self._queries.pop(0)

        class _FakeLLM:
            @staticmethod
            def stream(_messages):
                # 故意输出纯文本，验证服务会兜底格式化为 Markdown
                return iter(["欢迎回来。", "建议先定义你的目标。"])

            def get_num_tokens_from_messages(self, messages):
                return 10

        monkeypatch.setattr(
            "internal.service.language_model_service.LanguageModelService.get_feature_model",
            classmethod(lambda cls, feature_key: _FakeLLM()),
        )
        service = AssistantAgentService(
            db=SimpleNamespace(session=_Session()),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(get=lambda key: None, setex=lambda key, ttl, value: None),
        )
        account = SimpleNamespace(id=uuid4(), name="测试用户")

        events = list(service.generate_introduction(account))

        assert any(item.startswith("event: intro_chunk") for item in events)
        done_event = [item for item in events if item.startswith("event: intro_done")][
            0
        ]
        done_payload = json.loads(done_event.split("data:", 1)[1].strip())
        assert done_payload["is_first_time"] is False
        assert done_payload["suggested_questions_message_id"] == str(latest_message.id)
        assert done_payload["content"].startswith("### Hi，测试用户")

    def test_generate_introduction_should_use_cached_content_when_cache_hit(
        self, monkeypatch
    ):
        latest_message = SimpleNamespace(id=uuid4(), query="你好", answer="你好呀")

        class _Query:
            def __init__(self, rows):
                self._rows = rows

            def filter(self, *_args, **_kwargs):
                return self

            def order_by(self, *_args, **_kwargs):
                return self

            def limit(self, *_args, **_kwargs):
                return self

            def all(self):
                return self._rows

        class _Session:
            def __init__(self):
                self._queries = [
                    _Query([latest_message]),
                    _Query([("历史偏好：关注测试覆盖率",)]),
                ]

            def query(self, _model):
                return self._queries.pop(0)

        service = AssistantAgentService(
            db=SimpleNamespace(session=_Session()),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(),
        )
        cached_text = "### Hi，缓存用户\n\n欢迎回来，这是一段缓存介绍。"
        monkeypatch.setattr(
            service,
            "_get_cached_introduction",
            lambda *_args, **_kwargs: {
                "introduction": cached_text,
                "suggested_questions_message_id": "cached-msg-id",
            },
        )
        account = SimpleNamespace(id=uuid4(), name="缓存用户")

        events = list(service.generate_introduction(account))

        assert any(item.startswith("event: intro_chunk") for item in events)
        done_event = [item for item in events if item.startswith("event: intro_done")][
            0
        ]
        done_payload = json.loads(done_event.split("data:", 1)[1].strip())
        assert done_payload["content"] == cached_text
        assert done_payload["message_id"] == "cached-msg-id"
        assert done_payload["suggested_questions_message_id"] == "cached-msg-id"

    def test_chat_should_stream_events_and_save_aggregated_agent_thoughts(
        self, monkeypatch, app
    ):
        assistant_agent_id = uuid4()
        app.config["ASSISTANT_AGENT_ID"] = assistant_agent_id
        conversation = SimpleNamespace(id=uuid4(), summary="历史摘要")
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation=conversation)
        req = SimpleNamespace(
            query=SimpleNamespace(data="帮我创建一个客服Agent"),
            image_urls=SimpleNamespace(data=["https://example.com/demo.png"]),
            conversation_id=SimpleNamespace(data=""),
            confirm_deep_thinking=SimpleNamespace(data=False),
        )

        save_payload = {}
        service = AssistantAgentService(
            db=SimpleNamespace(
                session=SimpleNamespace(query=lambda *_a, **_kw: _QueryStub())
            ),
            faiss_service=SimpleNamespace(convert_faiss_to_tool=lambda: "faiss-tool"),
            conversation_service=SimpleNamespace(
                save_agent_thoughts=lambda **kwargs: save_payload.update(kwargs)
            ),
            redis_client=SimpleNamespace(),
            public_agent_a2a_service=SimpleNamespace(
                convert_public_agent_route_to_tool=lambda _account_id: "public-agent-route-tool"
            ),
        )

        message_id = uuid4()
        create_calls = []
        monkeypatch.setattr(
            service,
            "create",
            lambda model, **kwargs: create_calls.append((model, kwargs))
            or SimpleNamespace(id=message_id),
        )
        monkeypatch.setattr(
            service,
            "convert_create_app_to_tool",
            lambda _account_id: "create-app-tool",
        )

        llm_capture = {}

        class _FakeLLM:
            def __init__(self, **kwargs):
                llm_capture["kwargs"] = kwargs

            def convert_to_human_message(self, query, image_urls):
                llm_capture["human_message"] = (query, image_urls)
                return {"query": query, "image_urls": image_urls}

        class _FakeTokenBufferMemory:
            def __init__(self, **kwargs):
                llm_capture["memory_args"] = kwargs

            def build_context(self, conversation_id, current_query, account):
                llm_capture["build_context_args"] = (conversation_id, current_query, account)
                return {
                    "recent_messages": ["历史消息"],
                    "distant_summary": "历史摘要",
                    "relevant_facts": [],
                    "combined_token_count": 0,
                }

        executor_capture = {}

        class _FakeSingleAgentExecutor:
            collected_thoughts = []

            def __init__(self, **kwargs):
                executor_capture["kwargs"] = kwargs

            def execute(self, **_kwargs):
                return iter([
                    f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': 'AB', 'id': str(message_id), 'conversation_id': str(conversation.id), 'message_id': str(message_id)})}\n\n",
                ])

        # AgentConfig 的 tools 字段会校验 BaseTool；这里仅验证服务编排逻辑，使用轻量对象替代。
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.AgentConfig",
            lambda **kwargs: SimpleNamespace(**kwargs),
        )
        # 技能详情/记忆策展工具与断言相关，mock 为固定占位符以匹配当前实现追加工具的次序
        monkeypatch.setattr(
            "internal.service.memory.skill_detail_tool.create_skill_detail_tool",
            lambda **kwargs: "skill-detail-tool",
        )
        monkeypatch.setattr(
            "internal.service.memory.agent_memory_tool.create_agent_memory_tools",
            lambda **kwargs: ["memory-add-tool", "memory-replace-tool", "memory-remove-tool"],
        )
        monkeypatch.setattr(
            "internal.service.language_model_service.LanguageModelService.get_chat_model_by_tier",
            classmethod(lambda cls, tier: _FakeLLM()),
        )
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.TokenBufferMemory",
            _FakeTokenBufferMemory,
        )
        monkeypatch.setattr(
            "internal.service.executors.single_agent_executor.SingleAgentExecutor",
            _FakeSingleAgentExecutor,
        )

        with app.app_context():
            events = list(service.chat(req, account))

        assert create_calls[0][0] is Message
        assert create_calls[0][1]["app_id"] == assistant_agent_id
        assert create_calls[0][1]["conversation_id"] == conversation.id
        assert create_calls[0][1]["query"] == req.query.data
        assert create_calls[0][1]["image_urls"] == req.image_urls.data
        assert llm_capture["build_context_args"][1] == req.query.data
        assert executor_capture["kwargs"]["agent_config"].tools == [
            "public-agent-route-tool",
            "faiss-tool",
            "create-app-tool",
            "skill-detail-tool",
            "memory-add-tool",
            "memory-replace-tool",
            "memory-remove-tool",
        ]
        assert executor_capture["kwargs"]["history"] == ["历史消息"]
        assert len(events) == 4
        assert events[0].startswith("event: billing_started")
        assert events[1].startswith("event: agent_message")
        assert events[2].startswith("event: billing_summary")
        assert events[3].startswith("event: billing_final")
        assert save_payload["account_id"] == account.id
        assert save_payload["app_id"] == assistant_agent_id
        assert save_payload["conversation_id"] == conversation.id
        assert save_payload["message_id"] == message_id
        assert save_payload["routing_decision"]["execution_mode"] == "single_agent"

    def test_chat_should_record_routing_decision_without_changing_stream_events(
        self, monkeypatch, app
    ):
        assistant_agent_id = uuid4()
        app.config["ASSISTANT_AGENT_ID"] = assistant_agent_id
        conversation = SimpleNamespace(id=uuid4(), summary="")
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation=conversation)
        req = SimpleNamespace(
            query=SimpleNamespace(data="Python 中 list 和 tuple 有什么区别？"),
            image_urls=SimpleNamespace(data=[]),
            conversation_id=SimpleNamespace(data=""),
            confirm_deep_thinking=SimpleNamespace(data=False),
        )
        routing_calls = []
        save_payload = {}
        service = AssistantAgentService(
            db=SimpleNamespace(
                session=SimpleNamespace(query=lambda *_a, **_kw: _QueryStub())
            ),
            faiss_service=SimpleNamespace(convert_faiss_to_tool=lambda: "faiss-tool"),
            conversation_service=SimpleNamespace(
                save_agent_thoughts=lambda **kwargs: save_payload.update(kwargs)
            ),
            redis_client=SimpleNamespace(),
            orchestrator_service=SimpleNamespace(
                decide=lambda query, **kwargs: routing_calls.append((query, kwargs))
                or SimpleNamespace(
                    to_dict=lambda: {
                        "intent": "general_qa",
                        "complexity": "simple",
                        "execution_mode": "direct_answer",
                        "needs_tools": False,
                        "needs_agent": False,
                        "needs_multi_agent": False,
                        "recommended_model_tier": "cheap",
                        "risk_level": "safe",
                        "reason": "简单问答",
                    }
                )
            ),
        )
        monkeypatch.setattr(service, "create", lambda _model, **_kwargs: SimpleNamespace(id=uuid4()))
        monkeypatch.setattr(service, "convert_create_app_to_tool", lambda _account_id: "create-app-tool")

        class _FakeLLM:
            def __init__(self, **_kwargs):
                pass

            def convert_to_human_message(self, query, image_urls):
                return {"query": query, "image_urls": image_urls}

        class _FakeTokenBufferMemory:
            def __init__(self, **_kwargs):
                pass

            def build_context(self, conversation_id, current_query, account):
                return {
                    "recent_messages": [],
                    "distant_summary": "",
                    "relevant_facts": [],
                    "combined_token_count": 0,
                }

        class _FakeDirectAnswerExecutor:
            last_answer = "答案"
            last_token_usage = None
            collected_thoughts = []

            def __init__(self, **_kwargs):
                pass

            def stream(self, query, history=None, conversation_id="", message_id=""):
                return iter([
                    f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': '答案', 'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id})}\n\n",
                ])

        monkeypatch.setattr("internal.service.assistant_agent_service.AgentConfig", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr("internal.service.language_model_service.LanguageModelService.get_chat_model_by_tier", classmethod(lambda cls, tier: _FakeLLM()))
        monkeypatch.setattr("internal.service.assistant_agent_service.TokenBufferMemory", _FakeTokenBufferMemory)
        monkeypatch.setattr(
            "internal.service.executors.direct_answer_executor.DirectAnswerExecutor",
            _FakeDirectAnswerExecutor,
        )

        with app.app_context():
            events = list(service.chat(req, account))

        assert len(events) == 6
        assert events[0].startswith("event: agent_thought")
        assert events[1].startswith("event: billing_started")
        assert events[2].startswith("event: agent_message")
        assert events[3].startswith("event: billing_summary")
        assert events[4].startswith("event: billing_final")
        assert events[5].startswith("event: agent_end")
        assert routing_calls[0][0] == req.query.data
        assert routing_calls[0][1]["account_id"] == account.id
        assert save_payload["routing_decision"] is None

    def test_chat_should_yield_deep_thinking_proposal_when_mode_is_deep_thinking(
        self, monkeypatch, app
    ):
        assistant_agent_id = uuid4()
        app.config["ASSISTANT_AGENT_ID"] = assistant_agent_id
        conversation = SimpleNamespace(id=uuid4(), summary="")
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation=conversation)
        req = SimpleNamespace(
            query=SimpleNamespace(data="评估迁移到 gRPC 的利弊"),
            image_urls=SimpleNamespace(data=[]),
            conversation_id=SimpleNamespace(data=""),
            confirm_deep_thinking=SimpleNamespace(data=False),
        )
        service = AssistantAgentService(
            db=SimpleNamespace(session=SimpleNamespace()),
            faiss_service=SimpleNamespace(convert_faiss_to_tool=lambda: "faiss-tool"),
            conversation_service=SimpleNamespace(
                save_agent_thoughts=lambda **kwargs: None
            ),
            redis_client=SimpleNamespace(),
            public_agent_a2a_service=SimpleNamespace(
                convert_public_agent_route_to_tool=lambda _account_id: "public-agent-route-tool"
            ),
            orchestrator_service=SimpleNamespace(
                decide=lambda query, **kwargs: SimpleNamespace(
                    to_dict=lambda: {
                        "intent": "deep_thinking_task",
                        "execution_mode": "deep_thinking",
                        "cost_policy": {"allowed": True},
                        "reason": "需要多步推理",
                    }
                )
            ),
        )
        monkeypatch.setattr(service, "create", lambda _model, **_kwargs: SimpleNamespace(id=uuid4()))
        monkeypatch.setattr(service, "convert_create_app_to_tool", lambda _account_id: "create-app-tool")

        class _FakeLLM:
            def __init__(self, **_kwargs):
                pass

            def convert_to_human_message(self, query, image_urls):
                return {"query": query, "image_urls": image_urls}

        class _FakeTokenBufferMemory:
            def __init__(self, **_kwargs):
                pass

            def build_context(self, conversation_id, current_query, account):
                return {
                    "recent_messages": [],
                    "distant_summary": "",
                    "relevant_facts": [],
                    "combined_token_count": 0,
                }

        monkeypatch.setattr("internal.service.assistant_agent_service.AgentConfig", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr("internal.service.language_model_service.LanguageModelService.get_chat_model_by_tier", classmethod(lambda cls, tier: _FakeLLM()))
        monkeypatch.setattr("internal.service.assistant_agent_service.TokenBufferMemory", _FakeTokenBufferMemory)

        with app.app_context():
            events = list(service.chat(req, account))

        assert any("deep_thinking_proposal" in e for e in events)
        assert all("agent_message" not in e for e in events)

    def test_chat_should_stream_insufficient_balance_when_cost_policy_not_allowed(
        self, monkeypatch, app
    ):
        assistant_agent_id = uuid4()
        app.config["ASSISTANT_AGENT_ID"] = assistant_agent_id
        conversation = SimpleNamespace(id=uuid4(), summary="")
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation=conversation)
        req = SimpleNamespace(
            query=SimpleNamespace(data="随便问个问题"),
            image_urls=SimpleNamespace(data=[]),
            conversation_id=SimpleNamespace(data=""),
            confirm_deep_thinking=SimpleNamespace(data=False),
        )
        service = AssistantAgentService(
            db=SimpleNamespace(session=SimpleNamespace()),
            faiss_service=SimpleNamespace(convert_faiss_to_tool=lambda: "faiss-tool"),
            conversation_service=SimpleNamespace(
                save_agent_thoughts=lambda **kwargs: None
            ),
            redis_client=SimpleNamespace(),
            public_agent_a2a_service=SimpleNamespace(
                convert_public_agent_route_to_tool=lambda _account_id: "public-agent-route-tool"
            ),
            orchestrator_service=SimpleNamespace(
                decide=lambda query, **kwargs: SimpleNamespace(
                    to_dict=lambda: {
                        "execution_mode": "direct_answer",
                        "cost_policy": {"allowed": False},
                    }
                )
            ),
        )
        monkeypatch.setattr(service, "create", lambda _model, **_kwargs: SimpleNamespace(id=uuid4()))
        monkeypatch.setattr(service, "convert_create_app_to_tool", lambda _account_id: "create-app-tool")

        class _FakeLLM:
            def __init__(self, **_kwargs):
                pass

            def convert_to_human_message(self, query, image_urls):
                return {"query": query, "image_urls": image_urls}

        class _FakeTokenBufferMemory:
            def __init__(self, **_kwargs):
                pass

            def build_context(self, conversation_id, current_query, account):
                return {
                    "recent_messages": [],
                    "distant_summary": "",
                    "relevant_facts": [],
                    "combined_token_count": 0,
                }

        monkeypatch.setattr("internal.service.assistant_agent_service.AgentConfig", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr("internal.service.language_model_service.LanguageModelService.get_chat_model_by_tier", classmethod(lambda cls, tier: _FakeLLM()))
        monkeypatch.setattr("internal.service.assistant_agent_service.TokenBufferMemory", _FakeTokenBufferMemory)

        with app.app_context():
            events = list(service.chat(req, account))

        assert any("余额不足" in e for e in events)
        assert all("agent_message" not in e for e in events)

    def test_chat_should_use_runtime_language_model_resolution_when_available(
        self, monkeypatch, app
    ):
        assistant_agent_id = uuid4()
        app.config["ASSISTANT_AGENT_ID"] = assistant_agent_id
        conversation = SimpleNamespace(id=uuid4(), summary="历史摘要")
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation=conversation)
        req = SimpleNamespace(
            query=SimpleNamespace(data="请分析这张图"),
            image_urls=SimpleNamespace(data=["https://example.com/demo.png"]),
            conversation_id=SimpleNamespace(data=""),
            confirm_deep_thinking=SimpleNamespace(data=False),
        )
        llm = SimpleNamespace(
            features=["tool_call"],
            convert_to_human_message=lambda query, image_urls: {
                "query": query,
                "image_urls": image_urls,
            },
        )
        capabilities = {"image_input": {"enabled": True, "via_fallback": True}}
        resolution_capture = {}
        save_payload = {}
        service = AssistantAgentService(
            db=SimpleNamespace(
                session=SimpleNamespace(query=lambda *_a, **_kw: _QueryStub())
            ),
            faiss_service=SimpleNamespace(convert_faiss_to_tool=lambda: "faiss-tool"),
            conversation_service=SimpleNamespace(
                save_agent_thoughts=lambda **kwargs: save_payload.update(kwargs)
            ),
            redis_client=SimpleNamespace(),
            language_model_service=SimpleNamespace(
                get_assistant_agent_model_config=lambda: {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                },
                resolve_runtime_language_model=lambda model_config, image_urls, entrypoint, **_kwargs: resolution_capture.update(
                    {
                        "model_config": model_config,
                        "image_urls": image_urls,
                        "entrypoint": entrypoint,
                    }
                )
                or SimpleNamespace(llm=llm, capabilities=capabilities),
            ),
            public_agent_a2a_service=SimpleNamespace(
                convert_public_agent_route_to_tool=lambda _account_id: "public-agent-route-tool"
            ),
        )

        monkeypatch.setattr(
            service,
            "create",
            lambda _model, **_kwargs: SimpleNamespace(id=uuid4()),
        )
        monkeypatch.setattr(
            service,
            "convert_create_app_to_tool",
            lambda _account_id: "create-app-tool",
        )

        class _FakeTokenBufferMemory:
            def __init__(self, **_kwargs):
                pass

            def build_context(self, conversation_id, current_query, account):
                return {
                    "recent_messages": [],
                    "distant_summary": "",
                    "relevant_facts": [],
                    "combined_token_count": 0,
                }

        executor_capture = {}

        class _FakeSingleAgentExecutor:
            collected_thoughts = []

            def __init__(self, **kwargs):
                executor_capture["kwargs"] = kwargs

            def execute(self, **_kwargs):
                return iter([])

        monkeypatch.setattr(
            "internal.service.assistant_agent_service.AgentConfig",
            lambda **kwargs: SimpleNamespace(**kwargs),
        )
        # 技能详情/记忆策展工具与断言相关，mock 为固定占位符以匹配当前实现追加工具的次序
        monkeypatch.setattr(
            "internal.service.memory.skill_detail_tool.create_skill_detail_tool",
            lambda **kwargs: "skill-detail-tool",
        )
        monkeypatch.setattr(
            "internal.service.memory.agent_memory_tool.create_agent_memory_tools",
            lambda **kwargs: ["memory-add-tool", "memory-replace-tool", "memory-remove-tool"],
        )
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.TokenBufferMemory",
            _FakeTokenBufferMemory,
        )
        monkeypatch.setattr(
            "internal.service.executors.single_agent_executor.SingleAgentExecutor",
            _FakeSingleAgentExecutor,
        )

        with app.app_context():
            events = list(service.chat(req, account))

        assert len(events) == 3
        assert events[0].startswith("event: billing_started")
        assert events[1].startswith("event: billing_summary")
        assert events[2].startswith("event: billing_final")
        assert resolution_capture == {
            "model_config": {"provider": "openai", "model": "gpt-4o-mini"},
            "image_urls": req.image_urls.data,
            "entrypoint": "assistant_agent",
        }
        assert executor_capture["kwargs"]["llm"] is llm
        assert executor_capture["kwargs"]["agent_config"].tools == [
            "public-agent-route-tool",
            "faiss-tool",
            "create-app-tool",
            "skill-detail-tool",
            "memory-add-tool",
            "memory-replace-tool",
            "memory-remove-tool",
        ]
        assert save_payload["agent_thoughts"] == []

    def test_chat_should_use_a2a_deep_thinking_agent_when_enabled(
        self, monkeypatch, app
    ):
        assistant_agent_id = uuid4()
        app.config["ASSISTANT_AGENT_ID"] = assistant_agent_id
        conversation = SimpleNamespace(id=uuid4(), summary="历史摘要")
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation=conversation)
        req = SimpleNamespace(
            query=SimpleNamespace(data="帮我生成一个可下载的需求文档"),
            image_urls=SimpleNamespace(data=[]),
            conversation_id=SimpleNamespace(data=""),
            confirm_deep_thinking=SimpleNamespace(data=True),
        )

        service = AssistantAgentService(
            db=SimpleNamespace(
                session=SimpleNamespace(query=lambda *_a, **_kw: _QueryStub())
            ),
            faiss_service=SimpleNamespace(convert_faiss_to_tool=lambda: "faiss-tool"),
            conversation_service=SimpleNamespace(save_agent_thoughts=lambda **_kwargs: None),
            redis_client=SimpleNamespace(),
            public_agent_a2a_service=SimpleNamespace(
                convert_public_agent_route_to_tool=lambda _account_id: "public-agent-route-tool"
            ),
        )

        monkeypatch.setattr(
            service,
            "create",
            lambda _model, **_kwargs: SimpleNamespace(id=uuid4()),
        )
        monkeypatch.setattr(
            service,
            "convert_create_app_to_tool",
            lambda _account_id: "create-app-tool",
        )

        class _FakeLLM:
            def __init__(self, **_kwargs):
                pass

            def convert_to_human_message(self, query, image_urls):
                return {"query": query, "image_urls": image_urls}

        class _FakeTokenBufferMemory:
            def __init__(self, **_kwargs):
                pass

            def build_context(self, conversation_id, current_query, account):
                return {
                    "recent_messages": [],
                    "distant_summary": "",
                    "relevant_facts": [],
                    "combined_token_count": 0,
                }

        executor_capture = {}

        class _FakeSingleAgentExecutor:
            collected_thoughts = []

            def __init__(self, **kwargs):
                executor_capture["kwargs"] = kwargs

            def execute(self, **_kwargs):
                return iter([])

        monkeypatch.setattr(
            "internal.service.assistant_agent_service.AgentConfig",
            lambda **kwargs: SimpleNamespace(**kwargs),
        )
        monkeypatch.setattr(
            "internal.service.language_model_service.LanguageModelService.get_chat_model_by_tier",
            classmethod(lambda cls, tier: _FakeLLM()),
        )
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.TokenBufferMemory",
            _FakeTokenBufferMemory,
        )
        monkeypatch.setattr(
            "internal.service.executors.single_agent_executor.SingleAgentExecutor",
            _FakeSingleAgentExecutor,
        )

        with app.app_context():
            list(service.chat(req, account))

        assert executor_capture["kwargs"]["agent_config"].enable_deep_thinking is True
        assert executor_capture["kwargs"]["agent_config"].runtime_flask_app is not None
        assert executor_capture["kwargs"]["agent_config"].invoke_from == InvokeFrom.ASSISTANT_AGENT.value

    def test_chat_should_prefer_registry_search_tool_when_available(
        self, monkeypatch, app
    ):
        assistant_agent_id = uuid4()
        app.config["ASSISTANT_AGENT_ID"] = assistant_agent_id
        conversation = SimpleNamespace(id=uuid4(), summary="历史摘要")
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation=conversation)
        req = SimpleNamespace(
            query=SimpleNamespace(data="请使用护肤智能体回答我油痘肌该怎么护肤"),
            image_urls=SimpleNamespace(data=[]),
            conversation_id=SimpleNamespace(data=""),
            confirm_deep_thinking=SimpleNamespace(data=False),
        )

        service = AssistantAgentService(
            db=SimpleNamespace(
                session=SimpleNamespace(query=lambda *_a, **_kw: _QueryStub())
            ),
            faiss_service=SimpleNamespace(convert_faiss_to_tool=lambda: "faiss-tool"),
            conversation_service=SimpleNamespace(
                save_agent_thoughts=lambda **_kwargs: None
            ),
            redis_client=SimpleNamespace(),
            public_agent_a2a_service=SimpleNamespace(
                convert_public_agent_route_to_tool=lambda _account_id: "public-agent-route-tool"
            ),
            public_agent_registry_service=SimpleNamespace(
                convert_public_agent_search_to_tool=lambda: "registry-search-tool"
            ),
        )

        monkeypatch.setattr(
            service,
            "create",
            lambda _model, **_kwargs: SimpleNamespace(id=uuid4()),
        )
        monkeypatch.setattr(
            service,
            "convert_create_app_to_tool",
            lambda _account_id: "create-app-tool",
        )

        class _FakeLLM:
            def __init__(self, **_kwargs):
                pass

            def convert_to_human_message(self, query, image_urls):
                return {"query": query, "image_urls": image_urls}

        class _FakeTokenBufferMemory:
            def __init__(self, **_kwargs):
                pass

            def build_context(self, conversation_id, current_query, account):
                return {
                    "recent_messages": [],
                    "distant_summary": "",
                    "relevant_facts": [],
                    "combined_token_count": 0,
                }

        executor_capture = {}

        class _FakeSingleAgentExecutor:
            collected_thoughts = []

            def __init__(self, **kwargs):
                executor_capture["kwargs"] = kwargs

            def execute(self, **_kwargs):
                return iter([])

        monkeypatch.setattr(
            "internal.service.assistant_agent_service.AgentConfig",
            lambda **kwargs: SimpleNamespace(**kwargs),
        )
        # 技能详情/记忆策展工具与断言相关，mock 为固定占位符以匹配当前实现追加工具的次序
        monkeypatch.setattr(
            "internal.service.memory.skill_detail_tool.create_skill_detail_tool",
            lambda **kwargs: "skill-detail-tool",
        )
        monkeypatch.setattr(
            "internal.service.memory.agent_memory_tool.create_agent_memory_tools",
            lambda **kwargs: ["memory-add-tool", "memory-replace-tool", "memory-remove-tool"],
        )
        monkeypatch.setattr(
            "internal.service.language_model_service.LanguageModelService.get_chat_model_by_tier",
            classmethod(lambda cls, tier: _FakeLLM()),
        )
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.TokenBufferMemory",
            _FakeTokenBufferMemory,
        )
        monkeypatch.setattr(
            "internal.service.executors.single_agent_executor.SingleAgentExecutor",
            _FakeSingleAgentExecutor,
        )

        with app.app_context():
            list(service.chat(req, account))

        assert executor_capture["kwargs"]["agent_config"].tools == [
            "public-agent-route-tool",
            "registry-search-tool",
            "create-app-tool",
            "skill-detail-tool",
            "memory-add-tool",
            "memory-replace-tool",
            "memory-remove-tool",
        ]

    def test_generate_introduction_should_skip_empty_chunks(self, monkeypatch):
        latest_message = SimpleNamespace(id=uuid4(), query="你好", answer="你好呀")

        class _Query:
            def __init__(self, rows):
                self._rows = rows

            def filter(self, *_args, **_kwargs):
                return self

            def order_by(self, *_args, **_kwargs):
                return self

            def limit(self, *_args, **_kwargs):
                return self

            def all(self):
                return self._rows

        class _Session:
            def __init__(self):
                self._queries = [
                    _Query([latest_message]),
                    _Query([("历史偏好：更关注自动化",)]),
                ]

            def query(self, _model):
                return self._queries.pop(0)

        class _FakeLLM:
            @staticmethod
            def stream(_messages):
                # 这里故意混入空分块，验证服务会跳过空输出分片。
                return iter(["", {"text": "欢迎回来。"}, None, "建议先定义目标。"])

            def get_num_tokens_from_messages(self, messages):
                return 10

        monkeypatch.setattr(
            "internal.service.language_model_service.LanguageModelService.get_feature_model",
            classmethod(lambda cls, feature_key: _FakeLLM()),
        )
        service = AssistantAgentService(
            db=SimpleNamespace(session=_Session()),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(get=lambda key: None, setex=lambda key, ttl, value: None),
        )
        account = SimpleNamespace(id=uuid4(), name="测试用户")

        events = list(service.generate_introduction(account))

        intro_chunk_events = [
            item for item in events if item.startswith("event: intro_chunk")
        ]
        assert len(intro_chunk_events) == 2
        done_event = [item for item in events if item.startswith("event: intro_done")][
            0
        ]
        done_payload = json.loads(done_event.split("data:", 1)[1].strip())
        assert done_payload["is_first_time"] is False
        assert done_payload["suggested_questions_message_id"] == str(latest_message.id)

    def test_generate_introduction_should_emit_error_event_when_stream_failed(
        self, monkeypatch
    ):
        latest_message = SimpleNamespace(id=uuid4(), query="你好", answer="你好呀")

        class _Query:
            def __init__(self, rows):
                self._rows = rows

            def filter(self, *_args, **_kwargs):
                return self

            def order_by(self, *_args, **_kwargs):
                return self

            def limit(self, *_args, **_kwargs):
                return self

            def all(self):
                return self._rows

        class _Session:
            def __init__(self):
                self._queries = [
                    _Query([latest_message]),
                    _Query([("历史偏好：关注测试稳定性",)]),
                ]

            def query(self, _model):
                return self._queries.pop(0)

        class _FakeLLM:
            @staticmethod
            def stream(_messages):
                raise RuntimeError("stream boom")

            def get_num_tokens_from_messages(self, messages):
                return 10

        monkeypatch.setattr(
            "internal.service.language_model_service.LanguageModelService.get_feature_model",
            classmethod(lambda cls, feature_key: _FakeLLM()),
        )
        service = AssistantAgentService(
            db=SimpleNamespace(session=_Session()),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(get=lambda key: None, setex=lambda key, ttl, value: None),
        )
        account = SimpleNamespace(id=uuid4(), name="测试用户")

        events = list(service.generate_introduction(account))

        assert len(events) == 1
        assert events[0].startswith("event: error")
        payload = json.loads(events[0].split("data:", 1)[1].strip())
        assert "个性化介绍生成失败" in payload["observation"]

    def test_get_conversations_should_return_active_flag_and_timestamps(self, app):
        assistant_agent_id = uuid4()
        app.config["ASSISTANT_AGENT_ID"] = assistant_agent_id
        active_id = uuid4()
        now = datetime.now()
        conversations = [
            SimpleNamespace(
                id=active_id, name="当前会话", updated_at=now, created_at=now
            ),
            SimpleNamespace(
                id=uuid4(), name="历史会话", updated_at=now, created_at=now
            ),
        ]

        class _MessageIdQuery:
            def filter(self, *_args, **_kwargs):
                return self

            def exists(self):
                return True

        class _ConversationQuery:
            def filter(self, *_args, **_kwargs):
                return self

            def order_by(self, *_args, **_kwargs):
                return self

            def limit(self, *_args, **_kwargs):
                return self

            def all(self):
                return conversations

        class _Session:
            def __init__(self):
                self.calls = 0

            def query(self, _model):
                self.calls += 1
                if self.calls == 1:
                    return _MessageIdQuery()
                return _ConversationQuery()

        service = AssistantAgentService(
            db=SimpleNamespace(session=_Session()),
            faiss_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            redis_client=SimpleNamespace(),
        )
        req = SimpleNamespace(limit=SimpleNamespace(data=20))
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation_id=active_id)

        with app.app_context():
            result = service.get_conversations(req, account)

        assert len(result) == 2
        assert result[0]["id"] == active_id
        assert result[0]["is_active"] is True
        assert result[1]["is_active"] is False

    def test_extract_chunk_content_should_fallback_for_unknown_items(self):
        assert AssistantAgentService._extract_chunk_content([1, {"text": "b"}]) == "1b"
        assert AssistantAgentService._extract_chunk_content(123) == "123"

    def test_build_introduction_prompt_messages_should_skip_summary_and_empty_query_answer(
        self,
    ):
        account = SimpleNamespace(name="  ")
        messages = [
            SimpleNamespace(query="最近在做测试", answer=""),
            SimpleNamespace(query="", answer="建议先补单元测试"),
            SimpleNamespace(query=" ", answer=" "),
        ]

        prompt_messages = AssistantAgentService._build_introduction_prompt_messages(
            account=account,
            summary="",
            messages=messages,
        )

        contents = [getattr(item, "content", "") for item in prompt_messages]
        assert isinstance(prompt_messages[0], SystemMessage)
        assert "你是钰心AI" in prompt_messages[0].content
        assert all(isinstance(item, HumanMessage) for item in prompt_messages[1:])
        assert "用户历史会话摘要如下" not in "\n".join(contents)
        assert any("最近在做测试" in content for content in contents)
        assert all("建议先补单元测试" not in content for content in contents)

    def test_build_introduction_prompt_messages_should_not_include_ai_history(self):
        account = SimpleNamespace(name="开发者")
        messages = [
            SimpleNamespace(query="我想创建应用", answer="好的，我们开始。"),
            SimpleNamespace(query="我希望支持微信发布", answer="明白了。"),
        ]

        prompt_messages = AssistantAgentService._build_introduction_prompt_messages(
            account=account,
            summary="近期主要关注创建应用和发布渠道",
            messages=messages,
        )

        assert all(
            not hasattr(item, "type") or item.type != "ai" for item in prompt_messages
        )
        assert all(
            "好的，我们开始。" not in getattr(item, "content", "")
            for item in prompt_messages
        )
        assert all(
            "明白了。" not in getattr(item, "content", "") for item in prompt_messages
        )

    def test_contains_markdown_should_detect_code_fence(self):
        assert (
            AssistantAgentService._contains_markdown_syntax(
                "```python\nprint('hello')\n```"
            )
            is True
        )

    def test_ensure_introduction_markdown_should_cover_fallback_branches(self):
        empty_markdown = AssistantAgentService._ensure_introduction_markdown(
            introduction="",
            display_name="开发者",
        )
        assert empty_markdown.startswith("### Hi，开发者")
        markdown = "### 已有标题\n- 建议项"
        assert (
            AssistantAgentService._ensure_introduction_markdown(
                introduction=markdown,
                display_name="开发者",
            )
            == markdown
        )
        punctuation_only = AssistantAgentService._ensure_introduction_markdown(
            introduction="。。。！！！",
            display_name="开发者",
        )
        assert punctuation_only.startswith("### Hi，开发者")
        assert "。。。！！！" in punctuation_only

    def test_ensure_introduction_markdown_should_not_add_suggestion_block_for_single_sentence(
        self,
    ):
        markdown = AssistantAgentService._ensure_introduction_markdown(
            introduction="欢迎回来",
            display_name="开发者",
        )

        assert markdown.startswith("### Hi，开发者")
        assert "#### 建议下一步" not in markdown

    def test_get_conversation_messages_with_page_should_include_messages_with_empty_answer(
        self, monkeypatch
    ):
        """
        测试：验证修复了消息不显示问题

        问题描述：
        用户发送消息后，消息被创建但答案还在生成中（answer 为空）。
        前端立即查询消息时，后端因为过滤条件 Message.answer != "" 而返回 0 条记录。

        修复方案：
        改为只过滤 Message.query != ""，允许答案为空的消息显示。
        """
        service = self._build_service()
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation=None)
        conversation_id = uuid4()

        # 模拟请求对象
        req = SimpleNamespace(
            conversation_id=SimpleNamespace(data=str(conversation_id)),
            current_page=SimpleNamespace(data=1),
            page_size=SimpleNamespace(data=5),
            created_at=SimpleNamespace(data=0),
        )

        # 模拟对话对象
        conversation = SimpleNamespace(
            id=conversation_id,
            created_by=account.id,
            is_deleted=False,
            invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
        )

        # 模拟消息对象 - 答案为空（正在生成中）
        message_with_empty_answer = SimpleNamespace(
            id=uuid4(),
            conversation_id=conversation_id,
            query="你好",
            answer="",  # 答案为空
            status="normal",
            is_deleted=False,
            agent_thoughts=[],
        )

        # 模拟 _resolve_assistant_agent_conversation 方法
        def mock_resolve_conversation(*args, **kwargs):
            return conversation

        monkeypatch.setattr(
            service, "_resolve_assistant_agent_conversation", mock_resolve_conversation
        )

        # 模拟分页器
        mock_paginator = SimpleNamespace(
            paginate=lambda query: [message_with_empty_answer.id]
        )
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.Paginator",
            lambda **kwargs: mock_paginator,
        )

        # 模拟分页查询
        monkeypatch.setattr(
            service,
            "db",
            SimpleNamespace(
                session=SimpleNamespace(
                    query=lambda *args, **kwargs: SimpleNamespace(
                        filter=lambda *args, **kwargs: SimpleNamespace(
                            order_by=lambda *args, **kwargs: SimpleNamespace(
                                all=lambda: [message_with_empty_answer]
                            )
                        ),
                        options=lambda *args, **kwargs: SimpleNamespace(
                            filter=lambda *args, **kwargs: SimpleNamespace(
                                order_by=lambda *args, **kwargs: SimpleNamespace(
                                    all=lambda: [message_with_empty_answer]
                                )
                            )
                        ),
                    )
                )
            ),
        )

        # 调用方法
        messages, paginator = service.get_conversation_messages_with_page(req, account)

        # 验证结果 - 应该返回消息，即使答案为空
        assert len(messages) == 1
        assert messages[0].id == message_with_empty_answer.id
        assert messages[0].query == "你好"
        assert messages[0].answer == ""  # 答案为空也应该返回

    def test_get_conversation_messages_with_page_should_exclude_messages_with_empty_query(
        self, monkeypatch
    ):
        """
        测试：验证仍然过滤掉 query 为空的消息

        说明：
        虽然允许答案为空，但仍然应该过滤掉用户提问为空的消息。
        """
        service = self._build_service()
        account = SimpleNamespace(id=uuid4(), assistant_agent_conversation=None)
        conversation_id = uuid4()

        # 模拟请求对象
        req = SimpleNamespace(
            conversation_id=SimpleNamespace(data=str(conversation_id)),
            current_page=SimpleNamespace(data=1),
            page_size=SimpleNamespace(data=5),
            created_at=SimpleNamespace(data=0),
        )

        # 模拟对话对象
        conversation = SimpleNamespace(
            id=conversation_id,
            created_by=account.id,
            is_deleted=False,
            invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
        )

        # 模拟 _resolve_assistant_agent_conversation 方法
        def mock_resolve_conversation(*args, **kwargs):
            return conversation

        monkeypatch.setattr(
            service, "_resolve_assistant_agent_conversation", mock_resolve_conversation
        )

        # 模拟分页器 - 返回空列表
        mock_paginator = SimpleNamespace(paginate=lambda query: [])
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.Paginator",
            lambda **kwargs: mock_paginator,
        )

        # 模拟分页查询 - 返回空列表（因为 query 为空被过滤掉了）
        monkeypatch.setattr(
            service,
            "db",
            SimpleNamespace(
                session=SimpleNamespace(
                    query=lambda *args, **kwargs: SimpleNamespace(
                        filter=lambda *args, **kwargs: SimpleNamespace(
                            order_by=lambda *args, **kwargs: SimpleNamespace(
                                all=lambda: []  # 返回空列表
                            )
                        ),
                        options=lambda *args, **kwargs: SimpleNamespace(
                            filter=lambda *args, **kwargs: SimpleNamespace(
                                order_by=lambda *args, **kwargs: SimpleNamespace(
                                    all=lambda: []
                                )
                            )
                        ),
                    )
                )
            ),
        )

        # 调用方法
        messages, paginator = service.get_conversation_messages_with_page(req, account)

        # 验证结果 - 应该返回空列表
        assert len(messages) == 0
