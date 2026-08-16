"""用户侧回收站路由（Quart 异步端点）。

把平台回收站开放给用户端：
- 用户删除的内容（deleted_by_type=user）与 agent 代删的内容（deleted_by_type=agent）
  统一在该回收站中展示，仅归属账号可查看与恢复。
- admin 回收站（/admin/recycle-bin）与用户回收站按 deleted_by_type 隔离，互不混用。

通过 ``register_routes(quart_app)`` 一次性注册全部端点；使用模块级
``_registered`` 标志保证幂等，重复调用直接返回。
"""

_registered = False


def _int_arg(name, default):
    from quart import request

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

    # ------------------------------------------------------------------
    # 用户端回收站：列表 / 详情 / 恢复
    # ------------------------------------------------------------------
    @quart_app.get("/space/recycle-bin")
    async def user_recycle_bin_list():
        from quart import request

        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.recycle_bin_schema import RecycleBinListSchema
        from internal.service.recycle_bin_service import RecycleBinService

        result = await a._to_thread(
            a._get_service(RecycleBinService).list_user_items,
            account_id=account.id,
            page=_int_arg("page", 1),
            page_size=_int_arg("page_size", 20),
            resource_type=request.args.get("resource_type") or None,
            status=request.args.get("status") or "pending",
            search_word=request.args.get("search_word") or "",
            deleted_by_type=request.args.get("deleted_by_type") or None,
        )
        return a._ok(RecycleBinListSchema().dump(result))

    @quart_app.get("/space/recycle-bin/<int:item_id>")
    async def user_recycle_bin_get(item_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.exception import ForbiddenException, NotFoundException
        from internal.schema.recycle_bin_schema import RecycleBinDetailSchema
        from internal.service.recycle_bin_service import RecycleBinService

        try:
            item = await a._to_thread(a._get_service(RecycleBinService).get_item, item_id)
            a._get_service(RecycleBinService)._check_user_owned(item, account.id)
        except (NotFoundException, ForbiddenException) as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        return a._ok(RecycleBinDetailSchema().dump(item))

    @quart_app.post("/space/recycle-bin/<int:item_id>/restore")
    async def user_recycle_bin_restore(item_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from quart import request

        from internal.exception import (
            DeviceMismatchException,
            ForbiddenException,
            NotFoundException,
            ValidateErrorException,
        )
        from internal.schema.recycle_bin_schema import RecycleBinDetailSchema
        from internal.service.recycle_bin_service import RecycleBinService

        payload = {}
        raw_body = await request.get_json(silent=True)
        if isinstance(raw_body, dict):
            payload = raw_body
        target_path = str(payload.get("target_path") or "").strip()
        confirm_device_mismatch = bool(payload.get("confirm_device_mismatch"))

        try:
            item = await a._to_thread(
                a._get_service(RecycleBinService).restore_user_item,
                item_id,
                account.id,
                target_path=target_path,
                confirm_device_mismatch=confirm_device_mismatch,
            )
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        except ForbiddenException as exc:
            return a._json_resp(code="forbidden", message=str(exc), status=403)
        except DeviceMismatchException as exc:
            # 非本机删除：返回设备信息，前端提示并提供「按原路径 / 自选路径」两种恢复方式
            return a._json_resp(
                data={
                    "recorded_device": exc.recorded_device,
                    "current_device": exc.current_device,
                },
                code="device_mismatch",
                message=str(exc),
                status=200,
            )
        except ValidateErrorException as exc:
            return a._json_resp(code="validate_error", message=str(exc), status=400)
        return a._ok(RecycleBinDetailSchema().dump(item))
