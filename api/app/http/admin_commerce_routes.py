"""Admin 商务路由（Quart）：分销/订单/售后/提现/支付配置/上级绑定。

通过 ``register_routes(quart_app)`` 注册；权限点来自 RBAC 迁移种子
（distribution/order/refund/withdraw/payment_config:*）。
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
    """写入管理员操作审计。note 仅作过程说明（AuditLog 无独立备注列）。"""
    from internal.extension.database_extension import db
    from internal.model.admin import AuditLog

    db.session.add(AuditLog(
        admin_user_id=admin_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else "",
        before_data=before_data or {},
        after_data=after_data or {},
        ip="",
        user_agent="",
    ))


async def _json_payload():
    from quart import request

    return await request.get_json(force=True, silent=True) or {}


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    # =====================================================
    # 分销管理
    # =====================================================
    @quart_app.get("/admin/distribution/overview")
    async def admin_distribution_overview():
        from app.http import asgi_app as a
        from internal.service.admin_distribution_service import AdminDistributionService

        admin, err = await a._resolve_admin_permission("distribution:view")
        if err is not None:
            return err
        result = await a._to_thread(a._get_service(AdminDistributionService).overview)
        return a._ok(result)

    @quart_app.get("/admin/distribution/relations")
    async def admin_distribution_relations():
        from app.http import asgi_app as a
        from internal.service.admin_distribution_service import AdminDistributionService

        admin, err = await a._resolve_admin_permission("distribution:view")
        if err is not None:
            return err
        result = await a._to_thread(
            a._get_service(AdminDistributionService).list_relations,
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
            str(request_args().get("inviter_id") or ""),
        )
        return a._ok(result)

    @quart_app.get("/admin/distribution/commissions")
    async def admin_distribution_commissions():
        from app.http import asgi_app as a
        from internal.service.distribution_service import DistributionService

        admin, err = await a._resolve_admin_permission("distribution:view")
        if err is not None:
            return err
        from uuid import UUID as U

        user_id = str(request_args().get("user_id") or "")
        account_id = None
        if user_id:
            try:
                account_id = U(user_id)
            except ValueError:
                return a._json_resp(code="validate_error", message="user_id 格式错误", status=400)
        result = await a._to_thread(
            a._get_service(DistributionService).list_commissions,
            account_id,
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
        )
        return a._ok(result)

    @quart_app.put("/admin/users/<user_id>/superior")
    async def admin_user_bind_superior(user_id: str):
        from app.http import asgi_app as a
        from internal.schema.admin_commerce_schema import SuperiorBindReq
        from internal.service.admin_distribution_service import AdminDistributionService

        admin, err = await a._resolve_admin_permission("distribution:manage")
        if err is not None:
            return err
        payload = await _json_payload()
        form = SuperiorBindReq(data=payload)
        if not form.validate():
            return a._json_resp(code="validate_error", message="参数错误", data=form.errors, status=400)
        invitee_id = UUID(user_id)
        inviter_id = payload.get("inviter_id")
        before = {}
        result = await a._to_thread(
            a._get_service(AdminDistributionService).bind_or_unbind_superior,
            invitee_id,
            UUID(inviter_id) if inviter_id else None,
            admin["id"],
        )
        _write_audit(admin["id"], "bind_superior" if inviter_id else "unbind_superior", "distribution_relation", invitee_id, before, result)
        return a._ok(result)

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