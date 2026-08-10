"""Quart 异步端点迁移：管理员技能包（admin_skills_handler）与管理员 MCP（admin_mcp_handler）。

实现来源：
- internal/handler/admin_skills_handler.py
- internal/handler/admin_mcp_handler.py

路径与 HTTP 方法来源：internal/router/router.py 中 ``self.admin_skills_handler.`` 与
``self.admin_mcp_handler.`` 的注册段。同步 service 调用统一经 asyncio.to_thread 移入线程池。
"""

from quart import request

_registered = False


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    # ------------------------------------------------------------------ #
    #  管理员技能包模块（admin_skills_handler）                              #
    # ------------------------------------------------------------------ #

    @quart_app.get("/admin/skills/<uuid:skill_id>")
    async def admin_get_skill_package(skill_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.skill_schema import SkillPackageResp
        from internal.service.skill_service import SkillService

        skill_package = await a._to_thread(a._get_service(SkillService).get_skill_package, skill_id)
        return a._ok(SkillPackageResp().dump(skill_package))

    @quart_app.get("/admin/skills/<uuid:skill_id>/versions")
    async def admin_get_skill_package_versions(skill_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.skill_schema import SkillVersionResp
        from internal.service.skill_service import SkillService

        versions = await a._to_thread(a._get_service(SkillService).get_skill_package_versions, skill_id)
        return a._ok({"list": SkillVersionResp(many=True).dump(versions)})

    @quart_app.post("/admin/skills/<uuid:skill_id>/enable")
    async def admin_enable_skill_package(skill_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.skill_service import SkillService

        await a._to_thread(a._get_service(SkillService).enable_skill_package, skill_id)
        return a._ok_msg("启用技能包成功")

    @quart_app.post("/admin/skills/<uuid:skill_id>/disable")
    async def admin_disable_skill_package(skill_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.skill_service import SkillService

        await a._to_thread(a._get_service(SkillService).disable_skill_package, skill_id)
        return a._ok_msg("停用技能包成功")

    @quart_app.post("/admin/skills/<uuid:skill_id>/sync")
    async def admin_sync_skill_package(skill_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.skill_service import SkillService

        await a._to_thread(a._get_service(SkillService).sync_skill_package, skill_id)
        return a._ok_msg("同步技能包成功")

    @quart_app.post("/admin/skills/<uuid:skill_id>/rollback")
    async def admin_rollback_skill_package(skill_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.skill_service import SkillService

        data = await request.get_json(force=True, silent=True) or {}
        raw_version = data.get("version")
        if raw_version is None or str(raw_version).strip() == "":
            return a._json_resp(
                code="validate_error",
                message="技能版本不能为空",
                data={"version": ["技能版本不能为空"]},
                status=400,
            )
        try:
            version = int(raw_version)
        except (TypeError, ValueError):
            return a._json_resp(
                code="validate_error",
                message="技能版本必须大于0",
                data={"version": ["技能版本必须大于0"]},
                status=400,
            )
        await a._to_thread(a._get_service(SkillService).rollback_skill_package, skill_id, version)
        return a._ok_msg("回滚技能包成功")

    @quart_app.post("/admin/skills")
    async def admin_create_skill_package():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.skill_schema import SkillPackageResp
        from internal.service.skill_service import SkillService

        data = await request.get_json(force=True, silent=True) or {}
        source_key = str(data.get("source_key") or "").strip()
        if not source_key:
            return a._json_resp(
                code="validate_error",
                message="source_key 不能为空",
                data={"source_key": ["source_key 不能为空"]},
                status=400,
            )
        req = a.SimpleNamespace(
            source_key=a._field(source_key),
            name=a._field(data.get("name"), None),
            label=a._field(data.get("label"), None),
            description=a._field(data.get("description"), None),
            category=a._field(data.get("category"), None),
            icon=a._field(data.get("icon"), None),
            executor_type=a._field(data.get("executor_type"), "prompt"),
            enabled=a._field(data.get("enabled"), True),
            readme=a._field(data.get("readme"), None),
            skill_code=a._field(data.get("skill_code"), None),
            capabilities=a._field(data.get("capabilities"), None),
            task_keywords=a._field(data.get("task_keywords"), None),
        )
        payload = {
            "source_key": req.source_key.data,
            "name": req.name.data,
            "label": req.label.data,
            "description": req.description.data,
            "category": req.category.data,
            "icon": req.icon.data,
            "executor_type": req.executor_type.data,
            "enabled": req.enabled.data if req.enabled.data is not None else True,
            "readme": req.readme.data,
            "skill_code": req.skill_code.data,
            "tools": data.get("tools") or [],
            "tags": data.get("tags") or [],
            "capabilities": req.capabilities.data if req.capabilities.data is not None else (data.get("capabilities") or {}),
            "task_keywords": req.task_keywords.data if req.task_keywords.data is not None else [],
        }
        skill_package = await a._to_thread(a._get_service(SkillService).create_skill_package_for_admin, payload)
        return a._ok(SkillPackageResp().dump(skill_package))

    @quart_app.post("/admin/skills/<uuid:skill_id>")
    async def admin_update_skill_package(skill_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.skill_schema import SkillPackageResp
        from internal.service.skill_service import SkillService

        data = await request.get_json(force=True, silent=True) or {}
        req = a.SimpleNamespace(
            name=a._field(data.get("name"), None),
            label=a._field(data.get("label"), None),
            description=a._field(data.get("description"), None),
            category=a._field(data.get("category"), None),
            icon=a._field(data.get("icon"), None),
            executor_type=a._field(data.get("executor_type"), None),
            enabled=a._field(data.get("enabled"), None),
            readme=a._field(data.get("readme"), None),
            skill_code=a._field(data.get("skill_code"), None),
            capabilities=a._field(data.get("capabilities"), None),
            task_keywords=a._field(data.get("task_keywords"), None),
        )
        payload = {
            "name": req.name.data,
            "label": req.label.data,
            "description": req.description.data,
            "category": req.category.data,
            "icon": req.icon.data,
            "executor_type": req.executor_type.data,
            "enabled": req.enabled.data,
            "readme": req.readme.data,
            "skill_code": req.skill_code.data,
            "tools": data.get("tools") or [],
            "tags": data.get("tags") or [],
            "capabilities": req.capabilities.data if req.capabilities.data is not None else (data.get("capabilities") or {}),
            "task_keywords": req.task_keywords.data if req.task_keywords.data is not None else None,
        }
        skill_package = await a._to_thread(a._get_service(SkillService).update_skill_package_for_admin, skill_id, payload)
        return a._ok(SkillPackageResp().dump(skill_package))

    @quart_app.post("/admin/skills/<uuid:skill_id>/delete")
    async def admin_delete_skill_package(skill_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.skill_service import SkillService

        data = await request.get_json(force=True, silent=True) or {}
        retention_days = data.get("retention_days")
        await a._to_thread(
            a._get_service(SkillService).delete_skill_package_for_admin,
            skill_id,
            retention_days=retention_days,
            deleted_by=None,
        )
        return a._ok_msg("删除技能包成功")

    @quart_app.get("/admin/skills/catalog-packages")
    async def admin_list_catalog_packages():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.skill_schema import CatalogPackageResp
        from internal.service.skill_service import SkillService

        packages = await a._to_thread(a._get_service(SkillService).list_catalog_packages_for_admin)
        return a._ok({"list": CatalogPackageResp(many=True).dump(packages)})

    @quart_app.post("/admin/skills/import-catalog")
    async def admin_import_catalog_package():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.skill_schema import SkillPackageResp
        from internal.service.skill_service import SkillService

        data = await request.get_json(force=True, silent=True) or {}
        source_key = str(data.get("source_key") or "").strip()
        if not source_key:
            return a._json_resp(
                code="validate_error",
                message="source_key 不能为空",
                data={"source_key": ["source_key 不能为空"]},
                status=400,
            )
        skill_package = await a._to_thread(a._get_service(SkillService).import_catalog_package_for_admin, source_key)
        return a._ok(SkillPackageResp().dump(skill_package))

    @quart_app.post("/admin/skills/import-zip")
    async def admin_import_skill_zip():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.skill_import_service import SkillImportService

        files = await request.files
        file = files.get("file")
        if file is None or not getattr(file, "filename", ""):
            return a._json_resp(
                code="validate_error",
                message="请选择要上传的 zip 文件",
                data={"file": ["请选择要上传的 zip 文件"]},
                status=400,
            )
        form = await request.form or {}
        overwrite = str(form.get("overwrite") or "").lower() in ("true", "1", "yes")
        try:
            file_bytes = file.read()
        except Exception as exc:
            return a._json_resp(
                code="validate_error",
                message=f"读取上传文件失败: {exc}",
                data={"file": [f"读取上传文件失败: {exc}"]},
                status=400,
            )
        result = await a._to_thread(a._get_service(SkillImportService).import_from_zip, file_bytes, overwrite=overwrite)
        return a._ok(result)

    @quart_app.post("/admin/skills/import-github")
    async def admin_import_skill_github():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.skill_import_service import SkillImportService

        data = await request.get_json(force=True, silent=True) or {}
        github_url = str(data.get("github_url") or "").strip()
        if not github_url:
            return a._json_resp(
                code="validate_error",
                message="github_url 不能为空",
                data={"github_url": ["github_url 不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(SkillImportService).import_from_github_url,
            github_url,
            overwrite=bool(data.get("overwrite", False)),
        )
        return a._ok(result)

    @quart_app.post("/admin/skills/import-json")
    async def admin_import_skill_json():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.skill_import_service import SkillImportService

        data = await request.get_json(force=True, silent=True) or {}
        config_json = str(data.get("config_json") or "")
        if not config_json:
            return a._json_resp(
                code="validate_error",
                message="config_json 不能为空",
                data={"config_json": ["config_json 不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(SkillImportService).import_from_json,
            config_json,
            overwrite=bool(data.get("overwrite", False)),
        )
        return a._ok(result)

    # ------------------------------------------------------------------ #
    #  管理员 MCP 模块（admin_mcp_handler）                                 #
    # ------------------------------------------------------------------ #

    @quart_app.get("/admin/mcp/categories")
    async def admin_get_mcp_categories():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_service import McpService

        categories = await a._to_thread(a._get_service(McpService).get_mcp_categories)
        return a._ok({"categories": categories})

    @quart_app.post("/admin/mcp/import-mcp-json")
    async def admin_import_mcp_json():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_import_service import McpImportService

        data = await request.get_json(force=True, silent=True) or {}
        config_json = str(data.get("config_json") or "")
        if not config_json:
            return a._json_resp(
                code="validate_error",
                message="config_json 不能为空",
                data={"config_json": ["config_json 不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(McpImportService).import_from_mcp_json,
            config_json,
            overwrite=bool(data.get("overwrite", False)),
        )
        return a._ok(result)

    @quart_app.post("/admin/mcp/preview-url")
    async def admin_preview_mcp_url():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_import_service import McpImportService

        data = await request.get_json(force=True, silent=True) or {}
        url = str(data.get("url") or "").strip()
        if not url:
            return a._json_resp(
                code="validate_error",
                message="url 不能为空",
                data={"url": ["url 不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(McpImportService).preview_tools_from_url,
            url,
            headers=data.get("headers") or [],
            transport=str(data.get("transport") or "http"),
        )
        return a._ok(result)

    @quart_app.post("/admin/mcp/import-url")
    async def admin_import_mcp_url():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_import_service import McpImportService

        data = await request.get_json(force=True, silent=True) or {}
        url = str(data.get("url") or "").strip()
        name = str(data.get("name") or "").strip()
        if not url:
            return a._json_resp(
                code="validate_error",
                message="url 不能为空",
                data={"url": ["url 不能为空"]},
                status=400,
            )
        if not name:
            return a._json_resp(
                code="validate_error",
                message="MCP 名称不能为空",
                data={"name": ["MCP 名称不能为空"]},
                status=400,
            )
        provider = await a._to_thread(
            a._get_service(McpImportService).import_from_url,
            url,
            name,
            str(data.get("description") or ""),
            data.get("headers") or [],
            transport=str(data.get("transport") or "http"),
            category=str(data.get("category") or "other"),
            icon=str(data.get("icon") or ""),
        )
        return a._ok({"id": str(provider.id)})

    @quart_app.post("/admin/mcp/import-json")
    async def admin_import_mcp_json_config():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_import_service import McpImportService

        data = await request.get_json(force=True, silent=True) or {}
        config_json = str(data.get("config_json") or "")
        if not config_json:
            return a._json_resp(
                code="validate_error",
                message="config_json 不能为空",
                data={"config_json": ["config_json 不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(McpImportService).import_from_json,
            config_json,
            overwrite=bool(data.get("overwrite", False)),
        )
        return a._ok(result)

    @quart_app.post("/admin/mcp")
    async def admin_create_mcp_provider():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_service import McpService

        data = await request.get_json(force=True, silent=True) or {}
        name = str(data.get("name") or "").strip()
        description = str(data.get("description") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error",
                message="MCP 名称不能为空",
                data={"name": ["MCP 名称不能为空"]},
                status=400,
            )
        if not description:
            return a._json_resp(
                code="validate_error",
                message="MCP 描述不能为空",
                data={"description": ["MCP 描述不能为空"]},
                status=400,
            )
        req = a.SimpleNamespace(
            name=a._field(name),
            label=a._field(data.get("label"), ""),
            icon=a._field(data.get("icon"), ""),
            description=a._field(description),
            category=a._field(data.get("category"), "other"),
            transport=a._field(data.get("transport"), "streamable_http"),
            url=a._field(data.get("url"), ""),
            command=a._field(data.get("command"), ""),
            headers=a._field(data.get("headers") or []),
            tool_names=a._field(data.get("tool_names") or []),
            args=a._field(data.get("args") or []),
            env=a._field(data.get("env") or {}),
            timeout_seconds=a._field(data.get("timeout_seconds"), 30),
            task_keywords=a._field(data.get("task_keywords") or []),
        )
        provider = await a._to_thread(a._get_service(McpService).create_mcp_provider, req)
        return a._ok({"id": str(provider.id)})

    @quart_app.get("/admin/mcp/<uuid:provider_id>")
    async def admin_get_mcp_provider(provider_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.mcp_schema import McpProviderResp
        from internal.service.mcp_service import McpService

        provider = await a._to_thread(a._get_service(McpService).get_mcp_provider_for_admin, provider_id)
        return a._ok(McpProviderResp().dump(provider))

    @quart_app.patch("/admin/mcp/<uuid:provider_id>")
    async def admin_update_mcp_provider(provider_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_service import McpService

        data = await request.get_json(force=True, silent=True) or {}
        name = str(data.get("name") or "").strip()
        description = str(data.get("description") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error",
                message="MCP 名称不能为空",
                data={"name": ["MCP 名称不能为空"]},
                status=400,
            )
        if not description:
            return a._json_resp(
                code="validate_error",
                message="MCP 描述不能为空",
                data={"description": ["MCP 描述不能为空"]},
                status=400,
            )
        req = a.SimpleNamespace(
            name=a._field(name),
            label=a._field(data.get("label"), ""),
            icon=a._field(data.get("icon"), ""),
            description=a._field(description),
            category=a._field(data.get("category"), "other"),
            transport=a._field(data.get("transport"), "streamable_http"),
            url=a._field(data.get("url"), ""),
            command=a._field(data.get("command"), ""),
            headers=a._field(data.get("headers") or []),
            tool_names=a._field(data.get("tool_names") or []),
            args=a._field(data.get("args") or []),
            env=a._field(data.get("env") or {}),
            timeout_seconds=a._field(data.get("timeout_seconds"), 30),
            task_keywords=a._field(data.get("task_keywords") or []),
        )
        await a._to_thread(a._get_service(McpService).update_mcp_provider_for_admin, provider_id, req)
        return a._ok_msg("更新MCP成功")

    @quart_app.post("/admin/mcp/<uuid:provider_id>/regenerate-icon")
    async def admin_regenerate_mcp_icon(provider_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_service import McpService

        icon = await a._to_thread(a._get_service(McpService).regenerate_icon_for_admin, provider_id)
        return a._ok({"icon": icon})

    @quart_app.post("/admin/mcp/<uuid:provider_id>/publish")
    async def admin_publish_mcp_provider(provider_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_service import McpService

        await a._to_thread(a._get_service(McpService).publish_mcp_provider_for_admin, provider_id)
        return a._ok_msg("发布MCP成功")

    @quart_app.post("/admin/mcp/<uuid:provider_id>/unpublish")
    async def admin_unpublish_mcp_provider(provider_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_service import McpService

        await a._to_thread(a._get_service(McpService).unpublish_mcp_provider_for_admin, provider_id)
        return a._ok_msg("取消发布MCP成功")

    @quart_app.delete("/admin/mcp/<uuid:provider_id>")
    async def admin_delete_mcp_provider(provider_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.mcp_service import McpService

        data = await request.get_json(force=True, silent=True) or {}
        retention_days = data.get("retention_days")
        await a._to_thread(
            a._get_service(McpService).delete_mcp_provider_for_admin,
            provider_id,
            retention_days=retention_days,
            deleted_by=None,
        )
        return a._ok_msg("删除MCP成功")
