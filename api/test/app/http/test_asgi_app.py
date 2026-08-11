"""ASGI 流式入口（app.http.asgi_app）单元测试。

覆盖：
- 路由注册
- POST /api/async/chat/completion 输出 SSE 帧（text/event-stream）
- 请求参数透传（query / enable_deep_thinking / conversation_id 等）
- 流内异常时输出 error 帧
"""

import asyncio
import json
import time
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.http import asgi_app
from app.http import support


class _FakeAppRuntimeService:
    def __init__(self, frames, raise_on_call=False):
        self._frames = frames
        self.raise_on_call = raise_on_call
        self.calls = []

    async def stream_agent_events_async(self, **kwargs):
        if self.raise_on_call:
            raise RuntimeError("boom")
        self.calls.append(kwargs)
        for frame in self._frames:
            yield frame


def _build_fakes(monkeypatch, runtime_service):
    account = SimpleNamespace(id=uuid4())
    draft_app_config = {"model_config": {"model": "fake"}, "preset_prompt": "p"}
    llm = SimpleNamespace(convert_to_human_message=lambda query, image_urls: {})
    monkeypatch.setattr(
        support,
        "_load_runtime_context",
        lambda *a, **k: (account, draft_app_config, llm),
    )
    monkeypatch.setattr(support, "_load_account", lambda _aid: account)
    monkeypatch.setattr(
        support,
        "_get_services",
        lambda: (runtime_service, None, None, None),
    )
    return account, draft_app_config, llm


class TestAsgiApp:
    def test_route_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/api/async/chat/completion" in rules
        assert "/conversations/recent" in rules

    def test_chat_completion_streams_sse_frames(self, monkeypatch):
        runtime_service = _FakeAppRuntimeService([
            'event: agent_message\ndata:{"answer":"hi"}\n\n',
            'event: agent_end\ndata:{"answer":"hi"}\n\n',
        ])
        _build_fakes(monkeypatch, runtime_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/api/async/chat/completion",
                    json={
                        "app_id": str(uuid4()),
                        "account_id": str(uuid4()),
                        "query": "hello",
                        "enable_deep_thinking": True,
                    },
                )
                assert resp.status_code == 200
                assert resp.mimetype == "text/event-stream"
                body = b"".join([chunk async for chunk in resp.response])
                return resp, body

        resp, body = asyncio.run(_run())

        assert b"event: agent_message" in body
        assert b"event: agent_end" in body
        assert body.endswith(b"\n\n")
        assert len(runtime_service.calls) == 1
        call = runtime_service.calls[0]
        assert call["query"] == "hello"
        assert call["enable_deep_thinking"] is True
        assert call["flask_app"] is asgi_app.flask_app

    def test_chat_completion_passes_optional_fields(self, monkeypatch):
        runtime_service = _FakeAppRuntimeService([])
        _build_fakes(monkeypatch, runtime_service)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/api/async/chat/completion",
                    json={
                        "app_id": str(app_id),
                        "account_id": str(uuid4()),
                        "query": "q",
                        "image_urls": ["http://img/1.png"],
                        "history": [{"role": "user", "content": "prev"}],
                        "long_term_memory": "mem",
                        "conversation_id": "conv-1",
                        "message_id": "msg-1",
                    },
                )
                _ = b"".join([chunk async for chunk in resp.response])
                return resp

        asyncio.run(_run())

        assert len(runtime_service.calls) == 1
        call = runtime_service.calls[0]
        assert call["app_id"] == app_id
        assert call["image_urls"] == ["http://img/1.png"]
        assert call["history"] == [{"role": "user", "content": "prev"}]
        assert call["long_term_memory"] == "mem"
        assert call["conversation_id"] == "conv-1"
        assert call["message_id"] == "msg-1"

    def test_chat_completion_emits_error_frame_on_stream_failure(self, monkeypatch):
        runtime_service = _FakeAppRuntimeService([], raise_on_call=True)
        _build_fakes(monkeypatch, runtime_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/api/async/chat/completion",
                    json={
                        "app_id": str(uuid4()),
                        "account_id": str(uuid4()),
                        "query": "hello",
                    },
                )
                body = b"".join([chunk async for chunk in resp.response])
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert b'event: error' in body
        assert b'internal_error' in body

    def test_concurrent_streams_do_not_block_each_other(self, monkeypatch):
        """并发 50 个 SSE 流（每流 10 chunk × 5ms 模拟 LLM 流式延迟）。

        验证方案 B 核心价值：async 全链路下，单事件循环可并行承载大量流，
        总耗时应远小于串行总耗时（串行 ≈ 50 × 10 × 5ms = 2.5s）。
        """
        async def _slow_stream(**kwargs):
            for i in range(10):
                await asyncio.sleep(0.005)
                yield f"event: agent_message\ndata:{json.dumps({'chunk': i})}\n\n"
            yield 'event: agent_end\ndata:{"done":true}\n\n'

        runtime_service = SimpleNamespace(stream_agent_events_async=_slow_stream)
        _build_fakes(monkeypatch, runtime_service)

        async def _one_request(client, idx):
            resp = await client.post(
                "/api/async/chat/completion",
                json={
                    "app_id": str(uuid4()),
                    "account_id": str(uuid4()),
                    "query": f"q{idx}",
                },
            )
            body = b"".join([chunk async for chunk in resp.response])
            return resp, body

        async def _run():
            start = time.monotonic()
            async with asgi_app.quart_app.test_client() as client:
                results = await asyncio.gather(*[_one_request(client, i) for i in range(50)])
            elapsed = time.monotonic() - start
            return results, elapsed

        results, elapsed = asyncio.run(_run())

        assert len(results) == 50
        for resp, body in results:
            assert resp.status_code == 200
            assert body.count(b"event: agent_message") == 10
            assert b"event: agent_end" in body
        # 并发耗时应显著小于串行耗时 2.5s（给 CI 留余量）
        assert elapsed < 2.0, f"并发流总耗时 {elapsed:.2f}s，async 并行性未生效"


class _FakeConversationService:
    def __init__(self, results, raise_account=False):
        self._results = results
        self.raise_account = raise_account
        self.calls = []

    async def get_recent_conversations_async(self, account, limit=20, assistant_agent_id=None):
        self.calls.append((account, limit, assistant_agent_id))
        return self._results


