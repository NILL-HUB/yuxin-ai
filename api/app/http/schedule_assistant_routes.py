"""定时任务与助手路由模块（从 asgi_app.py 拆分）：/schedule-tasks*、/assistant-agent*、/openapi/*。"""
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID

from quart import Response, request

from app.http import support as _support
from app.http.support import (
    _field,
    _int_arg,
    _is_sync_iterator,
    _json_resp,
    _ok,
    _ok_msg,
    _resolve_account,
    _sse_response,
    _to_thread,
)

_registered = False


def _get_service(cls):
    return _support._get_service(cls)


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/schedule-tasks")
    async def async_schedule_task_list() -> Response:
        """async 获取定时任务列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.schedule_task_schema import ScheduleTaskResp
        from internal.service.schedule_task_service import ScheduleTaskService

        tasks, total = await _to_thread(
            _get_service(ScheduleTaskService).list_tasks,
            account,
            _int_arg("page", 1),
            _int_arg("page_size", 20),
        )
        return _ok({"items": ScheduleTaskResp.dump_many(tasks), "total": total})

    @quart_app.post("/schedule-tasks")
    async def async_schedule_task_create() -> Response:
        """async 创建定时任务。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.schedule_task_schema import ScheduleTaskResp
        from internal.service.schedule_task_service import ScheduleTaskService

        body = await request.get_json(force=True, silent=True) or {}
        name = str(body.get("name") or "").strip()
        prompt = str(body.get("prompt") or "").strip()
        cron_expression = str(body.get("cron_expression") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="任务名称不能为空",
                data={"name": ["任务名称不能为空"]},
                status=400,
            )
        if not prompt:
            return _json_resp(
                code="validate_error",
                message="任务需求不能为空",
                data={"prompt": ["任务需求不能为空"]},
                status=400,
            )
        if not cron_expression:
            return _json_resp(
                code="validate_error",
                message="定时表达式不能为空",
                data={"cron_expression": ["定时表达式不能为空"]},
                status=400,
            )
        try:
            task = await _to_thread(
                _get_service(ScheduleTaskService).create_task,
                account,
                name,
                prompt,
                cron_expression,
                description=str(body.get("description") or ""),
                cron_humanized=str(body.get("cron_humanized") or ""),
            )
        except Exception as exc:
            return _json_resp(
                code="validate_error",
                message=str(exc),
                data={"cron_expression": [str(exc)]},
                status=400,
            )
        return _ok(ScheduleTaskResp.pre_dump_process(task))

    @quart_app.post("/schedule-tasks/parse")
    async def async_schedule_task_parse() -> Response:
        """async 解析定时任务需求。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.schedule_intent_parser import ScheduleIntentParser

        body = await request.get_json(force=True, silent=True) or {}
        user_input = str(body.get("input") or "").strip()
        history = body.get("history") or []
        if not user_input:
            return _json_resp(
                code="validate_error",
                message="需求描述不能为空",
                data={"input": ["需求描述不能为空"]},
                status=400,
            )
        parser = _get_service(ScheduleIntentParser)
        try:
            result = await _to_thread(parser.parse, user_input, history)
            await _to_thread(parser.validate_cron, result.get("cron_expression", ""))
        except Exception as exc:
            return _json_resp(
                code="validate_error",
                message=str(exc),
                data={"input": [str(exc)]},
                status=400,
            )
        return _ok(result)

    @quart_app.post("/schedule-tasks/confirm")
    async def async_schedule_task_confirm() -> Response:
        """async 确认创建定时任务（智能建议场景）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.schedule_task_schema import ScheduleTaskResp
        from internal.service.schedule_task_service import ScheduleTaskService
        from internal.service.task_dedup_service import TaskDedupService

        body = await request.get_json(force=True, silent=True) or {}
        name = str(body.get("name") or "定时任务").strip()
        prompt = str(body.get("prompt") or "").strip()
        cron_expression = str(body.get("cron_expression") or "").strip()
        fingerprint = str(body.get("fingerprint") or "").strip()
        if not prompt or not cron_expression:
            return _json_resp(
                code="validate_error",
                message="缺少需求或定时表达式",
                data={"prompt": ["缺少需求或定时表达式"]},
                status=400,
            )
        task = await _to_thread(
            _get_service(ScheduleTaskService).create_task,
            account,
            name,
            prompt,
            cron_expression,
            cron_humanized=str(body.get("cron_humanized") or ""),
        )
        if fingerprint:
            await _to_thread(
                _get_service(TaskDedupService).mark_consumed, fingerprint
            )
        return _ok(ScheduleTaskResp.pre_dump_process(task))

    @quart_app.post("/schedule-tasks/reject-suggestion")
    async def async_schedule_task_reject_suggestion() -> Response:
        """async 忽略定时任务建议。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.task_dedup_service import TaskDedupService

        body = await request.get_json(force=True, silent=True) or {}
        fingerprint = str(body.get("fingerprint") or "").strip()
        if fingerprint:
            await _to_thread(_get_service(TaskDedupService).mark_rejected, fingerprint)
        return _ok_msg("已忽略该建议")

    @quart_app.post("/schedule-tasks/humanize")
    async def async_schedule_task_humanize() -> Response:
        """async 将 cron 表达式翻译为人类可读描述。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.schedule_intent_parser import ScheduleIntentParser

        body = await request.get_json(force=True, silent=True) or {}
        cron_expression = str(body.get("cron_expression") or "").strip()
        if not cron_expression:
            return _json_resp(
                code="validate_error",
                message="定时表达式不能为空",
                data={"cron_expression": ["定时表达式不能为空"]},
                status=400,
            )
        parser = _get_service(ScheduleIntentParser)
        try:
            cron_humanized = await _to_thread(parser.humanize, cron_expression)
        except Exception as exc:
            return _json_resp(
                code="validate_error",
                message=str(exc),
                data={"cron_expression": [str(exc)]},
                status=400,
            )
        return _ok({"cron_humanized": cron_humanized})

    @quart_app.get("/schedule-tasks/<uuid:task_id>")
    async def async_schedule_task_get(task_id) -> Response:
        """async 获取定时任务详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.schedule_task_schema import ScheduleTaskResp
        from internal.service.schedule_task_service import ScheduleTaskService

        task = await _to_thread(
            _get_service(ScheduleTaskService).get_task, task_id, account
        )
        return _ok(ScheduleTaskResp.pre_dump_process(task))

    @quart_app.put("/schedule-tasks/<uuid:task_id>")
    async def async_schedule_task_update(task_id) -> Response:
        """async 更新定时任务。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.schedule_task_schema import ScheduleTaskResp
        from internal.service.schedule_task_service import ScheduleTaskService

        body = await request.get_json(force=True, silent=True) or {}
        try:
            task = await _to_thread(
                _get_service(ScheduleTaskService).update_task,
                task_id,
                account,
                name=body.get("name"),
                prompt=body.get("prompt"),
                cron_expression=body.get("cron_expression"),
                description=body.get("description"),
                enabled=body.get("enabled"),
                cron_humanized=body.get("cron_humanized"),
            )
        except Exception as exc:
            return _json_resp(
                code="validate_error",
                message=str(exc),
                data={"cron_expression": [str(exc)]},
                status=400,
            )
        return _ok(ScheduleTaskResp.pre_dump_process(task))

    @quart_app.delete("/schedule-tasks/<uuid:task_id>")
    async def async_schedule_task_delete(task_id) -> Response:
        """async 删除定时任务。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.schedule_task_service import ScheduleTaskService

        await _to_thread(
            _get_service(ScheduleTaskService).delete_task, task_id, account
        )
        return _ok_msg("定时任务已删除")

    @quart_app.post("/schedule-tasks/<uuid:task_id>/enable")
    async def async_schedule_task_enable(task_id) -> Response:
        """async 启用/停用定时任务。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.schedule_task_schema import ScheduleTaskResp
        from internal.service.schedule_task_service import ScheduleTaskService

        body = await request.get_json(force=True, silent=True) or {}
        enabled = bool(body.get("enabled", True))
        task = await _to_thread(
            _get_service(ScheduleTaskService).update_task, task_id, account, enabled=enabled
        )
        return _ok(ScheduleTaskResp.pre_dump_process(task))

    @quart_app.post("/schedule-tasks/<uuid:task_id>/run-now")
    async def async_schedule_task_run_now(task_id) -> Response:
        """async 立即执行定时任务。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.schedule_task_schema import ScheduleTaskRunResp
        from internal.service.schedule_execution_service import ScheduleExecutionService
        from internal.service.schedule_task_service import ScheduleTaskService

        task = await _to_thread(
            _get_service(ScheduleTaskService).get_task, task_id, account
        )
        run = await _to_thread(
            _get_service(ScheduleExecutionService).execute_task, task
        )
        return _ok(ScheduleTaskRunResp.pre_dump_process(run))

    @quart_app.get("/schedule-tasks/<uuid:task_id>/runs")
    async def async_schedule_task_runs(task_id) -> Response:
        """async 获取定时任务执行记录。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.schedule_task_schema import ScheduleTaskRunResp
        from internal.service.schedule_task_service import ScheduleTaskService

        runs, total = await _to_thread(
            _get_service(ScheduleTaskService).list_runs,
            task_id,
            account,
            _int_arg("page", 1),
            _int_arg("page_size", 20),
        )
        return _ok({"items": ScheduleTaskRunResp.dump_many(runs), "total": total})

    @quart_app.get("/assistant-agent/capabilities")
    async def async_get_assistant_agent_capabilities() -> Response:
        """async 获取辅助 Agent 当前可用能力。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import AssistantAgentService

        capabilities = await _to_thread(
            _get_service(AssistantAgentService).get_capabilities
        )
        return _ok({"capabilities": capabilities})

    @quart_app.post("/assistant-agent/chat/<uuid:task_id>/stop")
    async def async_stop_assistant_agent_chat(task_id) -> Response:
        """async 停止与辅助智能体的对话聊天。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import AssistantAgentService

        await _to_thread(
            _get_service(AssistantAgentService).stop_chat, task_id, account
        )
        return _ok_msg("停止辅助智能体会话成功")

    @quart_app.get("/assistant-agent/messages")
    async def async_get_assistant_agent_messages_with_page() -> Response:
        """async 获取与辅助智能体的消息分页列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.assistant_agent_schema import GetAssistantAgentMessagesWithPageResp
        from internal.service import AssistantAgentService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            created_at=_field(request.args.get("created_at"), None),
        )
        messages, paginator = await _to_thread(
            _get_service(AssistantAgentService).get_conversation_messages_with_page,
            req,
            account,
        )
        resp = GetAssistantAgentMessagesWithPageResp(many=True)
        return _ok({"list": resp.dump(messages), "paginator": asdict(paginator)})

    @quart_app.get("/assistant-agent/conversations")
    async def async_get_assistant_agent_conversations() -> Response:
        """async 获取与辅助智能体的最近会话列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.assistant_agent_schema import GetAssistantAgentConversationsResp
        from internal.service import AssistantAgentService

        req = SimpleNamespace(
            limit=_field(_int_arg("limit", 10), 10),
        )
        conversations = await _to_thread(
            _get_service(AssistantAgentService).get_conversations, req, account
        )
        resp = GetAssistantAgentConversationsResp(many=True)
        return _ok(resp.dump(conversations))

    @quart_app.post("/assistant-agent/delete-conversation")
    async def async_delete_assistant_agent_conversation() -> Response:
        """async 清空与辅助智能体的聊天会话记录。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import AssistantAgentService

        await _to_thread(
            _get_service(AssistantAgentService).delete_conversation, account
        )
        return _ok_msg("清空辅助智能体会话成功")

    @quart_app.get("/openapi/api-keys")
    async def async_get_api_keys_with_page() -> Response:
        """async 获取当前账号的 API 密钥分页列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.api_key_schema import GetApiKeysWithPageResp
        from internal.service import ApiKeyService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
        )
        api_keys, paginator = await _to_thread(
            _get_service(ApiKeyService).get_api_keys_with_page, req, account
        )
        resp = GetApiKeysWithPageResp(many=True)
        return _ok({"list": resp.dump(api_keys), "paginator": asdict(paginator)})

    @quart_app.post("/openapi/api-keys")
    async def async_create_api_key() -> Response:
        """async 创建 API 密钥。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiKeyService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="名称不能为空",
                data={"name": ["名称不能为空"]},
                status=400,
            )
        req = SimpleNamespace(
            name=_field(name),
            description=_field(str(payload.get("description") or "")),
        )
        created_api_key = await _to_thread(
            _get_service(ApiKeyService).create_api_key, req, account
        )
        api_key_value = (
            created_api_key.get("api_key")
            if isinstance(created_api_key, dict)
            else getattr(created_api_key, "api_key", "")
        )
        return _ok({"api_key": api_key_value})

    @quart_app.post("/openapi/api-keys/<uuid:api_key_id>")
    async def async_update_api_key(api_key_id) -> Response:
        """async 更新 API 密钥信息。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiKeyService

        payload = await request.get_json(force=True, silent=True) or {}
        req_data = {}
        if payload.get("name"):
            req_data["name"] = str(payload["name"])
        if payload.get("description"):
            req_data["description"] = str(payload["description"])
        await _to_thread(
            _get_service(ApiKeyService).update_api_key, api_key_id, account, **req_data
        )
        return _ok_msg("更新API密钥成功")

    @quart_app.post("/openapi/api-keys/<uuid:api_key_id>/is-active")
    async def async_update_api_key_is_active(api_key_id) -> Response:
        """async 更新 API 密钥激活状态。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiKeyService

        payload = await request.get_json(force=True, silent=True) or {}
        req_data = {"is_active": bool(payload.get("is_active", True))}
        await _to_thread(
            _get_service(ApiKeyService).update_api_key, api_key_id, account, **req_data
        )
        return _ok_msg("更新API密钥激活状态成功")

    @quart_app.post("/openapi/api-keys/<uuid:api_key_id>/delete")
    async def async_delete_api_key(api_key_id) -> Response:
        """async 删除 API 密钥。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiKeyService

        await _to_thread(
            _get_service(ApiKeyService).delete_api_key, api_key_id, account
        )
        return _ok_msg("删除API密钥成功")

    @quart_app.post("/assistant-agent/chat")
    async def async_assistant_agent_chat() -> Response:
        """async 与辅助智能体对话（SSE 流式）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import AssistantAgentService

        payload = await request.get_json(force=True, silent=True) or {}
        query = str(payload.get("query") or "").strip()
        if not query:
            return _json_resp(
                code="validate_error",
                message="用户提问query不能为空",
                data={"query": ["用户提问query不能为空"]},
                status=400,
            )
        req = SimpleNamespace(
            query=_field(query),
            conversation_id=_field(str(payload.get("conversation_id") or "")),
            image_urls=_field(payload.get("image_urls") or []),
            confirm_deep_thinking=_field(bool(payload.get("confirm_deep_thinking", False))),
        )
        response = await _to_thread(
            _get_service(AssistantAgentService).chat, req, account
        )
        if _is_sync_iterator(response):
            return _sse_response(response)
        return _ok(response.data)

    @quart_app.post("/assistant-agent/introduction")
    async def async_generate_assistant_agent_introduction() -> Response:
        """async 生成辅助 Agent 个性化欢迎介绍（SSE 流式）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import AssistantAgentService

        response = await _to_thread(
            _get_service(AssistantAgentService).generate_introduction, account
        )
        if _is_sync_iterator(response):
            return _sse_response(response)
        return _ok(response.data)

    @quart_app.post("/openapi/chat")
    async def async_openapi_chat() -> Response:
        """async 开放 Chat 对话接口（SSE 流式）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.openapi_service import OpenAPIService

        payload = await request.get_json(force=True, silent=True) or {}
        raw_app_id = payload.get("app_id")
        try:
            app_id = UUID(str(raw_app_id))
        except (ValueError, TypeError):
            return _json_resp(
                code="validate_error",
                message="应用id不能为空",
                data={"app_id": ["应用id不能为空"]},
                status=400,
            )
        req = SimpleNamespace(
            app_id=_field(app_id),
            end_user_id=_field(str(payload.get("end_user_id") or "")),
            conversation_id=_field(str(payload.get("conversation_id") or "")),
            query=_field(str(payload.get("query") or "")),
            image_urls=_field(payload.get("image_urls") or []),
        )
        response = await _to_thread(_get_service(OpenAPIService).chat, req, account)
        if _is_sync_iterator(response):
            return _sse_response(response)
        return _ok(response.data)
