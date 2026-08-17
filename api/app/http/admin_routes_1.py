"""AdminApp 模块端点的 Quart 异步迁移（路由文件之一）。

实现来源：internal/handler/admin_app_handler.py
路径与 HTTP 方法来源：internal/router/router.py 中 ``self.admin_app_handler.`` 的注册段
"""
from uuid import UUID

from quart import request

from app.http.support import _int_arg

_registered = False


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/admin/apps")
    async def admin_app_list():
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.schema.admin_app_schema import AdminAppPageResp
        from internal.service.admin_app_service import AdminAppService

        result = await a._to_thread(
            a._get_service(AdminAppService).list_apps,
            search=request.args.get("search") or "",
            status=request.args.get("status") or "all",
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
        )
        resp = AdminAppPageResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/apps/<uuid:app_id>")
    async def admin_app_get(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.schema.admin_app_schema import AdminAppResp
        from internal.service.admin_app_service import AdminAppService

        result = await a._to_thread(a._get_service(AdminAppService).get_app, app_id)
        resp = AdminAppResp()
        return a._ok(resp.dump(result))

    @quart_app.patch("/admin/apps/<uuid:app_id>")
    async def admin_app_update(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.schema.admin_app_schema import AdminAppResp
        from internal.service.admin_app_service import AdminAppService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminAppService).update_app,
            app_id,
            status=payload.get("status"),
            is_public=payload.get("is_public") if "is_public" in payload else None,
            agent_metadata=payload.get("agent_metadata") if "agent_metadata" in payload else None,
        )
        resp = AdminAppResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/apps/<uuid:app_id>/offline")
    async def admin_app_offline(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service.admin_app_service import AdminAppService

        await a._to_thread(a._get_service(AdminAppService).offline_app, app_id)
        return a._ok_msg("下架应用成功")

    @quart_app.post("/admin/apps/batch/offline")
    async def admin_app_batch_offline():
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.schema.admin_app_schema import BatchOperationResp
        from internal.service.admin_app_service import AdminAppService

        payload = await request.get_json(force=True, silent=True) or {}
        app_ids = payload.get("app_ids") or []
        if not isinstance(app_ids, list) or len(app_ids) == 0:
            return a._json_resp(
                code="validate_error",
                message="应用ID列表不能为空",
                data={"app_ids": ["应用ID列表不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(AdminAppService).batch_offline_apps,
            [UUID(aid) for aid in app_ids],
        )
        resp = BatchOperationResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/apps/batch/delete")
    async def admin_app_batch_delete():
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.schema.admin_app_schema import BatchOperationResp
        from internal.service.admin_app_service import AdminAppService

        payload = await request.get_json(force=True, silent=True) or {}
        app_ids = payload.get("app_ids") or []
        if not isinstance(app_ids, list) or len(app_ids) == 0:
            return a._json_resp(
                code="validate_error",
                message="应用ID列表不能为空",
                data={"app_ids": ["应用ID列表不能为空"]},
                status=400,
            )
        retention_days = payload.get("retention_days")
        result = await a._to_thread(
            a._get_service(AdminAppService).batch_delete_apps,
            [UUID(aid) for aid in app_ids],
            retention_days=retention_days,
            deleted_by=str(account.id),
        )
        resp = BatchOperationResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/apps")
    async def admin_app_create():
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import AppService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error",
                message="应用名称不能为空",
                data={"name": ["应用名称不能为空"]},
                status=400,
            )
        req = a.SimpleNamespace(
            name=a._field(name),
            icon=a._field(str(payload.get("icon") or "")),
            description=a._field(str(payload.get("description") or "")),
        )
        app = await a._to_thread(
            a._get_service(AppService).create_app,
            req,
            None,
            created_by_admin=str(account.id),
        )
        return a._ok({"id": str(app.id)})

    @quart_app.delete("/admin/apps/<uuid:app_id>")
    async def admin_app_delete(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import AppService

        payload = await request.get_json(force=True, silent=True) or {}
        retention_days = payload.get("retention_days")
        await a._to_thread(
            a._get_service(AppService).delete_app_for_admin,
            app_id,
            retention_days=retention_days,
            deleted_by=str(account.id),
        )
        return a._ok_msg("删除Agent智能体应用成功")

    @quart_app.get("/admin/apps/<uuid:app_id>/draft-app-config")
    async def admin_app_get_draft_app_config(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import AppService

        draft_app_config = await a._to_thread(
            a._get_service(AppService).get_draft_app_config_for_admin, app_id
        )
        return a._ok(draft_app_config)

    @quart_app.post("/admin/apps/<uuid:app_id>/draft-app-config")
    async def admin_app_update_draft_app_config(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import AppService

        draft_app_config = await request.get_json(force=True, silent=True) or {}
        await a._to_thread(
            a._get_service(AppService).update_draft_app_config_for_admin,
            app_id,
            draft_app_config,
        )
        return a._ok_msg("更新应用草稿配置成功")

    @quart_app.get("/admin/apps/<uuid:app_id>/published-config")
    async def admin_app_get_published_config(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import AppService

        published_config = await a._to_thread(
            a._get_service(AppService).get_published_config_for_admin, app_id
        )
        return a._ok(published_config)

    @quart_app.post("/admin/apps/<uuid:app_id>/published-config/regenerate-web-app-token")
    async def admin_app_regenerate_web_app_token(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import AppService

        token = await a._to_thread(
            a._get_service(AppService).regenerate_web_app_token_for_admin, app_id
        )
        return a._ok({"token": token})

    @quart_app.get("/admin/apps/<uuid:app_id>/wechat-config")
    async def admin_app_get_wechat_config(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.schema.platform_schema import GetWechatConfigResp
        from internal.service import PlatformService

        wechat_config = await a._to_thread(
            a._get_service(PlatformService).get_wechat_config_for_admin, app_id
        )
        resp = GetWechatConfigResp()
        return a._ok(resp.dump(wechat_config))

    @quart_app.post("/admin/apps/<uuid:app_id>/wechat-config")
    async def admin_app_update_wechat_config(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import PlatformService

        payload = await request.get_json(force=True, silent=True) or {}
        req = a.SimpleNamespace(
            wechat_app_id=a._field(str(payload.get("wechat_app_id") or "")),
            wechat_app_secret=a._field(str(payload.get("wechat_app_secret") or "")),
            wechat_token=a._field(str(payload.get("wechat_token") or "")),
        )
        await a._to_thread(
            a._get_service(PlatformService).update_wechat_config_for_admin, app_id, req
        )
        return a._ok_msg("更新Agent应用微信公众号配置成功")

    @quart_app.post("/admin/apps/<uuid:app_id>/share-to-square")
    async def admin_app_share_app_to_square(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import PublicAppService

        payload = await request.get_json(force=True, silent=True) or {}
        tags = str(payload.get("tags") or "") or None
        await a._to_thread(
            a._get_service(PublicAppService).share_app_to_square_for_admin, app_id, tags
        )
        return a._ok_msg("应用已共享到广场")

    @quart_app.post("/admin/apps/<uuid:app_id>/unshare-from-square")
    async def admin_app_unshare_app_from_square(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import PublicAppService

        await a._to_thread(
            a._get_service(PublicAppService).unshare_app_from_square_for_admin, app_id
        )
        return a._ok_msg("应用已从广场取消共享")

    @quart_app.get("/admin/apps/tags")
    async def admin_app_get_app_tags():
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.entity.tag_entity import APP_TAG_NAMES, APP_TAG_PRIORITY
        from internal.extension.database_extension import db
        from internal.model import App

        def _collect_tags():
            apps_tags = db.session.query(App.tags).all()
            all_tags = set()
            for (tags,) in apps_tags:
                if tags:
                    all_tags.update(tags)
            return [
                {
                    "id": tag,
                    "name": APP_TAG_NAMES.get(tag, tag),
                    "priority": APP_TAG_PRIORITY.get(tag, 999),
                }
                for tag in sorted(all_tags, key=lambda t: APP_TAG_PRIORITY.get(t, 999))
            ]

        tags = await a._to_thread(_collect_tags)
        return a._ok({"tags": tags})

    @quart_app.post("/admin/apps/<uuid:app_id>/prompt-compare/chat")
    async def admin_app_prompt_compare_chat(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService
        from pkg.response import Response as PkgResponse

        payload = await request.get_json(force=True, silent=True) or {}
        query = str(payload.get("query") or "").strip()
        preset_prompt = str(payload.get("preset_prompt") or "").strip()
        if not query:
            return a._json_resp(
                code="validate_error",
                message="用户提问query不能为空",
                data={"query": ["用户提问query不能为空"]},
                status=400,
            )
        if not preset_prompt:
            return a._json_resp(
                code="validate_error",
                message="提示词不能为空",
                data={"preset_prompt": ["提示词不能为空"]},
                status=400,
            )
        req = a.SimpleNamespace(
            lane_id=a._field(str(payload.get("lane_id") or "")),
            query=a._field(query),
            preset_prompt=a._field(preset_prompt),
            model_config=a._field(payload.get("model_config") or {}),
            history=a._field(payload.get("history") or []),
        )
        response = await a._to_thread(
            a._get_service(AppDebugService).prompt_compare_chat_for_admin, app_id, req
        )
        if a._is_sync_iterator(response):
            return a._sse_response(response)
        if isinstance(response, PkgResponse):
            return a._ok(response.data)
        return a._ok(response)

    @quart_app.post("/admin/apps/<uuid:app_id>/prompt-compare/tasks/<uuid:task_id>/stop")
    async def admin_app_stop_prompt_compare_chat(app_id, task_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        await a._to_thread(
            a._get_service(AppDebugService).stop_prompt_compare_chat_for_admin,
            app_id,
            task_id,
        )
        return a._ok_msg("停止提示词对比调试会话成功")

    @quart_app.get("/admin/apps/<uuid:app_id>/summary")
    async def admin_app_get_debug_summary(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        summary = await a._to_thread(
            a._get_service(AppDebugService).get_debug_conversation_summary_for_admin,
            app_id,
        )
        return a._ok({"summary": summary})

    @quart_app.post("/admin/apps/<uuid:app_id>/summary")
    async def admin_app_update_debug_summary(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        payload = await request.get_json(force=True, silent=True) or {}
        summary = str(payload.get("summary") or "")
        await a._to_thread(
            a._get_service(AppDebugService).update_debug_conversation_summary_for_admin,
            app_id,
            summary,
        )
        return a._ok_msg("更新AI应用长期记忆成功")

    @quart_app.post("/admin/apps/<uuid:app_id>/conversations/delete-debug-conversation")
    async def admin_app_delete_debug_conversation(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        await a._to_thread(
            a._get_service(AppDebugService).delete_debug_conversation_for_admin,
            app_id,
        )
        return a._ok_msg("清空应用调试会话记录成功")

    @quart_app.post("/admin/apps/<uuid:app_id>/conversations/tasks/<uuid:task_id>/stop")
    async def admin_app_stop_debug_chat(app_id, task_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService

        await a._to_thread(
            a._get_service(AppDebugService).stop_debug_chat_for_admin,
            app_id,
            task_id,
        )
        return a._ok_msg("停止应用调试会话成功")

    @quart_app.get("/admin/apps/<uuid:app_id>/conversations/messages")
    async def admin_app_get_debug_conversation_messages(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from dataclasses import asdict as _asdict
        from internal.schema.app_schema import GetDebugConversationMessagesWithPageResp
        from internal.service.app_debug_service import AppDebugService

        req = a.SimpleNamespace(
            current_page=a._field(a._int_arg("current_page", 1), 1),
            page_size=a._field(a._int_arg("page_size", 20), 20),
            created_at=a._field(a._int_arg("created_at", 0), 0),
            conversation_id=a._field(request.args.get("conversation_id"), None),
        )
        messages, paginator = await a._to_thread(
            a._get_service(AppDebugService).get_debug_conversation_messages_with_page_for_admin,
            app_id,
            req,
        )
        resp = GetDebugConversationMessagesWithPageResp(many=True)
        return a._ok({"list": resp.dump(messages), "paginator": _asdict(paginator)})

    @quart_app.post("/admin/apps/<uuid:app_id>/conversations")
    async def admin_app_debug_chat(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service.app_debug_service import AppDebugService
        from pkg.response import Response as PkgResponse

        payload = await request.get_json(force=True, silent=True) or {}
        query = str(payload.get("query") or "").strip()
        if not query:
            return a._json_resp(
                code="validate_error",
                message="用户提问query不能为空",
                data={"query": ["用户提问query不能为空"]},
                status=400,
            )
        req = a.SimpleNamespace(
            query=a._field(query),
            conversation_id=a._field(str(payload.get("conversation_id") or "")),
            image_urls=a._field(payload.get("image_urls") or []),
            confirm_deep_thinking=a._field(bool(payload.get("confirm_deep_thinking", False))),
        )
        response = await a._to_thread(
            a._get_service(AppDebugService).debug_chat_for_admin,
            app_id,
            req,
        )
        if a._is_sync_iterator(response):
            return a._sse_response(response)
        if isinstance(response, PkgResponse):
            return a._ok(response.data)
        return a._ok(response)

    @quart_app.post("/admin/apps/<uuid:app_id>/workflow/debug")
    async def admin_app_debug_workflow(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import AppService, WorkflowAppService

        owner = await a._to_thread(
            a._get_service(AppService).get_app_owner_account_for_admin, app_id
        )
        inputs = (await request.get_json(force=True, silent=True)) or {}
        response = await a._to_thread(
            a._get_service(WorkflowAppService).execute_workflow_stream,
            app_id,
            inputs,
            owner,
        )
        if a._is_sync_iterator(response):
            return a._sse_response(response)
        return a._ok(response)

    @quart_app.get("/admin/apps/<uuid:app_id>/analysis")
    async def admin_app_get_app_analysis(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import AnalysisService

        app_analysis = await a._to_thread(
            a._get_service(AnalysisService).get_app_analysis_for_admin, app_id
        )
        return a._ok(app_analysis)

    @quart_app.get("/admin/apps/<uuid:app_id>/versions")
    async def admin_app_get_versions(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.schema.app_schema import GetPublishHistoriesWithPageResp
        from internal.service import AppService

        versions = await a._to_thread(
            a._get_service(AppService).get_versions_for_admin, app_id
        )
        resp = GetPublishHistoriesWithPageResp(many=True)
        return a._ok({"list": resp.dump(versions)})

    @quart_app.post("/admin/apps/import")
    async def admin_app_import_app():
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import AppService

        body = await request.get_json(force=True, silent=True)
        if not isinstance(body, dict):
            return a._json_resp(
                code="validate_error",
                message="请求体必须是 JSON 对象",
                data={"json_data": ["请求体必须是 JSON 对象"]},
                status=400,
            )
        if isinstance(body.get("json_data"), dict):
            json_data = body["json_data"]
            overwrite_name = bool(body.get("overwrite_name", False))
        elif body.get("format") in {"openagent-app", "yuxin-ai-app"}:
            json_data = body
            overwrite_name = request.args.get("overwrite_name", "").lower() in ("true", "1", "yes")
        else:
            return a._json_resp(
                code="validate_error",
                message="无法识别的导入数据格式，缺少 json_data 字段或 format 字段不正确",
                data={"json_data": ["无法识别的导入数据格式，缺少 json_data 字段或 format 字段不正确"]},
                status=400,
            )
        app = await a._to_thread(
            a._get_service(AppService).import_app_for_admin,
            json_data,
            overwrite_name=overwrite_name,
            created_by_admin=str(account.id),
        )
        return a._ok({"id": str(app.id)})

    @quart_app.get("/admin/apps/<uuid:app_id>/export")
    async def admin_app_export_app(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err

        from internal.service import AppService

        export_data = await a._to_thread(
            a._get_service(AppService).export_app_for_admin, app_id
        )
        return a._ok(export_data)
