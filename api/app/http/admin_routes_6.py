"""admin 管理后台 Quart 异步端点（阶段 6）。

迁移来源：internal/handler/admin_auth_handler.py、admin_user_handler.py、
admin_routing_quality_handler.py 与 admin_tool_governance_handler.py；
路径与 HTTP 方法来源：internal/router/router.py 中对应的注册段。

register_routes(quart_app) 通过全局 guard 变量保证幂等注册。
"""

from uuid import UUID

from quart import request

_registered = False


def _int_arg(name, default):
    raw = request.args.get(name)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _extract_bearer_token():
    auth_header = request.headers.get("Authorization", "")
    if " " not in auth_header:
        return None
    token_type, token = auth_header.split(None, 1)
    if token_type.lower() != "bearer" or not token:
        return None
    return token


async def _resolve_admin_id():
    """从 Authorization header 解析当前管理员 id（无 token 或解析失败返回 None）。"""
    token = _extract_bearer_token()
    if not token:
        return None
    from app.http import asgi_app as a
    try:
        from internal.service.admin_user_service import AdminUserService

        admin = await a._to_thread(
            a._get_service(AdminUserService).get_current_admin_from_token, token
        )
        if isinstance(admin, dict):
            return admin.get("id")
        return getattr(admin, "id", None)
    except Exception:
        return None