class TestAsgiRecentConversations:
    def test_returns_recent_conversations(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        fake_service = _FakeConversationService([
            {"id": str(uuid4()), "name": "会话A", "source_type": "app_debugger"},
        ])
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: fake_service)
        monkeypatch.setattr("app.http.conversation_routes.flask_app", SimpleNamespace(
            config={"ASSISTANT_AGENT_ID": "agent-1"},
        ))

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/conversations/recent?account_id={account.id}&limit=5"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]) == 1
        assert payload["data"][0]["name"] == "会话A"
        assert fake_service.calls[0][1] == 5
        assert fake_service.calls[0][2] == "agent-1"

    def test_invalid_account_id_returns_400(self, monkeypatch):
        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/conversations/recent?account_id=not-a-uuid")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "invalid_param"

    def test_account_not_found_returns_404(self, monkeypatch):
        monkeypatch.setattr(
            support,
            "_load_account",
            lambda _aid: (_ for _ in ()).throw(RuntimeError("account missing")),
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/conversations/recent?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 404
        assert payload["code"] == "account_not_found"


@dataclass
class _Paginator:
    total_page: int = 1
    total_record: int = 1
    current_page: int = 1
    page_size: int = 20


class _FakeMessageService:
    def __init__(self, messages=None, error=None):
        self._messages = messages or [
            SimpleNamespace(
                id=uuid4(),
                conversation_id=uuid4(),
                invoke_from="app_debugger",
                query="hi",
                image_urls=[],
                answer="hello",
                total_token_count=0,
                latency=0.0,
                agent_thoughts=[],
                suggested_questions=[],
                created_at=1710000000,
            )
        ]
        self._error = error
        self.calls = []

    async def get_conversation_messages_with_page_async(self, conversation_id, req, account):
        self.calls.append((conversation_id, req, account))
        if self._error:
            raise self._error
        return self._messages, _Paginator()


class TestAsgiConversationMessages:
    def test_returns_paginated_messages(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        conversation_id = uuid4()
        fake_service = _FakeMessageService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: fake_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/conversations/{conversation_id}/messages?account_id={account.id}&current_page=1&page_size=10"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]["list"]) == 1
        assert payload["data"]["paginator"]["page_size"] == 20
        assert fake_service.calls[0][0] == conversation_id
        assert fake_service.calls[0][1].page_size.data == 10

    def test_invalid_account_id_returns_400(self):
        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/conversations/{uuid4()}/messages?account_id=not-a-uuid"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "invalid_param"

    def test_conversation_not_found_returns_404(self, monkeypatch):
        from internal.exception import NotFoundException

        account = SimpleNamespace(id=uuid4())
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_conversation_service",
            lambda: _FakeMessageService(error=NotFoundException("不存在")),
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/conversations/{uuid4()}/messages?account_id={account.id}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 404
        assert payload["code"] == "conversation_not_found"


class _FakeActionsService:
    def __init__(self):
        self.deleted = []
        self.messages_deleted = []
        self.conversation = SimpleNamespace(name="会话A")
        self.updates = []
        self.searches = []
        self.raise_not_found = False

    def delete_conversation(self, conversation_id, account):
        self.deleted.append((conversation_id, account))
        if self.raise_not_found:
            from internal.exception import NotFoundException

            raise NotFoundException("不存在")

    def delete_message(self, conversation_id, message_id, account):
        self.messages_deleted.append((conversation_id, message_id, account))

    def get_conversation(self, conversation_id, account):
        return self.conversation

    def update_conversation(self, conversation_id, account, name=None, is_pinned=None):
        self.updates.append((conversation_id, account, name, is_pinned))

    def search_conversations(self, account, query, limit):
        self.searches.append((account, query, limit))
        return [
            SimpleNamespace(
                id=uuid4(),
                name="搜索结果",
                query=query,
                answer="ans",
                created_at=1710000000,
            )
        ]


class TestAsgiConversationActions:
    def test_delete_conversation(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        conversation_id = uuid4()
        fake = _FakeActionsService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: fake)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{conversation_id}/delete?account_id={account.id}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "删除会话成功"
        assert fake.deleted[0][0] == conversation_id

    def test_delete_conversation_not_found(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        fake = _FakeActionsService()
        fake.raise_not_found = True
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: fake)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{uuid4()}/delete?account_id={account.id}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 404
        assert payload["code"] == "conversation_not_found"

    def test_update_conversation_name(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        conversation_id = uuid4()
        fake = _FakeActionsService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: fake)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{conversation_id}/name?account_id={account.id}",
                    json={"name": "新名字"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert fake.updates[0][2] == "新名字"

    def test_update_conversation_name_rejects_empty(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: _FakeActionsService())

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{uuid4()}/name?account_id={account.id}",
                    json={"name": "  "},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "invalid_param"

    def test_update_conversation_is_pinned(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        conversation_id = uuid4()
        fake = _FakeActionsService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: fake)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{conversation_id}/is-pinned?account_id={account.id}",
                    json={"is_pinned": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert fake.updates[0][3] is True

    def test_get_conversation_name(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        conversation_id = uuid4()
        fake = _FakeActionsService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: fake)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/conversations/{conversation_id}/name?account_id={account.id}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "会话A"

    def test_search_conversations(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        fake = _FakeActionsService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: fake)

        async def _run():
            from urllib.parse import quote

            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/conversations/search?account_id={account.id}&query={quote('测试')}&limit=5"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert fake.searches[0][1] == "测试"
        assert fake.searches[0][2] == 5
        assert len(payload["data"]) == 1

    def test_delete_message(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        conversation_id = uuid4()
        message_id = uuid4()
        fake = _FakeActionsService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: fake)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{conversation_id}/messages/{message_id}/delete?account_id={account.id}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert fake.messages_deleted[0][1] == message_id


class _FakeVariableService:
    def __init__(self):
        self.variables = []
        self.sets = []
        self.batch = []
        self.deleted = []
        self.deleted_all = None

    def get_variables(self, conversation_id):
        return self.variables

    def set_variable(self, conversation_id, name, value, value_type):
        self.sets.append((conversation_id, name, value, value_type))
        return {"name": name, "value": value, "value_type": value_type}

    def batch_set_variables(self, conversation_id, variables):
        self.batch.append((conversation_id, variables))
        return variables

    def delete_variable(self, conversation_id, name):
        self.deleted.append((conversation_id, name))

    def delete_variables_by_conversation(self, conversation_id):
        self.deleted_all = conversation_id
        return 3


class TestAsgiConversationVariables:
    def _setup(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        conv_service = _FakeActionsService()
        var_service = _FakeVariableService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_conversation_service", lambda: conv_service)
        monkeypatch.setattr(support, "_get_service", lambda cls: var_service)
        return account, var_service

    def test_get_variables(self, monkeypatch):
        account, var_service = self._setup(monkeypatch)
        var_service.variables = [{"name": "city", "value": "北京"}]

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/conversations/{uuid4()}/variables?account_id={account.id}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == [{"name": "city", "value": "北京"}]

    def test_set_variable(self, monkeypatch):
        account, var_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{uuid4()}/variables?account_id={account.id}",
                    json={"name": "city", "value": "北京", "value_type": "string"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert var_service.sets[0][1] == "city"

    def test_set_variable_validation_error(self, monkeypatch):
        account, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{uuid4()}/variables?account_id={account.id}",
                    json={"name": "city"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


    def test_batch_set_variables(self, monkeypatch):
        account, var_service = self._setup(monkeypatch)
        variables = {"a": "1", "b": 2}

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{uuid4()}/variables/batch?account_id={account.id}",
                    json={"variables": variables},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert var_service.batch[0][1] == variables

    def test_delete_variable(self, monkeypatch):
        account, var_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{uuid4()}/variables/city/delete?account_id={account.id}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert var_service.deleted[0][1] == "city"

    def test_delete_all_variables(self, monkeypatch):
        account, var_service = self._setup(monkeypatch)
        conversation_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/conversations/{conversation_id}/variables/delete-all?account_id={account.id}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert var_service.deleted_all == conversation_id
        assert payload["data"]["count"] == 3


class _FakeAccountService:
    def __init__(self):
        self.calls = []

    def resolve_ip_location(self, client_ip):
        return "北京"

    def get_account_oauth_bindings(self, account):
        return []

    def change_password(self, account, current, new):
        self.calls.append(("pw", current, new))

    def update_account(self, account, **kwargs):
        self.calls.append(("update", kwargs))

    def send_change_email_code(self, account, email):
        self.calls.append(("send", email))

    def update_email(self, account, email, code, current_password):
        self.calls.append(("email", email, code))

    def get_account_sessions(self, account, current_session_id=None):
        self.calls.append(("sessions", current_session_id))
        return [{"id": str(uuid4()), "current": True}]

    def get_account_login_history(self, account, current_session_id=None, **kwargs):
        self.calls.append(("history", kwargs))
        return {"history": [], "total": 0, "current_page": 1, "page_size": 20}

    def revoke_account_session(self, account, session_id, current_session_id=None):
        self.calls.append(("revoke", session_id))

    def revoke_other_account_sessions(self, account, current_session_id=None):
        self.calls.append(("revoke_others", current_session_id))


class _FakeOAuthService:
    def __init__(self):
        self.calls = []

    def unbind_oauth(self, account, provider_name):
        self.calls.append((account, provider_name))


class TestAsgiAccount:
    def _setup(self, monkeypatch):
        from internal.service.account_service import AccountService
        from internal.service.oauth_service import OAuthService

        account = SimpleNamespace(
            id=uuid4(),
            name="测试用户",
            email="a@b.com",
            avatar="",
            last_login_at=1710000000,
            last_login_ip="1.2.3.4",
            is_password_set=True,
            created_at=1710000000,
        )
        account_service = _FakeAccountService()
        oauth_service = _FakeOAuthService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: (
                account_service if cls is AccountService else oauth_service
            ),
        )
        return account, account_service, oauth_service

    def test_get_current_user(self, monkeypatch):
        _, account_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/account?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "测试用户"

    def test_update_password(self, monkeypatch):
        _, account_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/account/password?account_id={uuid4()}",
                    json={"current_password": "old", "new_password": "new"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert account_service.calls[0] == ("pw", "old", "new")

    def test_update_password_missing_fields(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/account/password?account_id={uuid4()}",
                    json={"current_password": "old"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "invalid_param"

    def test_update_name(self, monkeypatch):
        _, account_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/account/name?account_id={uuid4()}", json={"name": "新名字"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert account_service.calls[0] == ("update", {"name": "新名字"})

    def test_update_avatar(self, monkeypatch):
        _, account_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/account/avatar?account_id={uuid4()}",
                    json={"avatar": "http://x/a.png"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert account_service.calls[0] == ("update", {"avatar": "http://x/a.png"})

    def test_send_change_email_code(self, monkeypatch):
        _, account_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/account/email/send-code?account_id={uuid4()}",
                    json={"email": "new@b.com"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert account_service.calls[0] == ("send", "new@b.com")

    def test_update_email(self, monkeypatch):
        _, account_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/account/email?account_id={uuid4()}",
                    json={"email": "new@b.com", "code": "1234"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert account_service.calls[0][0] == "email"

    def test_get_account_sessions(self, monkeypatch):
        _, account_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/account/sessions?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["session_capable"] is False

    def test_get_account_login_history(self, monkeypatch):
        _, account_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/account/login-history?account_id={uuid4()}&current_page=2"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert account_service.calls[0][0] == "history"
        assert account_service.calls[0][1]["current_page"] == 2

    def test_revoke_other_sessions(self, monkeypatch):
        _, account_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/account/sessions/revoke-others?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert account_service.calls[0][0] == "revoke_others"

    def test_revoke_account_session(self, monkeypatch):
        _, account_service, _ = self._setup(monkeypatch)
        session_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/account/sessions/{session_id}/revoke?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert account_service.calls[0][1] == session_id

    def test_unbind_oauth(self, monkeypatch):
        _, _, oauth_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/account/oauth/github/unbind?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert oauth_service.calls[0][1] == "github"


class TestAsgiSmallHandlers:
    def _setup(self, monkeypatch):
        from internal.service.analysis_service import AnalysisService
        from internal.service.home_service import HomeService
        from internal.service.language_model_service import LanguageModelService
        from internal.service.my_app_service import MyAppService
        from internal.service.tool_inventory_service import (
            ToolCandidateCollector,
            ToolPolicyFilter,
        )

        account = SimpleNamespace(id=uuid4())
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        services = {
            HomeService: SimpleNamespace(
                get_user_intent=lambda account: {"intent": "chat", "confidence": 0.9}
            ),
            AnalysisService: SimpleNamespace(
                get_app_analysis=lambda app_id, account: {"message_count": 10}
            ),
            ToolCandidateCollector: SimpleNamespace(collect=lambda aid: []),
            ToolPolicyFilter: SimpleNamespace(
                filter=lambda *a, **k: {
                    "candidates": [],
                    "filtered_out_tools": [],
                }
            ),
            LanguageModelService: SimpleNamespace(
                get_language_models=lambda: [{"provider_name": "openai"}],
                get_language_model=lambda p, m: {"provider_name": p, "model": m},
                get_language_model_icon=lambda p: (b"icon-bytes", "image/png"),
            ),
            MyAppService: SimpleNamespace(list_my_apps=lambda aid: []),
        }
        monkeypatch.setattr(support, "_get_service", lambda cls: services[cls])
        return account, services

    def test_get_intent(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/home/intent?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200

    def test_get_app_analysis(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/analysis/{uuid4()}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["message_count"] == 10

    def test_tool_inventory_route_is_not_registered(self, monkeypatch):
        self._setup(monkeypatch)

        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/tool-inventory" not in rules

    def test_get_language_models(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/language-models?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"][0]["provider_name"] == "openai"

    def test_get_language_model_icon(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/language-models/openai/icon")
                return resp

        resp = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "image/png"

    def test_get_language_model(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/language-models/openai/gpt-4?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["model"] == "gpt-4"

    def test_list_my_apps(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/my/apps?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []


class _FakeAppService:
    def __init__(self):
        self.calls = []

    def get_apps_with_page(self, req, account):
        self.calls.append(("list", req))
        return [], _Paginator(page_size=req.page_size.data)

    def create_app(self, req, account):
        self.calls.append(("create", req.name.data))
        return SimpleNamespace(id=uuid4())

    def get_app(self, app_id, account):
        return SimpleNamespace(
            id=app_id,
            name="测试应用",
            icon="",
            description="desc",
            status="draft",
            created_at=1710000000,
            updated_at=1710000000,
            is_public=False,
            agent_metadata=None,
            debug_conversation_id=uuid4(),
            draft_app_config=SimpleNamespace(updated_at=1710000000),
        )

    def update_app(self, app_id, account, **kwargs):
        self.calls.append(("update", app_id, kwargs))

    def delete_app(self, app_id, account):
        self.calls.append(("delete", app_id))

    def copy_app(self, app_id, account):
        self.calls.append(("copy", app_id))
        return SimpleNamespace(id=uuid4())

    def get_draft_app_config(self, app_id, account):
        return {"model_config": {}}

    def update_draft_app_config(self, app_id, config, account):
        self.calls.append(("draft", app_id))

    def publish_draft_app_config(self, app_id, account, share_to_square=True):
        self.calls.append(("publish", app_id, share_to_square))

    def cancel_publish_app_config(self, app_id, account):
        self.calls.append(("cancel", app_id))

    def get_publish_histories_with_page(self, app_id, req, account):
        return [], _Paginator()

    def get_versions(self, app_id, account):
        return []

    def fallback_history_to_draft(self, app_id, version_id, account):
        self.calls.append(("fallback", version_id))

    def get_published_config(self, app_id, account):
        return {"model_config": {}}

    def regenerate_web_app_token(self, app_id, account):
        return "token123"

    def regenerate_icon(self, app_id, account):
        return "http://icon.example/a.png"

    def generate_icon_preview(self, name, description):
        return "http://icon.example/preview.png"

    def import_app(self, json_data, account_id, overwrite_name=False):
        self.calls.append(("import", overwrite_name))
        return SimpleNamespace(id=uuid4())

    def export_app(self, app_id, account):
        return {"format": "yuxin-ai-app"}


class _FakeAppDebugService:
    def __init__(self):
        self.calls = []

    def get_debug_conversation_summary(self, app_id, account):
        return "长期记忆摘要"

    def update_debug_conversation_summary(self, app_id, summary, account):
        self.calls.append(("summary", summary))

    def delete_debug_conversation(self, app_id, account):
        self.calls.append(("delete_debug", app_id))

    def stop_debug_chat(self, app_id, task_id, account):
        self.calls.append(("stop", task_id))

    def stop_prompt_compare_chat(self, app_id, task_id, account):
        self.calls.append(("stop_pc", task_id))

    def get_debug_conversation_messages_with_page(self, app_id, req, account):
        return [], _Paginator()


class TestAsgiApps:
    def _setup(self, monkeypatch):
        from internal.service.app_debug_service import AppDebugService
        from internal.service.app_service import AppService

        account = SimpleNamespace(id=uuid4())
        app_service = _FakeAppService()
        app_debug_service = _FakeAppDebugService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: (
                app_service if cls is AppService else app_debug_service
            ),
        )
        return account, app_service, app_debug_service

    def test_get_apps_with_page(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/apps?account_id={uuid4()}&page_size=5")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["paginator"]["page_size"] == 5

    def test_create_app(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps?account_id={uuid4()}", json={"name": "新应用"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert "id" in payload["data"]
        assert app_service.calls[0] == ("create", "新应用")

    def test_create_app_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps?account_id={uuid4()}", json={"name": "  "}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "invalid_param"

    def test_get_app(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/apps/{uuid4()}?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "测试应用"

    def test_update_app(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}?account_id={uuid4()}", json={"name": "改名"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert app_service.calls[0][0] == "update"

    def test_delete_app(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/apps/{uuid4()}/delete?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert app_service.calls[0][0] == "delete"

    def test_copy_app(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/apps/{uuid4()}/copy?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert "id" in payload["data"]

    def test_get_draft_app_config(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/apps/{uuid4()}/draft-app-config?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert "model_config" in payload["data"]

    def test_update_draft_app_config(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/draft-app-config?account_id={uuid4()}",
                    json={"model_config": {"provider": "openai"}},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert app_service.calls[0][0] == "draft"

    def test_publish(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/publish?account_id={uuid4()}&share_to_square=true"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert app_service.calls[0][0] == "publish"
        assert app_service.calls[0][2] is True

    def test_get_publish_histories(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/apps/{uuid4()}/publish-histories?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200

    def test_fallback_history(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)
        version_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/fallback-history?account_id={uuid4()}",
                    json={"app_config_version_id": str(version_id)},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert app_service.calls[0][0] == "fallback"

    def test_get_debug_summary(self, monkeypatch):
        _, _, app_debug_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/apps/{uuid4()}/summary?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["summary"] == "长期记忆摘要"

    def test_stop_debug_chat(self, monkeypatch):
        _, _, app_debug_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/conversations/tasks/{uuid4()}/stop?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert app_debug_service.calls[0][0] == "stop"

    def test_get_published_config(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/apps/{uuid4()}/published-config?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert "model_config" in payload["data"]

    def test_regenerate_web_app_token(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/published-config/regenerate-web-app-token?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["token"] == "token123"

    def test_generate_icon_preview(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/generate-icon-preview?account_id={uuid4()}",
                    json={"name": "应用", "description": "描述"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert "icon" in payload["data"]

    def test_export_app(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/apps/{uuid4()}/export?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["format"] == "yuxin-ai-app"


class _FakeTagService:
    def __init__(self):
        self.calls = []
        self.tag = None

    def create_tag(self, account_id, name, description, tag_type):
        self.calls.append(("create", name))
        return SimpleNamespace(id=uuid4())

    def update_tag(self, tag_id, account_id, name, description):
        self.calls.append(("update", tag_id))
        return self.tag if self.tag is not None else SimpleNamespace(id=tag_id)

    def delete_tag(self, tag_id, account_id):
        self.calls.append(("delete", tag_id))
        return SimpleNamespace(id=tag_id)

    def get_tag_by_id(self, tag_id, account_id):
        return SimpleNamespace(
            id=tag_id, name="标签A", description="", tag_type="custom", created_at=1710000000
        )

    def get_tags_with_page(self, req, account_id):
        self.calls.append(("list", req))
        return [], _Paginator()

    def get_tag_dimensions(self):
        return [{"value": "industry", "label": "行业"}]

    def get_hot_tags(self):
        return {
            "热门": [
                {
                    "id": str(uuid4()),
                    "name": "热门",
                    "dimension": "custom",
                    "use_count": 5,
                }
            ]
        }


class _FakeNotificationService:
    def __init__(self):
        self.calls = []
        self.fail_read = False

    def get_user_notifications(self, account_id, limit, offset, notification_type):
        self.calls.append(("list", account_id))
        return [], 0

    def mark_as_read(self, account_id, notification_id):
        self.calls.append(("read", notification_id))
        return not self.fail_read

    def delete_notification(self, account_id, notification_id):
        self.calls.append(("delete", notification_id))
        return True


class _FakeBuiltinToolService:
    def get_builtin_tools(self):
        return {"list": [{"provider_name": "openai"}]}

    def get_provider_tool(self, provider_name, tool_name):
        return {"provider_name": provider_name, "tool_name": tool_name}

    def get_provider_icon(self, provider_name):
        return (b"icon", "image/png", None)

    def get_categories(self):
        return [{"key": "code", "label": "代码"}]


class TestAsgiTagsNotificationsTools:
    def _setup(self, monkeypatch):
        from internal.service import BuiltinToolService, TagService
        from internal.service.notification_service import NotificationService

        account = SimpleNamespace(id=uuid4())
        tag_service = _FakeTagService()
        notification_service = _FakeNotificationService()
        builtin_service = _FakeBuiltinToolService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: {
                TagService: tag_service,
                NotificationService: notification_service,
                BuiltinToolService: builtin_service,
            }.get(cls),
        )
        return account, tag_service, notification_service

    def test_get_builtin_tools(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/builtin-tools?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"][0]["provider_name"] == "openai"

    def test_get_provider_icon(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/builtin-tools/openai/icon?account_id={uuid4()}")
                return resp

        resp = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "image/png"

    def test_get_notifications(self, monkeypatch):
        _, _, notification_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/notifications?account_id={uuid4()}&limit=5")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["paginator"]["limit"] == 5

    def test_mark_notification_as_read(self, monkeypatch):
        _, _, notification_service = self._setup(monkeypatch)
        notification_id = "notif-1"

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/notifications/{notification_id}/read?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert notification_service.calls[0] == ("read", notification_id)

    def test_delete_notification(self, monkeypatch):
        _, _, notification_service = self._setup(monkeypatch)
        notification_id = "notif-1"

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/notifications/{notification_id}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert notification_service.calls[0][0] == "delete"

    def test_create_tag(self, monkeypatch):
        _, tag_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/tags?account_id={uuid4()}", json={"name": "新标签"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert tag_service.calls[0] == ("create", "新标签")

    def test_create_tag_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/tags?account_id={uuid4()}", json={"name": "  "}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_get_tag(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/tags/{uuid4()}?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "标签A"

    def test_list_tags(self, monkeypatch):
        _, tag_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/tags?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []

    def test_get_tag_dimensions(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/tags/dimensions")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["dimensions"][0]["value"] == "industry"

    def test_get_hot_tags(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/tags/hot")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["hot_tags"]["热门"][0]["name"] == "热门"


class _FakeSkillService:
    def __init__(self):
        self.calls = []

    def get_skill_categories(self):
        return {"total": 1, "categories": [{"category": "通用", "count": 1}]}

    def get_skill_packages_with_page(self, req):
        self.calls.append(("list", req))
        return [], _Paginator()

    def get_skill_package(self, skill_id):
        return SimpleNamespace(id=skill_id, name="技能包", version=1)

    def get_skill_package_icon(self, skill_id):
        return (b"icon", "image/png", None)

    def get_skill_package_versions(self, skill_id):
        return [SimpleNamespace(version=1, version_notes="v1")]

    def enable_skill_package(self, skill_id):
        self.calls.append(("enable", skill_id))

    def disable_skill_package(self, skill_id):
        self.calls.append(("disable", skill_id))

    def sync_skill_package(self, skill_id):
        self.calls.append(("sync", skill_id))

    def rollback_skill_package(self, skill_id, version):
        self.calls.append(("rollback", skill_id, version))


class _FakeApiToolService:
    def __init__(self):
        self.calls = []

    def get_api_tool_providers_wiith_page(self, req, account):
        self.calls.append(("list", req))
        return [], _Paginator()

    def parse_openapi_schema(self, openapi_schema):
        self.calls.append(("parse", openapi_schema))

    def create_api_tool(self, req, account):
        self.calls.append(("create", req.name.data))

    def import_from_url(self, url, name, description, headers, account, overwrite, task_keywords):
        self.calls.append(("import_url", name))
        return {"id": str(uuid4())}

    def import_from_file(self, file_content, name, description, headers, account, overwrite, task_keywords):
        self.calls.append(("import_file", name))
        return {"id": str(uuid4())}

    def get_api_tool_provider(self, provider_id, account):
        return SimpleNamespace(id=provider_id, name="提供者")

    def update_api_tool_provider(self, provider_id, req, account):
        self.calls.append(("update", provider_id))

    def get_api_tool(self, provider_id, tool_name, account):
        return SimpleNamespace(provider_id=provider_id, tool_name=tool_name)

    def delete_api_tool_provider(self, provider_id, account):
        self.calls.append(("delete", provider_id))

    def regenerate_icon(self, provider_id, account):
        return "http://icon.example/api.png"

    def generate_icon_preview(self, name, description):
        return "http://icon.example/preview.png"


class TestAsgiSkillsApiTools:
    def _setup(self, monkeypatch):
        from internal.service import ApiToolService
        from internal.service.skill_service import SkillService

        account = SimpleNamespace(id=uuid4())
        skill_service = _FakeSkillService()
        api_tool_service = _FakeApiToolService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: (
                skill_service if cls is SkillService else api_tool_service
            ),
        )
        return account, skill_service, api_tool_service

    def test_get_skill_categories(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/skills/categories?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["categories"][0]["category"] == "通用"

    def test_get_skills_with_page(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/skills?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []

    def test_get_skill_package_icon(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/skills/{uuid4()}/icon?account_id={uuid4()}")
                return resp

        resp = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "image/png"

    def test_enable_skill_package(self, monkeypatch):
        _, skill_service, _ = self._setup(monkeypatch)
        skill_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/skills/{skill_id}/enable?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert skill_service.calls[0] == ("enable", skill_id)

    def test_rollback_skill_package(self, monkeypatch):
        _, skill_service, _ = self._setup(monkeypatch)
        skill_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/skills/{skill_id}/rollback?account_id={uuid4()}",
                    json={"version": 2},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert skill_service.calls[0] == ("rollback", skill_id, 2)

    def test_get_api_tool_providers(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/api-tools?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []

    def test_create_api_tool_provider(self, monkeypatch):
        _, _, api_tool_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/api-tools?account_id={uuid4()}",
                    json={"name": "我的API"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert api_tool_service.calls[0] == ("create", "我的API")

    def test_validate_openapi_schema(self, monkeypatch):
        _, _, api_tool_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/api-tools/validate-openapi-schema?account_id={uuid4()}",
                    json={"openapi_schema": "{}"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert api_tool_service.calls[0][0] == "parse"

    def test_import_api_tool_from_url(self, monkeypatch):
        _, _, api_tool_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/api-tools/import-url?account_id={uuid4()}",
                    json={"url": "https://example.com/openapi.json", "name": "远程API"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert api_tool_service.calls[0][0] == "import_url"

    def test_import_api_tool_from_url_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/api-tools/import-url?account_id={uuid4()}",
                    json={"url": "https://example.com/openapi.json"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_delete_api_tool_provider(self, monkeypatch):
        _, _, api_tool_service = self._setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/api-tools/{provider_id}/delete?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert api_tool_service.calls[0] == ("delete", provider_id)


class _FakeWorkflowService:
    def __init__(self):
        self.calls = []

    def get_workflows_with_page(self, req, account):
        self.calls.append(("list", req))
        return [], _Paginator()

    def create_workflow(self, req, account):
        self.calls.append(("create", req.name.data))
        return SimpleNamespace(id=uuid4())

    def get_workflow(self, workflow_id, account):
        return SimpleNamespace(id=workflow_id, name="工作流A")

    def update_workflow(self, workflow_id, account, **kwargs):
        self.calls.append(("update", workflow_id))

    def delete_workflow(self, workflow_id, account):
        self.calls.append(("delete", workflow_id))

    def update_draft_graph(self, workflow_id, draft_graph_dict, account):
        self.calls.append(("draft", workflow_id))

    def get_draft_graph(self, workflow_id, account):
        return {"nodes": [], "edges": []}

    def publish_workflow(self, workflow_id, account):
        self.calls.append(("publish", workflow_id))

    def cancel_publish_workflow(self, workflow_id, account):
        self.calls.append(("cancel", workflow_id))

    def regenerate_icon(self, workflow_id, account):
        return "http://icon.example/wf.png"

    def generate_icon_preview(self, name, description):
        return "http://icon.example/preview.png"

    def share_workflow_to_public(self, workflow_id, account, is_public):
        self.calls.append(("share", workflow_id, is_public))

    def import_workflow(self, json_data, account_id, overwrite_name):
        self.calls.append(("import", account_id, overwrite_name))
        return SimpleNamespace(id=uuid4(), name="导入的工作流")

    def export_workflow(self, workflow_id, include_versions):
        return {"format": "yuxin-ai-workflow", "name": "工作流A"}


class _FakeWorkflowRunService:
    def get_runs_with_page(self, workflow_id, account, page, page_size, status, trigger_source):
        return [], _Paginator(page_size=page_size)

    def serialize_run(self, run):
        return {"id": str(run.id)}

    def get_run(self, run_id, account):
        return None

    def get_node_executions(self, run_id, account):
        return []

    def serialize_node_execution(self, node_exec):
        return {"node_id": str(uuid4())}


class TestAsgiWorkflows:
    def _setup(self, monkeypatch):
        from internal.service import WorkflowRunService, WorkflowService

        account = SimpleNamespace(id=uuid4())
        workflow_service = _FakeWorkflowService()
        run_service = _FakeWorkflowRunService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: (
                workflow_service if cls is WorkflowService else run_service
            ),
        )
        return account, workflow_service

    def test_get_workflows_with_page(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/workflows?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []

    def test_create_workflow(self, monkeypatch):
        _, workflow_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/workflows?account_id={uuid4()}", json={"name": "新工作流"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert workflow_service.calls[0] == ("create", "新工作流")

    def test_update_draft_graph(self, monkeypatch):
        _, workflow_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/workflows/{uuid4()}/draft-graph?account_id={uuid4()}",
                    json={"nodes": [], "edges": []},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert workflow_service.calls[0][0] == "draft"

    def test_get_draft_graph(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/workflows/{uuid4()}/draft-graph?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert "nodes" in payload["data"]

    def test_publish_workflow(self, monkeypatch):
        _, workflow_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/workflows/{uuid4()}/publish?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert workflow_service.calls[0][0] == "publish"

    def test_share_workflow(self, monkeypatch):
        _, workflow_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/workflows/{uuid4()}/share?account_id={uuid4()}",
                    json={"is_public": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert workflow_service.calls[0][2] is True

    def test_get_workflow_runs(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/workflows/{uuid4()}/runs?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []

    def test_import_workflow(self, monkeypatch):
        _, workflow_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/workflows/import?account_id={uuid4()}",
                    json={"json_data": {"name": "wf"}, "overwrite_name": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert workflow_service.calls[0][0] == "import"

    def test_export_workflow(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/workflows/{uuid4()}/export?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["format"] == "yuxin-ai-workflow"


class _FakeExternalDataSourceService:
    def __init__(self):
        self.calls = []

    def list_data_sources(self, account, status):
        self.calls.append(("list", status))
        return []

    def get_data_source(self, data_source_id, account):
        return SimpleNamespace(id=data_source_id, source_name="数据源A")

    def create_connection(self, account, knowledge_base, source_type, source_name, config):
        self.calls.append(("create", source_name))
        return SimpleNamespace(id=uuid4(), source_name=source_name)

    def authorize_data_source(self, data_source_id, account, auth_config):
        self.calls.append(("authorize", data_source_id))
        return SimpleNamespace(id=data_source_id)

    def manual_sync(self, data_source_id, account):
        self.calls.append(("sync", data_source_id))
        return {"synced": 5}

    def delete_data_source(self, data_source_id, account):
        self.calls.append(("delete", data_source_id))


class _FakeEDSKnowledgeBaseService:
    def get_user_content_base(self, kb_id, account):
        return SimpleNamespace(id=kb_id)

    def create_user_content_base(self, name, account):
        return SimpleNamespace(id=uuid4())


class _FakeToolConfirmationService:
    def __init__(self):
        self.calls = []

    def list_confirmations(self, account, status):
        self.calls.append(("list", status))
        return []

    def get_confirmation(self, confirmation_id, account):
        return SimpleNamespace(id=confirmation_id, tool_name="search")

    def create_confirmation(self, account, tool_name, **kwargs):
        self.calls.append(("create", tool_name))
        return SimpleNamespace(id=uuid4(), tool_name=tool_name)

    def confirm(self, confirmation_id, account):
        self.calls.append(("confirm", confirmation_id))
        return SimpleNamespace(id=confirmation_id)

    def cancel(self, confirmation_id, account):
        self.calls.append(("cancel", confirmation_id))
        return SimpleNamespace(id=confirmation_id)


class TestAsgiExternalDataSourcesToolConfirmations:
    def _setup(self, monkeypatch):
        from internal.service.external_data_source_service import (
            ExternalDataSourceService,
        )
        from internal.service.knowledge_base_service import KnowledgeBaseService
        from internal.service.tool_confirmation_service import (
            ToolConfirmationService,
        )

        account = SimpleNamespace(id=uuid4())
        edss = _FakeExternalDataSourceService()
        kbs = _FakeEDSKnowledgeBaseService()
        tcs = _FakeToolConfirmationService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        services = {
            ExternalDataSourceService: edss,
            KnowledgeBaseService: kbs,
            ToolConfirmationService: tcs,
        }
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return account, edss, kbs, tcs

    def test_external_data_source_list(self, monkeypatch):
        _, edss, _, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/external-data-sources?account_id={uuid4()}&status=connected"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["items"] == []
        assert edss.calls[0] == ("list", "connected")

    def test_external_data_source_create(self, monkeypatch):
        _, edss, _, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/external-data-sources?account_id={uuid4()}",
                    json={"source_name": "GitHub", "source_type": "github"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert edss.calls[0] == ("create", "GitHub")

    def test_external_data_source_delete(self, monkeypatch):
        _, edss, _, _ = self._setup(monkeypatch)
        ds_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/external-data-sources/{ds_id}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["deleted"] is True
        assert edss.calls[0] == ("delete", ds_id)

    def test_external_data_source_sync(self, monkeypatch):
        _, edss, _, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/external-data-sources/{uuid4()}/sync?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert edss.calls[0][0] == "sync"

    def test_tool_confirmation_list(self, monkeypatch):
        _, _, _, tcs = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/tool-confirmations?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["items"] == []

    def test_tool_confirmation_create(self, monkeypatch):
        _, _, _, tcs = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/tool-confirmations?account_id={uuid4()}",
                    json={"tool_name": "web_search"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert tcs.calls[0] == ("create", "web_search")

    def test_tool_confirmation_create_requires_tool_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/tool-confirmations?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_tool_confirmation_confirm(self, monkeypatch):
        _, _, _, tcs = self._setup(monkeypatch)
        confirmation_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/tool-confirmations/{confirmation_id}/confirm?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert tcs.calls[0] == ("confirm", confirmation_id)


class _FakeKnowledgeBaseService:
    def __init__(self):
        self.calls = []
        self.db = object()

    def list_user_content_bases(self, req, account):
        self.calls.append(("list", req))
        return [], _Paginator()

    def create_user_content_base_with_req(self, req, account):
        self.calls.append(("create", req.name.data))

    def get_user_content_base_detail(self, knowledge_base_id, account):
        return SimpleNamespace(
            id=knowledge_base_id,
            name="知识库A",
            description="desc",
            icon="",
            knowledge_scope="user_content",
            status="active",
            created_at=1710000000,
            updated_at=1710000000,
        )

    def update_user_content_base(self, knowledge_base_id, req, account):
        self.calls.append(("update", knowledge_base_id))

    def delete_user_content_base(self, knowledge_base_id, account):
        self.calls.append(("delete", knowledge_base_id))

    def hit_test(self, knowledge_base_id, req, account):
        self.calls.append(("hit", knowledge_base_id))
        return {"hits": []}

    def get_documents_with_page(self, knowledge_base_id, req, account):
        return [], _Paginator()

    def upload_document(self, knowledge_base_id, file, account):
        self.calls.append(("upload", knowledge_base_id, file.filename))

    def get_document_detail(self, knowledge_base_id, document_id, account):
        return SimpleNamespace(id=document_id, name="文档A")

    def delete_document(self, knowledge_base_id, document_id, account):
        self.calls.append(("doc_delete", document_id))

    def get_segments_with_page(self, knowledge_base_id, document_id, req, account):
        return [], _Paginator()

    def update_segment(self, knowledge_base_id, document_id, segment_id, req, account):
        self.calls.append(("seg_update", segment_id))

    def regenerate_icon(self, knowledge_base_id, account):
        return "http://icon.example/kb.png"

    def generate_icon_preview(self, name, description):
        return "http://icon.example/preview.png"


class _FakeUserContentKnowledgeService:
    def list_readable_system_bases(self):
        return [
            SimpleNamespace(
                id=uuid4(), name="系统知识库", description="desc", knowledge_scope="system"
            )
        ]


class TestAsgiKnowledgeBases:
    def _setup(self, monkeypatch):
        from internal.service import KnowledgeBaseService

        account = SimpleNamespace(id=uuid4())
        kb_service = _FakeKnowledgeBaseService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support, "_get_service", lambda cls: kb_service if cls is KnowledgeBaseService else None
        )
        return account, kb_service

    def test_list_knowledge_bases(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/space/knowledge-bases?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []

    def test_create_knowledge_base(self, monkeypatch):
        _, kb_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases?account_id={uuid4()}",
                    json={"name": "新知识库"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert kb_service.calls[0] == ("create", "新知识库")

    def test_create_knowledge_base_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_get_knowledge_base(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/space/knowledge-bases/{uuid4()}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "知识库A"

    def test_delete_knowledge_base(self, monkeypatch):
        _, kb_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{uuid4()}/delete?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert kb_service.calls[0][0] == "delete"

    def test_hit_test(self, monkeypatch):
        _, kb_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{uuid4()}/hit?account_id={uuid4()}",
                    json={"query": "测试"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert kb_service.calls[0][0] == "hit"

    def test_upload_document(self, monkeypatch):
        import io

        from werkzeug.datastructures import FileStorage

        _, kb_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{uuid4()}/documents/upload?account_id={uuid4()}",
                    files={
                        "file": FileStorage(
                            stream=io.BytesIO(b"content"), filename="doc.txt"
                        )
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert kb_service.calls[0][0] == "upload"

    def test_list_system_knowledge_bases(self, monkeypatch):
        from internal.service import KnowledgeBaseService
        from internal.service.scoped_knowledge_service import UserContentKnowledgeService

        _, kb_service = self._setup(monkeypatch)
        fake_system_service = SimpleNamespace(
            list_readable_system_bases=lambda: [
                SimpleNamespace(
                    id=uuid4(),
                    name="系统知识库",
                    description="desc",
                    knowledge_scope="system",
                )
            ]
        )
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: (
                kb_service if cls is KnowledgeBaseService else fake_system_service
            ),
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/space/system-knowledge-bases?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1


class _FakeMcpService:
    def __init__(self):
        self.calls = []

    def get_public_mcp_providers_with_page(self, req, account):
        self.calls.append(("public_list", account))
        return [], _Paginator()

    def get_public_mcp_provider(self, provider_key, account):
        self.calls.append(("public_get", provider_key, account))
        return SimpleNamespace(id=uuid4(), name="公共MCP")

    def get_mcp_providers_with_page(self, req, account):
        self.calls.append(("list", req))
        return [], _Paginator()

    def create_mcp_provider(self, req, account):
        self.calls.append(("create", req.name.data))
        return SimpleNamespace(id=uuid4())

    def get_mcp_provider(self, provider_id, account):
        return SimpleNamespace(id=provider_id, name="我的MCP")

    def update_mcp_provider(self, provider_id, req, account):
        self.calls.append(("update", provider_id))

    def delete_mcp_provider(self, provider_id, account):
        self.calls.append(("delete", provider_id))

    def publish_mcp_provider(self, provider_id, account):
        self.calls.append(("publish", provider_id))

    def unpublish_mcp_provider(self, provider_id, account):
        self.calls.append(("unpublish", provider_id))

    def regenerate_icon(self, provider_id, account):
        return "http://icon.example/mcp.png"

    def generate_icon_preview(self, name, description):
        return "http://icon.example/preview.png"


class _FakeMcpImportService:
    def import_from_mcp_json(self, config_json, account_id, overwrite):
        return {"imported": 1, "skipped": 0}


class TestAsgiMcp:
    def _setup(self, monkeypatch):
        from internal.service.mcp_import_service import McpImportService
        from internal.service.mcp_service import McpService

        account = SimpleNamespace(id=uuid4())
        mcp_service = _FakeMcpService()
        import_service = _FakeMcpImportService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        services = {McpService: mcp_service, McpImportService: import_service}
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return account, mcp_service, import_service

    def test_public_mcp_routes_are_not_registered(self, monkeypatch):
        self._setup(monkeypatch)

        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/public/mcp-providers" not in rules
        assert "/public/mcp-providers/categories" not in rules
        assert "/public/mcp-providers/<string:provider_key>" not in rules

    def test_get_mcp_providers(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/mcp-providers?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []

    def test_create_mcp_provider(self, monkeypatch):
        _, mcp_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/mcp-providers?account_id={uuid4()}", json={"name": "新MCP"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert mcp_service.calls[0] == ("create", "新MCP")

    def test_import_mcp_json(self, monkeypatch):
        _, _, import_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/mcp-providers/import-mcp-json?account_id={uuid4()}",
                    json={"config_json": "{\"mcpServers\":{}}", "overwrite": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["imported"] == 1

    def test_delete_mcp_provider(self, monkeypatch):
        _, mcp_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/mcp-providers/{uuid4()}/delete?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert mcp_service.calls[0][0] == "delete"

    def test_publish_mcp_provider(self, monkeypatch):
        _, mcp_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/mcp-providers/{uuid4()}/publish?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert mcp_service.calls[0][0] == "publish"

    def test_mcp_generate_icon_preview(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/mcp-providers/generate-icon-preview?account_id={uuid4()}",
                    json={"name": "图标"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert "icon" in payload["data"]

    def test_mcp_generate_icon_preview_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/mcp-providers/generate-icon-preview?account_id={uuid4()}",
                    json={},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class _FakeScheduleTaskService:
    def __init__(self):
        self.calls = []

    def _task(self, task_id=None):
        return SimpleNamespace(
            id=task_id or uuid4(),
            name="定时任务",
            prompt="需求",
            cron_expression="0 8 * * *",
            description="",
            enabled=True,
            status="enabled",
            cron_humanized="每天 8 点",
            trigger_type="cron",
            interval_config={},
            created_at=1710000000,
            updated_at=1710000000,
            run_count=0,
            last_run_at=None,
            last_run_status=None,
            last_result=None,
            next_run_at=None,
        )

    def list_tasks(self, account, page, page_size):
        self.calls.append(("list", account, page))
        return [self._task()], 1

    def create_task(self, account, name, prompt, cron_expression, **kwargs):
        self.calls.append(("create", name))
        return self._task()

    def update_task(self, task_id, account, **kwargs):
        self.calls.append(("update", task_id))
        return self._task(task_id)

    def delete_task(self, task_id, account):
        self.calls.append(("delete", task_id))

    def get_task(self, task_id, account):
        return self._task(task_id)

    def list_runs(self, task_id, account, page, page_size):
        self.calls.append(("runs", task_id))
        return [], 0


class _FakeScheduleExecutionService:
    def execute_task(self, task):
        import datetime as _dt

        return SimpleNamespace(
            id=uuid4(),
            schedule_task_id=task.id,
            status="success",
            trigger_source="manual",
            started_at=_dt.datetime(2026, 8, 8, 8, 0),
            finished_at=_dt.datetime(2026, 8, 8, 8, 1),
            result_summary="完成",
            result_data={},
            error_message=None,
        )


class _FakeScheduleIntentParser:
    def parse(self, user_input, history):
        return {"cron_expression": "0 8 * * *", "name": "任务"}

    def validate_cron(self, cron_expression):
        return None

    def humanize(self, cron_expression):
        return "每天 8 点"


class _FakeTaskDedupService:
    def __init__(self):
        self.calls = []

    def mark_consumed(self, fingerprint):
        self.calls.append(("consumed", fingerprint))

    def mark_rejected(self, fingerprint):
        self.calls.append(("rejected", fingerprint))


class TestAsgiScheduleTasks:
    def _setup(self, monkeypatch):
        from internal.service.schedule_execution_service import ScheduleExecutionService
        from internal.service.schedule_intent_parser import ScheduleIntentParser
        from internal.service.schedule_task_service import ScheduleTaskService
        from internal.service.task_dedup_service import TaskDedupService

        account = SimpleNamespace(id=uuid4())
        task_service = _FakeScheduleTaskService()
        execution_service = _FakeScheduleExecutionService()
        parser = _FakeScheduleIntentParser()
        dedup_service = _FakeTaskDedupService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        services = {
            ScheduleTaskService: task_service,
            ScheduleExecutionService: execution_service,
            ScheduleIntentParser: parser,
            TaskDedupService: dedup_service,
        }
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return account, task_service, dedup_service

    def test_list_tasks(self, monkeypatch):
        _, task_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/schedule-tasks?account_id={uuid4()}&page=2"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["total"] == 1
        assert task_service.calls[0][2] == 2

    def test_create_task(self, monkeypatch):
        _, task_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/schedule-tasks?account_id={uuid4()}",
                    json={"name": "任务A", "prompt": "需求", "cron_expression": "0 8 * * *"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert task_service.calls[0] == ("create", "任务A")

    def test_create_task_requires_fields(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/schedule-tasks?account_id={uuid4()}", json={"name": "任务A"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_parse(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/schedule-tasks/parse?account_id={uuid4()}",
                    json={"input": "每天早上 8 点"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["cron_expression"] == "0 8 * * *"

    def test_confirm(self, monkeypatch):
        _, task_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/schedule-tasks/confirm?account_id={uuid4()}",
                    json={"prompt": "需求", "cron_expression": "0 8 * * *", "fingerprint": "fp-1"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert task_service.calls[0][0] == "create"

    def test_delete_task(self, monkeypatch):
        _, task_service, _ = self._setup(monkeypatch)
        task_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/schedule-tasks/{task_id}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert task_service.calls[0] == ("delete", task_id)

    def test_enable_task(self, monkeypatch):
        _, task_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/schedule-tasks/{uuid4()}/enable?account_id={uuid4()}",
                    json={"enabled": False},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert task_service.calls[0][0] == "update"

    def test_run_now(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/schedule-tasks/{uuid4()}/run-now?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["status"] == "success"

    def test_humanize(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/schedule-tasks/humanize?account_id={uuid4()}",
                    json={"cron_expression": "0 8 * * *"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["cron_humanized"] == "每天 8 点"


class _FakeAssistantAgentService:
    def __init__(self):
        self.calls = []

    def get_capabilities(self):
        return ["chat", "memory"]

    def stop_chat(self, task_id, account):
        self.calls.append(("stop", task_id))

    def get_conversation_messages_with_page(self, req, account):
        self.calls.append(("messages", req))
        return [], _Paginator()

    def get_conversations(self, req, account):
        self.calls.append(("conversations", req.limit.data))
        return []

    def delete_conversation(self, account):
        self.calls.append(("delete", account))


class _FakeApiKeyService:
    def __init__(self):
        self.calls = []

    def get_api_keys_with_page(self, req, account):
        self.calls.append(("list", req))
        return [], _Paginator()

    def create_api_key(self, req, account):
        self.calls.append(("create", req.name.data))
        return {"api_key": "sk-xxxx"}

    def update_api_key(self, api_key_id, account, **kwargs):
        self.calls.append(("update", api_key_id, kwargs))

    def delete_api_key(self, api_key_id, account):
        self.calls.append(("delete", api_key_id))


class _FakeAIService:
    def generate_suggested_questions_from_message_id(self, message_id, account):
        return ["问题1", "问题2"]


class TestAsgiAssistantAgentApiKey:
    def _setup(self, monkeypatch):
        from internal.service import AIService, ApiKeyService, AssistantAgentService

        account = SimpleNamespace(id=uuid4())
        assistant_service = _FakeAssistantAgentService()
        api_key_service = _FakeApiKeyService()
        ai_service = _FakeAIService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        services = {
            AssistantAgentService: assistant_service,
            ApiKeyService: api_key_service,
            AIService: ai_service,
        }
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return account, assistant_service, api_key_service

    def test_assistant_agent_capabilities(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/assistant-agent/capabilities?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert "chat" in payload["data"]["capabilities"]

    def test_stop_assistant_agent_chat(self, monkeypatch):
        _, assistant_service, _ = self._setup(monkeypatch)
        task_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/assistant-agent/chat/{task_id}/stop?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert assistant_service.calls[0] == ("stop", task_id)

    def test_assistant_agent_messages(self, monkeypatch):
        _, assistant_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/assistant-agent/messages?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []

    def test_assistant_agent_conversations(self, monkeypatch):
        _, assistant_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/assistant-agent/conversations?account_id={uuid4()}&limit=5"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert assistant_service.calls[0][1] == 5

    def test_delete_assistant_agent_conversation(self, monkeypatch):
        _, assistant_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/assistant-agent/delete-conversation?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert assistant_service.calls[0][0] == "delete"

    def test_get_api_keys(self, monkeypatch):
        _, _, api_key_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/openapi/api-keys?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []

    def test_create_api_key(self, monkeypatch):
        _, _, api_key_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/openapi/api-keys?account_id={uuid4()}", json={"name": "密钥A"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["api_key"] == "sk-xxxx"
        assert api_key_service.calls[0] == ("create", "密钥A")

    def test_create_api_key_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/openapi/api-keys?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_update_api_key(self, monkeypatch):
        _, _, api_key_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/openapi/api-keys/{uuid4()}?account_id={uuid4()}",
                    json={"name": "新名字"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert api_key_service.calls[0][0] == "update"

    def test_delete_api_key(self, monkeypatch):
        _, _, api_key_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/openapi/api-keys/{uuid4()}/delete?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert api_key_service.calls[0][0] == "delete"

    def test_generate_suggested_questions(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/ai/suggested-questions?account_id={uuid4()}",
                    json={"message_id": str(uuid4())},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert len(payload["data"]) == 2


class _FakeAuthAccountService:
    def password_login(self, identifier, password):
        return {"access_token": "jwt-token", "expire_at": 1893456000, "challenge_required": False}

    def prepare_register(self, email, password, username=None):
        return None

    def direct_register(self, username, password):
        return {"access_token": "jwt-token", "expire_at": 1893456000, "challenge_required": False}

    def register_by_email_code(self, email, password, code, username=None):
        return {"access_token": "jwt-token", "expire_at": 1893456000, "challenge_required": False}

    def revoke_account_session(self, account, session_id, current_session_id=None, allow_current=False):
        return None

    def send_reset_code(self, email):
        return None

    def reset_password(self, email, code, new_password):
        return None

    def verify_login_challenge(self, challenge_id, code):
        return {"access_token": "jwt-token", "expire_at": 1893456000, "challenge_required": False}

    def resend_login_challenge(self, challenge_id):
        return None


class _FakeAuthOAuthService:
    def get_oauth_by_provider_name(self, provider_name):
        return SimpleNamespace(get_authorization_url=lambda: "https://oauth.example/auth")

    def oauth_login(self, provider_name, code):
        return {"access_token": "jwt", "expire_at": 1893456000, "challenge_required": False}

    def bind_oauth(self, account, provider_name, code, current_session=None):
        return {"access_token": "jwt", "expire_at": 1893456000, "challenge_required": False}


class _FakeCosService:
    def upload_file(self, file, is_image, account):
        return SimpleNamespace(
            id=uuid4(),
            account_id=uuid4(),
            name=file.filename or "",
            key="path/key.png",
            size=7,
            extension="png",
            mime_type="image/png",
            created_at=1710000000,
        )

    def get_file_url(self, key):
        return "https://cdn.example/key.png"


class TestAsgiAuthOAuthUpload:
    def _setup(self, monkeypatch):
        from internal.service import CosService
        from internal.service.account_service import AccountService
        from internal.service.oauth_service import OAuthService

        account = SimpleNamespace(id=uuid4())
        account_service = _FakeAuthAccountService()
        oauth_service = _FakeAuthOAuthService()
        cos_service = _FakeCosService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        services = {
            AccountService: account_service,
            OAuthService: oauth_service,
            CosService: cos_service,
        }
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return account, account_service

    def test_password_login(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/password-login",
                    json={"identifier": "user", "password": "pass"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["access_token"] == "jwt-token"

    def test_password_login_requires_fields(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/password-login", json={"identifier": "user"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_prepare_register(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/register/prepare",
                    json={"email": "a@b.com", "password": "pass"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200

    def test_direct_register(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/register/direct",
                    json={"username": "新用户", "password": "pass"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["access_token"] == "jwt-token"

    def test_auth_logout(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/auth/logout")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200

    def test_send_reset_code(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/send-reset-code", json={"email": "a@b.com"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200

    def test_reset_password(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/reset-password",
                    json={"email": "a@b.com", "code": "1234", "new_password": "new"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200

    def test_verify_login_challenge(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/login-challenge/verify",
                    json={"challenge_id": "c-1", "code": "1234"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["access_token"] == "jwt-token"

    def test_oauth_provider_redirect(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/oauth/github")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["redirect_url"] == "https://oauth.example/auth"

    def test_oauth_authorize(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/oauth/authorize/github", json={"code": "auth-code"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["access_token"] == "jwt"

    def test_upload_file(self, monkeypatch):
        import io

        from werkzeug.datastructures import FileStorage

        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/upload-files/file?account_id={uuid4()}",
                    files={
                        "file": FileStorage(
                            stream=io.BytesIO(b"content"), filename="doc.txt"
                        )
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["key"] == "path/key.png"

    def test_upload_image(self, monkeypatch):
        import io

        from werkzeug.datastructures import FileStorage

        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/upload-files/image?account_id={uuid4()}",
                    files={
                        "file": FileStorage(
                            stream=io.BytesIO(b"img"), filename="a.png"
                        )
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["image_url"] == "https://cdn.example/key.png"


class _FakeSseAppDebugService:
    def __init__(self):
        self.calls = []

    def _gen(self, marker):
        def gen():
            yield f"event: message\ndata:{marker}-1\n\n"
            yield f"event: message\ndata:{marker}-2\n\n"
        return gen()

    def debug_chat(self, app_id, req, account):
        self.calls.append(("debug_chat", req.query.data))
        return self._gen("debug")

    def prompt_compare_chat(self, app_id, req, account):
        self.calls.append(("pc", req.preset_prompt.data))
        return self._gen("pc")

    def get_debug_conversation_summary(self, app_id, account):
        return ""

    def update_debug_conversation_summary(self, app_id, summary, account):
        pass

    def delete_debug_conversation(self, app_id, account):
        pass

    def stop_debug_chat(self, app_id, task_id, account):
        pass

    def stop_prompt_compare_chat(self, app_id, task_id, account):
        pass

    def get_debug_conversation_messages_with_page(self, app_id, req, account):
        return [], _Paginator()


class _FakeWorkflowAppService:
    def execute_workflow_stream(self, app_id, inputs, account):
        def gen():
            yield "event: workflow_started\ndata:{}\n\n"
            yield "event: workflow_finished\ndata:{}\n\n"
        return gen()


class TestAsgiSseEndpoints:
    def _setup(self, monkeypatch):
        from internal.service import AssistantAgentService, WorkflowAppService
        from internal.service.app_debug_service import AppDebugService

        account = SimpleNamespace(id=uuid4())
        debug_service = _FakeSseAppDebugService()
        workflow_service = _FakeWorkflowAppService()

        class _SseAssistantService:
            def chat(self, req, account):
                def gen():
                    yield "event: message\ndata:hi\n\n"
                return gen()

            def generate_introduction(self, account):
                def gen():
                    yield "event: message\ndata:hi\n\n"
                return gen()

        assistant_service = _SseAssistantService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        services = {
            AppDebugService: debug_service,
            WorkflowAppService: workflow_service,
            AssistantAgentService: assistant_service,
        }
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return account, debug_service

    def test_debug_chat_sse(self, monkeypatch):
        _, debug_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/conversations?account_id={uuid4()}",
                    json={"query": "你好"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"


    def test_debug_chat_requires_query(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/conversations?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_debug_workflow_app_sse(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/workflow/debug?account_id={uuid4()}",
                    json={"query": "运行"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "workflow_started" in body


    def test_prompt_compare_chat_sse(self, monkeypatch):
        _, debug_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/prompt-compare/chat?account_id={uuid4()}",
                    json={"query": "q", "preset_prompt": "p"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert "pc-1" in body
        assert debug_service.calls[0] == ("pc", "p")

    def test_prompt_compare_chat_requires_prompt(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/prompt-compare/chat?account_id={uuid4()}",
                    json={"query": "q"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400

    def test_assistant_agent_chat_sse(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/assistant-agent/chat?account_id={uuid4()}",
                    json={"query": "hi"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "hi" in body

    def test_assistant_agent_introduction_sse(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/assistant-agent/introduction?account_id={uuid4()}"
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"


class TestAsgiInfraEndpoints:
    def test_health(self, monkeypatch):
        from internal.service.health_service import HealthService

        fake = SimpleNamespace(
            check=lambda: {"status": "healthy", "service": "llmops-api"}
        )
        monkeypatch.setattr(
            support, "_get_service", lambda cls: fake if cls is HealthService else None
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/health")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["status"] == "healthy"

    def test_health_should_aggregate_component_statuses(self, monkeypatch):
        from internal.service.health_service import HealthService

        service = HealthService(app_service=SimpleNamespace())
        monkeypatch.setattr(service, "_probe_database", lambda: {"status": "healthy", "detail": ""})
        monkeypatch.setattr(service, "_probe_redis", lambda: {"status": "unhealthy", "detail": "redis-down"})
        monkeypatch.setattr(service, "_probe_pgvector", lambda: {"status": "healthy", "detail": ""})
        monkeypatch.setattr(service, "_probe_celery", lambda: {"status": "skipped", "detail": ""})
        monkeypatch.setattr(
            support, "_get_service", lambda cls: service if cls is HealthService else None
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/health")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        data = payload["data"]
        assert data["status"] == "degraded"
        assert data["components"]["database"]["status"] == "healthy"
        assert data["components"]["redis"]["status"] == "unhealthy"
        assert data["components"]["pgvector"]["status"] == "healthy"
        assert data["metrics"]["unhealthy_components"] == 1

    def test_health_should_be_unhealthy_when_database_down(self, monkeypatch):
        from internal.service.health_service import HealthService

        service = HealthService(app_service=SimpleNamespace())
        monkeypatch.setattr(service, "_probe_database", lambda: {"status": "unhealthy", "detail": "db-down"})
        monkeypatch.setattr(service, "_probe_redis", lambda: {"status": "healthy", "detail": ""})
        monkeypatch.setattr(service, "_probe_pgvector", lambda: {"status": "healthy", "detail": ""})
        monkeypatch.setattr(service, "_probe_celery", lambda: {"status": "healthy", "detail": ""})
        monkeypatch.setattr(
            support, "_get_service", lambda cls: service if cls is HealthService else None
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/health")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        data = payload["data"]
        assert data["status"] == "unhealthy"
        assert data["components"]["database"]["detail"] == "db-down"

    def test_health_should_hide_probe_error_detail_in_production(self, monkeypatch):
        from internal.service.health_service import HealthService

        db_session = SimpleNamespace(
            execute=lambda _sql: (_ for _ in ()).throw(
                RuntimeError("connection refused: db:5432")
            )
        )
        service = HealthService(
            app_service=SimpleNamespace(db=SimpleNamespace(session=db_session))
        )
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setattr(service, "_probe_redis", lambda: {"status": "healthy", "detail": ""})
        monkeypatch.setattr(service, "_probe_pgvector", lambda: {"status": "healthy", "detail": ""})
        monkeypatch.setattr(service, "_probe_celery", lambda: {"status": "skipped", "detail": ""})
        monkeypatch.setattr(
            support, "_get_service", lambda cls: service if cls is HealthService else None
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/health")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        data = payload["data"]
        assert data["status"] == "unhealthy"
        assert data["components"]["database"]["detail"] == "internal error"
        assert "connection refused" not in data["components"]["database"]["detail"]

    def test_healthz(self, monkeypatch):
        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/healthz")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["status"] == "ok"

    def test_ping(self, monkeypatch):
        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/ping")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["pong"] == "success"

    def test_serve_local_storage_file(self, monkeypatch, tmp_path):
        import internal.service.storage.local_storage_service as lss

        monkeypatch.setattr(lss, "_get_local_storage_root", lambda: str(tmp_path))
        (tmp_path / "hello.txt").write_text("hello world", encoding="utf-8")

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/storage/local/hello.txt")
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert body == "hello world"

    def test_serve_local_storage_path_traversal(self, monkeypatch, tmp_path):
        import internal.service.storage.local_storage_service as lss

        monkeypatch.setattr(lss, "_get_local_storage_root", lambda: str(tmp_path))

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/storage/local/../etc/passwd")
                return resp

        resp = asyncio.run(_run())

        assert resp.status_code == 400

    def test_serve_local_storage_missing(self, monkeypatch, tmp_path):
        import internal.service.storage.local_storage_service as lss

        monkeypatch.setattr(lss, "_get_local_storage_root", lambda: str(tmp_path))

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/storage/local/no-such.txt")
                return resp

        resp = asyncio.run(_run())

        assert resp.status_code == 404

class _FakeWorkflowDebugService:
    def debug_workflow(self, workflow_id, inputs, account):
        def gen():
            yield "event: workflow_started\ndata:{}\n\n"
            yield "event: workflow_finished\ndata:{}\n\n"
        return gen()


class TestAsgiMetricsWorkflowDebug:
    def test_metrics(self, monkeypatch):
        import internal.service.memory.metrics as metrics_mod

        monkeypatch.setattr(
            metrics_mod, "render_metrics", lambda: (b"# metrics ok\n", "text/plain")
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/metrics")
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert "# metrics ok" in body

    def test_metrics_contains_expected_metric_names(self):
        expected = [
            "memory_write_total",
            "memory_write_latency_seconds",
            "memory_retrieve_total",
            "memory_retrieve_latency_seconds",
            "memory_retrieve_results_count",
            "memory_storage_tier_nodes",
            "memory_skill_count",
            "memory_digest_cache_hit",
            "memory_consolidation_duration_seconds",
            "memory_consolidation_errors_total",
            "memory_llm_tokens_total",
            "memory_conflict_detected_total",
            "memory_pii_filtered_total",
            "memory_spread_activation_depth",
        ]

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/metrics")
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert "text/plain" in resp.mimetype
        for name in expected:
            assert name in body, f"指标 {name} 未在 /metrics 输出中找到"

    def test_debug_workflow_sse(self, monkeypatch):
        from internal.service import WorkflowService

        account = SimpleNamespace(id=uuid4())
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: _FakeWorkflowDebugService() if cls is WorkflowService else None,
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/workflows/{uuid4()}/debug?account_id={uuid4()}",
                    json={"query": "运行"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "workflow_started" in body

class _FakeWebAppService:

    def __init__(self):
        self.calls = []

    def get_web_app_info(self, token):
        return {"id": str(uuid4()), "name": "WebApp", "token": token}

    def web_app_chat(self, token, req, actor):
        self.calls.append(("chat", token, req.query.data))

        def gen():
            yield "event: message\ndata:webapp-1\n\n"
        return gen()

    def stop_web_app_chat(self, token, task_id, actor):
        self.calls.append(("stop", task_id))

    def get_conversations(self, token, is_pinned, actor, current_page, page_size):
        self.calls.append(("conversations", is_pinned))
        return []


class _FakeOpenApiService:
    def chat(self, req, account):
        def gen():
            yield "event: message\ndata:openapi-1\n\n"
        return gen()


class _FakeMyAppService:
    def __init__(self):
        self.calls = []

    def get_assigned_app(self, account_id, app_id):
        self.calls.append(("assigned", account_id, app_id))

    def list_my_apps(self, account_id):
        return []


class TestAsgiWebAppOpenApi:
    def _setup(self, monkeypatch):
        from internal.service import OpenAPIService, WebAppService
        from internal.service.app_debug_service import AppDebugService
        from internal.service.my_app_service import MyAppService

        account = SimpleNamespace(id=uuid4())
        debug_service = _FakeSseAppDebugService()
        webapp_service = _FakeWebAppService()
        openapi_service = _FakeOpenApiService()
        my_app_service = _FakeMyAppService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        services = {
            AppDebugService: debug_service,
            WebAppService: webapp_service,
            OpenAPIService: openapi_service,
            MyAppService: my_app_service,
        }
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return account, webapp_service, my_app_service

    def test_get_web_app(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/web-apps/token-abc")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "WebApp"

    def test_web_app_chat_sse(self, monkeypatch):
        _, webapp_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/web-apps/token-abc/chat?visitor_id=%s" % uuid4(),
                    json={"query": "你好"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "webapp-1" in body
        assert webapp_service.calls[0] == ("chat", "token-abc", "你好")

    def test_stop_web_app_chat(self, monkeypatch):
        _, webapp_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/web-apps/token-abc/chat/{uuid4()}/stop"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert webapp_service.calls[0][0] == "stop"

    def test_get_web_app_conversations(self, monkeypatch):
        _, webapp_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/web-apps/token-abc/conversations?is_pinned=true"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"] == []
        assert webapp_service.calls[0] == ("conversations", True)

    def test_openapi_chat_sse(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/openapi/chat?account_id={uuid4()}",
                    json={"app_id": str(uuid4()), "query": "hi"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "openapi-1" in body

    def test_openapi_chat_requires_app_id(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/openapi/chat?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_my_app_chat_sse(self, monkeypatch):
        _, _, my_app_service = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/my/apps/{app_id}/chat?account_id={uuid4()}",
                    json={"query": "hi"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert my_app_service.calls[0][0] == "assigned"

