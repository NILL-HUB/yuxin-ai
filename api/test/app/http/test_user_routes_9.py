"""user_routes_9（Quart 异步端点迁移批次 9）单元测试。

覆盖 router.py 中以下 handler 的端点：
    redeem_code_handler / memory_handler / ai_handler / audio_handler /
    platform_handler / wechat_handler / public_app_handler /
    public_workflow_handler / routing_log_handler / showcase_handler

测试模式与 test_asgi_app.py 一致：asyncio.run + quart_app.test_client()，
monkeypatch asgi_app._load_account / _get_service 注入假服务。
"""

import asyncio
import io
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.user_routes_9 import register_routes

register_routes(asgi_app.quart_app)


@dataclass
class _Paginator:
    total_page: int = 1
    total_record: int = 1
    current_page: int = 1
    page_size: int = 20


def _run_coro(coro):
    return asyncio.run(coro)


class _FakeRedeemCodeService:
    def __init__(self):
        self.calls = []

    def _plan(self):
        return {
            "id": str(uuid4()),
            "code": "OA-PRO",
            "name": "专业版",
            "duration_days": 30,
            "grant_token_credits": 100,
        }

    def redeem(self, account_id, code):
        self.calls.append(("redeem", code))
        return {
            "plan": self._plan(),
            "membership": {
                "id": str(uuid4()),
                "status": "active",
                "started_at": 1710000000,
                "expires_at": 1712592000,
                "source": "redeem_code",
                "source_id": str(uuid4()),
                "plan": self._plan(),
            },
            "credit_account": {
                "account_id": str(account_id),
                "balance": 100,
                "total_granted": 100,
                "total_consumed": 0,
            },
            "redeem_code": {
                "id": str(uuid4()),
                "code_mask": "OA-****",
                "redeemed_at": 1710000000,
            },
        }

    def get_membership_summary(self, account_id):
        self.calls.append(("summary",))
        return {
            "membership": {
                "id": str(uuid4()),
                "status": "active",
                "started_at": 1710000000,
                "expires_at": 1712592000,
                "source": "redeem_code",
                "source_id": str(uuid4()),
                "plan": self._plan(),
            },
            "credit_account": {
                "account_id": str(account_id),
                "balance": 100,
                "total_granted": 100,
                "total_consumed": 0,
            },
            "recent_transactions": [],
        }

    def list_redeem_records(self, account_id):
        self.calls.append(("records",))
        return {
            "list": [
                {
                    "id": str(uuid4()),
                    "code_mask": "OA-****",
                    "redeemed_at": 1710000000,
                    "plan": self._plan(),
                    "grant_token_credits": 100,
                    "membership_expires_at": 1712592000,
                }
            ]
        }


