"""用户侧商务路由（Quart）：分销、余额、订单、提现、售后、自动续费、支付。

通过 ``register_routes(quart_app)`` 注册；模块级 ``_registered`` 保证幂等。
本文件按里程碑分批扩充（P3/P4 分销 → P5 订单/支付 → P6 自动续费 → P7 提现/售后）。
"""

import time

from quart import Response, request

_registered = False


def _int_arg(name, default):
    raw = request.args.get(name)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    # =====================================================
    # 可购套餐列表（用户侧，仅 active）
    # =====================================================
    @quart_app.get("/plans")
    async def commerce_plans():
        from app.http import asgi_app as a
        from internal.model.billing import Plan
        from internal.service.balance_service import BalanceService

        def _load():
            rows = (
                a._get_service(BalanceService).session.query(Plan)
                .filter(Plan.status == "active", Plan.deleted_at.is_(None))
                .order_by(Plan.sort_order.asc())
                .all()
            )
            return {
                "list": [
                    {
                        "id": str(plan.id),
                        "code": plan.code,
                        "name": plan.name,
                        "description": plan.description or "",
                        "plan_type": plan.plan_type or "membership",
                        "duration_days": int(plan.duration_days or 0),
                        "grant_token_credits": int(plan.grant_token_credits or 0),
                        "price": float(plan.price or 0),
                        "auto_renew_threshold_percent": int(plan.auto_renew_threshold_percent or 5),
                        "auto_renew_threshold_days": int(plan.auto_renew_threshold_days or 1),
                        "purchase_limit": int(plan.purchase_limit or 0),
                        "purchase_limit_period": (plan.purchase_limit_period or "none").strip().lower(),
                        "quota_refresh_period": (plan.quota_refresh_period or "none").strip().lower(),
                        "auto_renew_default": bool(plan.auto_renew_default),
                        "status": plan.status or "active",
                    }
                    for plan in rows
                ]
            }

        result = await a._to_thread(_load)
        return a._ok(result)

    # =====================================================
    # 分销中心
    # =====================================================
    @quart_app.get("/distribution/me")
    async def distribution_me():
        from app.http import asgi_app as a
        from internal.schema.distribution_schema import MyDistributionResp
        from internal.service.distribution_service import DistributionService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        base_url = request.host_url
        result = await a._to_thread(
            a._get_service(DistributionService).my_distribution_summary,
            account.id,
            base_url,
        )
        return a._ok(MyDistributionResp().dump(result))

    @quart_app.get("/distribution/subordinates")
    async def distribution_subordinates():
        from app.http import asgi_app as a
        from internal.schema.distribution_schema import SubordinateListResp
        from internal.service.distribution_service import DistributionService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        result = await a._to_thread(
            a._get_service(DistributionService).list_subordinates,
            account.id,
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
        )
        return a._ok(SubordinateListResp().dump(result))

    @quart_app.get("/distribution/commissions")
    async def distribution_commissions():
        from app.http import asgi_app as a
        from internal.schema.distribution_schema import CommissionListResp
        from internal.service.distribution_service import DistributionService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        result = await a._to_thread(
            a._get_service(DistributionService).list_commissions,
            account.id,
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
        )
        return a._ok(CommissionListResp().dump(result))

    @quart_app.put("/distribution/referral-code")
    async def distribution_update_referral_code():
        from app.http import asgi_app as a
        from internal.schema.distribution_schema import MyDistributionResp
        from internal.service.distribution_service import DistributionService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = await request.get_json(force=True, silent=True) or {}
        code = str(payload.get("code") or "").strip()
        if not code:
            return a._json_resp(
                code="validate_error",
                message="邀请码不能为空",
                data={"code": ["邀请码不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(DistributionService).update_referral_code,
            account.id,
            code,
        )
        base_url = request.host_url
        summary = await a._to_thread(
            a._get_service(DistributionService).my_distribution_summary,
            account.id,
            base_url,
        )
        return a._ok(MyDistributionResp().dump(summary))

    @quart_app.get("/distribution/qrcode")
    async def distribution_qrcode():
        """返回分享二维码 PNG；qrcode 库未安装时返回分享链接文本。"""
        from app.http import asgi_app as a
        from internal.service.distribution_service import DistributionService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        base_url = request.host_url
        summary = await a._to_thread(
            a._get_service(DistributionService).my_distribution_summary,
            account.id,
            base_url,
        )
        try:
            import io

            import qrcode

            image = qrcode.make(summary["share_url"], box_size=6, border=2)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return a.Response(
                buffer.getvalue(),
                mimetype="image/png",
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            return a._ok({"share_url": summary["share_url"]})

    # =====================================================
    # 余额概览
    # =====================================================
    @quart_app.get("/account/balance")
    async def account_balance():
        from app.http import asgi_app as a
        from internal.model.billing import CreditAccount
        from internal.service.balance_service import BalanceService

        account, err = await a._resolve_account()
        if err is not None:
            return err

        def _load():
            profile = a._get_service(BalanceService).profile(account.id)
            credit = (
                a._get_service(BalanceService).session.query(CreditAccount)
                .filter(CreditAccount.account_id == account.id)
                .one_or_none()
            )
            profile["quota_credit"] = int(credit.quota_credit or 0) if credit else 0
            profile["permanent_credit"] = int(credit.permanent_credit or 0) if credit else 0
            return profile

        result = await a._to_thread(_load)
        return a._ok(result)

    # =====================================================
    # 提现
    # =====================================================
    @quart_app.post("/balance/withdraw")
    async def balance_withdraw():
        from app.http import asgi_app as a
        from internal.schema.withdraw_schema import WithdrawResp
        from internal.service.withdrawal_service import WithdrawalService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = await request.get_json(force=True, silent=True) or {}
        amount = str(payload.get("amount") or "").strip()
        if not amount:
            return a._json_resp(code="validate_error", message="提现金额不能为空", data={"amount": ["提现金额不能为空"]}, status=400)
        row = await a._to_thread(a._get_service(WithdrawalService).create, account.id, amount)
        return a._ok(WithdrawResp().dump({
            "id": str(row.id),
            "account_id": str(row.account_id),
            "amount": float(row.amount),
            "status": row.status,
            "review_note": row.review_note,
            "created_at": None,
        }))

    @quart_app.get("/balance/withdrawals")
    async def balance_withdrawals():
        from app.http import asgi_app as a
        from internal.schema.withdraw_schema import WithdrawListResp
        from internal.service.withdrawal_service import WithdrawalService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        result = await a._to_thread(
            a._get_service(WithdrawalService).list_mine,
            account.id,
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
        )
        return a._ok(WithdrawListResp().dump(result))

    @quart_app.post("/balance/withdrawals/<withdraw_id>/cancel")
    async def balance_withdraw_cancel(withdraw_id: str):
        from app.http import asgi_app as a
        from internal.schema.withdraw_schema import WithdrawResp
        from internal.service.withdrawal_service import WithdrawalService
        from uuid import UUID

        account, err = await a._resolve_account()
        if err is not None:
            return err
        row = await a._to_thread(a._get_service(WithdrawalService).cancel, account.id, UUID(withdraw_id))
        return a._ok(WithdrawResp().dump({
            "id": str(row.id),
            "account_id": str(row.account_id),
            "amount": float(row.amount),
            "status": row.status,
            "review_note": row.review_note,
            "created_at": None,
        }))

    # =====================================================
    # 售后退款
    # =====================================================
    @quart_app.post("/refunds")
    async def refund_create():
        from app.http import asgi_app as a
        from internal.service.refund_service import RefundService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = await request.get_json(force=True, silent=True) or {}
        order_no = str(payload.get("order_no") or "").strip()
        if not order_no:
            return a._json_resp(code="validate_error", message="订单号不能为空", data={"order_no": ["订单号不能为空"]}, status=400)
        refund = await a._to_thread(
            a._get_service(RefundService).create,
            account.id,
            order_no,
            str(payload.get("reason") or "").strip(),
        )
        return a._ok({"id": str(refund.id), "order_no": order_no, "status": refund.status})

    @quart_app.get("/refunds")
    async def refund_list():
        from app.http import asgi_app as a
        from internal.schema.order_schema import RefundListResp
        from internal.service.refund_service import RefundService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        result = await a._to_thread(
            a._get_service(RefundService).list_mine,
            account.id,
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
        )
        return a._ok(RefundListResp().dump(result))

    # =====================================================
    # 自动续费 / 连续包月
    # =====================================================
    @quart_app.post("/auto-renewals")
    async def auto_renewal_create():
        from app.http import asgi_app as a
        from internal.service.auto_renewal_service import AutoRenewalService
        from uuid import UUID

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = await request.get_json(force=True, silent=True) or {}
        plan_id = str(payload.get("plan_id") or "").strip()
        pay_method = str(payload.get("pay_method") or "balance").strip()
        if not plan_id:
            return a._json_resp(code="validate_error", message="套餐不能为空", data={"plan_id": ["套餐不能为空"]}, status=400)
        renewal = await a._to_thread(
            a._get_service(AutoRenewalService).create,
            account.id,
            UUID(plan_id),
            pay_method,
        )
        return a._ok({
            "id": str(renewal.id),
            "plan_id": str(renewal.plan_id),
            "plan_type": renewal.plan_type,
            "pay_method": renewal.pay_method,
            "status": renewal.status,
        })

    @quart_app.get("/auto-renewals")
    async def auto_renewal_list():
        from app.http import asgi_app as a
        from internal.schema.auto_renewal_schema import AutoRenewalListResp
        from internal.service.auto_renewal_service import AutoRenewalService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        rows = await a._to_thread(a._get_service(AutoRenewalService).list_mine, account.id)
        return a._ok(AutoRenewalListResp().dump({"list": rows}))

    @quart_app.post("/auto-renewals/<renewal_id>/<action>")
    async def auto_renewal_action(renewal_id: str, action: str):
        from app.http import asgi_app as a
        from internal.service.auto_renewal_service import AutoRenewalService
        from uuid import UUID

        account, err = await a._resolve_account()
        if err is not None:
            return err
        if action not in ("pause", "resume", "cancel"):
            return a._json_resp(code="validate_error", message="不支持的操作", status=400)
        renewal = await a._to_thread(
            a._get_service(AutoRenewalService).set_status,
            account.id,
            UUID(renewal_id),
            action,
        )
        return a._ok({"id": str(renewal.id), "status": renewal.status})

    # =====================================================
    # 统一订单 + 在线支付（预留）
    # =====================================================
    @quart_app.post("/orders")
    async def order_create():
        from app.http import asgi_app as a
        from internal.schema.order_schema import OrderCreateResultResp, OrderResp
        from internal.service.order_service import OrderService
        from uuid import UUID

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = await request.get_json(force=True, silent=True) or {}
        plan_id = str(payload.get("plan_id") or "").strip()
        pay_method = str(payload.get("pay_method") or "").strip()
        if not plan_id or not pay_method:
            return a._json_resp(
                code="validate_error",
                message="套餐与支付方式不能为空",
                data={"plan_id": ["套餐与支付方式不能为空"]},
                status=400,
            )
        order_service = a._get_service(OrderService)
        order, payment_params = await a._to_thread(
            order_service.create_and_handle,
            account.id,
            UUID(plan_id),
            pay_method,
            "normal",
            str(request.remote_addr or ""),
        )
        return a._ok(OrderCreateResultResp().dump({
            "order": OrderResp().dump(order_service.serialize(order)),
            "payment_params": payment_params if isinstance(payment_params, dict) else None,
        }))

    @quart_app.get("/orders")
    async def order_list():
        from app.http import asgi_app as a
        from internal.schema.order_schema import OrderListResp
        from internal.service.order_service import OrderService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        result = await a._to_thread(
            a._get_service(OrderService).list_orders,
            account.id,
            _int_arg("current_page", 1),
            _int_arg("page_size", 20),
        )
        return a._ok(OrderListResp().dump(result))

    @quart_app.get("/orders/<order_no>")
    async def order_detail(order_no: str):
        from app.http import asgi_app as a
        from internal.schema.order_schema import OrderResp
        from internal.service.order_service import OrderService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        order = await a._to_thread(a._get_service(OrderService).get_order, order_no, account.id)
        return a._ok(OrderResp().dump(a._get_service(OrderService).serialize(order)))

    @quart_app.post("/orders/<order_no>/cancel")
    async def order_cancel(order_no: str):
        from app.http import asgi_app as a
        from internal.schema.order_schema import OrderResp
        from internal.service.order_service import OrderService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        order = await a._to_thread(a._get_service(OrderService).cancel, order_no, account.id)
        return a._ok(OrderResp().dump(a._get_service(OrderService).serialize(order)))

    @quart_app.post("/orders/<order_no>/mock-paid")
    async def order_mock_paid(order_no: str):
        """本地联调：模拟在线支付成功（仅 ALLOW_MOCK_PAYMENT 开启时生效）。"""
        from app.http import asgi_app as a
        from config.config import Config
        from internal.schema.order_schema import OrderResp
        from internal.service.order_service import OrderService

        if not Config().ALLOW_MOCK_PAYMENT:
            return a._json_resp(code="forbidden", message="模拟支付未开放", status=403)
        order = await a._to_thread(a._get_service(OrderService).mock_paid, order_no)
        return a._ok(OrderResp().dump(a._get_service(OrderService).serialize(order)))

    @quart_app.post("/payments/notify/<provider>")
    async def payment_notify(provider: str):
        """支付网关异步回调：微信（JSON body + Wechatpay-* 头）与支付宝（表单）走真实验签。

        验签通过后幂等确认订单（confirm_paid 处理权益/余额/佣金）。
        """
        from app.http import asgi_app as a
        from internal.service.order_service import OrderService
        from internal.service.payment.gateway_base import normalize_provider

        provider = normalize_provider(provider)
        headers = {str(k): str(v) for k, v in request.headers.items()}
        raw_body = await request.get_data()
        form_data = {}
        if request.mimetype == "application/x-www-form-urlencoded":
            form = await request.form
            form_data = {str(k): str(v) for k, v in form.items()}
        elif request.is_json:
            try:
                form_data = await request.get_json(force=True, silent=True) or {}
            except Exception:
                form_data = {}
        payload = form_data if form_data else raw_body
        try:
            result = await a._to_thread(
                a._get_service(OrderService).handle_notify,
                provider,
                payload,
                headers,
            )
        except Exception as exc:
            import logging

            logging.getLogger("payment.notify").warning("支付回调处理失败 provider=%s err=%s", provider, exc)
            if provider == "alipay":
                return Response(f"failure:{exc}", content_type="text/plain", status=400)
            return {"code": "FAIL", "message": str(exc)}
        if provider == "alipay":
            return Response("success", content_type="text/plain")
        return {"code": "SUCCESS", "message": "成功"}