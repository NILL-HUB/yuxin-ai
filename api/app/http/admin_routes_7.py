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


def _build_board_executor():
    """构造板块工具执行闸门（无状态，每次新建即可）。"""
    from internal.service.admin_agent_board_tools import BoardToolExecutor

    return BoardToolExecutor()


def _build_draft_service(a):
    """构造通用变更草稿服务（Db 依赖由 injector 提供）。"""
    from internal.service.admin_change_draft_service import AdminChangeDraftService

    try:
        return a._get_service(AdminChangeDraftService)
    except Exception:
        # AdminChangeDraftService 不是 @inject：injector 无法自动构造时
        # 回退到直接注入 db（与 ScopedKnowledgeService._get_audit_log_service 同思路）。
        from internal.extension.database_extension import db

        return AdminChangeDraftService(db=db)


def _build_audit_service():
    """构造审计服务（session=None → 走全局 db.session）。"""
    from internal.service.audit_log_service import AuditLogService

    return AuditLogService()


def _build_execution_service(a, *, board_executor, draft_service, audit_log_service):
    """构造执行编排服务。

    独立成模块级工厂是**刻意留的测试接缝**：该服务的三个依赖都需按请求现场
    组装（board_executor 无状态、draft/audit 依赖 db），因此无法经
    `_get_service` 单例解析；路由测试据此替换整条执行链，避免为了测"路由接线"
    而把真实 DB 写链路拉进来。
    """
    from internal.service.admin_agent_execution_service import (
        AdminAgentExecutionService,
    )

    return AdminAgentExecutionService(
        board_executor=board_executor,
        draft_service=draft_service,
        audit_log_service=audit_log_service,
    )


def _list_board_actions() -> dict:
    """拍平板块动作注册表为展示结构。

    返回 ``{"boards": [...板块名...], "actions": [...动作明细...]}``：
    前端既要知道"有哪些板块"（分组渲染），也要知道"每个板块能做什么"
    （动作明细与所需权限点）。
    """
    from internal.core.admin_agent_boards import BOARD_ACTIONS
    from internal.service.admin_agent_board_tools import available_boards

    return {
        "boards": list(available_boards()),
        "actions": [
            {
                "board": action.board,
                "action": action.action,
                "kind": action.kind,
                "permission_code": action.permission_code,
                "description": action.description,
            }
            for action in BOARD_ACTIONS
        ],
    }