class TestRedeemCodeRoutes:
    def _setup(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        service = _FakeRedeemCodeService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: service,
        )
        return account, service

    def test_redeem(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/redeem-codes/redeem?account_id={uuid4()}",
                    json={"code": "OATESTCODE123"},
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["credit_account"]["balance"] == 100
        assert service.calls[0] == ("redeem", "OATESTCODE123")

    def test_redeem_requires_code(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/redeem-codes/redeem?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_membership_summary(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/membership/summary?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["credit_account"]["balance"] == 100
        assert service.calls[0] == ("summary",)

    def test_membership_redeem_records(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/membership/redeem-records?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert service.calls[0] == ("records",)


class _FakeMemoryWriteService:
    def write_from_event(self, event):
        return {
            "status": "written",
            "memory_id": str(uuid4()),
            "created_at": "2026-08-08T08:00:00",
            "score": 0.9,
            "entity_count": 1,
            "edge_count": 0,
            "vector_id": "vec-1",
        }


class _FakeDigestManager:
    def get_digest(self, user_id):
        return "记忆摘要内容"

    def update_digest(self, user_id):
        return "重建后的记忆摘要"


class _FakeMemoryGovernor:
    def edit_memory(self, memory_id, user_id, new_content):
        return "new-memory-id"

    def soft_delete_memory(self, memory_id, user_id):
        return True

    def hard_delete_memory(self, memory_id, user_id):
        return True


class _FakeRetriever:
    def __init__(self, digest_manager=None):
        self.digest_manager = digest_manager
        self.calls = []

    def retrieve(self, query, user_id, options):
        self.calls.append((query, user_id, options))
        return [
            SimpleNamespace(
                source="digest_cache",
                content="缓存摘要",
                model_dump=lambda: {"memory_id": "m-1", "content": "缓存摘要"},
            )
        ]


class _FakeConsolidationEngine:
    def run_consolidation(self, user_id):
        return SimpleNamespace(
            is_success=True,
            total_items_processed=3,
            phases={"conflict_resolution": "done"},
            errors=[],
        )


class _FakeHebbianDecay:
    def manual_decay(self, memory_id, decay_factor):
        return 0.3


class TestMemoryRoutes:
    def _setup(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        write_service = _FakeMemoryWriteService()
        digest_manager = _FakeDigestManager()
        governor = _FakeMemoryGovernor()

        from internal.service.memory.consolidation_engine import (
            ConsolidationEngine,
        )
        from internal.service.memory.digest_manager import DigestManager
        from internal.service.memory.hebbian_decay import HebbianDecay
        from internal.service.memory.memory_governor import MemoryGovernor
        from internal.service.memory.memory_write_service import MemoryWriteService
        from internal.service.memory.retriever import MemoryRetriever

        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: {
                MemoryWriteService: write_service,
                DigestManager: digest_manager,
                MemoryGovernor: governor,
            }.get(cls),
        )
        monkeypatch.setattr(MemoryRetriever, "__init__", _FakeRetriever.__init__)
        monkeypatch.setattr(MemoryRetriever, "retrieve", _FakeRetriever.retrieve)
        monkeypatch.setattr(ConsolidationEngine, "__init__", lambda self: None)
        monkeypatch.setattr(
            ConsolidationEngine,
            "run_consolidation",
            _FakeConsolidationEngine.run_consolidation,
        )
        monkeypatch.setattr(HebbianDecay, "__init__", lambda self: None)
        monkeypatch.setattr(HebbianDecay, "manual_decay", _FakeHebbianDecay.manual_decay)
        monkeypatch.setattr("internal.service.memory.degradation_manager._degradation_manager", None)
        monkeypatch.setitem(asgi_app.flask_app.extensions, "neo4j", None)
        monkeypatch.setitem(asgi_app.flask_app.extensions, "redis", None)
        return account

    def test_memory_write(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/memory/write?account_id={uuid4()}",
                    json={"content": "记住用户喜欢咖啡", "memory_type": "user_message"},
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["status"] == "written"

    def test_memory_write_requires_content(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/memory/write?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_memory_health(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/memory/health")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["version"] == "1.0.0"

    def test_memory_health_all_deps_healthy(self, monkeypatch):
        self._setup(monkeypatch)
        dm = SimpleNamespace(
            get_status=lambda: {"neo4j": True, "pgvector": True, "redis": True}
        )
        monkeypatch.setattr(
            "internal.service.memory.degradation_manager.get_degradation_manager",
            lambda: dm,
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/memory/health")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        data = payload["data"]
        assert data["status"] == "healthy"
        assert data["neo4j"] == "healthy"
        assert data["pgvector"] == "healthy"
        assert data["redis"] == "healthy"

    def test_memory_health_degraded_when_one_dep_down(self, monkeypatch):
        self._setup(monkeypatch)
        dm = SimpleNamespace(
            get_status=lambda: {"neo4j": True, "pgvector": False, "redis": True}
        )
        monkeypatch.setattr(
            "internal.service.memory.degradation_manager.get_degradation_manager",
            lambda: dm,
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/memory/health")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        data = payload["data"]
        assert data["status"] == "degraded"
        assert data["neo4j"] == "healthy"
        assert data["pgvector"] == "unreachable"
        assert data["redis"] == "healthy"

    def test_memory_health_unhealthy_when_two_deps_down(self, monkeypatch):
        self._setup(monkeypatch)
        dm = SimpleNamespace(
            get_status=lambda: {"neo4j": False, "pgvector": False, "redis": True}
        )
        monkeypatch.setattr(
            "internal.service.memory.degradation_manager.get_degradation_manager",
            lambda: dm,
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/memory/health")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        data = payload["data"]
        assert data["status"] == "unhealthy"
        assert data["neo4j"] == "unreachable"
        assert data["pgvector"] == "unreachable"
        assert data["redis"] == "healthy"

    def test_memory_health_unhealthy_when_dm_not_initialized(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/memory/health")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        data = payload["data"]
        assert data["status"] == "unhealthy"
        assert data["neo4j"] == "unreachable"
        assert data["pgvector"] == "unreachable"
        assert data["redis"] == "unreachable"
        assert data["uptime_seconds"] >= 0.0
        assert isinstance(data["uptime_seconds"], (int, float))

    def test_memory_retrieve(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/memory/retrieve?account_id={uuid4()}",
                    json={"query": "咖啡", "top_k": 10},
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["retrieval_path"] == "system1"
        assert payload["data"]["summary"] == "缓存摘要"

    def test_memory_digest(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/memory/digest/{uuid4()}?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["digest"] == "记忆摘要内容"

    def test_memory_consolidate(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/memory/consolidate/{uuid4()}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["success"] is True
        assert payload["data"]["total_items"] == 3

    def test_memory_graph(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/memory/graph/{uuid4()}?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["clusters"] == []
        assert payload["data"]["total_nodes"] == 0

    def test_memory_cluster_subgraph(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/memory/graph/{uuid4()}/cluster/person?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["nodes"] == []
        assert payload["data"]["truncated"] is False

    def test_memory_detail(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/memory/mem-1?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"] == {}

    def test_memory_edit(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/memory/mem-1/edit?account_id={uuid4()}",
                    json={"new_content": "新的内容"},
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["success"] is True
        assert payload["data"]["new_memory_id"] == "new-memory-id"

    def test_memory_soft_delete(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/memory/mem-1/soft-delete?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["deleted"] is True

    def test_memory_hard_delete(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/memory/mem-1/hard-delete?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["deleted"] is True

    def test_memory_decay(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/memory/mem-1/decay?account_id={uuid4()}",
                    json={"decay_factor": "0.4"},
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["memory_id"] == "mem-1"
        assert payload["data"]["new_weight"] == 0.3

    def test_memory_skills(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/memory/skills/{uuid4()}?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["skills"] == []
        assert payload["data"]["total"] == 0


class _FakeAIService:
    def __init__(self):
        self.calls = []

    def _gen(self, marker):
        def gen():
            yield f"event: message\ndata:{marker}-1\n\n"
            yield f"event: message\ndata:{marker}-2\n\n"
        return gen()

    def optimize_prompt(self, prompt):
        self.calls.append(("optimize", prompt))
        return self._gen("opt")

    def generate_suggested_questions_from_message_id(self, message_id, account):
        self.calls.append(("suggested", message_id))
        return ["问题1", "问题2"]

    def code_assistant_chat(self, question):
        self.calls.append(("code", question))
        return self._gen("code")

    def openapi_schema_assistant_chat(self, question):
        self.calls.append(("openapi", question))
        return self._gen("openapi")

    def mcp_schema_assistant_chat(self, question):
        self.calls.append(("mcp", question))
        return self._gen("mcp")


class TestAIRoutes:
    def _setup(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        service = _FakeAIService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_service", lambda cls: service)
        return account, service

    def test_optimize_prompt_sse(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/ai/optimize-prompt?account_id={uuid4()}",
                    json={"prompt": "请优化"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = _run_coro(_run())
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "opt-1" in body
        assert service.calls[0][0] == "optimize"

    def test_optimize_prompt_requires_prompt(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/ai/optimize-prompt?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_generate_suggested_questions(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/ai/suggested-questions?account_id={uuid4()}",
                    json={"message_id": str(uuid4())},
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert len(payload["data"]) == 2
        assert service.calls[0][0] == "suggested"

    def test_ai_chat_sse(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/ai/chat?account_id={uuid4()}",
                    json={"question": "帮我写代码"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = _run_coro(_run())
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "code-1" in body
        assert service.calls[0][0] == "code"

    def test_ai_openapi_schema_chat_sse(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/ai/openapi-schema-chat?account_id={uuid4()}",
                    json={"question": "生成 schema"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = _run_coro(_run())
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "openapi-1" in body
        assert service.calls[0][0] == "openapi"

    def test_ai_mcp_schema_chat_sse(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/ai/mcp-schema-chat?account_id={uuid4()}",
                    json={"question": "生成 mcp schema"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = _run_coro(_run())
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "mcp-1" in body
        assert service.calls[0][0] == "mcp"


class _FakeAudioService:
    def __init__(self):
        self.calls = []

    def audio_to_text(self, file):
        self.calls.append(("to_text",))
        return "转写文本"

    def message_to_audio(self, message_id, account):
        self.calls.append(("message_audio", message_id))

        def gen():
            yield "event: audio\ndata:audio-1\n\n"
        return gen()

    def text_to_audio(self, message_id, text, account):
        self.calls.append(("text_audio", text))

        def gen():
            yield "event: audio\ndata:audio-2\n\n"
        return gen()


class TestAudioRoutes:
    def _setup(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        service = _FakeAudioService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_service", lambda cls: service)
        return account, service

    def test_audio_to_text(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/audio/audio-to-text?account_id={uuid4()}",
                    files={
                        "file": FileStorage(
                            stream=io.BytesIO(b"audio"), filename="a.webm"
                        )
                    },
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["text"] == "转写文本"
        assert service.calls[0][0] == "to_text"

    def test_audio_to_text_requires_file(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/audio/audio-to-text?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_message_to_audio_sse(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/audio/message-to-audio?account_id={uuid4()}",
                    json={"message_id": "msg-1"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = _run_coro(_run())
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "audio-1" in body
        assert service.calls[0][1] == "msg-1"

    def test_text_to_audio_sse(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/audio/text-to-audio?account_id={uuid4()}",
                    json={"text": "你好", "message_id": "msg-1"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = _run_coro(_run())
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "audio-2" in body
        assert service.calls[0][1] == "你好"


class _FakePlatformService:
    def __init__(self):
        self.calls = []

    def get_wechat_config(self, app_id, account):
        self.calls.append(("get", app_id))
        return SimpleNamespace(
            app_id=app_id,
            wechat_app_id="wx123",
            wechat_app_secret="secret",
            wechat_token="token",
            status="configured",
            updated_at=1710000000,
            created_at=1710000000,
        )

    def update_wechat_config(self, app_id, req, account):
        self.calls.append((app_id, req, account))


class _FakeWechatService:
    def __init__(self):
        self.calls = []

    def wechat(self, app_id, method=None, body=None, query=None):
        self.calls.append((app_id, method, body, query))
        return {"app_id": str(app_id), "verified": True}


class TestPlatformWechatRoutes:
    def _setup(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        platform_service = _FakePlatformService()
        wechat_service = _FakeWechatService()

        from internal.service import PlatformService, WechatService

        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: {
                PlatformService: platform_service,
                WechatService: wechat_service,
            }.get(cls),
        )
        return account, platform_service, wechat_service

    def test_get_wechat_config(self, monkeypatch):
        _, platform_service, _ = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/platform/{app_id}/wechat-config?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["wechat_app_id"] == "wx123"
        assert platform_service.calls

    def test_update_wechat_config(self, monkeypatch):
        _, platform_service, _ = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/platform/{app_id}/wechat-config?account_id={uuid4()}",
                    json={"wechat_app_id": "wx456"},
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["message"] == "更新Agent应用微信公众号配置成功"
        assert platform_service.calls[0][0] == app_id
        assert platform_service.calls[0][1].wechat_app_id.data == "wx456"

    def test_wechat_get(self, monkeypatch):
        _, _, wechat_service = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/wechat/{app_id}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["verified"] is True
        assert wechat_service.calls == [(app_id, "GET", b"", {})]

    def test_wechat_post(self, monkeypatch):
        _, _, wechat_service = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/wechat/{app_id}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert wechat_service.calls == [(app_id, "POST", b"", {})]


class _FakePublicAppService:
    def __init__(self):
        self.calls = []

    def get_public_apps_with_page(self, req, account):
        self.calls.append(("list", account))
        return [{"id": str(uuid4()), "name": "公共应用"}], _Paginator()

    def get_public_app_detail(self, app_id, account):
        self.calls.append(("detail", account))
        return {"id": app_id, "name": "公共应用"}

    def share_app_to_square(self, app_id, tags, account):
        self.calls.append(("share", tags))

    def unshare_app_from_square(self, app_id, account):
        self.calls.append(("unshare",))

    def fork_public_app(self, app_id, account):
        self.calls.append(("fork", app_id))
        return SimpleNamespace(id=uuid4(), name="Fork应用")


class _FakePublicAgentA2AService:
    def __init__(self):
        self.calls = []

    def get_agent_card(self, app_id):
        self.calls.append(("card", app_id))
        return {"agentCard": {"name": "agent"}}

    def stream_message(self, app_id, payload):
        self.calls.append(("stream", app_id))

        def gen():
            yield "event: message\ndata:a2a-1\n\n"
        return gen()

    def list_public_app_conversation_messages(self, app_id, conversation_id):
        self.calls.append(("messages", conversation_id))
        return [{"id": "msg-1"}]

    def get_latest_public_app_conversation_id(self, app_id):
        self.calls.append(("latest", app_id))
        return "conv-1"


class TestPublicAppRoutes:
    def _setup(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        app_service = _FakePublicAppService()
        a2a_service = _FakePublicAgentA2AService()

        from internal.service.public_agent_a2a_service import PublicAgentA2AService
        from internal.service.public_app_service import PublicAppService

        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: {
                PublicAppService: app_service,
                PublicAgentA2AService: a2a_service,
            }.get(cls),
        )
        return account, app_service, a2a_service

    def test_get_public_apps(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/public/apps?page_size=5")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert payload["data"]["paginator"]["page_size"] == 20
        assert app_service.calls[0][0] == "list"

    def test_get_public_app_detail(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)
        app_id = str(uuid4())

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/public/apps/{app_id}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["name"] == "公共应用"

    def test_get_public_app_tags(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/public/apps/tags")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert "tags" in payload["data"]

    def test_public_app_a2a_card_route_is_not_registered(self, monkeypatch):
        self._setup(monkeypatch)

        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/public/apps/<string:app_id>/a2a/agent-card" not in rules

    def test_send_public_app_a2a_message_sse(self, monkeypatch):
        _, _, a2a_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/public/apps/{uuid4()}/a2a/messages",
                    json={"message": "hi"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = _run_coro(_run())
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "a2a-1" in body

    def test_get_public_app_a2a_conversation_messages(self, monkeypatch):
        _, _, a2a_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/public/apps/{uuid4()}/a2a/conversations/conv-1/messages"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"][0]["id"] == "msg-1"

    def test_public_app_latest_conversation_route_is_not_registered(self, monkeypatch):
        self._setup(monkeypatch)

        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/public/apps/<string:app_id>/a2a/conversations/latest" not in rules

    def test_share_app_to_square(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{app_id}/share-to-square?account_id={uuid4()}",
                    json={"tags": ["效率"]},
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["message"] == "应用已共享到广场"
        assert app_service.calls[0][0] == "share"

    def test_unshare_app_from_square(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/apps/{uuid4()}/unshare-from-square?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["message"] == "应用已从广场取消共享"
        assert app_service.calls[0][0] == "unshare"

    def test_fork_public_app(self, monkeypatch):
        _, app_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/public/apps/{uuid4()}/fork?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert "id" in payload["data"]
        assert app_service.calls[0][0] == "fork"


class TestRemovedPublicWorkflowRoutes:
    """公开工作流广场已从用户端下线，路由不应再注册。"""

    def test_public_workflow_routes_are_not_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/public/workflows" not in rules
        assert "/public/workflows/<uuid:workflow_id>" not in rules
        assert "/public/workflows/<uuid:workflow_id>/draft-graph" not in rules
        assert "/public/workflows/<uuid:workflow_id>/fork" not in rules


class _FakeRoutingSummaryService:
    def get_user_summary(self, account_id, limit=20):
        return {"total_logs": 3, "recent": [], "limit": limit}


class TestRoutingLogRoutes:
    def test_summary(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        service = _FakeRoutingSummaryService()

        from internal.service.user_routing_summary_service import (
            UserRoutingSummaryService,
        )

        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_service", lambda cls: service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/routing-logs/summary?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["total_logs"] == 3


def _fake_case(**overrides):
    base = {
        "id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "account_id": str(uuid4()),
        "title": "示例案例",
        "summary": "摘要",
        "query": "问题",
        "answer": "回答",
        "tags": ["效率"],
        "rating": 5,
        "status": "pending",
        "reject_reason": "",
        "created_at": 1710000000,
        "approved_at": None,
        "approved_by": None,
        "updated_at": 1710000000,
    }
    base.update(overrides)
    return base


class _FakeShowcaseService:
    def __init__(self):
        self.calls = []

    def create_case(self, **kwargs):
        self.calls.append(("create", kwargs))
        return _fake_case(**kwargs)

    def list_public_cases(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {
            "list": [_fake_case(status="approved")],
            "paginator": {
                "total_record": 1,
                "total_page": 1,
                "current_page": kwargs.get("page", 1),
                "page_size": kwargs.get("per_page", 20),
            },
        }

    def get_case(self, case_id):
        self.calls.append(("get", case_id))
        return _fake_case(id=str(case_id), status="approved")

    def admin_list_cases(self, **kwargs):
        self.calls.append(("admin_list", kwargs))
        return {
            "list": [_fake_case()],
            "paginator": {
                "total_record": 1,
                "total_page": 1,
                "current_page": 1,
                "page_size": 20,
            },
        }

    def approve_case(self, case_id, admin_id=None):
        self.calls.append(("approve", case_id, admin_id))
        return _fake_case(id=str(case_id), status="approved")

    def reject_case(self, case_id, admin_id=None, reason=""):
        self.calls.append(("reject", case_id, admin_id, reason))
        return _fake_case(id=str(case_id), status="rejected", reject_reason=reason)

    def offline_case(self, case_id, admin_id=None):
        self.calls.append(("offline", case_id, admin_id))
        return _fake_case(id=str(case_id), status="offline")


class TestShowcaseRoutes:
    def _setup(self, monkeypatch):
        account = SimpleNamespace(id=uuid4())
        service = _FakeShowcaseService()

        from internal.service.showcase_service import ShowcaseService

        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(support, "_get_service", lambda cls: service)
        return account, service

    def test_create_case(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/showcase/cases?account_id={uuid4()}",
                    json={
                        "conversation_id": str(uuid4()),
                        "title": "我的案例",
                        "summary": "摘要",
                        "query": "问题",
                        "answer": "回答",
                        "tags": ["效率"],
                        "rating": 5,
                    },
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["title"] == "我的案例"
        assert service.calls[0][0] == "create"

    def test_create_case_requires_fields(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/showcase/cases?account_id={uuid4()}",
                    json={"title": "只有标题"},
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_list_cases(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/showcase/cases?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert service.calls[0][0] == "list"

    def test_showcase_case_detail_route_is_not_registered(self, monkeypatch):
        self._setup(monkeypatch)

        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/showcase/cases/<uuid:case_id>" not in rules

    def test_admin_list_cases(self, monkeypatch):
        _, service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/showcase/cases?status=all")
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert service.calls[0][0] == "admin_list"

    def test_approve_case(self, monkeypatch):
        _, service = self._setup(monkeypatch)
        case_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/showcase/cases/{case_id}/approve?admin_id=admin-1"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["status"] == "approved"
        assert service.calls[0] == ("approve", case_id, "admin-1")

    def test_reject_case(self, monkeypatch):
        _, service = self._setup(monkeypatch)
        case_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/showcase/cases/{case_id}/reject?admin_id=admin-1",
                    json={"reason": "内容不合规"},
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["status"] == "rejected"
        assert service.calls[0][0] == "reject"

    def test_offline_case(self, monkeypatch):
        _, service = self._setup(monkeypatch)
        case_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/showcase/cases/{case_id}/offline?admin_id=admin-1"
                )
                return resp, await resp.json

        resp, payload = _run_coro(_run())
        assert resp.status_code == 200
        assert payload["data"]["status"] == "offline"


class TestRegisterIdempotent:
    def test_register_routes_twice_is_safe(self):
        from app.http.user_routes_9 import _registered

        register_routes(asgi_app.quart_app)
        assert _registered is True

    def test_route_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        for expected in (
            "/redeem-codes/redeem",
            "/membership/summary",
            "/memory/write",
            "/memory/health",
            "/memory/retrieve",
            "/ai/optimize-prompt",
            "/ai/chat",
            "/audio/audio-to-text",
            "/platform/<uuid:app_id>/wechat-config",
            "/wechat/<uuid:app_id>",
            "/public/apps",
            "/routing-logs/summary",
            "/showcase/cases",
        ):
            assert expected in rules
