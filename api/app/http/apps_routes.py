"""应用路由模块（从 asgi_app.py 拆分）：/apps*、/my/apps*、/web-apps*。"""
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID

from quart import Response, request

from app.http import support as _support
from app.http.support import (
    _err,
    _field,
    _int_arg,
    _is_sync_iterator,
    _json_resp,
    _ok,
    _ok_msg,
    _resolve_account,
    _resolve_webapp_actor,
    _sse_response,
    _to_thread,
)
from internal.service.app_service import AppService

_registered = False


def _get_service(cls):
    return _support._get_service(cls)


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/my/apps")
    async def async_list_my_apps() -> Response:
        """async 获取我的应用列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.my_app_schema import MyAppListResp
        from internal.service.my_app_service import MyAppService

        apps = await _to_thread(_get_service(MyAppService).list_my_apps, account.id)
        return _ok(MyAppListResp().dump({"list": apps}))

    @quart_app.get("/apps")
    async def async_get_apps_with_page() -> Response:
        """async 获取应用分页列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.app_schema import GetAppsWithPageResp

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            search_word=_field(request.args.get("search_word"), None),
            published_only=_field(request.args.get("published_only") in ("true", "1"), False),
        )
        apps, paginator = await _to_thread(
            _get_service(AppService).get_apps_with_page, req, account
        )
        resp = GetAppsWithPageResp(many=True)
        return _ok({"list": resp.dump(apps), "paginator": asdict(paginator)})

    @quart_app.post("/apps")
    async def async_create_app() -> Response:
        """async 创建应用。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _err("invalid_param", "应用名称不能为空", 400)

        req = SimpleNamespace(
            name=_field(name),
            description=_field(str(payload.get("description") or "")),
            icon=_field(str(payload.get("icon") or "")),
        )
        app = await _to_thread(_get_service(AppService).create_app, req, account)
        return _ok({"id": str(app.id)})

    @quart_app.get("/apps/<uuid:app_id>")
    async def async_get_app(app_id) -> Response:
        """async 获取应用详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.exception import NotFoundException, ForbiddenException
        from internal.schema.app_schema import GetAppResp

        try:
            app = await _to_thread(_get_service(AppService).get_app, app_id, account)
        except (NotFoundException, ForbiddenException) as exc:
            return _err("app_not_found", str(exc), 404)
        return _ok(GetAppResp().dump(app))

    @quart_app.post("/apps/<uuid:app_id>")
    async def async_update_app(app_id) -> Response:
        """async 更新应用。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        await _to_thread(_get_service(AppService).update_app, app_id, account, **payload)
        return _ok_msg("修改Agent智能体应用成功")

    @quart_app.post("/apps/<uuid:app_id>/delete")
    async def async_delete_app(app_id) -> Response:
        """async 删除应用。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        await _to_thread(_get_service(AppService).delete_app, app_id, account)
        return _ok_msg("删除Agent智能体应用成功")

    @quart_app.post("/apps/<uuid:app_id>/copy")
    async def async_copy_app(app_id) -> Response:
        """async 拷贝应用。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        app = await _to_thread(_get_service(AppService).copy_app, app_id, account)
        return _ok({"id": str(app.id)})

    @quart_app.get("/apps/<uuid:app_id>/draft-app-config")
    async def async_get_draft_app_config(app_id) -> Response:
        """async 获取应用草稿配置。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        config = await _to_thread(
            _get_service(AppService).get_draft_app_config, app_id, account
        )
        return _ok(config)

    @quart_app.post("/apps/<uuid:app_id>/draft-app-config")
    async def async_update_draft_app_config(app_id) -> Response:
        """async 更新应用草稿配置。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        config = await request.get_json(force=True) or {}
        await _to_thread(
            _get_service(AppService).update_draft_app_config, app_id, config, account
        )
        return _ok_msg("更新应用草稿配置成功")

    @quart_app.post("/apps/<uuid:app_id>/publish")
    async def async_publish(app_id) -> Response:
        """async 发布应用配置。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        share_to_square = request.args.get("share_to_square", "false").lower() == "true"
        await _to_thread(
            _get_service(AppService).publish_draft_app_config,
            app_id,
            account,
            share_to_square=share_to_square,
        )
        return _ok_msg("发布/更新应用配置成功")

    @quart_app.post("/apps/<uuid:app_id>/cancel-publish")
    async def async_cancel_publish(app_id) -> Response:
        """async 取消发布应用配置。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        await _to_thread(
            _get_service(AppService).cancel_publish_app_config, app_id, account
        )
        return _ok_msg("取消发布应用配置成功")

    @quart_app.get("/apps/<uuid:app_id>/publish-histories")
    async def async_get_publish_histories_with_page(app_id) -> Response:
        """async 获取应用发布历史分页。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.app_schema import GetPublishHistoriesWithPageResp

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
        )
        versions, paginator = await _to_thread(
            _get_service(AppService).get_publish_histories_with_page, app_id, req, account
        )
        resp = GetPublishHistoriesWithPageResp(many=True)
        return _ok({"list": resp.dump(versions), "paginator": asdict(paginator)})

    @quart_app.get("/apps/<uuid:app_id>/versions")
    async def async_get_versions(app_id) -> Response:
        """async 获取应用版本对比数据。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.app_schema import GetPublishHistoriesWithPageResp

        versions = await _to_thread(
            _get_service(AppService).get_versions, app_id, account
        )
        resp = GetPublishHistoriesWithPageResp(many=True)
        return _ok({"list": resp.dump(versions)})

    @quart_app.post("/apps/<uuid:app_id>/fallback-history")
    async def async_fallback_history_to_draft(app_id) -> Response:
        """async 回退历史配置至草稿。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        raw_version_id = payload.get("app_config_version_id") or request.args.get("app_config_version_id")
        try:
            version_id = UUID(str(raw_version_id))
        except (ValueError, TypeError):
            return _err("invalid_param", "app_config_version_id 参数无效", 400)

        await _to_thread(
            _get_service(AppService).fallback_history_to_draft,
            app_id,
            version_id,
            account,
        )
        return _ok_msg("回退历史配置至草稿成功")

    @quart_app.get("/apps/<uuid:app_id>/summary")
    async def async_get_debug_conversation_summary(app_id) -> Response:
        """async 获取调试会话长期记忆。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        summary = await _to_thread(
            _get_service(AppDebugService).get_debug_conversation_summary, app_id, account
        )
        return _ok({"summary": summary})

    @quart_app.post("/apps/<uuid:app_id>/summary")
    async def async_update_debug_conversation_summary(app_id) -> Response:
        """async 更新调试会话长期记忆。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        payload = await request.get_json(force=True) or {}
        summary = str(payload.get("summary") or "")
        await _to_thread(
            _get_service(AppDebugService).update_debug_conversation_summary,
            app_id,
            summary,
            account,
        )
        return _ok_msg("更新AI应用长期记忆成功")

    @quart_app.post("/apps/<uuid:app_id>/conversations/delete-debug-conversation")
    async def async_delete_debug_conversation(app_id) -> Response:
        """async 清空应用调试会话记录。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        await _to_thread(
            _get_service(AppDebugService).delete_debug_conversation, app_id, account
        )
        return _ok_msg("清空应用调试会话记录成功")

    @quart_app.post("/apps/<uuid:app_id>/conversations/tasks/<uuid:task_id>/stop")
    async def async_stop_debug_chat(app_id, task_id) -> Response:
        """async 停止应用调试会话。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        await _to_thread(
            _get_service(AppDebugService).stop_debug_chat, app_id, task_id, account
        )
        return _ok_msg("停止应用调试会话成功")

    @quart_app.post("/apps/<uuid:app_id>/prompt-compare/tasks/<uuid:task_id>/stop")
    async def async_stop_prompt_compare_chat(app_id, task_id) -> Response:
        """async 停止提示词对比调试会话。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        await _to_thread(
            _get_service(AppDebugService).stop_prompt_compare_chat, app_id, task_id, account
        )
        return _ok_msg("停止提示词对比调试会话成功")

    @quart_app.get("/apps/<uuid:app_id>/conversations/messages")
    async def async_get_debug_conversation_messages_with_page(app_id) -> Response:
        """async 获取应用调试会话消息分页。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.app_schema import GetDebugConversationMessagesWithPageResp
        from internal.service.app_debug_service import AppDebugService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            created_at=_field(request.args.get("created_at"), None),
        )
        messages, paginator = await _to_thread(
            _get_service(AppDebugService).get_debug_conversation_messages_with_page,
            app_id,
            req,
            account,
        )
        resp = GetDebugConversationMessagesWithPageResp(many=True)
        return _ok({"list": resp.dump(messages), "paginator": asdict(paginator)})

    @quart_app.get("/apps/<uuid:app_id>/published-config")
    async def async_get_published_config(app_id) -> Response:
        """async 获取应用发布配置。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        config = await _to_thread(
            _get_service(AppService).get_published_config, app_id, account
        )
        return _ok(config)

    @quart_app.post("/apps/<uuid:app_id>/published-config/regenerate-web-app-token")
    async def async_regenerate_web_app_token(app_id) -> Response:
        """async 重新生成 WebApp 凭证。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        token = await _to_thread(
            _get_service(AppService).regenerate_web_app_token, app_id, account
        )
        return _ok({"token": token})

    @quart_app.post("/apps/<uuid:app_id>/regenerate-icon")
    async def async_regenerate_icon(app_id) -> Response:
        """async 重新生成应用图标。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        icon_url = await _to_thread(
            _get_service(AppService).regenerate_icon, app_id, account
        )
        return _ok({"icon": icon_url})

    @quart_app.post("/apps/generate-icon-preview")
    async def async_generate_icon_preview() -> Response:
        """async 生成图标预览。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        name = str(payload.get("name") or "").strip()
        description = str(payload.get("description") or "").strip()
        if not name:
            return _err("invalid_param", "应用名称不能为空", 400)

        icon_url = await _to_thread(
            _get_service(AppService).generate_icon_preview, name, description
        )
        return _ok({"icon": icon_url})

    @quart_app.post("/apps/import")
    async def async_import_app() -> Response:
        """async 导入应用 JSON。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        body = await request.get_json(force=True, silent=True)
        if not isinstance(body, dict):
            return _err("invalid_param", "请求体必须是 JSON 对象", 400)

        if isinstance(body.get("json_data"), dict):
            json_data = body["json_data"]
            overwrite_name = bool(body.get("overwrite_name", False))
        elif body.get("format") in {"openagent-app", "yuxin-ai-app"}:
            json_data = body
            overwrite_name = request.args.get("overwrite_name", "").lower() in ("true", "1", "yes")
        else:
            return _err("invalid_param", "无法识别的导入数据格式", 400)

        app = await _to_thread(
            _get_service(AppService).import_app,
            json_data,
            account.id,
            overwrite_name=overwrite_name,
        )
        return _ok({"id": str(app.id)})

    @quart_app.get("/apps/<uuid:app_id>/export")
    async def async_export_app(app_id) -> Response:
        """async 导出应用 JSON。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        export_data = await _to_thread(
            _get_service(AppService).export_app, app_id, account
        )
        return _ok(export_data)

    @quart_app.post("/apps/<uuid:app_id>/conversations")
    async def async_debug_chat(app_id) -> Response:
        """async 应用调试会话（SSE 流式）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

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
            _get_service(AppDebugService).debug_chat, app_id, req, account
        )
        if _is_sync_iterator(response):
            return _sse_response(response)
        return _ok(response.data)

    @quart_app.post("/apps/<uuid:app_id>/workflow/debug")
    async def async_debug_workflow_app(app_id) -> Response:
        """async workflow 应用调试（SSE 流式）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowAppService

        inputs = (await request.get_json(force=True, silent=True)) or {}
        response = await _to_thread(
            _get_service(WorkflowAppService).execute_workflow_stream,
            app_id,
            inputs,
            account,
        )
        if _is_sync_iterator(response):
            return _sse_response(response)
        return _ok(response.data)

    @quart_app.post("/apps/<uuid:app_id>/prompt-compare/chat")
    async def async_prompt_compare_chat(app_id) -> Response:
        """async 提示词对比调试（SSE 流式）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        payload = await request.get_json(force=True, silent=True) or {}
        query = str(payload.get("query") or "").strip()
        preset_prompt = str(payload.get("preset_prompt") or "").strip()
        if not query:
            return _json_resp(
                code="validate_error",
                message="用户提问query不能为空",
                data={"query": ["用户提问query不能为空"]},
                status=400,
            )
        if not preset_prompt:
            return _json_resp(
                code="validate_error",
                message="提示词不能为空",
                data={"preset_prompt": ["提示词不能为空"]},
                status=400,
            )
        req = SimpleNamespace(
            lane_id=_field(str(payload.get("lane_id") or "")),
            query=_field(query),
            preset_prompt=_field(preset_prompt),
            model_config=_field(payload.get("model_config") or {}),
            history=_field(payload.get("history") or []),
        )
        response = await _to_thread(
            _get_service(AppDebugService).prompt_compare_chat, app_id, req, account
        )
        if _is_sync_iterator(response):
            return _sse_response(response)
        return _ok(response.data)

    @quart_app.post("/my/apps/<uuid:app_id>/chat")
    async def async_my_app_chat(app_id) -> Response:
        """async 我的应用会话（SSE 流式）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService
        from internal.service.my_app_service import MyAppService

        await _to_thread(_get_service(MyAppService).get_assigned_app, account.id, app_id)
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
            _get_service(AppDebugService).debug_chat, app_id, req, account
        )
        if _is_sync_iterator(response):
            return _sse_response(response)
        return _ok(response.data)

    @quart_app.get("/web-apps/<string:token>")
    async def async_get_web_app(token) -> Response:
        """async 根据 token 获取 WebApp 基础信息。"""
        from internal.service import WebAppService

        account = None
        raw_account_id = request.args.get("account_id") or ""
        if raw_account_id:
            account, err = await _resolve_account()
            if err is not None:
                return err
        actor, _ = _resolve_webapp_actor()
        if account is not None:
            actor = account
        resp = await _to_thread(_get_service(WebAppService).get_web_app_info, token)
        return _ok(resp)

    @quart_app.post("/web-apps/<string:token>/chat")
    async def async_web_app_chat(token) -> Response:
        """async WebApp 对话（SSE 流式）。"""
        from internal.service import WebAppService

        account = None
        raw_account_id = request.args.get("account_id") or ""
        if raw_account_id:
            account, err = await _resolve_account()
            if err is not None:
                return err
        actor, _ = _resolve_webapp_actor()
        if account is not None:
            actor = account

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
            _get_service(WebAppService).web_app_chat, token, req, actor
        )
        if _is_sync_iterator(response):
            return _sse_response(response)
        return _ok(response.data)

    @quart_app.post("/web-apps/<string:token>/chat/<uuid:task_id>/stop")
    async def async_stop_web_app_chat(token, task_id) -> Response:
        """async 停止 WebApp 对话。"""
        from internal.service import WebAppService

        actor, _ = _resolve_webapp_actor()
        await _to_thread(
            _get_service(WebAppService).stop_web_app_chat, token, task_id, actor
        )
        return _ok_msg("停止WebApp会话成功")

    @quart_app.get("/web-apps/<string:token>/conversations")
    async def async_get_web_app_conversations(token) -> Response:
        """async 获取 WebApp 会话列表。"""
        from internal.schema.web_app_schema import GetConversationsResp
        from internal.service import WebAppService

        actor, _ = _resolve_webapp_actor()

        is_pinned_raw = request.args.get("is_pinned")
        is_pinned = is_pinned_raw in ("true", "1") if is_pinned_raw else None
        conversation = await _to_thread(
            _get_service(WebAppService).get_conversations,
            token,
            is_pinned,
            actor,
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
        )
        resp = GetConversationsResp(many=True)
        return _ok(resp.dump(conversation))
