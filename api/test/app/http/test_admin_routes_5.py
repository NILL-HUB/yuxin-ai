"""app.http.admin_routes_5 管理员端点（Quart 异步）单元测试。

覆盖 admin_schedule_task / admin_redeem_code / admin_api_tool 全部端点。
"""

import asyncio
import io
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from werkzeug.datastructures import FileStorage

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_5 import register_routes

register_routes(asgi_app.quart_app)


@dataclass
class _Paginator:
    total_page: int = 1
    total_record: int = 1
    current_page: int = 1
    page_size: int = 20


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

    def list_tasks(self, account, page, page_size, owner_type="user"):
        self.calls.append(("list", page))
        return [self._task()], 1

    def create_task(self, account, name, prompt, cron_expression, **kwargs):
        self.calls.append(("create", name))
        return self._task()

    def update_task(self, task_id, account, **kwargs):
        self.calls.append(("update", task_id))
        return self._task(task_id)

    def delete_task(self, task_id, account, owner_type="user"):
        self.calls.append(("delete", task_id))

    def get_task(self, task_id, account, owner_type="user"):
        return self._task(task_id)

    def list_runs(self, task_id, account, page, page_size, owner_type="user"):
        self.calls.append(("runs", task_id))
        return [], 0


class _FakeScheduleExecutionService:
    def execute_task(self, task):
        return SimpleNamespace(
            id=uuid4(),
            schedule_task_id=task.id,
            status="success",
            trigger_source="manual",
            started_at=datetime(2026, 8, 8, 8, 0),
            finished_at=datetime(2026, 8, 8, 8, 1),
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


class TestAdminScheduleTask:
    def _setup(self, monkeypatch):
        from internal.service.schedule_execution_service import ScheduleExecutionService
        from internal.service.schedule_intent_parser import ScheduleIntentParser
        from internal.service.schedule_task_service import ScheduleTaskService
        from internal.service.task_dedup_service import TaskDedupService

        task_service = _FakeScheduleTaskService()
        execution_service = _FakeScheduleExecutionService()
        parser = _FakeScheduleIntentParser()
        dedup_service = _FakeTaskDedupService()
        services = {
            ScheduleTaskService: task_service,
            ScheduleExecutionService: execution_service,
            ScheduleIntentParser: parser,
            TaskDedupService: dedup_service,
        }
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return task_service, dedup_service

    def test_list_tasks(self, monkeypatch):
        task_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/schedule-tasks?page=2")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["total"] == 1
        assert task_service.calls[0] == ("list", 2)

    def test_create_task(self, monkeypatch):
        task_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/schedule-tasks",
                    json={
                        "name": "任务A",
                        "prompt": "需求",
                        "cron_expression": "0 8 * * *",
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert task_service.calls[0] == ("create", "任务A")
        assert payload["data"]["name"] == "定时任务"

    def test_create_task_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/schedule-tasks",
                    json={"prompt": "需求", "cron_expression": "0 8 * * *"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["data"]["name"] == ["任务名称不能为空"]

    def test_parse(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/schedule-tasks/parse", json={"input": "每天早上 8 点"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["cron_expression"] == "0 8 * * *"

    def test_confirm(self, monkeypatch):
        task_service, dedup_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/schedule-tasks/confirm",
                    json={
                        "prompt": "需求",
                        "cron_expression": "0 8 * * *",
                        "fingerprint": "fp-1",
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert task_service.calls[0][0] == "create"
        assert dedup_service.calls[0] == ("consumed", "fp-1")

    def test_reject_suggestion(self, monkeypatch):
        _, dedup_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/schedule-tasks/reject-suggestion",
                    json={"fingerprint": "fp-2"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "已忽略该建议"
        assert dedup_service.calls[0] == ("rejected", "fp-2")

    def test_humanize(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/schedule-tasks/humanize",
                    json={"cron_expression": "0 8 * * *"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["cron_humanized"] == "每天 8 点"

    def test_get_task(self, monkeypatch):
        self._setup(monkeypatch)
        task_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/schedule-tasks/{task_id}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["id"] == str(task_id)

    def test_update_task(self, monkeypatch):
        task_service, _ = self._setup(monkeypatch)
        task_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.put(
                    f"/admin/schedule-tasks/{task_id}", json={"name": "改名"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert task_service.calls[0] == ("update", task_id)

    def test_delete_task(self, monkeypatch):
        task_service, _ = self._setup(monkeypatch)
        task_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(f"/admin/schedule-tasks/{task_id}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "定时任务已删除"
        assert task_service.calls[0] == ("delete", task_id)

    def test_enable_task(self, monkeypatch):
        task_service, _ = self._setup(monkeypatch)
        task_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/schedule-tasks/{task_id}/enable", json={"enabled": False}
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
                    f"/admin/schedule-tasks/{uuid4()}/run-now"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["status"] == "success"

    def test_runs(self, monkeypatch):
        task_service, _ = self._setup(monkeypatch)
        task_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/schedule-tasks/{task_id}/runs")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["items"] == []
        assert payload["data"]["total"] == 0
        assert task_service.calls[0] == ("runs", task_id)


class _FakeAdminRedeemCodeService:
    def __init__(self):
        self.calls = []

    def generate_codes(self, payload, *, operator_id=None, ip="", user_agent=""):
        self.calls.append(("generate", payload))
        return {
            "batch": {
                "id": str(uuid4()),
                "name": payload["name"],
                "plan_id": str(payload["plan_id"]),
                "quantity": payload.get("quantity", 1),
                "status": "active",
                "expires_at": None,
                "disabled_at": None,
                "created_by": operator_id,
                "created_at": 1710000000,
            },
            "codes": [{"plain_code": "OA-XXXX", "code_mask": "OA-***"}],
        }

    def list_batches(self, *, keyword="", current_page=1, page_size=20):
        self.calls.append(("batches", keyword, current_page, page_size))
        return {"list": [], "paginator": {"total_record": 0, "total_page": 0, "current_page": current_page, "page_size": page_size}}

    def list_codes(self, *, batch_id=None, status="", code_keyword="", current_page=1, page_size=20):
        self.calls.append(("codes", batch_id, status, code_keyword))
        return {"list": [], "paginator": {"total_record": 0, "total_page": 0, "current_page": current_page, "page_size": page_size}}

    def disable_code(self, code_id, *, operator_id=None, ip="", user_agent=""):
        self.calls.append(("disable", code_id))
        return {
            "id": str(code_id),
            "batch_id": str(uuid4()),
            "plan_id": str(uuid4()),
            "code_mask": "OA-***",
            "status": "disabled",
            "redeemed_by": None,
            "redeemed_at": None,
            "expires_at": None,
            "disabled_at": 1710000000,
            "created_at": 1710000000,
        }

    def disable_batch(self, batch_id, *, operator_id=None, ip="", user_agent=""):
        self.calls.append(("disable_batch", batch_id))
        return {"batch_id": str(batch_id), "status": "disabled"}


class TestAdminRedeemCode:
    def _setup(self, monkeypatch):
        from internal.service.admin_redeem_code_service import AdminRedeemCodeService

        service = _FakeAdminRedeemCodeService()
        monkeypatch.setattr(
            support, "_get_service", lambda cls: service if cls is AdminRedeemCodeService else None
        )
        return service

    def test_generate(self, monkeypatch):
        service = self._setup(monkeypatch)
        plan_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/redeem-code-batches",
                    json={"name": "批次", "plan_id": str(plan_id), "quantity": 5},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["batch"]["name"] == "批次"
        assert service.calls[0][0] == "generate"
        assert service.calls[0][1]["quantity"] == 5

    def test_generate_requires_fields(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/redeem-code-batches", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["data"]["name"] == ["名称不能为空"]

    def test_list_batches(self, monkeypatch):
        service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/redeem-code-batches?keyword=abc&current_page=2")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["list"] == []
        assert service.calls[0] == ("batches", "abc", 2, 20)

    def test_list_codes(self, monkeypatch):
        service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/redeem-codes?status=unused")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["list"] == []
        assert service.calls[0][0] == "codes"
        assert service.calls[0][2] == "unused"

    def test_disable(self, monkeypatch):
        service = self._setup(monkeypatch)
        code_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/redeem-codes/{code_id}/disable")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["id"] == str(code_id)
        assert payload["data"]["status"] == "disabled"
        assert service.calls[0] == ("disable", code_id)

    def test_disable_batch(self, monkeypatch):
        service = self._setup(monkeypatch)
        batch_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/redeem-code-batches/{batch_id}/disable")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["batch_id"] == str(batch_id)
        assert service.calls[0] == ("disable_batch", batch_id)


class _FakeApiToolService:
    def __init__(self):
        self.calls = []

    def get_api_tool_providers_with_page_for_admin(self, req):
        self.calls.append(("list", req))
        return [], _Paginator()

    def create_api_tool(self, req, account=None, *, created_by_admin=None):
        self.calls.append(("create", req.name.data))

    def get_api_tool_provider_for_admin(self, provider_id):
        self.calls.append(("get", provider_id))
        return SimpleNamespace(
            id=provider_id,
            name="提供者A",
            icon="http://icon.example/a.png",
            openapi_schema="{}",
            headers=[],
            updated_at=1710000000,
            created_at=1710000000,
        )

    def update_api_tool_provider_for_admin(self, provider_id, req):
        self.calls.append(("update", provider_id))

    def delete_api_tool_provider_for_admin(self, provider_id, *, retention_days=None, deleted_by=None):
        self.calls.append(("delete", provider_id))

    def generate_icon_preview(self, name, description):
        return "http://icon.example/preview.png"

    def parse_openapi_schema(self, openapi_schema):
        self.calls.append(("parse", openapi_schema))

    def import_from_url_for_admin(
        self, url, name, description, headers, *, overwrite=False, task_keywords=None, created_by_admin=None
    ):
        self.calls.append(("import_url", name))
        return {"id": str(uuid4())}

    def import_from_file_for_admin(
        self, file_content, name, description, headers, *, overwrite=False, task_keywords=None, created_by_admin=None
    ):
        self.calls.append(("import_file", name))
        return {"id": str(uuid4())}


class TestAdminApiTool:
    def _setup(self, monkeypatch):
        from internal.service import ApiToolService

        service = _FakeApiToolService()
        monkeypatch.setattr(
            support, "_get_service", lambda cls: service if cls is ApiToolService else None
        )
        return service

    def test_list(self, monkeypatch):
        service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/api-tools?current_page=1")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["list"] == []
        assert service.calls[0][0] == "list"

    def test_create(self, monkeypatch):
        service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/api-tools",
                    json={"name": "插件", "openapi_schema": "{}", "icon": "http://x/a.png"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "创建自定义API插件成功"
        assert service.calls[0] == ("create", "插件")

    def test_create_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/api-tools", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["data"]["name"] == ["名称不能为空"]

    def test_get(self, monkeypatch):
        service = self._setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/api-tools/{provider_id}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["name"] == "提供者A"
        assert service.calls[0] == ("get", provider_id)

    def test_update(self, monkeypatch):
        service = self._setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/api-tools/{provider_id}", json={"name": "改名"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "更新自定义API插件成功"
        assert service.calls[0] == ("update", provider_id)

    def test_delete(self, monkeypatch):
        service = self._setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(f"/admin/api-tools/{provider_id}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除自定义API插件成功"
        assert service.calls[0] == ("delete", provider_id)

    def test_generate_icon_preview(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/api-tools/generate-icon-preview",
                    json={"name": "插件", "description": "描述"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["icon"] == "http://icon.example/preview.png"

    def test_generate_icon_preview_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/api-tools/generate-icon-preview", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["data"]["name"] == ["插件名称不能为空"]

    def test_validate_openapi_schema(self, monkeypatch):
        service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/api-tools/validate-openapi-schema",
                    json={"openapi_schema": "{}"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "数据校验成功"
        assert service.calls[0][0] == "parse"

    def test_validate_openapi_schema_requires_field(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/api-tools/validate-openapi-schema", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_import_from_url(self, monkeypatch):
        service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/api-tools/import-url",
                    json={"url": "https://example.com/openapi.json", "name": "远程API"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert "id" in payload["data"]
        assert service.calls[0] == ("import_url", "远程API")

    def test_import_from_url_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/api-tools/import-url",
                    json={"url": "https://example.com/openapi.json"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["data"]["name"] == ["提供者名称不能为空"]

    def test_import_from_file(self, monkeypatch):
        service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/api-tools/import-file",
                    files={
                        "file": FileStorage(
                            stream=io.BytesIO(b"content"), filename="openapi.yaml"
                        )
                    },
                    form={"name": "文件API"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert "id" in payload["data"]
        assert service.calls[0] == ("import_file", "文件API")

    def test_import_from_file_requires_file(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/api-tools/import-file", form={"name": "文件API"})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
