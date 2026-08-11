"""Admin 管理端点 Quart 异步迁移（批次 8）。

将 internal/router/router.py 中以下 handler 注册的 Flask 同步端点迁移为
Quart async 端点（挂载到 asgi_app.quart_app）：
- admin_prompt_template_handler      -> PromptSyncService / SystemPromptLibraryService
- admin_builtin_tool_handler        -> BuiltinToolService（get_tool/update_tool 走模块级 DB helper）
- admin_public_ai_feature_handler   -> PublicAIFeatureService（models/update 走模块级 DB helper）
- admin_app_assignment_handler      -> AdminAppAssignmentService
- admin_routing_log_handler         -> RoutingLogService / RoutingLogRetentionService
- admin_resource_entry_handler      -> AdminToolGovernanceService / McpService / SkillService
- admin_recycle_bin_handler         -> RecycleBinService
- admin_cost_stats_handler          -> CostStatsService
- admin_orchestration_flag_handler  -> OrchestrationFeatureFlagService
- admin_audit_log_handler           -> AuditLogService
- admin_orchestration_release_handler -> OrchestrationReleaseCheckService
- admin_upload_file_handler         -> CosService

每个端点函数体内第一行 ``from app.http import asgi_app as a``，
以规避模块导入阶段的循环依赖。管理员操作者上下文通过
``a._resolve_account()`` 解析（account.id 作为操作者 ID）。
"""
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID

from quart import request

from internal.model.builtin_tool import BuiltinTool, BuiltinToolProvider

_registered = False


def to_timestamp(dt) -> int:
    """将 datetime 转换为秒级时间戳（兼容 None）。"""
    if dt is None:
        return 0
    import datetime as _dt
    if isinstance(dt, _dt.datetime):
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return int(dt)


def tool_to_dict(tool: BuiltinTool, provider: BuiltinToolProvider | None = None) -> dict:
    """将 BuiltinTool 模型序列化为 dict（原 admin_builtin_tool_handler._tool_to_dict）。"""
    result = {
        "id": str(tool.id),
        "provider_id": str(tool.provider_id),
        "name": tool.name,
        "label": tool.label,
        "description": tool.description,
        "params": tool.params or [],
        "task_keywords": tool.task_keywords or [],
        "python_module": tool.python_module,
        "source": tool.source,
        "enabled": tool.enabled,
        "updated_at": to_timestamp(tool.updated_at),
        "created_at": to_timestamp(tool.created_at),
    }
    if provider is not None:
        result["provider"] = {
            "id": str(provider.id),
            "name": provider.name,
            "label": provider.label,
            "description": provider.description,
            "icon": provider.icon,
            "background": provider.background,
            "category": provider.category,
        }
    return result


def _builtin_tool_detail(tool_id):
    """按 DB 主键读取 builtin 工具详情（与 admin_builtin_tool_handler.get_tool 一致）。

    工具不存在时返回 None。DB 访问在 Flask app context 中执行。
    """
    from app.http import asgi_app as a
    from internal.extension.database_extension import db
    from internal.model.builtin_tool import BuiltinTool, BuiltinToolProvider

    with a.flask_app.app_context():
        tool = db.session.get(BuiltinTool, tool_id)
        if tool is None:
            return None
        provider = db.session.get(BuiltinToolProvider, tool.provider_id)
        return tool_to_dict(tool, provider)


def _builtin_tool_update(tool_id, data):
    """编辑 builtin 工具元数据（与 admin_builtin_tool_handler.update_tool 一致）。

    校验失败时返回 ``{"_errors": {...}}``；工具不存在时抛 NotFoundException。
    """
    from app.http import asgi_app as a
    from internal.exception import NotFoundException
    from internal.extension.database_extension import db
    from internal.model.builtin_tool import BuiltinTool, BuiltinToolProvider

    with a.flask_app.app_context():
        tool = db.session.get(BuiltinTool, tool_id)
        if tool is None:
            raise NotFoundException(f"builtin 工具 {tool_id} 不存在")

        allowed_fields = {"label", "description", "task_keywords", "icon"}
        provided_fields = set(data.keys()) & allowed_fields
        if not provided_fields:
            return {
                "_errors": {"form": ["至少提供 label/description/task_keywords/icon 中的一个字段"]}
            }
        if "task_keywords" in data:
            kw = data["task_keywords"]
            if not isinstance(kw, list) or not all(isinstance(x, str) for x in kw):
                return {"_errors": {"task_keywords": ["task_keywords 必须是字符串列表"]}}
        if "label" in data and not isinstance(data["label"], str):
            return {"_errors": {"label": ["label 必须是字符串"]}}
        if "description" in data and not isinstance(data["description"], str):
            return {"_errors": {"description": ["description 必须是字符串"]}}
        if "icon" in data and not isinstance(data["icon"], str):
            return {"_errors": {"icon": ["icon 必须是字符串"]}}

        if "label" in data:
            tool.label = data["label"]
        if "description" in data:
            tool.description = data["description"]
        if "task_keywords" in data:
            tool.task_keywords = data["task_keywords"]
        if "icon" in data:
            provider = db.session.get(BuiltinToolProvider, tool.provider_id)
            if provider is None:
                raise NotFoundException("工具对应的 provider 不存在")
            provider.icon = data["icon"]

        db.session.commit()
        db.session.refresh(tool)
        provider = db.session.get(BuiltinToolProvider, tool.provider_id)
        return tool_to_dict(tool, provider)


