"""Admin 商务路由（Quart）：订单/售后/提现/支付配置。

通过 ``register_routes(quart_app)`` 注册；权限点来自 RBAC 迁移种子
（order/refund/withdraw/payment_config:*）。

注意：管理端**不提供分销能力**——分销上下级绑定是用户端独有功能
（管理员若需使用分销应走用户端注册账号）。此处不注册任何 distribution/* 端点，
分销开关的启停统一由「编排控制」页的功能开关（ENABLE_DISTRIBUTION）管理。
"""

from uuid import UUID

_registered = False


def _int_arg(name, default):
    from quart import request

    raw = request.args.get(name)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _write_audit(admin_id, action, resource_type, resource_id, before_data, after_data, note=None):
    """写入管理员操作审计。note 归入 after_data（AuditLog 无独立备注列）。

    必须用 `commit=True`（而非直接 db.session.add 后不管）：本函数运行在
    **事件循环线程**，与线程池 worker 的 session 不是同一个；且 asgi teardown
    只做 `remove()` 不提交，业务事务的提交不会捎带这条审计。历史上此处 4 类
    审计（关单 / 提现 / 退款 / 支付配置）因此全部丢失。

    走 AuditLogService 而非直接构造 AuditLog，可复用统一的空值保护与序列化。
    """
    from internal.service.audit_log_service import AuditLogService

    merged_after = dict(after_data or {})
    if note:
        merged_after.setdefault("_note", note)
    AuditLogService().record(
        admin_user_id=admin_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else "",
        before_data=before_data,
        after_data=merged_after,
        commit=True,
    )