async def _get_operator_context():
    """构造操作审计上下文 (operator_id, ip, user_agent)。"""
    operator_id = await _resolve_admin_id()
    remote_addr = getattr(request, "remote_addr", None) or ""
    return (
        operator_id,
        request.headers.get("X-Forwarded-For", remote_addr),
        request.headers.get("User-Agent", ""),
    )


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    # ===================== admin_auth =====================
    @quart_app.post("/admin/auth/login")
    async def admin_auth_login():
        from app.http import asgi_app as a
        from internal.schema.admin_auth_schema import AdminPasswordLoginResp
        from internal.service.admin_user_service import AdminUserService

        payload = await request.get_json(force=True, silent=True) or {}
        identifier = str(payload.get("identifier") or payload.get("email") or "").strip()
        password = str(payload.get("password") or "")
        if not identifier:
            return a._json_resp(
                code="validate_error",
                message="账号不能为空",
                data={"identifier": ["账号不能为空"]},
                status=400,
            )
        if not password:
            return a._json_resp(
                code="validate_error",
                message="密码不能为空",
                data={"password": ["密码不能为空"]},
                status=400,
            )
        x_forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        client_ip = x_forwarded or (request.remote_addr or "")
        user_agent = request.headers.get("User-Agent") or ""
        credential = await a._to_thread(
            a._get_service(AdminUserService).password_login,
            identifier,
            password,
            client_ip,
            user_agent,
        )
        return a._ok(AdminPasswordLoginResp().dump(credential))

    @quart_app.get("/admin/auth/me")
    async def admin_auth_me():
        from app.http import asgi_app as a
        from internal.service.admin_user_service import AdminUserService

        token = _extract_bearer_token()
        if token is None:
            return a._json_resp(
                code="unauthorized", message="管理员接口需要授权才能访问", data=None, status=401
            )
        admin_user = await a._to_thread(
            a._get_service(AdminUserService).get_current_admin_from_token, token
        )
        return a._ok(admin_user)

    @quart_app.post("/admin/auth/logout")
    async def admin_auth_logout():
        from app.http import asgi_app as a
        from internal.service.admin_user_service import AdminUserService

        token = _extract_bearer_token()
        if token is None:
            return a._json_resp(
                code="unauthorized", message="管理员接口需要授权才能访问", data=None, status=401
            )
        await a._to_thread(a._get_service(AdminUserService).logout, token)
        return a._ok_msg("退出登录成功")

    @quart_app.post("/admin/auth/password")
    async def admin_auth_change_password():
        from app.http import asgi_app as a
        from internal.service.admin_user_service import AdminUserService

        token = _extract_bearer_token()
        if token is None:
            return a._json_resp(
                code="unauthorized", message="管理员接口需要授权才能访问", data=None, status=401
            )
        payload = await request.get_json(force=True, silent=True) or {}
        current_password = str(payload.get("current_password") or "")
        new_password = str(payload.get("new_password") or "")
        if not current_password:
            return a._json_resp(
                code="validate_error",
                message="当前密码不能为空",
                data={"current_password": ["当前密码不能为空"]},
                status=400,
            )
        if not new_password:
            return a._json_resp(
                code="validate_error",
                message="新密码不能为空",
                data={"new_password": ["新密码不能为空"]},
                status=400,
            )
        current_admin = await a._to_thread(
            a._get_service(AdminUserService).get_current_admin_from_token, token
        )
        result = await a._to_thread(
            a._get_service(AdminUserService).change_own_password,
            current_admin["id"],
            current_password=current_password,
            new_password=new_password,
        )
        return a._ok(result)

    # ===================== admin_user =====================
    @quart_app.get("/admin/admin-users")
    async def admin_user_list():
        from app.http import asgi_app as a
        from internal.schema.admin_user_schema import AdminUserPageResp
        from internal.service.admin_user_service import AdminUserService

        result = await a._to_thread(
            a._get_service(AdminUserService).list_admin_users,
            search=request.args.get("search") or "",
            status=request.args.get("status") or "all",
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
        )
        resp = AdminUserPageResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/admin-users")
    async def admin_user_create():
        from app.http import asgi_app as a
        from internal.schema.admin_user_schema import AdminUserResp
        from internal.service.admin_user_service import AdminUserService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        password = str(payload.get("password") or "")
        if not name:
            return a._json_resp(
                code="validate_error",
                message="名称不能为空",
                data={"name": ["名称不能为空"]},
                status=400,
            )
        if not password:
            return a._json_resp(
                code="validate_error",
                message="密码不能为空",
                data={"password": ["密码不能为空"]},
                status=400,
            )
        operator_id, ip, user_agent = await _get_operator_context()
        result = await a._to_thread(
            a._get_service(AdminUserService).create_admin_user,
            email=str(payload.get("email") or ""),
            name=name,
            password=password,
            role_codes=payload.get("role_codes", []) or [],
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminUserResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/admin-users/<uuid:admin_id>")
    async def admin_user_get(admin_id):
        from app.http import asgi_app as a
        from internal.schema.admin_user_schema import AdminUserResp
        from internal.service.admin_user_service import AdminUserService

        result = await a._to_thread(
            a._get_service(AdminUserService).get_admin_user, admin_id
        )
        resp = AdminUserResp()
        return a._ok(resp.dump(result))

    @quart_app.patch("/admin/admin-users/<uuid:admin_id>")
    async def admin_user_update(admin_id):
        from app.http import asgi_app as a
        from internal.schema.admin_user_schema import AdminUserResp
        from internal.service.admin_user_service import AdminUserService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = await _get_operator_context()
        result = await a._to_thread(
            a._get_service(AdminUserService).update_admin_user,
            admin_id,
            name=str(payload["name"]) if payload.get("name") is not None else None,
            email=str(payload["email"]) if payload.get("email") is not None else None,
            status=str(payload["status"]) if payload.get("status") is not None else None,
            role_codes=payload.get("role_codes") if "role_codes" in payload else None,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminUserResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/admin-users/<uuid:admin_id>/disable")
    async def admin_user_disable(admin_id):
        from app.http import asgi_app as a
        from internal.service.admin_user_service import AdminUserService

        operator_id, ip, user_agent = await _get_operator_context()
        await a._to_thread(
            a._get_service(AdminUserService).disable_admin_user,
            admin_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        return a._ok_msg("禁用管理员成功")

    @quart_app.post("/admin/admin-users/<uuid:admin_id>/enable")
    async def admin_user_enable(admin_id):
        from app.http import asgi_app as a
        from internal.schema.admin_user_schema import AdminUserResp
        from internal.service.admin_user_service import AdminUserService

        operator_id, ip, user_agent = await _get_operator_context()
        result = await a._to_thread(
            a._get_service(AdminUserService).enable_admin_user,
            admin_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminUserResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/admin-users/<uuid:admin_id>/reset-password")
    async def admin_user_reset_password(admin_id):
        from app.http import asgi_app as a
        from internal.schema.admin_user_schema import AdminUserResp
        from internal.service.admin_user_service import AdminUserService

        payload = await request.get_json(force=True, silent=True) or {}
        password = str(payload.get("password") or "")
        if not password:
            return a._json_resp(
                code="validate_error",
                message="密码不能为空",
                data={"password": ["密码不能为空"]},
                status=400,
            )
        operator_id, ip, user_agent = await _get_operator_context()
        result = await a._to_thread(
            a._get_service(AdminUserService).reset_admin_user_password,
            admin_id,
            password=password,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminUserResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/admin-users/<uuid:admin_id>/sessions/revoke")
    async def admin_user_revoke_sessions(admin_id):
        from app.http import asgi_app as a
        from internal.schema.admin_user_schema import RevokeAdminUserSessionsResp
        from internal.service.admin_user_service import AdminUserService

        operator_id, ip, user_agent = await _get_operator_context()
        result = await a._to_thread(
            a._get_service(AdminUserService).revoke_admin_sessions,
            admin_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = RevokeAdminUserSessionsResp()
        return a._ok(resp.dump(result))

    # ===================== admin_routing_quality =====================
    @quart_app.post("/admin/routing-quality/feedback")
    async def admin_routing_quality_feedback_create():
        from app.http import asgi_app as a
        from internal.schema.admin_routing_quality_schema import RoutingQualityFeedbackResp
        from internal.service.routing_quality_feedback_service import (
            RoutingQualityFeedbackService,
        )

        data = await request.get_json(force=True, silent=True) or {}
        required_fields = ["routing_log_id", "rating"]
        if any(field not in data for field in required_fields):
            return a._json_resp(
                code="validate_error",
                message="Missing required data",
                data={"routing_log_id": ["Missing required data"]},
                status=400,
            )
        admin_id = await _resolve_admin_id()
        try:
            result = await a._to_thread(
                a._get_service(RoutingQualityFeedbackService).create_feedback,
                routing_log_id=UUID(str(data["routing_log_id"])),
                source="admin",
                rating=int(data["rating"]),
                dimension_scores=data.get("dimension_scores") or {},
                comment=data.get("comment") or "",
                metadata=data.get("metadata") or {},
                created_by=UUID(str(admin_id)) if admin_id else None,
            )
        except (TypeError, ValueError) as exc:
            return a._json_resp(code="fail", message=str(exc), data=None, status=400)
        return a._ok(RoutingQualityFeedbackResp().dump(result))

    @quart_app.get("/admin/routing-quality/feedback")
    async def admin_routing_quality_feedback_list():
        from app.http import asgi_app as a
        from internal.schema.admin_routing_quality_schema import RoutingQualityFeedbackResp
        from internal.service.routing_quality_feedback_service import (
            RoutingQualityFeedbackService,
        )

        routing_log_id = request.args.get("routing_log_id")
        result = await a._to_thread(
            a._get_service(RoutingQualityFeedbackService).list_feedback,
            routing_log_id=UUID(routing_log_id) if routing_log_id else None,
            source=request.args.get("source"),
            page=_int_arg("page", 1),
            page_size=_int_arg("page_size", 20),
        )
        return a._ok(RoutingQualityFeedbackResp(many=True).dump(result))

    @quart_app.get("/admin/routing-quality/metrics")
    async def admin_routing_quality_metrics():
        from app.http import asgi_app as a
        from internal.schema.admin_routing_quality_schema import RoutingQualityMetricsResp
        from internal.service.routing_quality_metrics_service import (
            RoutingQualityMetricsService,
        )

        metrics = await a._to_thread(
            a._get_service(RoutingQualityMetricsService).build_metrics
        )
        return a._ok(RoutingQualityMetricsResp().dump(metrics))

    @quart_app.get("/admin/routing-quality/suggestions")
    async def admin_routing_quality_suggestions():
        from app.http import asgi_app as a
        from internal.schema.admin_routing_quality_schema import (
            RoutingOptimizationSuggestionResp,
        )
        from internal.service.routing_optimization_suggestion_service import (
            RoutingOptimizationSuggestionService,
        )
        from internal.service.routing_quality_metrics_service import (
            RoutingQualityMetricsService,
        )

        status = request.args.get("status", "")
        if status:
            suggestions = await a._to_thread(
                a._get_service(RoutingOptimizationSuggestionService).list_suggestions,
                status=status,
            )
        else:
            metrics = await a._to_thread(
                a._get_service(RoutingQualityMetricsService).build_metrics
            )
            suggestions = await a._to_thread(
                a._get_service(RoutingOptimizationSuggestionService).generate_suggestions,
                metrics,
            )
        return a._ok(RoutingOptimizationSuggestionResp(many=True).dump(suggestions))

    @quart_app.post("/admin/routing-quality/suggestions/<uuid:suggestion_id>/accept")
    async def admin_routing_quality_suggestion_accept(suggestion_id):
        from app.http import asgi_app as a
        from internal.schema.admin_routing_quality_schema import SuggestionActionResp
        from internal.service.routing_optimization_suggestion_service import (
            RoutingOptimizationSuggestionService,
        )

        admin_id = await _resolve_admin_id()
        try:
            result = await a._to_thread(
                a._get_service(RoutingOptimizationSuggestionService).accept_suggestion,
                suggestion_id,
                admin_id,
            )
        except Exception as exc:
            return a._json_resp(code="fail", message=str(exc), data=None, status=400)
        return a._ok(SuggestionActionResp().dump(result))

    @quart_app.post("/admin/routing-quality/suggestions/<uuid:suggestion_id>/dismiss")
    async def admin_routing_quality_suggestion_dismiss(suggestion_id):
        from app.http import asgi_app as a
        from internal.schema.admin_routing_quality_schema import SuggestionActionResp
        from internal.service.routing_optimization_suggestion_service import (
            RoutingOptimizationSuggestionService,
        )

        payload = await request.get_json(force=True, silent=True) or {}
        admin_id = await _resolve_admin_id()
        try:
            result = await a._to_thread(
                a._get_service(RoutingOptimizationSuggestionService).dismiss_suggestion,
                suggestion_id,
                admin_id,
                payload.get("reason", ""),
            )
        except Exception as exc:
            return a._json_resp(code="fail", message=str(exc), data=None, status=400)
        return a._ok(SuggestionActionResp().dump(result))

    @quart_app.get("/admin/routing-quality/suggestions/<uuid:suggestion_id>/preview")
    async def admin_routing_quality_suggestion_preview(suggestion_id):
        from app.http import asgi_app as a
        from internal.schema.admin_routing_quality_schema import PolicyChangePreviewResp
        from internal.service.routing_policy_change_service import (
            RoutingPolicyChangeService,
        )

        try:
            preview = await a._to_thread(
                a._get_service(RoutingPolicyChangeService).generate_preview, suggestion_id
            )
        except Exception as exc:
            return a._json_resp(code="fail", message=str(exc), data=None, status=400)
        return a._ok(PolicyChangePreviewResp().dump(preview))

    @quart_app.post("/admin/routing-quality/suggestions/<uuid:suggestion_id>/apply")
    async def admin_routing_quality_suggestion_apply(suggestion_id):
        from app.http import asgi_app as a
        from internal.service.routing_policy_change_service import (
            RoutingPolicyChangeService,
        )

        data = await request.get_json(force=True, silent=True) or {}
        admin_id = await _resolve_admin_id()
        try:
            result = await a._to_thread(
                a._get_service(RoutingPolicyChangeService).apply_draft,
                suggestion_id,
                admin_id,
                data,
            )
        except Exception as exc:
            return a._json_resp(code="fail", message=str(exc), data=None, status=400)
        return a._ok(result)

    @quart_app.get("/admin/routing-quality/policy-changes")
    async def admin_routing_quality_policy_change_list():
        from app.http import asgi_app as a
        from internal.schema.admin_routing_quality_schema import PolicyChangeListResp
        from internal.service.routing_policy_change_service import (
            RoutingPolicyChangeService,
        )

        status = request.args.get("status", "")
        drafts = await a._to_thread(
            a._get_service(RoutingPolicyChangeService).list_drafts, status=status
        )
        return a._ok(PolicyChangeListResp().dump({"items": drafts, "total": len(drafts)}))

    @quart_app.post("/admin/routing-quality/policy-changes/<uuid:draft_id>/rollback")
    async def admin_routing_quality_policy_change_rollback(draft_id):
        from app.http import asgi_app as a
        from internal.service.routing_policy_change_service import (
            RoutingPolicyChangeService,
        )

        data = await request.get_json(force=True, silent=True) or {}
        admin_id = await _resolve_admin_id()
        try:
            result = await a._to_thread(
                a._get_service(RoutingPolicyChangeService).rollback_draft,
                draft_id,
                admin_id,
                data.get("reason", ""),
            )
        except Exception as exc:
            return a._json_resp(code="fail", message=str(exc), data=None, status=400)
        return a._ok(result)

    # ===================== admin_tool_governance =====================
    @quart_app.get("/admin/tool-governance")
    async def admin_tool_governance_list():
        from app.http import asgi_app as a
        from internal.schema.admin_tool_governance_schema import (
            AdminToolGovernancePolicyPageResp,
        )
        from internal.service.admin_tool_governance_service import (
            AdminToolGovernanceService,
        )

        result = await a._to_thread(
            a._get_service(AdminToolGovernanceService).list_policies,
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
            source_type=request.args.get("source_type") or "",
            risk_level=request.args.get("risk_level") or "",
            visibility=request.args.get("visibility") or "",
            enabled=request.args.get("enabled") or None,
            keyword=request.args.get("keyword") or "",
        )
        resp = AdminToolGovernancePolicyPageResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/tool-governance")
    async def admin_tool_governance_create():
        from app.http import asgi_app as a
        from internal.schema.admin_tool_governance_schema import (
            AdminToolGovernancePolicyResp,
        )
        from internal.service.admin_tool_governance_service import (
            AdminToolGovernanceService,
        )

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminToolGovernanceService).create_policy, payload
        )
        resp = AdminToolGovernancePolicyResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/tool-governance/<uuid:policy_id>")
    async def admin_tool_governance_get(policy_id):
        from app.http import asgi_app as a
        from internal.schema.admin_tool_governance_schema import (
            AdminToolGovernancePolicyResp,
        )
        from internal.service.admin_tool_governance_service import (
            AdminToolGovernanceService,
        )

        result = await a._to_thread(
            a._get_service(AdminToolGovernanceService).get_policy, policy_id
        )
        resp = AdminToolGovernancePolicyResp()
        return a._ok(resp.dump(result))

    @quart_app.patch("/admin/tool-governance/<uuid:policy_id>")
    async def admin_tool_governance_update(policy_id):
        from app.http import asgi_app as a
        from internal.schema.admin_tool_governance_schema import (
            AdminToolGovernancePolicyResp,
        )
        from internal.service.admin_tool_governance_service import (
            AdminToolGovernanceService,
        )

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminToolGovernanceService).update_policy, policy_id, payload
        )
        resp = AdminToolGovernancePolicyResp()
        return a._ok(resp.dump(result))

    @quart_app.delete("/admin/tool-governance/<uuid:policy_id>")
    async def admin_tool_governance_delete(policy_id):
        from app.http import asgi_app as a
        from internal.service.admin_tool_governance_service import (
            AdminToolGovernanceService,
        )

        await a._to_thread(
            a._get_service(AdminToolGovernanceService).delete_policy, policy_id
        )
        return a._ok_msg("删除工具治理策略成功")

    @quart_app.post("/admin/tool-governance/<uuid:policy_id>/status")
    async def admin_tool_governance_status(policy_id):
        from app.http import asgi_app as a
        from internal.schema.admin_tool_governance_schema import (
            AdminToolGovernancePolicyResp,
        )
        from internal.service.admin_tool_governance_service import (
            AdminToolGovernanceService,
        )

        payload = await request.get_json(force=True, silent=True) or {}
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            return a._json_resp(
                code="validate_error",
                message="enabled 必须为布尔值",
                data={"enabled": ["enabled 必须为布尔值"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(AdminToolGovernanceService).set_enabled, policy_id, enabled
        )
        resp = AdminToolGovernancePolicyResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/tool-governance/batch-risk")
    async def admin_tool_governance_batch_risk():
        from app.http import asgi_app as a
        from internal.schema.admin_tool_governance_schema import (
            AdminToolGovernanceBatchRiskResp,
        )
        from internal.service.admin_tool_governance_service import (
            AdminToolGovernanceService,
        )

        payload = await request.get_json(force=True, silent=True) or {}
        policy_ids = payload.get("policy_ids")
        risk_level = payload.get("risk_level")
        if not policy_ids:
            return a._json_resp(
                code="validate_error",
                message="policy_ids不能为空",
                data={"policy_ids": ["policy_ids不能为空"]},
                status=400,
            )
        if not risk_level:
            return a._json_resp(
                code="validate_error",
                message="risk_level不能为空",
                data={"risk_level": ["risk_level不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(AdminToolGovernanceService).batch_update_risk,
            policy_ids,
            risk_level,
        )
        resp = AdminToolGovernanceBatchRiskResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/tool-governance/audit")
    async def admin_tool_governance_audit():
        from app.http import asgi_app as a
        from internal.schema.admin_tool_governance_schema import (
            AdminToolGovernanceAuditPageResp,
        )
        from internal.service.admin_tool_governance_service import (
            AdminToolGovernanceService,
        )

        result = await a._to_thread(
            a._get_service(AdminToolGovernanceService).list_audit_logs,
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
            tool_id=request.args.get("tool_id") or "",
            status=request.args.get("status") or "",
            start_date=request.args.get("start_date") or "",
            end_date=request.args.get("end_date") or "",
        )
        resp = AdminToolGovernanceAuditPageResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/tool-governance/stats")
    async def admin_tool_governance_stats():
        from app.http import asgi_app as a
        from internal.schema.admin_tool_governance_schema import (
            AdminToolGovernanceStatsResp,
        )
        from internal.service.admin_tool_governance_service import (
            AdminToolGovernanceService,
        )

        result = await a._to_thread(
            a._get_service(AdminToolGovernanceService).get_governance_stats
        )
        resp = AdminToolGovernanceStatsResp()
        return a._ok(resp.dump(result))