def _list_available_models(model_type):
    """列出可选模型池配置（与 admin_public_ai_feature_handler.list_available_models 一致）。"""
    from app.http import asgi_app as a
    from internal.extension.database_extension import db
    from internal.model.model_pool_entity import ModelPoolConfig

    with a.flask_app.app_context():
        query = db.session.query(ModelPoolConfig).filter_by(status="active")
        if model_type:
            # 兼容历史数据：功能的 model_type 与模型池类型存在别名差异时，
            # 仍把可用的同族模型列出来，避免下拉框为空导致无法配置。
            aliases = {
                "image": {"image", "image_generation", "text_to_image"},
                "audio": {"audio", "speech_to_text", "tts", "asr"},
            }
            model_types = {model_type}
            model_types.update(aliases.get(model_type, set()))
            query = query.filter(ModelPoolConfig.model_type.in_(list(model_types)))
        models = query.order_by(
            ModelPoolConfig.provider.asc(),
            ModelPoolConfig.model_name.asc(),
        ).all()
        return [
            {
                "id": str(m.id),
                "label": f"{m.provider} / {m.model_name} ({m.model_type}, {m.tier})",
                "provider": m.provider,
                "model_name": m.model_name,
                "model_type": m.model_type,
                "tier": m.tier,
            }
            for m in models
        ]


def _update_public_ai_feature(feature_key, payload):
    """更新公共 AI 功能配置（与 admin_public_ai_feature_handler.update_feature 一致）。

    功能不存在时抛 NotFoundException；模型配置不存在时抛 FailException。
    """
    from app.http import asgi_app as a
    from internal.exception import FailException, NotFoundException
    from internal.extension.database_extension import db
    from internal.model import PublicAIFeatureConfig
    from internal.model.model_pool_entity import ModelPoolConfig

    with a.flask_app.app_context():
        record = (
            db.session.query(PublicAIFeatureConfig)
            .filter_by(feature_key=feature_key)
            .first()
        )
        if record is None:
            raise NotFoundException(f"功能配置不存在: {feature_key}")

        model_config_id = str(payload.get("model_config_id") or "").strip()
        if model_config_id:
            model = db.session.query(ModelPoolConfig).filter_by(id=model_config_id).first()
            if model is None:
                raise FailException(f"模型配置不存在: {model_config_id}")
            record.model_config_id = model_config_id
        else:
            record.model_config_id = None

        # BooleanField("enabled", default=True)：未显式传 enabled 时视为 True
        enabled_value = payload.get("enabled")
        if enabled_value is None:
            enabled_value = True
        record.enabled = bool(enabled_value)
        if payload.get("fallback_tier"):
            record.fallback_tier = payload["fallback_tier"]
        billable_value = payload.get("billable")
        if billable_value is not None:
            record.billable = bool(billable_value)

        db.session.commit()
        db.session.refresh(record)
        return record


