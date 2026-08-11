"""技能与工具路由模块（从 asgi_app.py 拆分）：/builtin-tools、/skills/*、/api-tools/*。"""
import json
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

_registered = False


def _get_service(cls):
    return _support._get_service(cls)


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/builtin-tools")
    async def async_get_builtin_tools() -> Response:
        """async 获取全部内置工具信息。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import BuiltinToolService

        return _ok(await _to_thread(_get_service(BuiltinToolService).get_builtin_tools))

    @quart_app.get("/builtin-tools/<string:provider_name>/tools/<string:tool_name>")
    async def async_get_provider_tool(provider_name, tool_name) -> Response:
        """async 获取指定提供商+工具的信息。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import BuiltinToolService

        return _ok(
            await _to_thread(
                _get_service(BuiltinToolService).get_provider_tool,
                provider_name,
                tool_name,
            )
        )

    @quart_app.get("/builtin-tools/<string:provider_name>/icon")
    async def async_get_provider_icon(provider_name) -> Response:
        """async 获取提供商图标（返回图片或跳转 URL）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import BuiltinToolService

        icon, mimetype, icon_url = await _to_thread(
            _get_service(BuiltinToolService).get_provider_icon, provider_name
        )
        if icon_url:
            return Response("", status=302, headers={"Location": icon_url})
        return Response(icon or b"", mimetype=mimetype or "image/png")

    @quart_app.get("/builtin-tools/categories")
    async def async_get_categories() -> Response:
        """async 获取全部内置提供商分类。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import BuiltinToolService

        return _ok(await _to_thread(_get_service(BuiltinToolService).get_categories))

    @quart_app.get("/skills/categories")
    async def async_get_skill_categories() -> Response:
        """async 获取技能分类统计。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.skill_schema import GetSkillsCategoriesResp
        from internal.service.skill_service import SkillService

        return _ok(
            GetSkillsCategoriesResp().dump(
                await _to_thread(_get_service(SkillService).get_skill_categories)
            )
        )

    @quart_app.get("/skills")
    async def async_get_skills_with_page() -> Response:
        """async 获取技能包分页列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.skill_schema import SkillPackageResp
        from internal.service.skill_service import SkillService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            search_word=_field(request.args.get("search_word"), None),
            category=_field(request.args.get("category"), None),
        )
        skills, paginator = await _to_thread(
            _get_service(SkillService).get_skill_packages_with_page, req
        )
        resp = SkillPackageResp(many=True)
        return _ok({"list": resp.dump(skills), "paginator": asdict(paginator)})

    @quart_app.get("/skills/<uuid:skill_id>")
    async def async_get_skill_package(skill_id) -> Response:
        """async 获取技能包详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.skill_schema import SkillPackageResp
        from internal.service.skill_service import SkillService

        skill_package = await _to_thread(
            _get_service(SkillService).get_skill_package, skill_id
        )
        return _ok(SkillPackageResp().dump(skill_package))

    @quart_app.get("/skills/<uuid:skill_id>/icon")
    async def async_get_skill_package_icon(skill_id) -> Response:
        """async 获取技能包图标。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.skill_service import SkillService

        icon, mimetype, icon_url = await _to_thread(
            _get_service(SkillService).get_skill_package_icon, skill_id
        )
        if icon_url:
            return Response("", status=302, headers={"Location": icon_url})
        return Response(icon or b"", mimetype=mimetype or "application/octet-stream")

    @quart_app.get("/skills/<uuid:skill_id>/versions")
    async def async_get_skill_package_versions(skill_id) -> Response:
        """async 获取技能包版本历史。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.skill_schema import SkillVersionResp
        from internal.service.skill_service import SkillService

        versions = await _to_thread(
            _get_service(SkillService).get_skill_package_versions, skill_id
        )
        return _ok({"list": SkillVersionResp(many=True).dump(versions)})

    @quart_app.post("/skills/<uuid:skill_id>/enable")
    async def async_enable_skill_package(skill_id) -> Response:
        """async 启用技能包。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.skill_service import SkillService

        await _to_thread(_get_service(SkillService).enable_skill_package, skill_id)
        return _ok_msg("启用技能包成功")

    @quart_app.post("/skills/<uuid:skill_id>/disable")
    async def async_disable_skill_package(skill_id) -> Response:
        """async 停用技能包。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.skill_service import SkillService

        await _to_thread(_get_service(SkillService).disable_skill_package, skill_id)
        return _ok_msg("停用技能包成功")

    @quart_app.post("/skills/<uuid:skill_id>/sync")
    async def async_sync_skill_package(skill_id) -> Response:
        """async 强制同步技能包到 SCF。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.skill_service import SkillService

        await _to_thread(_get_service(SkillService).sync_skill_package, skill_id)
        return _ok_msg("同步技能包成功")

    @quart_app.post("/skills/<uuid:skill_id>/rollback")
    async def async_rollback_skill_package(skill_id) -> Response:
        """async 回滚技能包版本。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.skill_service import SkillService

        payload = await request.get_json(force=True, silent=True) or {}
        try:
            version = int(payload.get("version"))
        except (TypeError, ValueError):
            return _json_resp(
                code="validate_error",
                message="版本号无效",
                data={"version": ["版本号无效"]},
                status=400,
            )
        await _to_thread(
            _get_service(SkillService).rollback_skill_package, skill_id, version
        )
        return _ok_msg("回滚技能包成功")

    @quart_app.get("/api-tools")
    async def async_get_api_tool_providers_with_page() -> Response:
        """async 获取 API 工具提供者分页列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.api_tool_schema import GetApiToolProvidersWithPageResp
        from internal.service import ApiToolService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            search_word=_field(request.args.get("search_word"), None),
        )
        providers, paginator = await _to_thread(
            _get_service(ApiToolService).get_api_tool_providers_wiith_page,
            req,
            account,
        )
        resp = GetApiToolProvidersWithPageResp(many=True)
        return _ok({"list": resp.dump(providers), "paginator": asdict(paginator)})

    @quart_app.post("/api-tools/validate-openapi-schema")
    async def async_validate_openapi_schema() -> Response:
        """async 校验 OpenAPI schema。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiToolService

        payload = await request.get_json(force=True, silent=True) or {}
        openapi_schema = str(payload.get("openapi_schema") or "")
        if not openapi_schema:
            return _json_resp(
                code="validate_error",
                message="openapi_schema 不能为空",
                data={"openapi_schema": ["openapi_schema 不能为空"]},
                status=400,
            )
        await _to_thread(
            _get_service(ApiToolService).parse_openapi_schema, openapi_schema
        )
        return _ok_msg("数据校验成功")

    @quart_app.post("/api-tools")
    async def async_create_api_tool_provider() -> Response:
        """async 创建自定义 API 工具。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiToolService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="名称不能为空",
                data={"name": ["名称不能为空"]},
                status=400,
            )
        req = SimpleNamespace(
            name=_field(name),
            description=_field(str(payload.get("description") or "")),
            icon=_field(str(payload.get("icon") or "")),
            openapi_schema=_field(payload.get("openapi_schema")),
            headers=_field(payload.get("headers") or []),
        )
        await _to_thread(_get_service(ApiToolService).create_api_tool, req, account)
        return _ok_msg("创建自定义API插件成功")

    @quart_app.post("/api-tools/import-url")
    async def async_import_api_tool_from_url() -> Response:
        """async 从 OpenAPI URL 导入 API 工具。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiToolService

        data = await request.get_json(force=True, silent=True) or {}
        name = str(data.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="提供者名称不能为空",
                data={"name": ["提供者名称不能为空"]},
                status=400,
            )
        result = await _to_thread(
            _get_service(ApiToolService).import_from_url,
            url=str(data.get("url") or "").strip(),
            name=name,
            description=str(data.get("description") or "").strip(),
            headers=data.get("headers") or [],
            account=account,
            overwrite=bool(data.get("overwrite", False)),
            task_keywords=data.get("task_keywords") or [],
        )
        return _ok(result)

    @quart_app.post("/api-tools/import-file")
    async def async_import_api_tool_from_file() -> Response:
        """async 从上传的 OpenAPI 文件导入 API 工具。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiToolService

        files = await request.files
        file = files.get("file")
        if file is None or not file.filename:
            return _json_resp(
                code="validate_error",
                message="请选择要上传的 OpenAPI 文件",
                data={"file": ["请选择要上传的 OpenAPI 文件"]},
                status=400,
            )
        form = (await request.form) or {}
        name = str(form.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="提供者名称不能为空",
                data={"name": ["提供者名称不能为空"]},
                status=400,
            )
        try:
            raw_bytes = await file.read()
            content = raw_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            return _json_resp(
                code="validate_error",
                message=f"读取上传文件失败: {exc}",
                data={"file": [f"读取上传文件失败: {exc}"]},
                status=400,
            )
        try:
            headers = json.loads(form.get("headers") or "[]")
        except Exception:
            headers = []
        result = await _to_thread(
            _get_service(ApiToolService).import_from_file,
            file_content=content,
            name=name,
            description=str(form.get("description") or "").strip(),
            headers=headers if isinstance(headers, list) else [],
            account=account,
            overwrite=str(form.get("overwrite") or "").lower() in ("true", "1", "yes"),
            task_keywords=[],
        )
        return _ok(result)

    @quart_app.get("/api-tools/<uuid:provider_id>")
    async def async_get_api_tool_provider(provider_id) -> Response:
        """async 获取 API 工具提供者原始信息。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.api_tool_schema import GetApiToolProviderResp
        from internal.service import ApiToolService

        provider = await _to_thread(
            _get_service(ApiToolService).get_api_tool_provider, provider_id, account
        )
        return _ok(GetApiToolProviderResp().dump(provider))

    @quart_app.post("/api-tools/<uuid:provider_id>")
    async def async_update_api_tool_provider(provider_id) -> Response:
        """async 更新 API 工具提供者。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiToolService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="名称不能为空",
                data={"name": ["名称不能为空"]},
                status=400,
            )
        req = SimpleNamespace(
            name=_field(name),
            description=_field(str(payload.get("description") or "")),
            icon=_field(str(payload.get("icon") or "")),
            openapi_schema=_field(payload.get("openapi_schema")),
            headers=_field(payload.get("headers") or []),
        )
        await _to_thread(
            _get_service(ApiToolService).update_api_tool_provider,
            provider_id,
            req,
            account,
        )
        return _ok_msg("更新自定义API插件成功")

    @quart_app.get("/api-tools/<uuid:provider_id>/tools/<string:tool_name>")
    async def async_get_api_tool(provider_id, tool_name) -> Response:
        """async 获取指定提供者+工具名详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.api_tool_schema import GetApiToolResp
        from internal.service import ApiToolService

        api_tool = await _to_thread(
            _get_service(ApiToolService).get_api_tool, provider_id, tool_name, account
        )
        return _ok(GetApiToolResp().dump(api_tool))

    @quart_app.post("/api-tools/<uuid:provider_id>/delete")
    async def async_delete_api_tool_provider(provider_id) -> Response:
        """async 删除 API 工具提供者。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiToolService

        await _to_thread(
            _get_service(ApiToolService).delete_api_tool_provider, provider_id, account
        )
        return _ok_msg("删除自定义API插件成功")

    @quart_app.post("/api-tools/<uuid:provider_id>/regenerate-icon")
    async def async_api_tool_regenerate_icon(provider_id) -> Response:
        """async 重新生成 API 插件图标。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiToolService

        icon_url = await _to_thread(
            _get_service(ApiToolService).regenerate_icon, provider_id, account
        )
        return _ok({"icon": icon_url})

    @quart_app.post("/api-tools/generate-icon-preview")
    async def async_api_tool_generate_icon_preview() -> Response:
        """async 生成 API 插件图标预览。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import ApiToolService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="插件名称不能为空",
                data={"name": ["插件名称不能为空"]},
                status=400,
            )
        icon_url = await _to_thread(
            _get_service(ApiToolService).generate_icon_preview,
            name,
            str(payload.get("description") or ""),
        )
        return _ok({"icon": icon_url})
