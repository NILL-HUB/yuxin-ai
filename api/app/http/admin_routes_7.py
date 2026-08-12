"""Admin 管理端点 Quart 异步迁移（批次 7）。

将 internal/router/router.py 中以下 handler 注册的 Flask 同步端点迁移为
Quart async 端点（挂载到 asgi_app.quart_app）：
- admin_rbac_handler         -> AdminRbacService
- admin_customer_user_handler -> AdminCustomerUserService
- admin_billing_plan_handler -> AdminBillingPlanService
- admin_storage_handler      -> StorageConfigService / StorageMigrationService
- admin_agent_pool_handler   -> AdminAgentPoolService
- admin_sub_pool_handler     -> AdminSubPoolService

每个端点函数体内第一行 ``from app.http import asgi_app as a``，
以规避模块导入阶段的循环依赖。
"""

import json as _json
import os as _os

from quart import request

_registered = False


def _build_kkfileview_url(url):
    """生成 kkFileView 在线预览地址（与 admin_storage_handler 逻辑一致）。"""
    import base64
    from urllib.parse import quote

    if not url:
        return None
    if url.startswith(("http://", "https://")):
        preview_file_url = url
    else:
        inner_host = (_os.getenv("KKFILEVIEW_FILE_HOST") or "http://llmops-nginx:80").rstrip("/")
        preview_file_url = f"{inner_host}{url}"
    encoded = base64.b64encode(preview_file_url.encode("utf-8")).decode("ascii")
    return f"/kkfileview/onlinePreview?url={quote(encoded, safe='')}"


def _local_file_exists(key) -> bool:
    """本地存储后端下判断文件实体是否仍存在。"""
    import os.path as _osp

    from internal.service.storage.local_storage_service import _get_local_storage_root

    storage_root = _osp.abspath(_get_local_storage_root())
    safe_key = _osp.normpath(key or "").lstrip("/\\")
    if ".." in safe_key.split(_osp.sep):
        return False
    return _osp.isfile(_osp.join(storage_root, safe_key))


def _build_file_items(
    files,
    runtime_storage_service,
    *,
    dedupe_groups=None,
    sources=None,
    valid_ids=None,
):
    """为迁移文件列表补充访问 URL 与 kkFileView 预览 URL。"""
    from internal.lib.helper import datetime_to_timestamp

    dedupe_groups = dedupe_groups or {}
    sources = sources or {}
    valid_ids = valid_ids or set()
    items = []
    for file in files:
        url = None
        kkfileview_url = None
        file_id = str(file.id)
        group_key = (getattr(file, "hash", "") or "").strip() or (file.key or "")
        group = dedupe_groups.get(group_key) or {}
        source = sources.get(file_id) or {
            "type": "unknown",
            "label": "直接上传 / 未知",
        }
        try:
            backend = (getattr(file, "storage_backend", "") or "").strip() or None
            url = runtime_storage_service.get_file_url(file.key, backend=backend)
            file_missing = file_id not in valid_ids
            if file_missing:
                url = None
                kkfileview_url = None
            else:
                kkfileview_url = _build_kkfileview_url(url)
        except Exception:
            pass
        in_use = False
        try:
            from app.http import asgi_app as a
            from internal.service.storage.storage_migration_service import StorageMigrationService
            in_use = a._get_service(StorageMigrationService)._is_file_in_use(file_id)
        except Exception:
            in_use = False
        resolved_backend = (
            (getattr(file, "storage_backend", "") or "").strip()
            or (_os.getenv("STORAGE_BACKEND") or "local").strip().lower()
        )
        items.append(
            {
                "id": file_id,
                "name": getattr(file, "name", ""),
                "key": getattr(file, "key", ""),
                "size": getattr(file, "size", 0),
                "extension": getattr(file, "extension", ""),
                "mime_type": getattr(file, "mime_type", ""),
                "hash": getattr(file, "hash", ""),
                "storage_backend": getattr(file, "storage_backend", None),
                "resolved_backend": resolved_backend,
                "url": url,
                "kkfileview_url": kkfileview_url,
                "source_type": source.get("type", "unknown"),
                "source_label": source.get("label", "直接上传 / 未知"),
                "duplicate_count": int(group.get("size") or 1),
                "is_latest": bool(group.get("latest_id") == file_id),
                "is_valid": file_id in valid_ids,
                "in_use": in_use,
                "created_at": datetime_to_timestamp(getattr(file, "created_at", None)),
            }
        )
    return items


