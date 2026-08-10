"""管理员 API 工具 / 定时任务 / 卡密端点（Quart 异步迁移）。

迁移自 internal/router/router.py 中 admin_api_tool_handler、
admin_schedule_task_handler 与 admin_redeem_code_handler 的注册段，
实现来源为 internal/handler/ 下对应 handler。
"""

import json as _json
from datetime import datetime, timezone
from uuid import UUID

from quart import request

from internal.service import ApiToolService
from internal.service.admin_redeem_code_service import AdminRedeemCodeService
from internal.service.schedule_execution_service import ScheduleExecutionService
from internal.service.schedule_intent_parser import ScheduleIntentParser
from internal.service.schedule_task_service import ScheduleTaskService
from internal.service.task_dedup_service import TaskDedupService

_registered = False


def _json_loads_list(value) -> list:
    if not value:
        return []
    try:
        parsed = _json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    # ------------------------------------------------------------------ #
    #  平台级定时任务（admin 端）：静态路径注册在 /admin/schedule-tasks/<uuid:task_id> 之前
    # ------------------------------------------------------------------ #

    @quart_app.get("/admin/schedule-tasks")
    async def admin_schedule_task_list():
        from app.http import asgi_app as a

        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))
        tasks, total = await a._to_thread(
            a._get_service(ScheduleTaskService).list_tasks,
            None,
            page,
            page_size,
            owner_type="admin",
        )
        from internal.schema.schedule_task_schema import ScheduleTaskResp

        return a._ok({"items": ScheduleTaskResp.dump_many(tasks), "total": total})

    @quart_app.post("/admin/schedule-tasks")
    async def admin_schedule_task_create():
        from app.http import asgi_app as a

        body = await request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "").strip()
        prompt = (body.get("prompt") or "").strip()
        trigger_type = (body.get("trigger_type") or "cron").strip()
        cron_expression = (body.get("cron_expression") or "").strip()
        interval_config = body.get("interval_config")
        description = (body.get("description") or "").strip()
        cron_humanized = (body.get("cron_humanized") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error", message="任务名称不能为空",
                data={"name": ["任务名称不能为空"]}, status=400,
            )
        if not prompt:
            return a._json_resp(
                code="validate_error", message="任务需求不能为空",
                data={"prompt": ["任务需求不能为空"]}, status=400,
            )
        if trigger_type not in ("cron", "interval"):
            return a._json_resp(
                code="validate_error", message="触发类型不合法",
                data={"trigger_type": ["触发类型不合法"]}, status=400,
            )
        if trigger_type == "cron" and not cron_expression:
            return a._json_resp(
                code="validate_error", message="定时表达式不能为空",
                data={"cron_expression": ["定时表达式不能为空"]}, status=400,
            )
        try:
            task = await a._to_thread(
                a._get_service(ScheduleTaskService).create_task,
                None,
                name,
                prompt,
                cron_expression,
                description=description,
                cron_humanized=cron_humanized,
                owner_type="admin",
                trigger_type=trigger_type,
                interval_config=interval_config,
            )
        except Exception as exc:
            return a._json_resp(
                code="validate_error", message=str(exc),
                data={"cron_expression": [str(exc)]}, status=400,
            )
        from internal.schema.schedule_task_schema import ScheduleTaskResp

        return a._ok(ScheduleTaskResp.pre_dump_process(task))

    @quart_app.post("/admin/schedule-tasks/parse")
    async def admin_schedule_task_parse():
        from app.http import asgi_app as a

        body = await request.get_json(force=True, silent=True) or {}
        user_input = (body.get("input") or "").strip()
        history = body.get("history") or []
        if not user_input:
            return a._json_resp(
                code="validate_error", message="需求描述不能为空",
                data={"input": ["需求描述不能为空"]}, status=400,
            )
        parser = a._get_service(ScheduleIntentParser)
        try:
            result = await a._to_thread(parser.parse, user_input, history)
            await a._to_thread(parser.validate_cron, result.get("cron_expression", ""))
        except Exception as exc:
            return a._json_resp(
                code="validate_error", message=str(exc),
                data={"input": [str(exc)]}, status=400,
            )
        return a._ok(result)

    @quart_app.post("/admin/schedule-tasks/confirm")
    async def admin_schedule_task_confirm():
        from app.http import asgi_app as a

        body = await request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "定时任务").strip()
        prompt = (body.get("prompt") or "").strip()
        cron_expression = (body.get("cron_expression") or "").strip()
        cron_humanized = (body.get("cron_humanized") or "").strip()
        fingerprint = (body.get("fingerprint") or "").strip()
        if not prompt or not cron_expression:
            return a._json_resp(
                code="validate_error", message="缺少需求或定时表达式",
                data={"prompt": ["缺少需求或定时表达式"]}, status=400,
            )
        task = await a._to_thread(
            a._get_service(ScheduleTaskService).create_task,
            None,
            name,
            prompt,
            cron_expression,
            cron_humanized=cron_humanized,
            owner_type="admin",
        )
        if fingerprint:
            await a._to_thread(
                a._get_service(TaskDedupService).mark_consumed, fingerprint
            )
        from internal.schema.schedule_task_schema import ScheduleTaskResp

        return a._ok(ScheduleTaskResp.pre_dump_process(task))

    @quart_app.post("/admin/schedule-tasks/reject-suggestion")
    async def admin_schedule_task_reject_suggestion():
        from app.http import asgi_app as a

        body = await request.get_json(force=True, silent=True) or {}
        fingerprint = (body.get("fingerprint") or "").strip()
        if fingerprint:
            await a._to_thread(
                a._get_service(TaskDedupService).mark_rejected, fingerprint
            )
        return a._ok_msg("已忽略该建议")

    @quart_app.post("/admin/schedule-tasks/humanize")
    async def admin_schedule_task_humanize():
        from app.http import asgi_app as a

        body = await request.get_json(force=True, silent=True) or {}
        cron_expression = (body.get("cron_expression") or "").strip()
        if not cron_expression:
            return a._json_resp(
                code="validate_error", message="定时表达式不能为空",
                data={"cron_expression": ["定时表达式不能为空"]}, status=400,
            )
        parser = a._get_service(ScheduleIntentParser)
        try:
            cron_humanized = await a._to_thread(parser.humanize, cron_expression)
        except Exception as exc:
            return a._json_resp(
                code="validate_error", message=str(exc),
                data={"cron_expression": [str(exc)]}, status=400,
            )
        return a._ok({"cron_humanized": cron_humanized})

    @quart_app.get("/admin/schedule-tasks/<uuid:task_id>")
    async def admin_schedule_task_get(task_id):
        from app.http import asgi_app as a

        task = await a._to_thread(
            a._get_service(ScheduleTaskService).get_task,
            task_id,
            None,
            owner_type="admin",
        )
        from internal.schema.schedule_task_schema import ScheduleTaskResp

        return a._ok(ScheduleTaskResp.pre_dump_process(task))

    @quart_app.put("/admin/schedule-tasks/<uuid:task_id>")
    async def admin_schedule_task_update(task_id):
        from app.http import asgi_app as a

        body = await request.get_json(force=True, silent=True) or {}
        try:
            task = await a._to_thread(
                a._get_service(ScheduleTaskService).update_task,
                task_id,
                None,
                name=body.get("name"),
                prompt=body.get("prompt"),
                cron_expression=body.get("cron_expression"),
                description=body.get("description"),
                enabled=body.get("enabled"),
                cron_humanized=body.get("cron_humanized"),
                owner_type="admin",
                trigger_type=body.get("trigger_type"),
                interval_config=body.get("interval_config"),
            )
        except Exception as exc:
            return a._json_resp(
                code="validate_error", message=str(exc),
                data={"cron_expression": [str(exc)]}, status=400,
            )
        from internal.schema.schedule_task_schema import ScheduleTaskResp

        return a._ok(ScheduleTaskResp.pre_dump_process(task))

    @quart_app.delete("/admin/schedule-tasks/<uuid:task_id>")
    async def admin_schedule_task_delete(task_id):
        from app.http import asgi_app as a

        await a._to_thread(
            a._get_service(ScheduleTaskService).delete_task,
            task_id,
            None,
            owner_type="admin",
        )
        return a._ok_msg("定时任务已删除")

    @quart_app.post("/admin/schedule-tasks/<uuid:task_id>/enable")
    async def admin_schedule_task_enable(task_id):
        from app.http import asgi_app as a

        body = await request.get_json(force=True, silent=True) or {}
        enabled = bool(body.get("enabled", True))
        task = await a._to_thread(
            a._get_service(ScheduleTaskService).update_task,
            task_id,
            None,
            enabled=enabled,
            owner_type="admin",
        )
        from internal.schema.schedule_task_schema import ScheduleTaskResp

        return a._ok(ScheduleTaskResp.pre_dump_process(task))

    @quart_app.post("/admin/schedule-tasks/<uuid:task_id>/run-now")
    async def admin_schedule_task_run_now(task_id):
        from app.http import asgi_app as a

        task = await a._to_thread(
            a._get_service(ScheduleTaskService).get_task,
            task_id,
            None,
            owner_type="admin",
        )
        run = await a._to_thread(
            a._get_service(ScheduleExecutionService).execute_task, task
        )
        from internal.schema.schedule_task_schema import ScheduleTaskRunResp

        return a._ok(ScheduleTaskRunResp.pre_dump_process(run))

    @quart_app.get("/admin/schedule-tasks/<uuid:task_id>/runs")
    async def admin_schedule_task_runs(task_id):
        from app.http import asgi_app as a

        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))
        runs, total = await a._to_thread(
            a._get_service(ScheduleTaskService).list_runs,
            task_id,
            None,
            page,
            page_size,
            owner_type="admin",
        )
        from internal.schema.schedule_task_schema import ScheduleTaskRunResp

        return a._ok({"items": ScheduleTaskRunResp.dump_many(runs), "total": total})

    # ------------------------------------------------------------------ #
    #  卡密（redeem code）管理
    # ------------------------------------------------------------------ #

    @quart_app.get("/admin/redeem-code-batches")
    async def admin_redeem_code_batch_list():
        from app.http import asgi_app as a

        def _int_arg(name, default):
            raw = request.args.get(name)
            try:
                return int(raw) if raw is not None else default
            except (ValueError, TypeError):
                return default

        result = await a._to_thread(
            a._get_service(AdminRedeemCodeService).list_batches,
            keyword=request.args.get("keyword") or "",
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
        )
        from internal.schema.admin_redeem_code_schema import RedeemCodeBatchPageResp

        resp = RedeemCodeBatchPageResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/redeem-code-batches")
    async def admin_redeem_code_generate():
        from app.http import asgi_app as a

        payload = await request.get_json(force=True, silent=True) or {}
        name = (payload.get("name") or "").strip()
        plan_id = payload.get("plan_id")
        quantity = payload.get("quantity")
        if not name:
            return a._json_resp(
                code="validate_error", message="名称不能为空",
                data={"name": ["名称不能为空"]}, status=400,
            )
        if not plan_id:
            return a._json_resp(
                code="validate_error", message="plan_id不能为空",
                data={"plan_id": ["plan_id不能为空"]}, status=400,
            )
        if quantity is None:
            return a._json_resp(
                code="validate_error", message="quantity不能为空",
                data={"quantity": ["quantity不能为空"]}, status=400,
            )
        try:
            parsed_plan_id = UUID(str(plan_id))
        except (ValueError, TypeError):
            return a._json_resp(
                code="validate_error", message="plan_id无效",
                data={"plan_id": ["plan_id无效"]}, status=400,
            )
        expires_at = None
        if payload.get("expires_at"):
            expires_at = datetime.fromtimestamp(
                int(payload["expires_at"]), tz=timezone.utc
            ).replace(tzinfo=None)
        operator_id = None
        ip = request.headers.get("X-Forwarded-For", "")
        user_agent = request.headers.get("User-Agent", "")
        result = await a._to_thread(
            a._get_service(AdminRedeemCodeService).generate_codes,
            {
                "name": name,
                "plan_id": parsed_plan_id,
                "quantity": int(quantity or 1),
                "expires_at": expires_at,
            },
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        from internal.schema.admin_redeem_code_schema import GenerateRedeemCodesResp

        resp = GenerateRedeemCodesResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/redeem-codes")
    async def admin_redeem_code_list():
        from app.http import asgi_app as a

        def _int_arg(name, default):
            raw = request.args.get(name)
            try:
                return int(raw) if raw is not None else default
            except (ValueError, TypeError):
                return default

        batch_id = None
        raw_batch_id = request.args.get("batch_id")
        if raw_batch_id:
            batch_id = UUID(raw_batch_id)
        result = await a._to_thread(
            a._get_service(AdminRedeemCodeService).list_codes,
            batch_id=batch_id,
            status=request.args.get("status") or "",
            code_keyword=request.args.get("code_keyword") or "",
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
        )
        from internal.schema.admin_redeem_code_schema import RedeemCodePageResp

        resp = RedeemCodePageResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/redeem-codes/<uuid:code_id>/disable")
    async def admin_redeem_code_disable(code_id):
        from app.http import asgi_app as a

        operator_id = None
        ip = request.headers.get("X-Forwarded-For", "")
        user_agent = request.headers.get("User-Agent", "")
        result = await a._to_thread(
            a._get_service(AdminRedeemCodeService).disable_code,
            code_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        from internal.schema.admin_redeem_code_schema import RedeemCodeResp

        resp = RedeemCodeResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/redeem-code-batches/<uuid:batch_id>/disable")
    async def admin_redeem_code_batch_disable(batch_id):
        from app.http import asgi_app as a

        operator_id = None
        ip = request.headers.get("X-Forwarded-For", "")
        user_agent = request.headers.get("User-Agent", "")
        result = await a._to_thread(
            a._get_service(AdminRedeemCodeService).disable_batch,
            batch_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        return a._ok(result)

    # ------------------------------------------------------------------ #
    #  管理员自定义 API 插件管理：静态路径注册在 /admin/api-tools/<uuid:provider_id> 之前
    # ------------------------------------------------------------------ #

    @quart_app.get("/admin/api-tools")
    async def admin_api_tool_list():
        from app.http import asgi_app as a

        def _int_arg(name, default):
            raw = request.args.get(name)
            try:
                return int(raw) if raw is not None else default
            except (ValueError, TypeError):
                return default

        req = a.SimpleNamespace(
            current_page=a._field(_int_arg("current_page", 1), 1),
            page_size=a._field(_int_arg("page_size", 20), 20),
            search_word=a._field(request.args.get("search_word"), None),
        )
        providers, paginator = await a._to_thread(
            a._get_service(ApiToolService).get_api_tool_providers_with_page_for_admin,
            req,
        )
        from internal.schema.api_tool_schema import GetApiToolProvidersWithPageResp

        resp = GetApiToolProvidersWithPageResp(many=True)
        return a._ok({"list": resp.dump(providers), "paginator": a.asdict(paginator)})

    @quart_app.post("/admin/api-tools")
    async def admin_api_tool_create():
        from app.http import asgi_app as a

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error", message="名称不能为空",
                data={"name": ["名称不能为空"]}, status=400,
            )
        req = a.SimpleNamespace(
            name=a._field(name),
            icon=a._field(str(payload.get("icon") or "")),
            openapi_schema=a._field(payload.get("openapi_schema")),
            headers=a._field(payload.get("headers") or []),
            task_keywords=a._field(payload.get("task_keywords") or []),
        )
        await a._to_thread(
            a._get_service(ApiToolService).create_api_tool,
            req,
            created_by_admin=None,
        )
        return a._ok_msg("创建自定义API插件成功")

    @quart_app.post("/admin/api-tools/import-url")
    async def admin_api_tool_import_url():
        from app.http import asgi_app as a

        data = await request.get_json(force=True, silent=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error", message="提供者名称不能为空",
                data={"name": ["提供者名称不能为空"]}, status=400,
            )
        result = await a._to_thread(
            a._get_service(ApiToolService).import_from_url_for_admin,
            url=(data.get("url") or "").strip(),
            name=name,
            description=(data.get("description") or "").strip(),
            headers=data.get("headers") or [],
            overwrite=bool(data.get("overwrite", False)),
            task_keywords=data.get("task_keywords") or [],
            created_by_admin=None,
        )
        return a._ok(result)

    @quart_app.post("/admin/api-tools/import-file")
    async def admin_api_tool_import_file():
        from app.http import asgi_app as a

        files = await request.files
        file = files.get("file")
        if file is None or not file.filename:
            return a._json_resp(
                code="validate_error", message="请选择要上传的 OpenAPI 文件",
                data={"file": ["请选择要上传的 OpenAPI 文件"]}, status=400,
            )
        form = (await request.form) or {}
        name = (form.get("name") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error", message="提供者名称不能为空",
                data={"name": ["提供者名称不能为空"]}, status=400,
            )
        try:
            raw_bytes = file.read()
            content = raw_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            return a._json_resp(
                code="validate_error", message=f"读取上传文件失败: {exc}",
                data={"file": [f"读取上传文件失败: {exc}"]}, status=400,
            )
        try:
            headers = _json.loads(form.get("headers") or "[]")
        except Exception:
            headers = []
        result = await a._to_thread(
            a._get_service(ApiToolService).import_from_file_for_admin,
            file_content=content,
            name=name,
            description=(form.get("description") or "").strip(),
            headers=headers if isinstance(headers, list) else [],
            overwrite=(form.get("overwrite") or "").lower() in ("true", "1", "yes"),
            task_keywords=_json_loads_list(form.get("task_keywords")),
            created_by_admin=None,
        )
        return a._ok(result)

    @quart_app.get("/admin/api-tools/<uuid:provider_id>")
    async def admin_api_tool_get(provider_id):
        from app.http import asgi_app as a

        provider = await a._to_thread(
            a._get_service(ApiToolService).get_api_tool_provider_for_admin,
            provider_id,
        )
        from internal.schema.api_tool_schema import GetApiToolProviderResp

        resp = GetApiToolProviderResp()
        return a._ok(resp.dump(provider))

    @quart_app.patch("/admin/api-tools/<uuid:provider_id>")
    async def admin_api_tool_update(provider_id):
        from app.http import asgi_app as a

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error", message="名称不能为空",
                data={"name": ["名称不能为空"]}, status=400,
            )
        req = a.SimpleNamespace(
            name=a._field(name),
            icon=a._field(str(payload.get("icon") or "")),
            openapi_schema=a._field(payload.get("openapi_schema")),
            headers=a._field(payload.get("headers") or []),
            task_keywords=a._field(payload.get("task_keywords") or []),
        )
        await a._to_thread(
            a._get_service(ApiToolService).update_api_tool_provider_for_admin,
            provider_id,
            req,
        )
        return a._ok_msg("更新自定义API插件成功")

    @quart_app.delete("/admin/api-tools/<uuid:provider_id>")
    async def admin_api_tool_delete(provider_id):
        from app.http import asgi_app as a

        payload = await request.get_json(force=True, silent=True) or {}
        retention_days = payload.get("retention_days")
        await a._to_thread(
            a._get_service(ApiToolService).delete_api_tool_provider_for_admin,
            provider_id,
            retention_days=retention_days,
            deleted_by=None,
        )
        return a._ok_msg("删除自定义API插件成功")

    @quart_app.post("/admin/api-tools/generate-icon-preview")
    async def admin_api_tool_generate_icon_preview():
        from app.http import asgi_app as a

        data = await request.get_json(force=True, silent=True) or {}
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error", message="插件名称不能为空",
                data={"name": ["插件名称不能为空"]}, status=400,
            )
        icon_url = await a._to_thread(
            a._get_service(ApiToolService).generate_icon_preview, name, description
        )
        return a._ok({"icon": icon_url})

    @quart_app.post("/admin/api-tools/validate-openapi-schema")
    async def admin_api_tool_validate_openapi_schema():
        from app.http import asgi_app as a

        payload = await request.get_json(force=True, silent=True) or {}
        openapi_schema = str(payload.get("openapi_schema") or "").strip()
        if not openapi_schema:
            return a._json_resp(
                code="validate_error", message="openapi_schema 不能为空",
                data={"openapi_schema": ["openapi_schema 不能为空"]}, status=400,
            )
        await a._to_thread(
            a._get_service(ApiToolService).parse_openapi_schema, openapi_schema
        )
        return a._ok_msg("数据校验成功")
