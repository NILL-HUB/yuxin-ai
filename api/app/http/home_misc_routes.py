"""杂项路由模块（从 asgi_app.py 拆分）：home/analysis/tool-inventory/language-models/notifications/tags/health/storage/metrics。"""
import logging
from dataclasses import asdict
from types import SimpleNamespace

from quart import Response, request

from app.http import support as _support
from app.http.support import (
    _field,
    _int_arg,
    _json_resp,
    _ok,
    _ok_msg,
    _resolve_account,
    _to_thread,
)
from internal.service.language_model_service import LanguageModelService

_registered = False


def _get_service(cls):
    return _support._get_service(cls)


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/home/intent")
    async def async_get_intent() -> Response:
        """async 获取用户意图识别结果。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.home_schema import GetIntentResp
        from internal.service.home_service import HomeService

        intent_result = await _to_thread(
            _get_service(HomeService).get_user_intent, account
        )
        return _ok(GetIntentResp().dump(intent_result))

    @quart_app.get("/analysis/<uuid:app_id>")
    async def async_get_app_analysis(app_id) -> Response:
        """async 获取应用统计分析。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.analysis_service import AnalysisService

        app_analysis = await _to_thread(
            _get_service(AnalysisService).get_app_analysis, app_id, account
        )
        return _ok(app_analysis)

    @quart_app.get("/tool-inventory")
    async def async_get_tool_inventory() -> Response:
        """async 获取工具清单（candidates + 策略过滤结果）。"""
        raw_account_id = request.args.get("account_id") or ""
        if raw_account_id:
            account, err = await _resolve_account()
            if err is not None:
                return err
            account_id = account.id
        else:
            account_id = None

        if account_id is None:
            return _ok({"candidates": [], "filtered_out_tools": []})

        from internal.service.tool_inventory_service import (
            ToolCandidateCollector,
            ToolPolicyFilter,
            filter_candidates,
            with_runtime_fields,
        )

        collector = _get_service(ToolCandidateCollector)
        policy_filter = _get_service(ToolPolicyFilter)
        candidates = await _to_thread(collector.collect, account_id)
        result = await _to_thread(
            policy_filter.filter,
            candidates,
            account_id=str(account_id),
            agent_pool=request.args.get("agent_pool") or None,
            budget_level=request.args.get("budget_level") or "medium",
            allow_confirmation=request.args.get("allow_confirmation") == "true",
        )
        tool_pool = request.args.get("tool_pool") or ""
        risk_level = request.args.get("risk_level") or ""
        result["candidates"] = with_runtime_fields(
            filter_candidates(
                result["candidates"], tool_pool=tool_pool, risk_level=risk_level
            )
        )
        return _ok(result)

    @quart_app.get("/language-models")
    async def async_get_language_models() -> Response:
        """async 获取全部语言模型提供商。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        return _ok(
            await _to_thread(_get_service(LanguageModelService).get_language_models)
        )

    @quart_app.get("/language-models/<string:provider_name>/icon")
    async def async_get_language_model_icon(provider_name) -> Response:
        """async 获取语言模型提供商图标。"""
        icon, mimetype = await _to_thread(
            _get_service(LanguageModelService).get_language_model_icon, provider_name
        )
        return Response(icon, mimetype=mimetype or "image/png")

    @quart_app.get("/language-models/<string:provider_name>/<string:model_name>")
    async def async_get_language_model(provider_name, model_name) -> Response:
        """async 获取语言模型详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        return _ok(
            await _to_thread(
                _get_service(LanguageModelService).get_language_model,
                provider_name,
                model_name,
            )
        )

    @quart_app.get("/notifications")
    async def async_get_notifications() -> Response:
        """async 获取用户通知列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.entity.agent_notification_entity import AgentNotificationEntity
        from internal.entity.document_index_notification_entity import (
            DocumentIndexNotificationEntity,
        )
        from internal.schema.agent_notification_schema import AgentNotificationSchema
        from internal.schema.document_index_notification_schema import (
            DocumentIndexNotificationSchema,
        )
        from internal.service.notification_service import NotificationService

        page = _int_arg("page", 1)
        limit = _int_arg("limit", 10)
        notification_type = request.args.get("type") or None
        if notification_type not in (None, "document", "agent"):
            return _json_resp(
                code="validate_error", message="通知类型非法", data={"type": ["通知类型非法"]}, status=400
            )

        notifications, total = await _to_thread(
            _get_service(NotificationService).get_user_notifications,
            account.id,
            limit=limit,
            offset=(page - 1) * limit,
            notification_type=notification_type,
        )
        serialized = []
        for notification in notifications:
            if isinstance(notification, AgentNotificationEntity):
                serialized.append(AgentNotificationSchema().dump(notification))
            elif isinstance(notification, DocumentIndexNotificationEntity):
                serialized.append(DocumentIndexNotificationSchema().dump(notification))
        return _ok(
            {
                "list": serialized,
                "paginator": {
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "total_page": (total + limit - 1) // limit if total else 0,
                },
            }
        )

    @quart_app.post("/notifications/<string:notification_id>/read")
    async def async_mark_notification_as_read(notification_id) -> Response:
        """async 标记通知为已读。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.notification_service import NotificationService

        success = await _to_thread(
            _get_service(NotificationService).mark_as_read,
            account.id,
            notification_id,
        )
        if not success:
            return _json_resp(
                code="validate_error",
                message="通知不存在或无权限",
                data={"notification_id": ["通知不存在或无权限"]},
                status=400,
            )
        return _ok_msg("标记成功")

    @quart_app.delete("/notifications/<string:notification_id>")
    async def async_delete_notification(notification_id) -> Response:
        """async 删除通知。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.notification_service import NotificationService

        success = await _to_thread(
            _get_service(NotificationService).delete_notification,
            account.id,
            notification_id,
        )
        if not success:
            return _json_resp(
                code="validate_error",
                message="通知不存在或无权限",
                data={"notification_id": ["通知不存在或无权限"]},
                status=400,
            )
        return _ok_msg("删除成功")

    @quart_app.post("/tags")
    async def async_create_tag() -> Response:
        """async 创建标签。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import TagService

        payload = await request.get_json(force=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error", message="标签名称不能为空", data={"name": ["标签名称不能为空"]}, status=400
            )
        tag = await _to_thread(
            _get_service(TagService).create_tag,
            account_id=account.id,
            name=name,
            description=str(payload.get("description") or ""),
            tag_type=str(payload.get("tag_type") or "custom"),
        )
        return _ok({"id": tag.id})

    @quart_app.post("/tags/<uuid:tag_id>")
    async def async_update_tag(tag_id) -> Response:
        """async 更新标签。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import TagService

        payload = await request.get_json(force=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error", message="标签名称不能为空", data={"name": ["标签名称不能为空"]}, status=400
            )
        tag = await _to_thread(
            _get_service(TagService).update_tag,
            tag_id=tag_id,
            account_id=account.id,
            name=name,
            description=str(payload.get("description") or ""),
        )
        if not tag:
            return _json_resp(code="not_found", message="标签不存在", data=None, status=404)
        return _ok_msg("更新标签成功")

    @quart_app.post("/tags/<uuid:tag_id>/delete")
    async def async_delete_tag(tag_id) -> Response:
        """async 删除标签。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import TagService

        tag = await _to_thread(
            _get_service(TagService).delete_tag, tag_id, account.id
        )
        if not tag:
            return _json_resp(code="not_found", message="标签不存在", data=None, status=404)
        return _ok_msg("删除标签成功")

    @quart_app.get("/tags/<uuid:tag_id>")
    async def async_get_tag(tag_id) -> Response:
        """async 获取标签详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.tag_schema import TagResp
        from internal.service import TagService

        tag = await _to_thread(
            _get_service(TagService).get_tag_by_id, tag_id, account.id
        )
        if not tag:
            return _json_resp(code="not_found", message="标签不存在", data=None, status=404)
        return _ok(TagResp().dump(tag))

    @quart_app.get("/tags")
    async def async_list_tags() -> Response:
        """async 获取标签列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.tag_schema import TagResp
        from internal.service import TagService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            tag_type=_field(request.args.get("tag_type"), None),
            search_word=_field(request.args.get("search_word"), None),
        )
        tags, paginator = await _to_thread(
            _get_service(TagService).get_tags_with_page,
            req=req,
            account_id=account.id,
        )
        resp = TagResp(many=True)
        return _ok({"list": resp.dump(tags), "paginator": asdict(paginator)})

    @quart_app.get("/tags/dimensions")
    async def async_get_tag_dimensions() -> Response:
        """async 获取标签维度。"""
        from internal.schema.tag_schema import GetTagDimensionsResp
        from internal.service import TagService

        return _ok(
            GetTagDimensionsResp().dump(
                {"dimensions": await _to_thread(_get_service(TagService).get_tag_dimensions)}
            )
        )

    @quart_app.get("/tags/hot")
    async def async_get_hot_tags() -> Response:
        """async 获取热门标签。"""
        from internal.schema.tag_schema import GetHotTagsResp
        from internal.service import TagService

        return _ok(
            GetHotTagsResp().dump(
                {"hot_tags": await _to_thread(_get_service(TagService).get_hot_tags)}
            )
        )

    @quart_app.get("/health")
    async def async_health() -> Response:
        """async 健康检查接口（无需认证，探测数据库/缓存等依赖）。"""
        from internal.service.health_service import HealthService

        data = await _to_thread(_get_service(HealthService).check)
        return _ok(data)

    @quart_app.get("/healthz")
    async def async_healthz() -> Response:
        """async 轻量存活检查（不探测外部依赖）。"""
        return _ok({"status": "ok", "service": "llmops-api"})

    @quart_app.get("/ping")
    async def async_ping() -> Response:
        """async 心跳检查。"""
        return _ok({"pong": "success"})

    @quart_app.get("/storage/local/<path:key>")
    async def async_serve_local_storage_file(key) -> Response:
        """async 提供本地存储文件的 HTTP 访问（始终启用，支持运行时切换 local 后端）。"""
        import os.path as _osp

        from quart import send_file
        from internal.service.storage.local_storage_service import _get_local_storage_root

        storage_root = _osp.abspath(await _to_thread(_get_local_storage_root))
        safe_key = _osp.normpath(key).lstrip("/\\")
        if ".." in safe_key.split(_osp.sep):
            return Response("非法路径", status=400)
        file_path = _osp.join(storage_root, safe_key)
        if not _osp.isfile(file_path):
            return Response("文件不存在", status=404)
        download_name = request.args.get("download") or None
        if download_name and "/" in download_name.replace("\\", "/"):
            download_name = _osp.basename(download_name)
        return await send_file(
            file_path,
            as_attachment=download_name is not None,
            attachment_filename=download_name,
        )

    @quart_app.get("/metrics")
    async def async_metrics() -> Response:
        """async Prometheus 指标暴露（无需鉴权）。"""
        from internal.service.memory.metrics import render_metrics

        try:
            body_bytes, content_type = await _to_thread(render_metrics)
            return Response(body_bytes, mimetype=content_type, status=200)
        except Exception:
            logging.exception("渲染 Prometheus 指标失败")
            return Response(b"", mimetype="text/plain", status=500)