def register_routes(quart_app):
    """把批次 7 的 Admin 端点注册到 quart_app（幂等，重复调用直接返回）。"""
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

    def _operator_context():
        operator_id = request.headers.get("X-Admin-Id") or None
        ip = request.headers.get("X-Forwarded-For") or ""
        user_agent = request.headers.get("User-Agent") or ""
        return operator_id, ip, user_agent

    # ------------------------------------------------------------------
    # admin_rbac_handler -> AdminRbacService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/roles")
    async def admin_rbac_list_roles():
        from app.http import asgi_app as a
        from internal.schema.admin_rbac_schema import RoleResp
        from internal.service.admin_rbac_service import AdminRbacService

        result = await a._to_thread(a._get_service(AdminRbacService).list_roles)
        resp = RoleResp(many=True)
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/roles")
    async def admin_rbac_create_role():
        from app.http import asgi_app as a
        from internal.schema.admin_rbac_schema import RoleResp
        from internal.service.admin_rbac_service import AdminRbacService

        payload = await request.get_json(force=True, silent=True) or {}
        code = str(payload.get("code") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not code:
            return a._json_resp(
                code="validate_error",
                message="角色编码不能为空",
                data={"code": ["角色编码不能为空"]},
                status=400,
            )
        if not name:
            return a._json_resp(
                code="validate_error",
                message="角色名称不能为空",
                data={"name": ["角色名称不能为空"]},
                status=400,
            )
        operator_id, ip, user_agent = _operator_context()
        result = await a._to_thread(
            a._get_service(AdminRbacService).create_role,
            code=code,
            name=name,
            description=str(payload.get("description") or ""),
            permission_ids=payload.get("permission_ids", []) or [],
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = RoleResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/roles/<uuid:role_id>")
    async def admin_rbac_get_role(role_id):
        from app.http import asgi_app as a
        from internal.schema.admin_rbac_schema import RoleResp
        from internal.service.admin_rbac_service import AdminRbacService

        result = await a._to_thread(a._get_service(AdminRbacService).get_role, role_id)
        resp = RoleResp()
        return a._ok(resp.dump(result))

    @quart_app.patch("/admin/roles/<uuid:role_id>")
    async def admin_rbac_update_role(role_id):
        from app.http import asgi_app as a
        from internal.schema.admin_rbac_schema import RoleResp
        from internal.service.admin_rbac_service import AdminRbacService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = _operator_context()
        name = payload.get("name")
        if name is not None:
            name = str(name)
        description = payload.get("description")
        if description is not None:
            description = str(description)
        result = await a._to_thread(
            a._get_service(AdminRbacService).update_role,
            role_id,
            name=name,
            description=description,
            permission_ids=payload.get("permission_ids") if "permission_ids" in payload else None,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = RoleResp()
        return a._ok(resp.dump(result))

    @quart_app.delete("/admin/roles/<uuid:role_id>")
    async def admin_rbac_delete_role(role_id):
        from app.http import asgi_app as a
        from internal.service.admin_rbac_service import AdminRbacService

        operator_id, ip, user_agent = _operator_context()
        await a._to_thread(
            a._get_service(AdminRbacService).delete_role,
            role_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        return a._ok_msg("删除角色成功")

    @quart_app.get("/admin/permissions")
    async def admin_rbac_list_permissions():
        from app.http import asgi_app as a
        from internal.schema.admin_rbac_schema import PermissionResp
        from internal.service.admin_rbac_service import AdminRbacService

        result = await a._to_thread(a._get_service(AdminRbacService).list_permissions)
        resp = PermissionResp(many=True)
        return a._ok(resp.dump(result))

    # ------------------------------------------------------------------
    # admin_customer_user_handler -> AdminCustomerUserService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/users")
    async def admin_customer_user_list():
        from app.http import asgi_app as a
        from internal.schema.admin_customer_user_schema import AdminCustomerUserPageResp
        from internal.service.admin_customer_user_service import AdminCustomerUserService

        result = await a._to_thread(
            a._get_service(AdminCustomerUserService).list_customer_users,
            keyword=request.args.get("keyword") or "",
            status=request.args.get("status") or "",
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
        )
        resp = AdminCustomerUserPageResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/users/<uuid:account_id>")
    async def admin_customer_user_get(account_id):
        from app.http import asgi_app as a
        from internal.schema.admin_customer_user_schema import AdminCustomerUserResp
        from internal.service.admin_customer_user_service import AdminCustomerUserService

        result = await a._to_thread(
            a._get_service(AdminCustomerUserService).get_customer_user, account_id
        )
        resp = AdminCustomerUserResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/users/<uuid:account_id>/disable")
    async def admin_customer_user_disable(account_id):
        from app.http import asgi_app as a
        from internal.schema.admin_customer_user_schema import AdminCustomerUserResp
        from internal.service.admin_customer_user_service import AdminCustomerUserService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = _operator_context()
        result = await a._to_thread(
            a._get_service(AdminCustomerUserService).disable_customer_user,
            account_id,
            reason=str(payload.get("reason") or ""),
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminCustomerUserResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/users/<uuid:account_id>/enable")
    async def admin_customer_user_enable(account_id):
        from app.http import asgi_app as a
        from internal.schema.admin_customer_user_schema import AdminCustomerUserResp
        from internal.service.admin_customer_user_service import AdminCustomerUserService

        operator_id, ip, user_agent = _operator_context()
        result = await a._to_thread(
            a._get_service(AdminCustomerUserService).enable_customer_user,
            account_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminCustomerUserResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/users/<uuid:account_id>/sessions/revoke")
    async def admin_customer_user_revoke_sessions(account_id):
        from app.http import asgi_app as a
        from internal.schema.admin_customer_user_schema import RevokeCustomerUserSessionsResp
        from internal.service.admin_customer_user_service import AdminCustomerUserService

        operator_id, ip, user_agent = _operator_context()
        result = await a._to_thread(
            a._get_service(AdminCustomerUserService).revoke_customer_user_sessions,
            account_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = RevokeCustomerUserSessionsResp()
        return a._ok(resp.dump(result))

    # ------------------------------------------------------------------
    # admin_billing_plan_handler -> AdminBillingPlanService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/plans")
    async def admin_plan_list():
        from app.http import asgi_app as a
        from internal.schema.admin_billing_plan_schema import AdminPlanPageResp
        from internal.service.admin_billing_plan_service import AdminBillingPlanService

        result = await a._to_thread(
            a._get_service(AdminBillingPlanService).list_plans,
            keyword=request.args.get("keyword") or "",
            status=request.args.get("status") or "",
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
        )
        resp = AdminPlanPageResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/plans")
    async def admin_plan_create():
        from app.http import asgi_app as a
        from internal.schema.admin_billing_plan_schema import AdminPlanResp
        from internal.service.admin_billing_plan_service import AdminBillingPlanService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = _operator_context()
        result = await a._to_thread(
            a._get_service(AdminBillingPlanService).create_plan,
            payload,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminPlanResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/plans/<uuid:plan_id>")
    async def admin_plan_get(plan_id):
        from app.http import asgi_app as a
        from internal.schema.admin_billing_plan_schema import AdminPlanResp
        from internal.service.admin_billing_plan_service import AdminBillingPlanService

        result = await a._to_thread(a._get_service(AdminBillingPlanService).get_plan, plan_id)
        resp = AdminPlanResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/plans/<uuid:plan_id>")
    async def admin_plan_update(plan_id):
        from app.http import asgi_app as a
        from internal.schema.admin_billing_plan_schema import AdminPlanResp
        from internal.service.admin_billing_plan_service import AdminBillingPlanService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = _operator_context()
        result = await a._to_thread(
            a._get_service(AdminBillingPlanService).update_plan,
            plan_id,
            payload,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminPlanResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/plans/<uuid:plan_id>/status")
    async def admin_plan_set_status(plan_id):
        from app.http import asgi_app as a
        from internal.schema.admin_billing_plan_schema import AdminPlanResp
        from internal.service.admin_billing_plan_service import AdminBillingPlanService

        payload = await request.get_json(force=True, silent=True) or {}
        status_raw = payload.get("status")
        if status_raw is None or str(status_raw).strip() == "":
            return a._json_resp(
                code="validate_error",
                message="status不能为空",
                data={"status": ["status不能为空"]},
                status=400,
            )
        operator_id, ip, user_agent = _operator_context()
        result = await a._to_thread(
            a._get_service(AdminBillingPlanService).set_plan_status,
            plan_id,
            str(status_raw),
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminPlanResp()
        return a._ok(resp.dump(result))

    # ------------------------------------------------------------------
    # admin_storage_handler -> StorageConfigService / StorageMigrationService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/storage/overview")
    async def admin_storage_overview():
        from app.http import asgi_app as a
        from internal.schema.admin_storage_schema import StorageOverviewSchema
        from internal.service.storage.storage_config_service import StorageConfigService

        active_backend = await a._to_thread(a._get_service(StorageConfigService).get_active_backend)
        configs = await a._to_thread(a._get_service(StorageConfigService).list_configs)
        stats = await a._to_thread(a._get_service(StorageConfigService).get_storage_stats)
        overview = {
            "active_backend": active_backend,
            "backend_items": configs,
            "stats": stats,
        }
        resp = StorageOverviewSchema()
        return a._ok(resp.dump(overview))

    @quart_app.get("/admin/storage/configs")
    async def admin_storage_list_configs():
        from app.http import asgi_app as a
        from internal.schema.admin_storage_schema import StorageConfigListSchema
        from internal.service.storage.storage_config_service import StorageConfigService

        configs = await a._to_thread(a._get_service(StorageConfigService).list_configs)
        resp = StorageConfigListSchema()
        return a._ok(resp.dump({"items": configs}))

    @quart_app.post("/admin/storage/configs/<string:backend>")
    async def admin_storage_update_config(backend):
        from app.http import asgi_app as a
        from internal.schema.admin_storage_schema import StorageConfigItemSchema
        from internal.service.storage.storage_config_service import StorageConfigService

        payload = await request.get_json(force=True, silent=True) or {}
        configs = payload.get("configs") or {}
        if isinstance(configs, str):
            try:
                configs = _json.loads(configs)
            except (ValueError, TypeError):
                configs = {}
        config = await a._to_thread(
            a._get_service(StorageConfigService).upsert_config, backend, configs
        )
        resp = StorageConfigItemSchema()
        return a._ok(resp.dump(config))

    @quart_app.post("/admin/storage/activate")
    async def admin_storage_activate():
        from app.http import asgi_app as a
        from internal.schema.admin_storage_schema import StorageConfigItemSchema
        from internal.service.storage.storage_config_service import (
            SUPPORTED_BACKENDS,
            StorageConfigService,
        )

        payload = await request.get_json(force=True, silent=True) or {}
        backend = str(payload.get("backend") or "").strip()
        if backend not in SUPPORTED_BACKENDS:
            return a._json_resp(
                code="validate_error",
                message=f"必须为 {'/'.join(SUPPORTED_BACKENDS)} 之一",
                data={"backend": [f"必须为 {'/'.join(SUPPORTED_BACKENDS)} 之一"]},
                status=400,
            )
        config = await a._to_thread(a._get_service(StorageConfigService).set_active_backend, backend)
        resp = StorageConfigItemSchema()
        return a._ok(resp.dump(config))

    @quart_app.get("/admin/storage/migration/files")
    async def admin_storage_migration_files():
        from app.http import asgi_app as a
        from internal.schema.admin_storage_schema import StorageMigrationListSchema
        from internal.service.storage.runtime_storage_service import RuntimeStorageProxy
        from internal.service.storage.storage_config_service import StorageConfigService
        from internal.service.storage.storage_migration_service import StorageMigrationService

        source_backend = (
            (request.args.get("source_backend") or "").strip()
            or await a._to_thread(a._get_service(StorageConfigService).get_active_backend)
        )
        migration_service = a._get_service(StorageMigrationService)
        result = await a._to_thread(
            migration_service.list_files,
            source_backend=source_backend,
            page=_int_arg("page", 1),
            page_size=_int_arg("page_size", 20),
            extension=(request.args.get("extension") or "").strip() or None,
            search_word=(request.args.get("search_word") or "").strip(),
        )
        extensions = await a._to_thread(
            migration_service.list_extensions, source_backend
        )
        file_ids = [str(item.id) for item in result["items"]]
        resolve_sources = getattr(migration_service, "resolve_file_sources", None)
        list_valid_ids = getattr(migration_service, "list_valid_file_ids", None)
        sources = (
            await a._to_thread(resolve_sources, file_ids)
            if resolve_sources is not None
            else {}
        )
        valid_ids = (
            await a._to_thread(list_valid_ids, result["items"])
            if list_valid_ids is not None
            else set()
        )
        items = _build_file_items(
            result["items"],
            a._get_service(RuntimeStorageProxy),
            dedupe_groups=result.get("dedupe_groups") or {},
            sources=sources,
            valid_ids=valid_ids,
        )
        payload = {
            "items": items,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "total_pages": result["total_pages"],
            "total_record": result["total_record"],
            "extensions": extensions,
            "summary": result.get("summary") or {},
        }
        resp = StorageMigrationListSchema()
        return a._ok(resp.dump(payload))

    @quart_app.post("/admin/storage/migration/run")
    async def admin_storage_migration_run():
        from app.http import asgi_app as a
        from internal.schema.admin_storage_schema import StorageMigrationResultSchema
        from internal.service.storage.storage_migration_service import StorageMigrationService

        payload = await request.get_json(force=True, silent=True) or {}
        file_ids = payload.get("file_ids") or []
        if not isinstance(file_ids, list):
            file_ids = []
        file_ids = [fid for fid in file_ids if str(fid).strip()]
        result = await a._to_thread(
            a._get_service(StorageMigrationService).migrate,
            source_backend=(payload.get("source_backend") or "").strip(),
            target_backend=(payload.get("target_backend") or "").strip(),
            file_ids=file_ids or None,
            extension=(payload.get("extension") or "").strip() or None,
            search_word=(payload.get("search_word") or "").strip(),
            delete_source=bool(payload.get("delete_source", False)),
        )
        resp = StorageMigrationResultSchema()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/storage/files/delete")
    async def admin_storage_files_delete():
        from app.http import asgi_app as a
        from internal.service.audit_log_service import AuditLogService
        from internal.service.storage.storage_migration_service import StorageMigrationService

        payload = await request.get_json(force=True, silent=True) or {}
        file_ids = payload.get("file_ids") or []
        if not isinstance(file_ids, list):
            file_ids = []
        file_ids = [fid for fid in file_ids if str(fid).strip()]
        if not file_ids:
            return a._json_resp(
                code="validate_error",
                message="file_ids 不能为空",
                data={"file_ids": ["file_ids 不能为空"]},
                status=400,
            )
        from app.http.admin_routes_6 import _get_operator_context
        operator_id, ip, user_agent = await _get_operator_context()
        result = await a._to_thread(
            a._get_service(StorageMigrationService).delete_files,
            file_ids=file_ids,
            force=bool(payload.get("force", False)),
            deleted_by=operator_id,
            retention_days=payload.get("retention_days"),
        )
        if operator_id:
            try:
                await a._to_thread(
                    a._get_service(AuditLogService).record,
                    admin_user_id=operator_id,
                    action="storage.file_delete",
                    resource_type="storage_file",
                    resource_id=",".join(str(fid) for fid in file_ids),
                    ip=ip,
                    user_agent=user_agent,
                    after_data=result,
                )
            except Exception:
                pass
        return a._ok(result)

    # ------------------------------------------------------------------
    # admin_agent_pool_handler -> AdminAgentPoolService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/agent-pool")
    async def admin_agent_pool_list():
        from app.http import asgi_app as a
        from internal.schema.admin_agent_pool_schema import AdminAgentPoolConfigPageResp
        from internal.service.admin_agent_pool_service import AdminAgentPoolService

        result = await a._to_thread(
            a._get_service(AdminAgentPoolService).list_configs,
            page=_int_arg("current_page", 1),
            per_page=_int_arg("page_size", 20),
            enabled=request.args.get("enabled") or "",
            keyword=request.args.get("keyword") or "",
        )
        resp = AdminAgentPoolConfigPageResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/agent-pool")
    async def admin_agent_pool_create():
        from app.http import asgi_app as a
        from internal.schema.admin_agent_pool_schema import AdminAgentPoolConfigResp
        from internal.service.admin_agent_pool_service import AdminAgentPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(a._get_service(AdminAgentPoolService).create_config, payload)
        resp = AdminAgentPoolConfigResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/agent-pool/stats")
    async def admin_agent_pool_list_stats():
        from app.http import asgi_app as a
        from internal.schema.admin_agent_pool_schema import AdminAgentPoolStatsResp
        from internal.service.admin_agent_pool_service import AdminAgentPoolService

        result = await a._to_thread(a._get_service(AdminAgentPoolService).list_pool_stats)
        resp = AdminAgentPoolStatsResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/agent-pool/<uuid:config_id>")
    async def admin_agent_pool_get(config_id):
        from app.http import asgi_app as a
        from internal.schema.admin_agent_pool_schema import AdminAgentPoolConfigResp
        from internal.service.admin_agent_pool_service import AdminAgentPoolService

        result = await a._to_thread(a._get_service(AdminAgentPoolService).get_config, config_id)
        resp = AdminAgentPoolConfigResp()
        return a._ok(resp.dump(result))

    @quart_app.patch("/admin/agent-pool/<uuid:config_id>")
    async def admin_agent_pool_update(config_id):
        from app.http import asgi_app as a
        from internal.schema.admin_agent_pool_schema import AdminAgentPoolConfigResp
        from internal.service.admin_agent_pool_service import AdminAgentPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminAgentPoolService).update_config, config_id, payload
        )
        resp = AdminAgentPoolConfigResp()
        return a._ok(resp.dump(result))

    @quart_app.delete("/admin/agent-pool/<uuid:config_id>")
    async def admin_agent_pool_delete(config_id):
        from app.http import asgi_app as a
        from internal.service.admin_agent_pool_service import AdminAgentPoolService

        await a._to_thread(a._get_service(AdminAgentPoolService).delete_config, config_id)
        return a._ok_msg("删除Agent池配置成功")

    @quart_app.post("/admin/agent-pool/<uuid:config_id>/status")
    async def admin_agent_pool_set_status(config_id):
        from app.http import asgi_app as a
        from internal.schema.admin_agent_pool_schema import AdminAgentPoolConfigResp
        from internal.service.admin_agent_pool_service import AdminAgentPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        enabled_raw = payload.get("enabled")
        if enabled_raw is None or str(enabled_raw).strip() == "":
            return a._json_resp(
                code="validate_error",
                message="enabled不能为空",
                data={"enabled": ["enabled不能为空"]},
                status=400,
            )
        enabled = str(enabled_raw).lower() == "true"
        result = await a._to_thread(
            a._get_service(AdminAgentPoolService).set_enabled, config_id, enabled
        )
        resp = AdminAgentPoolConfigResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/agent-pool/<uuid:config_id>/health")
    async def admin_agent_pool_check_health(config_id):
        from app.http import asgi_app as a
        from internal.schema.admin_agent_pool_schema import AdminAgentPoolConfigResp
        from internal.service.admin_agent_pool_service import AdminAgentPoolService

        result = await a._to_thread(a._get_service(AdminAgentPoolService).check_health, config_id)
        resp = AdminAgentPoolConfigResp()
        return a._ok(resp.dump(result))

    # ------------------------------------------------------------------
    # admin_sub_pool_handler -> AdminSubPoolService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/sub-pool-definitions")
    async def admin_sub_pool_list():
        from app.http import asgi_app as a
        from internal.service.admin_sub_pool_service import AdminSubPoolService

        result = await a._to_thread(
            a._get_service(AdminSubPoolService).list_definitions,
            page=_int_arg("current_page", 1),
            per_page=_int_arg("page_size", 20),
            pool_type=request.args.get("pool_type") or "",
            enabled=request.args.get("enabled") or "",
            keyword=request.args.get("keyword") or "",
        )
        return a._ok(result)

    @quart_app.post("/admin/sub-pool-definitions")
    async def admin_sub_pool_create():
        from app.http import asgi_app as a
        from internal.service.admin_sub_pool_service import AdminSubPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(a._get_service(AdminSubPoolService).create_definition, payload)
        return a._ok(result)

    @quart_app.get("/admin/sub-pool-definitions/<uuid:def_id>")
    async def admin_sub_pool_get(def_id):
        from app.http import asgi_app as a
        from internal.service.admin_sub_pool_service import AdminSubPoolService

        result = await a._to_thread(a._get_service(AdminSubPoolService).get_definition, def_id)
        return a._ok(result)

    @quart_app.patch("/admin/sub-pool-definitions/<uuid:def_id>")
    async def admin_sub_pool_update(def_id):
        from app.http import asgi_app as a
        from internal.service.admin_sub_pool_service import AdminSubPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminSubPoolService).update_definition, def_id, payload
        )
        return a._ok(result)

    @quart_app.delete("/admin/sub-pool-definitions/<uuid:def_id>")
    async def admin_sub_pool_delete(def_id):
        from app.http import asgi_app as a
        from internal.service.admin_sub_pool_service import AdminSubPoolService

        await a._to_thread(a._get_service(AdminSubPoolService).delete_definition, def_id)
        return a._ok_msg("删除子池定义成功")

    @quart_app.post("/admin/sub-pool-definitions/<uuid:def_id>/status")
    async def admin_sub_pool_set_status(def_id):
        from app.http import asgi_app as a
        from internal.service.admin_sub_pool_service import AdminSubPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        enabled = str(payload.get("enabled", "true")).lower() == "true"
        result = await a._to_thread(
            a._get_service(AdminSubPoolService).set_enabled, def_id, enabled
        )
        return a._ok(result)