def register_routes(quart_app):
    """把批次 8 的 Admin 端点注册到 quart_app（幂等，重复调用直接返回）。"""
    global _registered
    if _registered:
        return
    _registered = True

    def _int_arg(name, default):
        raw = request.args.get(name)
        try:
            return int(raw) if raw not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def _pagination_args():
        try:
            current_page = max(int(request.args.get("current_page", 1)), 1)
        except (TypeError, ValueError):
            current_page = 1
        try:
            page_size = max(min(int(request.args.get("page_size", 20)), 50), 1)
        except (TypeError, ValueError):
            page_size = 20
        keyword = (request.args.get("keyword") or "").strip()
        return current_page, page_size, keyword

    # ------------------------------------------------------------------
    # admin_prompt_template_handler -> PromptSyncService / SystemPromptLibraryService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/prompt-templates")
    async def admin_prompt_template_list():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_prompt_template_schema import PromptTemplateListSchema
        from internal.service.prompt_sync_service import PromptSyncService
        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        category = (request.args.get("category") or "").strip() or None
        items = await a._to_thread(a._get_service(PromptSyncService).list_prompts, category=category)
        items += await a._to_thread(
            a._get_service(SystemPromptLibraryService).list_managed_prompts, category=category
        )
        return a._ok(PromptTemplateListSchema().dump({"items": items}))

    @quart_app.get("/admin/prompt-templates/<string:prompt_key>")
    async def admin_prompt_template_get(prompt_key):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_prompt_template_schema import PromptTemplateDetailSchema
        from internal.service.prompt_sync_service import PromptSyncService
        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        yaml_prompts = await a._to_thread(
            a._get_service(SystemPromptLibraryService).load_yaml_prompts
        )
        if prompt_key in yaml_prompts:
            detail = await a._to_thread(
                a._get_service(SystemPromptLibraryService).get_managed_prompt_detail, prompt_key
            )
        else:
            detail = await a._to_thread(
                a._get_service(PromptSyncService).get_prompt_detail, prompt_key
            )
        if detail is None:
            return a._json_resp(code="not_found", message="Prompt 模板不存在", status=404)
        return a._ok(PromptTemplateDetailSchema().dump(detail))

    @quart_app.patch("/admin/prompt-templates/<string:prompt_key>")
    async def admin_prompt_template_update(prompt_key):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_prompt_template_schema import PromptTemplateDetailSchema
        from internal.service.prompt_sync_service import PromptSyncService
        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        payload = await request.get_json(force=True, silent=True) or {}
        content = payload.get("content")
        description = payload.get("description")
        enabled = payload.get("enabled")

        yaml_prompts = await a._to_thread(
            a._get_service(SystemPromptLibraryService).load_yaml_prompts
        )
        if prompt_key in yaml_prompts:
            result = await a._to_thread(
                a._get_service(SystemPromptLibraryService).update_managed_prompt,
                prompt_key,
                content=content,
                description=description,
                enabled=enabled,
            )
        else:
            result = await a._to_thread(
                a._get_service(PromptSyncService).update_prompt,
                prompt_key,
                content=content,
                description=description,
                enabled=enabled,
            )
        if result is None:
            return a._json_resp(code="not_found", message="Prompt 模板不存在", status=404)
        return a._ok(PromptTemplateDetailSchema().dump(result))

    @quart_app.post("/admin/prompt-templates/<string:prompt_key>/reset")
    async def admin_prompt_template_reset(prompt_key):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_prompt_template_schema import PromptTemplateDetailSchema
        from internal.service.prompt_sync_service import PromptSyncService
        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        yaml_prompts = await a._to_thread(
            a._get_service(SystemPromptLibraryService).load_yaml_prompts
        )
        if prompt_key in yaml_prompts:
            result = await a._to_thread(
                a._get_service(SystemPromptLibraryService).reset_managed_prompt, prompt_key
            )
        else:
            result = await a._to_thread(
                a._get_service(PromptSyncService).reset_prompt, prompt_key
            )
        if result is None:
            return a._json_resp(code="not_found", message="Prompt 模板不存在", status=404)
        return a._ok(PromptTemplateDetailSchema().dump(result))

    @quart_app.delete("/admin/prompt-templates/<string:prompt_key>")
    async def admin_prompt_template_delete(prompt_key):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        yaml_prompts = await a._to_thread(
            a._get_service(SystemPromptLibraryService).load_yaml_prompts
        )
        if prompt_key not in yaml_prompts:
            return a._json_resp(
                code="validate_error",
                message="该提示词为 prompt_template 表来源，不支持删除",
                data={"prompt_key": ["该提示词为 prompt_template 表来源，不支持删除"]},
                status=400,
            )
        payload = await request.get_json(force=True, silent=True) or {}
        deleted = await a._to_thread(
            a._get_service(SystemPromptLibraryService).delete_managed_prompt,
            prompt_key,
            deleted_by=account.id,
            retention_days=payload.get("retention_days"),
        )
        if not deleted:
            return a._json_resp(code="not_found", message="Prompt 模板不存在", status=404)
        return a._ok({"prompt_key": prompt_key})

    # ------------------------------------------------------------------
    # admin_builtin_tool_handler -> BuiltinToolService（详情/编辑走模块级 DB helper）
    # ------------------------------------------------------------------
    @quart_app.get("/admin/builtin-tools")
    async def admin_builtin_tools():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import BuiltinToolService

        result = await a._to_thread(a._get_service(BuiltinToolService).get_builtin_tools)
        return a._ok(result)

    @quart_app.get("/admin/builtin-tools/categories")
    async def admin_builtin_tool_categories():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import BuiltinToolService

        result = await a._to_thread(a._get_service(BuiltinToolService).get_categories)
        return a._ok(result)

    @quart_app.get("/admin/builtin-tools/<uuid:tool_id>")
    async def admin_builtin_tool_detail(tool_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        result = await a._to_thread(_builtin_tool_detail, tool_id)
        if result is None:
            return a._json_resp(
                code="not_found", message=f"builtin 工具 {tool_id} 不存在", status=404
            )
        return a._ok(result)

    @quart_app.patch("/admin/builtin-tools/<uuid:tool_id>")
    async def admin_builtin_tool_update(tool_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.exception import NotFoundException

        data = await request.get_json(force=True, silent=True) or {}
        try:
            result = await a._to_thread(_builtin_tool_update, tool_id, data)
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        if isinstance(result, dict) and "_errors" in result:
            errors = result["_errors"]
            first_msg = next(iter(errors.values()))[0]
            return a._json_resp(code="validate_error", message=first_msg, data=errors, status=400)
        return a._ok(result)

    # ------------------------------------------------------------------
    # admin_public_ai_feature_handler -> PublicAIFeatureService（models/update 走模块级 DB helper）
    # ------------------------------------------------------------------
    @quart_app.get("/admin/public-ai-features")
    async def admin_public_ai_feature_list():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_public_ai_feature_schema import PublicAIFeatureListSchema
        from internal.service.public_ai_feature_service import PublicAIFeatureService

        category = (request.args.get("category") or "").strip()
        enabled = (request.args.get("enabled") or "").strip()
        model_type = (request.args.get("model_type") or "").strip()
        billable = (request.args.get("billable") or "").strip().lower()
        deprecated = (request.args.get("deprecated") or "").strip().lower()

        items = await a._to_thread(a._get_service(PublicAIFeatureService).list_all_features)
        if category:
            items = [item for item in items if item.feature_category == category]
        if enabled == "true":
            items = [item for item in items if item.enabled]
        elif enabled == "false":
            items = [item for item in items if not item.enabled]
        if model_type:
            items = [item for item in items if item.model_type == model_type]
        if billable in ("true", "false"):
            items = [item for item in items if bool(item.billable) == (billable == "true")]
        if deprecated in ("true", "false"):
            items = [item for item in items if bool(item.deprecated) == (deprecated == "true")]
        return a._ok(PublicAIFeatureListSchema().dump({"items": items, "total": len(items)}))

    @quart_app.get("/admin/public-ai-features/models")
    async def admin_public_ai_feature_models():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        model_type = (request.args.get("model_type") or "").strip()
        items = await a._to_thread(_list_available_models, model_type)
        return a._ok({"items": items})

    @quart_app.get("/admin/public-ai-features/<string:feature_key>")
    async def admin_public_ai_feature_get(feature_key):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_public_ai_feature_schema import PublicAIFeatureItemSchema
        from internal.service.public_ai_feature_service import PublicAIFeatureService

        record = await a._to_thread(
            a._get_service(PublicAIFeatureService).get_feature_config, feature_key
        )
        if record is None:
            return a._json_resp(
                code="not_found", message=f"功能配置不存在: {feature_key}", status=404
            )
        return a._ok(PublicAIFeatureItemSchema().dump(record))

    @quart_app.patch("/admin/public-ai-features/<string:feature_key>")
    async def admin_public_ai_feature_update(feature_key):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.exception import FailException, NotFoundException
        from internal.schema.admin_public_ai_feature_schema import PublicAIFeatureItemSchema

        payload = await request.get_json(force=True, silent=True) or {}
        try:
            record = await a._to_thread(_update_public_ai_feature, feature_key, payload)
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        except FailException as exc:
            return a._json_resp(code="fail", message=str(exc), status=400)
        return a._ok(PublicAIFeatureItemSchema().dump(record))

    # ------------------------------------------------------------------
    # admin_app_assignment_handler -> AdminAppAssignmentService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/users/<uuid:account_id>/app-assignments")
    async def admin_app_assignment_list(account_id):
        from app.http import asgi_app as a

        operator, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_app_assignment_schema import AppAssignmentListResp
        from internal.service.admin_app_assignment_service import AdminAppAssignmentService

        result = await a._to_thread(
            a._get_service(AdminAppAssignmentService).list_assignments, account_id
        )
        return a._ok(AppAssignmentListResp().dump(result))

    @quart_app.post("/admin/users/<uuid:account_id>/app-assignments")
    async def admin_app_assignment_assign(account_id):
        from app.http import asgi_app as a

        operator, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_app_assignment_schema import AssignAppsResp
        from internal.service.admin_app_assignment_service import AdminAppAssignmentService

        payload = await request.get_json(force=True, silent=True) or {}
        app_ids = payload.get("app_ids") or []
        if not isinstance(app_ids, list) or not app_ids:
            return a._json_resp(
                code="validate_error",
                message="应用 ID 列表不能为空",
                data={"app_ids": ["应用 ID 列表不能为空"]},
                status=400,
            )
        try:
            app_ids = [UUID(str(app_id)) for app_id in app_ids]
        except (TypeError, ValueError):
            return a._json_resp(
                code="validate_error",
                message="应用 ID 格式错误",
                data={"app_ids": ["应用 ID 格式错误"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(AdminAppAssignmentService).assign_apps,
            account_id,
            app_ids,
            operator_id=operator.id,
            ip=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
            user_agent=request.headers.get("User-Agent", ""),
        )
        return a._ok(AssignAppsResp().dump(result))

    @quart_app.post("/admin/users/<uuid:account_id>/app-assignments/<uuid:assignment_id>/revoke")
    async def admin_app_assignment_revoke(account_id, assignment_id):
        from app.http import asgi_app as a

        operator, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_app_assignment_schema import AppAssignmentResp
        from internal.service.admin_app_assignment_service import AdminAppAssignmentService

        result = await a._to_thread(
            a._get_service(AdminAppAssignmentService).revoke_assignment,
            account_id,
            assignment_id,
            operator_id=operator.id,
            ip=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
            user_agent=request.headers.get("User-Agent", ""),
        )
        return a._ok(AppAssignmentResp().dump(result))

    # ------------------------------------------------------------------
    # admin_routing_log_handler -> RoutingLogService / RoutingLogRetentionService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/routing-logs")
    async def admin_routing_log_list():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_routing_log_schema import RoutingLogPageResp
        from internal.service.routing_log_service import RoutingLogService

        raw_account_id = request.args.get("account_id") or ""
        try:
            account_id = UUID(raw_account_id) if raw_account_id else None
        except (TypeError, ValueError):
            return a._json_resp(
                code="validate_error",
                message="account_id 参数无效",
                data={"account_id": ["account_id 参数无效"]},
                status=400,
            )

        result = await a._to_thread(
            a._get_service(RoutingLogService).page,
            page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
            account_id=account_id,
            status=request.args.get("status") or None,
            agent_id=request.args.get("agent_id") or None,
            agent_pool=request.args.get("agent_pool") or None,
            tool_name=request.args.get("tool_name") or None,
            tool_pool=request.args.get("tool_pool") or None,
            model_id=request.args.get("model_id") or None,
            key_id=request.args.get("key_id") or None,
            start_at=request.args.get("start_at") or None,
            end_at=request.args.get("end_at") or None,
        )
        return a._ok(RoutingLogPageResp().dump(result))

    @quart_app.get("/admin/routing-logs/retention")
    async def admin_routing_log_retention_get():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_routing_log_schema import RoutingLogRetentionResp
        from internal.service.routing_log_retention_service import RoutingLogRetentionService

        result = await a._to_thread(a._get_service(RoutingLogRetentionService).describe)
        return a._ok(RoutingLogRetentionResp().dump(result))

    @quart_app.post("/admin/routing-logs/retention")
    async def admin_routing_log_retention_set():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_routing_log_schema import RoutingLogRetentionResp
        from internal.service.routing_log_retention_service import RoutingLogRetentionService

        payload = await request.get_json(force=True, silent=True) or {}
        try:
            retention_days = int(payload.get("retention_days"))
        except (TypeError, ValueError):
            return a._json_resp(
                code="validate_error",
                message="retention_days 必须是整数",
                data={"retention_days": ["retention_days 必须是整数"]},
                status=400,
            )
        try:
            days = await a._to_thread(
                a._get_service(RoutingLogRetentionService).set_retention_days,
                retention_days,
                UUID(str(account.id)),
            )
        except ValueError as exc:
            return a._json_resp(code="fail", message=str(exc), status=400)
        describe = await a._to_thread(a._get_service(RoutingLogRetentionService).describe)
        describe = {**describe, "retention_days": days}
        return a._ok(RoutingLogRetentionResp().dump(describe))

    # ------------------------------------------------------------------
    # admin_resource_entry_handler -> AdminToolGovernanceService / McpService / SkillService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/tools")
    async def admin_resource_entry_tools():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.admin_tool_governance_service import AdminToolGovernanceService

        current_page, page_size, keyword = _pagination_args()
        result = await a._to_thread(
            a._get_service(AdminToolGovernanceService).list_policies,
            source_type="api_tool",
            current_page=current_page,
            page_size=page_size,
            keyword=keyword,
        )
        return a._ok(result)

    @quart_app.get("/admin/mcp")
    async def admin_resource_entry_mcp():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.mcp_schema import McpProviderResp
        from internal.service.mcp_service import McpService

        req = SimpleNamespace(
            current_page=a._field(_int_arg("current_page", 1), 1),
            page_size=a._field(_int_arg("page_size", 20), 20),
            search_word=a._field(request.args.get("search_word"), None),
            category=a._field(request.args.get("category"), None),
        )
        providers, paginator = await a._to_thread(
            a._get_service(McpService).get_admin_mcp_providers_with_page, req
        )
        resp = McpProviderResp(many=True)
        return a._ok({"list": resp.dump(providers), "paginator": asdict(paginator)})

    @quart_app.get("/admin/skills")
    async def admin_resource_entry_skills():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.skill_schema import SkillPackageResp
        from internal.service.skill_service import SkillService

        req = SimpleNamespace(
            current_page=a._field(_int_arg("current_page", 1), 1),
            page_size=a._field(_int_arg("page_size", 20), 20),
            search_word=a._field(request.args.get("search_word"), None),
            category=a._field(request.args.get("category"), None),
        )
        skills, paginator = await a._to_thread(
            a._get_service(SkillService).get_skill_packages_with_page, req
        )
        resp = SkillPackageResp(many=True)
        return a._ok({"list": resp.dump(skills), "paginator": asdict(paginator)})

    # ------------------------------------------------------------------
    # admin_recycle_bin_handler -> RecycleBinService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/recycle-bin")
    async def admin_recycle_bin_list():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_recycle_bin_schema import RecycleBinListSchema
        from internal.service.recycle_bin_service import RecycleBinService

        result = await a._to_thread(
            a._get_service(RecycleBinService).list_items,
            page=_int_arg("page", 1),
            page_size=_int_arg("page_size", 20),
            resource_type=request.args.get("resource_type") or None,
            status=request.args.get("status") or "pending",
            search_word=request.args.get("search_word") or "",
            deleted_by_type=request.args.get("deleted_by_type") or None,
        )
        return a._ok(RecycleBinListSchema().dump(result))

    @quart_app.get("/admin/recycle-bin/<int:item_id>")
    async def admin_recycle_bin_get(item_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.exception import NotFoundException
        from internal.schema.admin_recycle_bin_schema import RecycleBinDetailSchema
        from internal.service.recycle_bin_service import RecycleBinService

        try:
            item = await a._to_thread(a._get_service(RecycleBinService).get_item, item_id)
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        return a._ok(RecycleBinDetailSchema().dump(item))

    @quart_app.post("/admin/recycle-bin/<int:item_id>/restore")
    async def admin_recycle_bin_restore(item_id):
        from app.http import asgi_app as a

        operator, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.exception import NotFoundException, ValidateErrorException
        from internal.schema.admin_recycle_bin_schema import RecycleBinDetailSchema
        from internal.service.recycle_bin_service import RecycleBinService

        try:
            item = await a._to_thread(
                a._get_service(RecycleBinService).restore_item,
                item_id,
                admin_user_id=operator.id,
            )
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        except ValidateErrorException as exc:
            return a._json_resp(code="validate_error", message=str(exc), status=400)
        return a._ok(RecycleBinDetailSchema().dump(item))

    # ------------------------------------------------------------------
    # admin_cost_stats_handler -> CostStatsService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/cost-stats/overview")
    async def admin_cost_stats_overview():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_cost_stats_schema import CostStatsOverviewResp
        from internal.service.cost_stats_service import CostStatsService

        result = await a._to_thread(
            a._get_service(CostStatsService).overview,
            start_at=_int_arg("start_at", 0) or None,
            end_at=_int_arg("end_at", 0) or None,
        )
        return a._ok(CostStatsOverviewResp().dump(result))

    @quart_app.get("/admin/cost-stats/by-dimension")
    async def admin_cost_stats_by_dimension():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_cost_stats_schema import CostStatsByDimensionResp
        from internal.service.cost_stats_service import CostStatsService

        result = await a._to_thread(
            a._get_service(CostStatsService).by_dimension,
            dimension=request.args.get("dimension") or "user",
            start_at=_int_arg("start_at", 0) or None,
            end_at=_int_arg("end_at", 0) or None,
            limit=_int_arg("limit", 10) or 10,
        )
        return a._ok(CostStatsByDimensionResp().dump(result))

    @quart_app.get("/admin/cost-stats/timeseries")
    async def admin_cost_stats_timeseries():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_cost_stats_schema import CostStatsTimeseriesResp
        from internal.service.cost_stats_service import CostStatsService

        result = await a._to_thread(
            a._get_service(CostStatsService).timeseries,
            granularity=request.args.get("granularity") or "day",
            start_at=_int_arg("start_at", 0) or None,
            end_at=_int_arg("end_at", 0) or None,
        )
        return a._ok(CostStatsTimeseriesResp().dump(result))

    # ------------------------------------------------------------------
    # admin_orchestration_flag_handler -> OrchestrationFeatureFlagService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/orchestration-flags")
    async def admin_orchestration_flag_list():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_orchestration_flag_schema import OrchestrationFlagResp
        from internal.service.orchestration_feature_flag_service import (
            OrchestrationFeatureFlagService,
        )

        flags = await a._to_thread(a._get_service(OrchestrationFeatureFlagService).list_flags)
        return a._ok(OrchestrationFlagResp(many=True).dump(flags))

    @quart_app.post("/admin/orchestration-flags/<string:code>")
    async def admin_orchestration_flag_update(code):
        from app.http import asgi_app as a

        operator, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_orchestration_flag_schema import OrchestrationFlagResp
        from internal.service.orchestration_feature_flag_service import (
            OrchestrationFeatureFlagService,
        )

        payload = await request.get_json(force=True, silent=True) or {}
        enabled = bool(payload.get("enabled", False))
        try:
            result = await a._to_thread(
                a._get_service(OrchestrationFeatureFlagService).update_flag,
                code=code,
                enabled=enabled,
                operator_id=UUID(str(operator.id)),
            )
        except ValueError as exc:
            return a._json_resp(code="fail", message=str(exc), status=400)
        return a._ok(OrchestrationFlagResp().dump(result))

    # ------------------------------------------------------------------
    # admin_audit_log_handler -> AuditLogService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/audit-logs")
    async def admin_audit_log_list():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_audit_log_schema import AuditLogPageResp
        from internal.service.audit_log_service import AuditLogService

        result = await a._to_thread(
            a._get_service(AuditLogService).list_audit_logs,
            action=request.args.get("action") or "",
            resource_type=request.args.get("resource_type") or "",
            admin_user_id=request.args.get("admin_user_id") or "",
            start_time=_int_arg("start_time", 0) or None,
            end_time=_int_arg("end_time", 0) or None,
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
        )
        return a._ok(AuditLogPageResp().dump(result))

    # ------------------------------------------------------------------
    # admin_orchestration_release_handler -> OrchestrationReleaseCheckService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/orchestration-release-check")
    async def admin_orchestration_release_check():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.admin_orchestration_release_schema import OrchestrationReleaseCheckResp
        from internal.service.orchestration_release_check_service import (
            OrchestrationReleaseCheckService,
        )

        report = await a._to_thread(
            a._get_service(OrchestrationReleaseCheckService).build_report
        )
        return a._ok(OrchestrationReleaseCheckResp().dump(report))

    # ------------------------------------------------------------------
    # admin_upload_file_handler -> CosService
    # ------------------------------------------------------------------
    @quart_app.post("/admin/upload-files/image")
    async def admin_upload_file_image():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import CosService

        files = await request.files
        file = files.get("file")
        if file is None or not file.filename:
            return a._json_resp(
                code="validate_error",
                message="上传图片不能为空",
                data={"file": ["上传图片不能为空"]},
                status=400,
            )
        upload_file = await a._to_thread(a._get_service(CosService).upload_file, file, True)
        image_url = await a._to_thread(a._get_service(CosService).get_file_url, upload_file.key)
        return a._ok({"image_url": image_url})

    # ------------------------------------------------------------------
    # admin store 只读镜像：让 admin 商店页走 admin 凭证，不依赖用户域接口
    # ------------------------------------------------------------------
    @quart_app.get("/admin/store/builtin-tools")
    async def admin_store_builtin_tools():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import BuiltinToolService

        result = await a._to_thread(a._get_service(BuiltinToolService).get_builtin_tools)
        return a._ok(result)

    @quart_app.get("/admin/store/builtin-tools/categories")
    async def admin_store_builtin_tool_categories():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import BuiltinToolService

        result = await a._to_thread(a._get_service(BuiltinToolService).get_categories)
        return a._ok(result)

    @quart_app.get("/admin/store/builtin-tools/<string:provider_name>/tools/<string:tool_name>")
    async def admin_store_builtin_tool_detail(provider_name, tool_name):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import BuiltinToolService

        result = await a._to_thread(
            a._get_service(BuiltinToolService).get_provider_tool,
            provider_name,
            tool_name,
        )
        return a._ok(result)

    @quart_app.get("/admin/store/builtin-tools/<string:provider_name>/icon")
    async def admin_store_builtin_tool_icon(provider_name):
        from app.http import asgi_app as a

        from internal.service import BuiltinToolService

        icon, mimetype, icon_url = await a._to_thread(
            a._get_service(BuiltinToolService).get_provider_icon, provider_name
        )
        if icon_url:
            return a.Response("", status=302, headers={"Location": icon_url})
        return a.Response(icon or b"", mimetype=mimetype or "image/png")

    @quart_app.get("/admin/store/skills/categories")
    async def admin_store_skill_categories():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.skill_schema import GetSkillsCategoriesResp
        from internal.service.skill_service import SkillService

        return a._ok(
            GetSkillsCategoriesResp().dump(
                await a._to_thread(a._get_service(SkillService).get_skill_categories)
            )
        )

    @quart_app.get("/admin/store/skills")
    async def admin_store_skills_with_page():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.skill_schema import SkillPackageResp
        from internal.service.skill_service import SkillService

        req = a.SimpleNamespace(
            current_page=a._field(a._int_arg("current_page", 1), 1),
            page_size=a._field(a._int_arg("page_size", 20), 20),
            search_word=a._field(request.args.get("search_word"), None),
            category=a._field(request.args.get("category"), None),
        )
        skills, paginator = await a._to_thread(
            a._get_service(SkillService).get_skill_packages_with_page, req
        )
        resp = SkillPackageResp(many=True)
        return a._ok({"list": resp.dump(skills), "paginator": asdict(paginator)})

    @quart_app.get("/admin/store/skills/<uuid:skill_id>")
    async def admin_store_skill_detail(skill_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.skill_schema import SkillPackageResp
        from internal.service.skill_service import SkillService

        skill_package = await a._to_thread(
            a._get_service(SkillService).get_skill_package, skill_id
        )
        return a._ok(SkillPackageResp().dump(skill_package))

    @quart_app.get("/admin/store/skills/<uuid:skill_id>/icon")
    async def admin_store_skill_icon(skill_id):
        from app.http import asgi_app as a

        from internal.service.skill_service import SkillService

        icon, mimetype, icon_url = await a._to_thread(
            a._get_service(SkillService).get_skill_package_icon, skill_id
        )
        if icon_url:
            return a.Response("", status=302, headers={"Location": icon_url})
        return a.Response(icon or b"", mimetype=mimetype or "application/octet-stream")

    @quart_app.get("/admin/store/mcp-providers/categories")
    async def admin_store_mcp_categories():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.mcp_schema import GetMcpCategoriesResp

        return a._ok(GetMcpCategoriesResp().dump({}))

    @quart_app.get("/admin/store/mcp-providers")
    async def admin_store_mcp_providers_with_page():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.mcp_schema import McpProviderResp
        from internal.service.mcp_service import McpService

        req = a.SimpleNamespace(
            current_page=a._field(a._int_arg("current_page", 1), 1),
            page_size=a._field(a._int_arg("page_size", 20), 20),
            search_word=a._field(request.args.get("search_word"), None),
            category=a._field(request.args.get("category"), None),
        )
        providers, paginator = await a._to_thread(
            a._get_service(McpService).get_public_mcp_providers_with_page, req, account
        )
        resp = McpProviderResp(many=True)
        return a._ok({"list": resp.dump(providers), "paginator": asdict(paginator)})

    @quart_app.get("/admin/store/mcp-providers/<string:provider_key>")
    async def admin_store_mcp_provider(provider_key):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.mcp_schema import McpProviderResp
        from internal.service.mcp_service import McpService

        provider = await a._to_thread(
            a._get_service(McpService).get_public_mcp_provider, provider_key, account
        )
        return a._ok(McpProviderResp().dump(provider))

    # ------------------------------------------------------------------
    # admin OpenAPI 密钥：让 admin 页面走 admin 凭证，不依赖用户域接口
    # ------------------------------------------------------------------
    @quart_app.get("/admin/openapi/api-keys")
    async def admin_get_api_keys_with_page():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.api_key_schema import GetApiKeysWithPageResp
        from internal.service import ApiKeyService

        req = a.SimpleNamespace(
            current_page=a._field(a._int_arg("current_page", 1), 1),
            page_size=a._field(a._int_arg("page_size", 20), 20),
        )
        api_keys, paginator = await a._to_thread(
            a._get_service(ApiKeyService).get_api_keys_with_page, req, account
        )
        resp = GetApiKeysWithPageResp(many=True)
        return a._ok({"list": resp.dump(api_keys), "paginator": asdict(paginator)})

    @quart_app.post("/admin/openapi/api-keys")
    async def admin_create_api_key():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import ApiKeyService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error",
                message="名称不能为空",
                data={"name": ["名称不能为空"]},
                status=400,
            )
        req = a.SimpleNamespace(
            name=a._field(name),
            description=a._field(str(payload.get("description") or "")),
        )
        created_api_key = await a._to_thread(
            a._get_service(ApiKeyService).create_api_key, req, account
        )
        api_key_value = (
            created_api_key.get("api_key")
            if isinstance(created_api_key, dict)
            else getattr(created_api_key, "api_key", "")
        )
        return a._ok({"api_key": api_key_value})

    @quart_app.post("/admin/openapi/api-keys/<uuid:api_key_id>")
    async def admin_update_api_key(api_key_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import ApiKeyService

        payload = await request.get_json(force=True, silent=True) or {}
        req_data = {}
        if payload.get("name"):
            req_data["name"] = str(payload["name"])
        if payload.get("description"):
            req_data["description"] = str(payload["description"])
        await a._to_thread(
            a._get_service(ApiKeyService).update_api_key, api_key_id, account, **req_data
        )
        return a._ok_msg("更新API密钥成功")

    @quart_app.post("/admin/openapi/api-keys/<uuid:api_key_id>/is-active")
    async def admin_update_api_key_is_active(api_key_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import ApiKeyService

        payload = await request.get_json(force=True, silent=True) or {}
        req_data = {"is_active": bool(payload.get("is_active", True))}
        await a._to_thread(
            a._get_service(ApiKeyService).update_api_key, api_key_id, account, **req_data
        )
        return a._ok_msg("更新API密钥激活状态成功")

    @quart_app.post("/admin/openapi/api-keys/<uuid:api_key_id>/delete")
    async def admin_delete_api_key(api_key_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import ApiKeyService

        await a._to_thread(
            a._get_service(ApiKeyService).delete_api_key, api_key_id, account
        )
        return a._ok_msg("删除API密钥成功")

    # ------------------------------------------------------------------
    # admin 应用详情选择器自包含：语言模型 / 系统知识库
    # ------------------------------------------------------------------
    @quart_app.get("/admin/language-models")
    async def admin_get_language_models():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.language_model_service import LanguageModelService

        result = await a._to_thread(a._get_service(LanguageModelService).get_language_models)
        return a._ok(result)

    @quart_app.get("/admin/language-models/<string:provider_name>/<string:model_name>")
    async def admin_get_language_model(provider_name, model_name):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.language_model_service import LanguageModelService

        result = await a._to_thread(
            a._get_service(LanguageModelService).get_language_model,
            provider_name,
            model_name,
        )
        return a._ok(result)

    @quart_app.get("/admin/space/system-knowledge-bases")
    async def admin_list_system_knowledge_bases():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.scoped_knowledge_service import UserContentKnowledgeService

        user_content_service = a._get_service(UserContentKnowledgeService)
        bases = await a._to_thread(user_content_service.list_readable_system_bases)
        result = [
            {
                "id": str(base.id),
                "name": base.name,
                "description": base.description or "",
                "knowledge_scope": base.knowledge_scope,
            }
            for base in bases
        ]
        return a._ok({"list": result})
