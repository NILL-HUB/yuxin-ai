"""知识库与 MCP 路由模块（从 asgi_app.py 拆分）：/space/*、/external-data-sources*、/tool-confirmations*、/mcp-providers*。"""
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID

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

    @quart_app.get("/external-data-sources")
    async def async_external_data_source_list() -> Response:
        """async 获取外部数据源列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.external_data_source_schema import ExternalDataSourceListResp
        from internal.service.external_data_source_service import ExternalDataSourceService

        data_sources = await _to_thread(
            _get_service(ExternalDataSourceService).list_data_sources,
            account=account,
            status=request.args.get("status") or "",
        )
        return _ok(
            ExternalDataSourceListResp().dump(
                {"items": data_sources, "total": len(data_sources)}
            )
        )

    @quart_app.post("/external-data-sources")
    async def async_external_data_source_create() -> Response:
        """async 创建外部数据源连接。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.external_data_source_schema import ExternalDataSourceResp
        from internal.service.external_data_source_service import ExternalDataSourceService
        from internal.service.knowledge_base_service import KnowledgeBaseService

        payload = await request.get_json(force=True, silent=True) or {}
        source_name = str(payload.get("source_name") or "").strip()
        source_type = str(payload.get("source_type") or "").strip()
        if not source_name or not source_type:
            return _json_resp(
                code="validate_error",
                message="source_name/source_type 不能为空",
                data={"source_name": ["source_name/source_type 不能为空"]},
                status=400,
            )
        kb_id_raw = payload.get("knowledge_base_id")
        if kb_id_raw:
            knowledge_base = await _to_thread(
                _get_service(KnowledgeBaseService).get_user_content_base,
                UUID(str(kb_id_raw)),
                account,
            )
        else:
            knowledge_base = await _to_thread(
                _get_service(KnowledgeBaseService).create_user_content_base,
                name=source_name,
                account=account,
            )
        data_source = await _to_thread(
            _get_service(ExternalDataSourceService).create_connection,
            account=account,
            knowledge_base=knowledge_base,
            source_type=source_type,
            source_name=source_name,
            config=payload.get("config") or {},
        )
        return _ok(ExternalDataSourceResp().dump(data_source))

    @quart_app.get("/external-data-sources/<uuid:data_source_id>")
    async def async_external_data_source_get(data_source_id) -> Response:
        """async 获取外部数据源详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.external_data_source_schema import ExternalDataSourceResp
        from internal.service.external_data_source_service import ExternalDataSourceService

        data_source = await _to_thread(
            _get_service(ExternalDataSourceService).get_data_source,
            data_source_id,
            account,
        )
        return _ok(ExternalDataSourceResp().dump(data_source))

    @quart_app.delete("/external-data-sources/<uuid:data_source_id>")
    async def async_external_data_source_delete(data_source_id) -> Response:
        """async 删除外部数据源连接。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.external_data_source_service import ExternalDataSourceService

        await _to_thread(
            _get_service(ExternalDataSourceService).delete_data_source,
            data_source_id,
            account,
        )
        return _ok({"deleted": True})

    @quart_app.post("/external-data-sources/<uuid:data_source_id>/authorize")
    async def async_external_data_source_authorize(data_source_id) -> Response:
        """async 授权外部数据源。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.external_data_source_schema import ExternalDataSourceResp
        from internal.service.external_data_source_service import ExternalDataSourceService

        payload = await request.get_json(force=True, silent=True) or {}
        data_source = await _to_thread(
            _get_service(ExternalDataSourceService).authorize_data_source,
            data_source_id,
            account,
            payload.get("auth_config") or {},
        )
        return _ok(ExternalDataSourceResp().dump(data_source))

    @quart_app.post("/external-data-sources/<uuid:data_source_id>/sync")
    async def async_external_data_source_sync(data_source_id) -> Response:
        """async 手动同步外部数据源。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.external_data_source_schema import ExternalDataSourceSyncResp
        from internal.service.external_data_source_service import ExternalDataSourceService

        result = await _to_thread(
            _get_service(ExternalDataSourceService).manual_sync,
            data_source_id,
            account,
        )
        return _ok(ExternalDataSourceSyncResp().dump(result))

    @quart_app.get("/tool-confirmations")
    async def async_tool_confirmation_list() -> Response:
        """async 获取工具确认列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.tool_confirmation_schema import ToolConfirmationListResp
        from internal.service.tool_confirmation_service import ToolConfirmationService

        confirmations = await _to_thread(
            _get_service(ToolConfirmationService).list_confirmations,
            account=account,
            status=request.args.get("status") or "",
        )
        return _ok(
            ToolConfirmationListResp().dump(
                {"items": confirmations, "total": len(confirmations)}
            )
        )

    @quart_app.get("/tool-confirmations/<uuid:confirmation_id>")
    async def async_tool_confirmation_get(confirmation_id) -> Response:
        """async 获取工具确认详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.tool_confirmation_schema import ToolConfirmationResp
        from internal.service.tool_confirmation_service import ToolConfirmationService

        confirmation = await _to_thread(
            _get_service(ToolConfirmationService).get_confirmation,
            confirmation_id,
            account,
        )
        return _ok(ToolConfirmationResp().dump(confirmation))

    @quart_app.post("/tool-confirmations")
    async def async_tool_confirmation_create() -> Response:
        """async 创建工具确认。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.tool_confirmation_schema import ToolConfirmationResp
        from internal.service.tool_confirmation_service import ToolConfirmationService

        payload = await request.get_json(force=True, silent=True) or {}
        tool_name = str(payload.get("tool_name") or "")
        if not tool_name:
            return _json_resp(
                code="validate_error",
                message="tool_name 不能为空",
                data={"tool_name": ["tool_name 不能为空"]},
                status=400,
            )
        confirmation = await _to_thread(
            _get_service(ToolConfirmationService).create_confirmation,
            account=account,
            tool_name=tool_name,
            risk_level=str(payload.get("risk_level") or ""),
            tool_input=payload.get("tool_input"),
            spent_credits=payload.get("spent_credits"),
            reason=str(payload.get("reason") or ""),
            target_system=str(payload.get("target_system") or ""),
            target_environment=str(payload.get("target_environment") or ""),
            execution_summary=str(payload.get("execution_summary") or ""),
            impact_scope=str(payload.get("impact_scope") or ""),
            rollback_strategy=str(payload.get("rollback_strategy") or ""),
            audit_hint=str(payload.get("audit_hint") or ""),
        )
        return _ok(ToolConfirmationResp().dump(confirmation))

    @quart_app.post("/tool-confirmations/<uuid:confirmation_id>/confirm")
    async def async_tool_confirmation_confirm(confirmation_id) -> Response:
        """async 确认工具执行。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.tool_confirmation_schema import ToolConfirmationResp
        from internal.service.tool_confirmation_service import ToolConfirmationService

        confirmation = await _to_thread(
            _get_service(ToolConfirmationService).confirm,
            confirmation_id,
            account,
        )
        return _ok(ToolConfirmationResp().dump(confirmation))

    @quart_app.post("/tool-confirmations/<uuid:confirmation_id>/cancel")
    async def async_tool_confirmation_cancel(confirmation_id) -> Response:
        """async 取消工具执行。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.tool_confirmation_schema import ToolConfirmationResp
        from internal.service.tool_confirmation_service import ToolConfirmationService

        confirmation = await _to_thread(
            _get_service(ToolConfirmationService).cancel,
            confirmation_id,
            account,
        )
        return _ok(ToolConfirmationResp().dump(confirmation))

    @quart_app.get("/space/knowledge-bases")
    async def async_get_knowledge_bases_with_page() -> Response:
        """async 获取用户端知识库分页列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.knowledge_base_schema import GetKnowledgeBasesWithPageResp
        from internal.service import KnowledgeBaseService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            search_word=_field(request.args.get("search_word"), None),
        )
        knowledge_bases, paginator = await _to_thread(
            _get_service(KnowledgeBaseService).list_user_content_bases, req, account
        )
        resp = GetKnowledgeBasesWithPageResp(many=True)
        return _ok({"list": resp.dump(knowledge_bases), "paginator": asdict(paginator)})

    @quart_app.post("/space/knowledge-bases")
    async def async_create_knowledge_base() -> Response:
        """async 创建用户端知识库。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="知识库名称不能为空",
                data={"name": ["知识库名称不能为空"]},
                status=400,
            )
        req = SimpleNamespace(
            name=_field(name),
            description=_field(str(payload.get("description") or "")),
            icon=_field(str(payload.get("icon") or "")),
        )
        await _to_thread(
            _get_service(KnowledgeBaseService).create_user_content_base_with_req,
            req,
            account,
        )
        return _ok_msg("创建知识库成功")

    @quart_app.get("/space/knowledge-bases/<uuid:knowledge_base_id>")
    async def async_get_knowledge_base(knowledge_base_id) -> Response:
        """async 获取知识库详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.knowledge_base_schema import GetKnowledgeBaseResp
        from internal.service import KnowledgeBaseService

        knowledge_base = await _to_thread(
            _get_service(KnowledgeBaseService).get_user_content_base_detail,
            knowledge_base_id,
            account,
        )
        return _ok(GetKnowledgeBaseResp().dump(knowledge_base))

    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>")
    async def async_update_knowledge_base(knowledge_base_id) -> Response:
        """async 更新知识库。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        payload = await request.get_json(force=True, silent=True) or {}
        req = SimpleNamespace(
            name=_field(str(payload.get("name") or "")),
            description=_field(str(payload.get("description") or "")),
            icon=_field(str(payload.get("icon") or "")),
        )
        await _to_thread(
            _get_service(KnowledgeBaseService).update_user_content_base,
            knowledge_base_id,
            req,
            account,
        )
        return _ok_msg("更新知识库成功")

    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>/delete")
    async def async_delete_knowledge_base(knowledge_base_id) -> Response:
        """async 删除知识库。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        await _to_thread(
            _get_service(KnowledgeBaseService).delete_user_content_base,
            knowledge_base_id,
            account,
        )
        return _ok_msg("删除知识库成功")

    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>/hit")
    async def async_hit_test(knowledge_base_id) -> Response:
        """async 知识库召回测试。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        payload = await request.get_json(force=True, silent=True) or {}
        req = SimpleNamespace(
            query=_field(str(payload.get("query") or "")),
            top_k=_field(payload.get("top_k") or 5),
        )
        hit_result = await _to_thread(
            _get_service(KnowledgeBaseService).hit_test,
            knowledge_base_id,
            req,
            account,
        )
        return _ok(hit_result)

    @quart_app.get("/space/knowledge-bases/<uuid:knowledge_base_id>/documents")
    async def async_get_documents_with_page(knowledge_base_id) -> Response:
        """async 获取知识库文档分页列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.knowledge_base_schema import GetKnowledgeDocumentsWithPageResp
        from internal.service import KnowledgeBaseService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            search_word=_field(request.args.get("search_word"), None),
        )
        documents, paginator = await _to_thread(
            _get_service(KnowledgeBaseService).get_documents_with_page,
            knowledge_base_id,
            req,
            account,
        )
        resp = GetKnowledgeDocumentsWithPageResp(many=True)
        return _ok({"list": resp.dump(documents), "paginator": asdict(paginator)})

    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>/documents/upload")
    async def async_upload_document(knowledge_base_id) -> Response:
        """async 上传文档到知识库。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        files = await request.files
        file = files.get("file")
        if file is None or not file.filename:
            return _json_resp(
                code="validate_error",
                message="请选择要上传的文件",
                data={"file": ["请选择要上传的文件"]},
                status=400,
            )
        await _to_thread(
            _get_service(KnowledgeBaseService).upload_document,
            knowledge_base_id,
            file,
            account,
        )
        return _ok_msg("上传文档成功")

    @quart_app.get("/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>")
    async def async_get_document(knowledge_base_id, document_id) -> Response:
        """async 获取文档详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.knowledge_base_schema import GetKnowledgeDocumentResp
        from internal.service import KnowledgeBaseService

        document = await _to_thread(
            _get_service(KnowledgeBaseService).get_document_detail,
            knowledge_base_id,
            document_id,
            account,
        )
        return _ok(GetKnowledgeDocumentResp().dump(document))

    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/delete")
    async def async_delete_document(knowledge_base_id, document_id) -> Response:
        """async 删除文档。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        await _to_thread(
            _get_service(KnowledgeBaseService).delete_document,
            knowledge_base_id,
            document_id,
            account,
        )
        return _ok_msg("删除文档成功")

    @quart_app.get("/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/segments")
    async def async_get_segments_with_page(knowledge_base_id, document_id) -> Response:
        """async 获取文档片段分页列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.knowledge_base_schema import GetKnowledgeSegmentsWithPageResp
        from internal.service import KnowledgeBaseService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            search_word=_field(request.args.get("search_word"), None),
        )
        segments, paginator = await _to_thread(
            _get_service(KnowledgeBaseService).get_segments_with_page,
            knowledge_base_id,
            document_id,
            req,
            account,
        )
        resp = GetKnowledgeSegmentsWithPageResp(many=True)
        return _ok({"list": resp.dump(segments), "paginator": asdict(paginator)})

    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/segments/<uuid:segment_id>")
    async def async_update_segment(knowledge_base_id, document_id, segment_id) -> Response:
        """async 更新文档片段。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        payload = await request.get_json(force=True, silent=True) or {}
        req = SimpleNamespace(
            content=_field(str(payload.get("content") or "")),
            is_enabled=_field(bool(payload.get("is_enabled", True))),
        )
        await _to_thread(
            _get_service(KnowledgeBaseService).update_segment,
            knowledge_base_id,
            document_id,
            segment_id,
            req,
            account,
        )
        return _ok_msg("更新片段成功")

    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>/regenerate-icon")
    async def async_knowledge_base_regenerate_icon(knowledge_base_id) -> Response:
        """async 重新生成知识库图标。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        icon_url = await _to_thread(
            _get_service(KnowledgeBaseService).regenerate_icon, knowledge_base_id, account
        )
        return _ok({"icon": icon_url})

    @quart_app.post("/space/knowledge-bases/generate-icon-preview")
    async def async_knowledge_base_generate_icon_preview() -> Response:
        """async 生成知识库图标预览。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="知识库名称不能为空",
                data={"name": ["知识库名称不能为空"]},
                status=400,
            )
        icon_url = await _to_thread(
            _get_service(KnowledgeBaseService).generate_icon_preview,
            name,
            str(payload.get("description") or ""),
        )
        return _ok({"icon": icon_url})

    @quart_app.get("/space/system-knowledge-bases")
    async def async_list_system_knowledge_bases() -> Response:
        """async 列出对 Agent 可读的系统知识库。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.scoped_knowledge_service import UserContentKnowledgeService

        user_content_service = _get_service(UserContentKnowledgeService)
        bases = await _to_thread(user_content_service.list_readable_system_bases)
        result = [
            {
                "id": str(base.id),
                "name": base.name,
                "description": base.description or "",
                "knowledge_scope": base.knowledge_scope,
            }
            for base in bases
        ]
        return _ok({"list": result})

    @quart_app.get("/mcp-providers/categories")
    async def async_get_mcp_categories_for_space() -> Response:
        """async 获取个人空间 MCP 分类列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.mcp_schema import GetMcpCategoriesResp

        return _ok(GetMcpCategoriesResp().dump({}))

    @quart_app.get("/mcp-providers")
    async def async_get_mcp_providers_with_page() -> Response:
        """async 获取个人 MCP 分页列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.mcp_schema import McpProviderResp
        from internal.service.mcp_service import McpService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            search_word=_field(request.args.get("search_word"), None),
        )
        providers, paginator = await _to_thread(
            _get_service(McpService).get_mcp_providers_with_page, req, account
        )
        resp = McpProviderResp(many=True)
        return _ok({"list": resp.dump(providers), "paginator": asdict(paginator)})

    @quart_app.post("/mcp-providers")
    async def async_create_mcp_provider() -> Response:
        """async 创建 MCP。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.mcp_service import McpService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="MCP 名称不能为空",
                data={"name": ["MCP 名称不能为空"]},
                status=400,
            )
        req = SimpleNamespace(
            name=_field(name),
            description=_field(str(payload.get("description") or "")),
            config=_field(payload.get("config") or {}),
            icon=_field(str(payload.get("icon") or "")),
        )
        provider = await _to_thread(
            _get_service(McpService).create_mcp_provider, req, account
        )
        return _ok({"id": str(provider.id)})

    @quart_app.post("/mcp-providers/import-mcp-json")
    async def async_import_mcp_json() -> Response:
        """async 标准 mcp.json 批量导入。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.mcp_import_service import McpImportService

        payload = await request.get_json(force=True, silent=True) or {}
        config_json = str(payload.get("config_json") or "")
        if not config_json:
            return _json_resp(
                code="validate_error",
                message="config_json 不能为空",
                data={"config_json": ["config_json 不能为空"]},
                status=400,
            )
        result = await _to_thread(
            _get_service(McpImportService).import_from_mcp_json,
            config_json,
            account.id,
            overwrite=bool(payload.get("overwrite", False)),
        )
        return _ok(result)

    @quart_app.get("/mcp-providers/<uuid:provider_id>")
    async def async_get_mcp_provider(provider_id) -> Response:
        """async 获取个人 MCP 详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.mcp_schema import McpProviderResp
        from internal.service.mcp_service import McpService

        provider = await _to_thread(
            _get_service(McpService).get_mcp_provider, provider_id, account
        )
        return _ok(McpProviderResp().dump(provider))

    @quart_app.post("/mcp-providers/<uuid:provider_id>")
    async def async_update_mcp_provider(provider_id) -> Response:
        """async 更新 MCP。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.mcp_service import McpService

        payload = await request.get_json(force=True, silent=True) or {}
        req = SimpleNamespace(
            name=_field(str(payload.get("name") or "")),
            description=_field(str(payload.get("description") or "")),
            config=_field(payload.get("config") or {}),
            icon=_field(str(payload.get("icon") or "")),
        )
        await _to_thread(
            _get_service(McpService).update_mcp_provider, provider_id, req, account
        )
        return _ok_msg("更新 MCP 成功")

    @quart_app.post("/mcp-providers/<uuid:provider_id>/delete")
    async def async_delete_mcp_provider(provider_id) -> Response:
        """async 删除 MCP。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.mcp_service import McpService

        await _to_thread(
            _get_service(McpService).delete_mcp_provider, provider_id, account
        )
        return _ok_msg("删除 MCP 成功")

    @quart_app.post("/mcp-providers/<uuid:provider_id>/publish")
    async def async_publish_mcp_provider(provider_id) -> Response:
        """async 发布 MCP 到广场。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.mcp_service import McpService

        await _to_thread(
            _get_service(McpService).publish_mcp_provider, provider_id, account
        )
        return _ok_msg("MCP 已发布到广场")

    @quart_app.post("/mcp-providers/<uuid:provider_id>/unpublish")
    async def async_unpublish_mcp_provider(provider_id) -> Response:
        """async 取消 MCP 发布。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.mcp_service import McpService

        await _to_thread(
            _get_service(McpService).unpublish_mcp_provider, provider_id, account
        )
        return _ok_msg("MCP 已取消发布")

    @quart_app.post("/mcp-providers/<uuid:provider_id>/regenerate-icon")
    async def async_mcp_regenerate_icon(provider_id) -> Response:
        """async 重新生成 MCP 图标。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.mcp_service import McpService

        icon = await _to_thread(
            _get_service(McpService).regenerate_icon, provider_id, account
        )
        return _ok({"icon": icon})

    @quart_app.post("/mcp-providers/generate-icon-preview")
    async def async_mcp_generate_icon_preview() -> Response:
        """async 生成 MCP 图标预览。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.mcp_service import McpService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="MCP 名称不能为空",
                data={"name": ["MCP 名称不能为空"]},
                status=400,
            )
        icon = await _to_thread(
            _get_service(McpService).generate_icon_preview,
            name,
            str(payload.get("description") or ""),
        )
        return _ok({"icon": icon})