async def _json_payload():
    from quart import request

    return await request.get_json(force=True, silent=True) or {}


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    # =====================================================
    # 订单管理
    # =====================================================
    @quart_app.get("/admin/orders")
    async def admin_order_list():
        from app.http import asgi_app as a
        from internal.service.admin_order_service import AdminOrderService

        admin, err = await a._resolve_admin_permission("order:view")
        if err is not None:
            return err
        result = await a._to_thread(
            a._get_service(AdminOrderService).list_all,
            str(request_args().get("status") or ""),
            str(request_args().get("order_source") or ""),
            str(request_args().get("account_id") or ""),
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
        )
        return a._ok(result)

    @quart_app.get("/admin/orders/<order_id>")
    async def admin_order_detail(order_id: str):
        from app.http import asgi_app as a
        from internal.service.admin_order_service import AdminOrderService

        admin, err = await a._resolve_admin_permission("order:view")
        if err is not None:
            return err
        result = await a._to_thread(a._get_service(AdminOrderService).detail, UUID(order_id))
        return a._ok(result)

    @quart_app.post("/admin/orders/<order_id>/close")
    async def admin_order_close(order_id: str):
        from app.http import asgi_app as a
        from internal.service.admin_order_service import AdminOrderService

        admin, err = await a._resolve_admin_permission("order:manage")
        if err is not None:
            return err
        result = await a._to_thread(a._get_service(AdminOrderService).close, UUID(order_id))
        _write_audit(admin["id"], "close_order", "purchase_order", order_id, {}, result)
        return a._ok(result)

    # =====================================================
    # 提现审核
    # =====================================================
    @quart_app.get("/admin/withdrawals")
    async def admin_withdrawal_list():
        from app.http import asgi_app as a
        from internal.service.withdrawal_service import WithdrawalService

        admin, err = await a._resolve_admin_permission("withdraw:view")
        if err is not None:
            return err
        result = await a._to_thread(
            a._get_service(WithdrawalService).list_all,
            str(request_args().get("status") or ""),
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
        )
        return a._ok(result)

    @quart_app.post("/admin/withdrawals/<withdraw_id>/<action>")
    async def admin_withdrawal_review(withdraw_id: str, action: str):
        from app.http import asgi_app as a
        from internal.service.withdrawal_service import WithdrawalService

        admin, err = await a._resolve_admin_permission("withdraw:manage")
        if err is not None:
            return err
        payload = await _json_payload()
        note = str((payload or {}).get("note") or "")
        service = a._get_service(WithdrawalService)
        if action == "approve":
            row = await a._to_thread(service.approve, UUID(withdraw_id), admin["id"], note)
        elif action == "reject":
            row = await a._to_thread(service.reject, UUID(withdraw_id), admin["id"], note)
        else:
            return a._json_resp(code="validate_error", message="不支持的操作", status=400)
        _write_audit(admin["id"], f"withdraw_{action}", "withdrawal_request", withdraw_id, {}, {"status": row.status}, note)
        return a._ok({"id": str(row.id), "status": row.status})

    # =====================================================
    # 售后管理
    # =====================================================
    @quart_app.get("/admin/refunds")
    async def admin_refund_list():
        from app.http import asgi_app as a
        from internal.service.refund_service import RefundService

        admin, err = await a._resolve_admin_permission("refund:view")
        if err is not None:
            return err
        result = await a._to_thread(
            a._get_service(RefundService).list_all,
            str(request_args().get("status") or ""),
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
        )
        return a._ok(result)

    @quart_app.post("/admin/refunds/<refund_id>/<action>")
    async def admin_refund_review(refund_id: str, action: str):
        from app.http import asgi_app as a
        from internal.service.refund_service import RefundService

        admin, err = await a._resolve_admin_permission("refund:manage")
        if err is not None:
            return err
        payload = await _json_payload()
        note = str((payload or {}).get("note") or "")
        service = a._get_service(RefundService)
        if action == "approve":
            row = await a._to_thread(service.approve, UUID(refund_id), admin["id"], note)
        elif action == "reject":
            row = await a._to_thread(service.reject, UUID(refund_id), admin["id"], note)
        else:
            return a._json_resp(code="validate_error", message="不支持的操作", status=400)
        _write_audit(admin["id"], f"refund_{action}", "return_request", refund_id, {}, {"status": row.status}, note)
        return a._ok({"id": str(row.id), "status": row.status})

    # =====================================================
    # 支付配置
    # =====================================================
    @quart_app.get("/admin/payment-configs")
    async def admin_payment_config_list():
        from app.http import asgi_app as a
        from internal.service.payment_config_service import PaymentConfigService

        admin, err = await a._resolve_admin_permission("payment_config:read")
        if err is not None:
            return err
        service = a._get_service(PaymentConfigService)
        await a._to_thread(service.ensure_defaults)
        result = await a._to_thread(service.list_sanitized)
        return a._ok({"list": result})

    @quart_app.put("/admin/payment-configs/<provider>")
    async def admin_payment_config_upsert(provider: str):
        from app.http import asgi_app as a
        from internal.service.payment_config_service import PaymentConfigService

        admin, err = await a._resolve_admin_permission("payment_config:manage")
        if err is not None:
            return err
        payload = await _json_payload()
        config = await a._to_thread(
            a._get_service(PaymentConfigService).upsert,
            provider,
            str((payload or {}).get("name") or ""),
            (payload or {}).get("configs") or {},
            admin["id"],
        )
        return a._ok({"provider": config.provider, "enabled": bool(config.enabled)})

    @quart_app.post("/admin/payment-configs/<provider>/enabled")
    async def admin_payment_config_enabled(provider: str):
        from app.http import asgi_app as a
        from internal.service.payment_config_service import PaymentConfigService

        admin, err = await a._resolve_admin_permission("payment_config:manage")
        if err is not None:
            return err
        payload = await _json_payload()
        enabled = bool((payload or {}).get("enabled"))
        config = await a._to_thread(
            a._get_service(PaymentConfigService).set_enabled,
            provider,
            enabled,
            admin["id"],
        )
        _write_audit(admin["id"], "payment_config_enabled", "payment_provider_config", provider, {}, {"enabled": enabled})
        return a._ok({"provider": config.provider, "enabled": bool(config.enabled)})


def request_args():
    from quart import request

    return request.args