def _dump_draft(draft) -> dict:
    """序列化变更草稿（UUID / datetime → 字符串 / 时间戳）。"""
    from internal.lib.helper import datetime_to_timestamp

    return {
        "id": str(draft.id),
        "policy_type": draft.policy_type,
        "target_id": draft.target_id,
        "before_config": draft.before_config or {},
        "after_config": draft.after_config or {},
        "diff": draft.diff or {},
        "impact": draft.impact or {},
        "status": draft.status,
        "created_at": datetime_to_timestamp(draft.created_at),
    }


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

    async def _operator_context():
        from app.http.admin_routes_6 import _get_operator_context

        return await _get_operator_context()

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
        operator_id, ip, user_agent = await _operator_context()
        result = await a._to_thread(
            a._get_service(AdminRbacService).create_role,
            code=code,
            name=name,
            description=str(payload.get("description") or ""),
            permission_codes=payload.get("permission_codes", []) or [],
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = RoleResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/roles/<string:role_code>")
    async def admin_rbac_get_role(role_code):
        from app.http import asgi_app as a
        from internal.schema.admin_rbac_schema import RoleResp
        from internal.service.admin_rbac_service import AdminRbacService

        result = await a._to_thread(a._get_service(AdminRbacService).get_role, role_code)
        resp = RoleResp()
        return a._ok(resp.dump(result))

    @quart_app.patch("/admin/roles/<string:role_code>")
    async def admin_rbac_update_role(role_code):
        from app.http import asgi_app as a
        from internal.schema.admin_rbac_schema import RoleResp
        from internal.service.admin_rbac_service import AdminRbacService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = await _operator_context()
        name = payload.get("name")
        if name is not None:
            name = str(name)
        description = payload.get("description")
        if description is not None:
            description = str(description)
        result = await a._to_thread(
            a._get_service(AdminRbacService).update_role,
            role_code,
            name=name,
            description=description,
            permission_codes=payload.get("permission_codes") if "permission_codes" in payload else None,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = RoleResp()
        return a._ok(resp.dump(result))

    @quart_app.delete("/admin/roles/<string:role_code>")
    async def admin_rbac_delete_role(role_code):
        from app.http import asgi_app as a
        from internal.service.admin_rbac_service import AdminRbacService

        operator_id, ip, user_agent = await _operator_context()
        await a._to_thread(
            a._get_service(AdminRbacService).delete_role,
            role_code,
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
    # admin_agent_handler -> AdminAgentService（管理端 Agent 治理，设计 §4）
    # ------------------------------------------------------------------
    @quart_app.get("/admin/agents/assignable-permissions")
    async def admin_agent_assignable_permissions():
        """返回当前管理员**可下放**的权限点（交集，不是全量目录）。

        设计 §4.3「展示即受限」：管理员看不到自己没有的权限点，无从选择。
        注意：这里返回的是**后端算好的交集**，而不是"把全量目录交给前端过滤"
        ——前端过滤不是安全边界。具体的保存校验在
        `assert_grantable`（第二层），运行时在每次请求实时重算（第三层）。
        """
        from app.http import asgi_app as a

        admin, err = await a._resolve_admin_permission("agent_pool:read")
        if err is not None:
            return err

        from internal.schema.admin_agent_schema import (
            AdminAgentAssignablePermissionsResp,
        )
        from internal.service.admin_agent_service import AdminAgentService

        codes = await a._to_thread(
            a._get_service(AdminAgentService).list_assignable_permissions,
            admin_permissions=list(admin.get("permissions") or []),
        )
        resp = AdminAgentAssignablePermissionsResp()
        return a._ok(resp.dump({"codes": codes}))

    @quart_app.get("/admin/agents/boards")
    async def admin_agent_boards_list():
        """列出已登记的治理板块与动作。

        供前端渲染"这个 Agent 能做什么"，也是 `available_boards()` 的生产消费者。
        注意路径用 `boards` 而非 uuid，与 `/admin/agents/<uuid:agent_id>/*` 不冲突。
        """
        from app.http import asgi_app as a

        admin, err = await a._resolve_admin_permission("agent_pool:read")
        if err is not None:
            return err

        return a._ok(_list_board_actions())

    @quart_app.post("/admin/agents/<uuid:agent_id>/invoke")
    async def admin_agent_invoke(agent_id):
        """执行一个板块动作（管理端 Agent 治理，设计 §7.1 执行四步）。

        权限点由全局 RBAC 门禁强制为 `agent_pool:manage`（见 support.py）——
        执行入口代表"让 Agent 在后台动手"，不接受只读权限触发。

        本路由只做接线：把当前管理员的**实时权限**交给 `get_principal`
        重算三重交集，再把分流/执行/审计交给 `AdminAgentExecutionService`。
        """
        from app.http import asgi_app as a

        admin, err = await a._resolve_admin_permission("agent_pool:manage")
        if err is not None:
            return err

        from internal.schema.admin_agent_schema import AdminAgentInvokeReq
        from internal.service.admin_agent_service import AdminAgentService

        body = await request.get_json(force=True, silent=True) or {}
        form = AdminAgentInvokeReq()
        try:
            req = form.load(body)
        except Exception as exc:
            return a._json_resp(
                code="validate_error", message=f"参数错误: {exc}", status=400
            )

        admin_user_id = admin.get("id")
        admin_permissions = list(admin.get("permissions") or [])

        def _run():
            principal = a._get_service(AdminAgentService).get_principal(
                agent_id=agent_id,
                admin_user_id=admin_user_id,
                admin_permissions=admin_permissions,
            )
            if principal is None:
                return None
            execution = _build_execution_service(
                a,
                board_executor=_build_board_executor(),
                draft_service=_build_draft_service(a),
                audit_log_service=_build_audit_service(),
            )
            return execution.run(
                principal,
                board=req["board"],
                action=req["action"],
                payload=req.get("payload") or {},
            )

        try:
            result = await a._to_thread(_run)
        except PermissionError as exc:
            return a._json_resp(code="forbidden", message=str(exc), status=403)
        except ValueError as exc:
            return a._json_resp(code="validate_error", message=str(exc), status=400)
        if result is None:
            return a._json_resp(code="not_found", message="Agent 不存在", status=404)
        return a._ok(result)

    @quart_app.get("/admin/agents/<uuid:agent_id>/drafts")
    async def admin_agent_drafts(agent_id):
        """列出某 Agent 产出的待应用变更草稿（供后台「待批准变更」消费）。"""
        from app.http import asgi_app as a

        admin, err = await a._resolve_admin_permission("agent_pool:read")
        if err is not None:
            return err

        from internal.schema.admin_agent_schema import AdminAgentDraftListResp
        from internal.service.admin_agent_service import AdminAgentService

        admin_user_id = admin.get("id")

        def _run():
            agent = a._get_service(AdminAgentService).get_agent(
                agent_id=agent_id, admin_user_id=admin_user_id
            )
            if agent is None:
                return None
            rows = _build_draft_service(a).list_drafts(status="pending")
            # 草稿表用 impact.agent_id 记录提议者，据此做归属隔离
            mine = [
                d
                for d in rows
                if str((d.impact or {}).get("agent_id") or "") == str(agent_id)
            ]
            return {"items": [_dump_draft(d) for d in mine]}

        try:
            result = await a._to_thread(_run)
        except PermissionError as exc:
            return a._json_resp(code="forbidden", message=str(exc), status=403)
        if result is None:
            return a._json_resp(code="not_found", message="Agent 不存在", status=404)
        resp = AdminAgentDraftListResp()
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

    @quart_app.post("/admin/users")
    async def admin_customer_user_create():
        from app.http import asgi_app as a
        from internal.schema.admin_customer_user_schema import AdminCustomerUserResp
        from internal.service.admin_customer_user_service import AdminCustomerUserService

        payload = await request.get_json(force=True, silent=True) or {}
        email = str(payload.get("email") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not email:
            return a._json_resp(
                code="validate_error",
                message="邮箱不能为空",
                data={"email": ["邮箱不能为空"]},
                status=400,
            )
        if not name:
            return a._json_resp(
                code="validate_error",
                message="名称不能为空",
                data={"name": ["名称不能为空"]},
                status=400,
            )
        operator_id, ip, user_agent = await _operator_context()
        result = await a._to_thread(
            a._get_service(AdminCustomerUserService).create_customer_user,
            email=email,
            name=name,
            password=str(payload.get("password") or ""),
            username=str(payload.get("username") or "").strip(),
            phone=str(payload.get("phone") or "").strip(),
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminCustomerUserResp()
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

    @quart_app.patch("/admin/users/<uuid:account_id>")
    async def admin_customer_user_update(account_id):
        from app.http import asgi_app as a
        from internal.schema.admin_customer_user_schema import AdminCustomerUserResp
        from internal.service.admin_customer_user_service import AdminCustomerUserService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = await _operator_context()
        result = await a._to_thread(
            a._get_service(AdminCustomerUserService).update_customer_user,
            account_id,
            name=str(payload["name"]) if payload.get("name") is not None else None,
            email=str(payload["email"]) if payload.get("email") is not None else None,
            phone=str(payload["phone"]) if payload.get("phone") is not None else None,
            password=str(payload["password"]) if payload.get("password") is not None else None,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminCustomerUserResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/users/<uuid:account_id>/delete")
    async def admin_customer_user_delete(account_id):
        from app.http import asgi_app as a
        from internal.schema.admin_customer_user_schema import AdminCustomerUserResp
        from internal.service.admin_customer_user_service import AdminCustomerUserService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = await _operator_context()
        result = await a._to_thread(
            a._get_service(AdminCustomerUserService).delete_customer_user,
            account_id,
            reason=str(payload.get("reason") or ""),
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminCustomerUserResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/users/<uuid:account_id>/disable")
    async def admin_customer_user_disable(account_id):
        from app.http import asgi_app as a
        from internal.schema.admin_customer_user_schema import AdminCustomerUserResp
        from internal.service.admin_customer_user_service import AdminCustomerUserService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = await _operator_context()
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

        operator_id, ip, user_agent = await _operator_context()
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

        operator_id, ip, user_agent = await _operator_context()
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
        operator_id, ip, user_agent = await _operator_context()
        result = await a._to_thread(
            a._get_service(AdminBillingPlanService).create_plan,
            payload,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminPlanResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/billing-config")
    async def admin_billing_config_get():
        from app.http import asgi_app as a
        from internal.schema.admin_billing_config_schema import BillingConfigResp
        from internal.service.admin_billing_config_service import AdminBillingConfigService

        code = request.args.get("code") or None
        result = await a._to_thread(a._get_service(AdminBillingConfigService).get_config, code)
        resp = BillingConfigResp()
        return a._ok(resp.dump(result))

    @quart_app.put("/admin/billing-config")
    async def admin_billing_config_upsert():
        from app.http import asgi_app as a
        from internal.schema.admin_billing_config_schema import BillingConfigResp
        from internal.service.admin_billing_config_service import AdminBillingConfigService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = await _operator_context()
        result = await a._to_thread(
            a._get_service(AdminBillingConfigService).upsert_config,
            payload,
            code=payload.get("code") or None,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = BillingConfigResp()
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
        operator_id, ip, user_agent = await _operator_context()
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
        operator_id, ip, user_agent = await _operator_context()
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

    @quart_app.delete("/admin/plans/<uuid:plan_id>")
    async def admin_plan_delete(plan_id):
        from app.http import asgi_app as a
        from internal.schema.admin_billing_plan_schema import AdminPlanResp
        from internal.service.admin_billing_plan_service import AdminBillingPlanService

        operator_id, ip, user_agent = await _operator_context()
        result = await a._to_thread(
            a._get_service(AdminBillingPlanService).delete_plan,
            plan_id,
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

    # ------------------------------------------------------------------
    # admin_billing_reconciliation -> AdminBillingReconciliationService
    # ------------------------------------------------------------------
    @quart_app.get("/admin/billing-reconciliations")
    async def admin_billing_reconciliations_list():
        from app.http import asgi_app as a
        from internal.schema.admin_billing_reconciliation_schema import AdminReconciliationResp
        from internal.service.admin_billing_reconciliation_service import (
            AdminBillingReconciliationService,
        )

        current_page = max(int(request.args.get("current_page", 1) or 1), 1)
        page_size = max(int(request.args.get("page_size", 20) or 20), 1)
        alert = request.args.get("alert") or None
        result = await a._to_thread(
            a._get_service(AdminBillingReconciliationService).list_reconciliations,
            alert=alert,
            current_page=current_page,
            page_size=page_size,
        )
        resp = AdminReconciliationResp(many=True)
        return a._ok({"list": resp.dump(result["list"]), "paginator": result["paginator"]})

    @quart_app.get("/admin/billing-reconciliations/margin")
    async def admin_billing_reconciliations_margin():
        from app.http import asgi_app as a
        from internal.service.admin_billing_reconciliation_service import (
            AdminBillingReconciliationService,
        )

        result = await a._to_thread(
            a._get_service(AdminBillingReconciliationService).model_margin_summary
        )
        return a._ok(result)
