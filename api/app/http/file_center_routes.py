"""用户侧文件中心路由（/space/files/*）。"""
from uuid import UUID

_registered = False


def _uuid_arg(value):
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/space/files")
    async def file_center_list():
        from quart import request

        from app.http import asgi_app as a
        from internal.schema.file_center_schema import FileCenterChildrenSchema
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        parent_id = _uuid_arg(request.args.get("parent_id"))
        items = await a._to_thread(
            lambda: a._get_service(FileCenterService).list_children_view(
                account.id, parent_id=parent_id
            )
        )
        return a._ok(
            FileCenterChildrenSchema().dump(
                {"items": items, "parent_id": str(parent_id) if parent_id else None}
            )
        )

    @quart_app.get("/space/files/all")
    async def file_center_list_all():
        from quart import request

        from app.http import asgi_app as a
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err

        def _int_arg(name, default):
            raw = request.args.get(name)
            try:
                return int(raw) if raw is not None else default
            except (TypeError, ValueError):
                return default

        result = await a._to_thread(
            lambda: a._get_service(FileCenterService).list_all_files(
                account_id=account.id,
                page=_int_arg("page", 1),
                page_size=_int_arg("page_size", 20),
            )
        )
        return a._ok(result)

    @quart_app.post("/space/files/folders")
    async def file_center_mkdir():
        from quart import request

        from app.http import asgi_app as a
        from internal.exception import NotFoundException, ValidateErrorException
        from internal.schema.file_center_schema import FileCenterEntrySchema
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = {}
        raw_body = await request.get_json(silent=True)
        if isinstance(raw_body, dict):
            payload = raw_body
        try:
            entry = await a._to_thread(
                lambda: a._get_service(FileCenterService).mkdir(
                    account.id,
                    parent_id=_uuid_arg(payload.get("parent_id")),
                    name=str(payload.get("name") or ""),
                )
            )
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        except ValidateErrorException as exc:
            return a._json_resp(code="validate_error", message=str(exc), status=400)
        return a._ok(FileCenterEntrySchema().dump(entry))

    @quart_app.patch("/space/files/<string:entry_id>")
    async def file_center_update(entry_id):
        from quart import request

        from app.http import asgi_app as a
        from internal.exception import NotFoundException, ValidateErrorException
        from internal.schema.file_center_schema import FileCenterEntrySchema
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = {}
        raw_body = await request.get_json(silent=True)
        if isinstance(raw_body, dict):
            payload = raw_body
        service = a._get_service(FileCenterService)
        try:
            if "parent_id" in payload:
                entry = await a._to_thread(
                    lambda: service.move(
                        account.id, UUID(entry_id), _uuid_arg(payload.get("parent_id"))
                    )
                )
            else:
                entry = await a._to_thread(
                    lambda: service.rename(
                        account.id, UUID(entry_id), str(payload.get("name") or "")
                    )
                )
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        except ValidateErrorException as exc:
            return a._json_resp(code="validate_error", message=str(exc), status=400)
        return a._ok(FileCenterEntrySchema().dump(entry))

    @quart_app.delete("/space/files/<string:entry_id>")
    async def file_center_delete(entry_id):
        from app.http import asgi_app as a
        from internal.exception import NotFoundException
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        try:
            await a._to_thread(
                lambda: a._get_service(FileCenterService).delete_node(
                    account.id, UUID(entry_id)
                )
            )
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        return a._ok_msg("已移入回收站")

    @quart_app.post("/space/files/import")
    async def file_center_import():
        from quart import request

        from app.http import asgi_app as a
        from internal.exception import NotFoundException, ValidateErrorException
        from internal.schema.file_center_schema import FileCenterEntrySchema
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = {}
        raw_body = await request.get_json(silent=True)
        if isinstance(raw_body, dict):
            payload = raw_body
        upload_file_id = _uuid_arg(payload.get("upload_file_id"))
        if upload_file_id is None:
            return a._json_resp(
                code="validate_error", message="upload_file_id 无效", status=400
            )
        try:
            entry = await a._to_thread(
                lambda: a._get_service(FileCenterService).import_upload_file(
                    account.id,
                    upload_file_id=upload_file_id,
                    parent_id=_uuid_arg(payload.get("parent_id")),
                    name=str(payload.get("name") or ""),
                )
            )
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        except ValidateErrorException as exc:
            return a._json_resp(code="validate_error", message=str(exc), status=400)
        return a._ok(FileCenterEntrySchema().dump(entry))
