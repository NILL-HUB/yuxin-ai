"""管理员工作流 + 管理员系统知识库 Quart 异步端点（阶段 2.3 迁移）。

实现来源：
- internal/handler/admin_workflow_handler.py
- internal/handler/admin_system_knowledge_handler.py

路径与 HTTP 方法来源：internal/router/router.py 中
``self.admin_workflow_handler.`` 与 ``self.admin_system_knowledge_handler.`` 注册段。

调用方式（幂等，可重复注册）：
    register_routes(asgi_app.quart_app)
"""

from quart import request

_registered = False


def register_routes(quart_app):
    """在给定 Quart 应用上注册 admin 工作流/系统知识库端点（幂等）。"""
    global _registered
    if _registered:
        return
    _registered = True

    # ------------------------------------------------------------------
    # AdminWorkflowHandler 端点
    # ------------------------------------------------------------------

    @quart_app.get("/admin/workflows")
    async def async_admin_workflow_list():
        from app.http import asgi_app as a
        from internal.schema.admin_workflow_schema import AdminWorkflowPageResp
        from internal.service.admin_workflow_service import AdminWorkflowService

        def _int_arg(name, default):
            raw = request.args.get(name)
            try:
                return int(raw) if raw is not None else default
            except ValueError:
                return default

        result = await a._to_thread(
            a._get_service(AdminWorkflowService).list_workflows,
            search=request.args.get("search") or "",
            status=request.args.get("status") or "all",
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
        )
        return a._ok(AdminWorkflowPageResp().dump(result))

    @quart_app.get("/admin/workflows/<uuid:workflow_id>")
    async def async_admin_workflow_get(workflow_id):
        from app.http import asgi_app as a
        from internal.schema.admin_workflow_schema import AdminWorkflowResp
        from internal.service.admin_workflow_service import AdminWorkflowService

        result = await a._to_thread(
            a._get_service(AdminWorkflowService).get_workflow, workflow_id
        )
        return a._ok(AdminWorkflowResp().dump(result))

    @quart_app.patch("/admin/workflows/<uuid:workflow_id>")
    async def async_admin_workflow_update(workflow_id):
        from app.http import asgi_app as a
        from internal.schema.admin_workflow_schema import AdminWorkflowResp
        from internal.service.admin_workflow_service import AdminWorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        task_keywords = payload.get("task_keywords")
        if task_keywords is not None and not isinstance(task_keywords, list):
            return a._json_resp(
                code="validate_error",
                message="task_keywords 必须是数组",
                data={"task_keywords": ["task_keywords 必须是数组"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(AdminWorkflowService).update_workflow,
            workflow_id,
            status=str(payload.get("status") or "") or None,
            is_public=payload.get("is_public") if "is_public" in payload else None,
            task_keywords=task_keywords,
        )
        return a._ok(AdminWorkflowResp().dump(result))

    @quart_app.post("/admin/workflows/<uuid:workflow_id>/offline")
    async def async_admin_workflow_offline(workflow_id):
        from app.http import asgi_app as a
        from internal.service.admin_workflow_service import AdminWorkflowService

        await a._to_thread(
            a._get_service(AdminWorkflowService).offline_workflow, workflow_id
        )
        return a._ok_msg("下架工作流成功")

    @quart_app.post("/admin/workflows")
    async def async_admin_workflow_create():
        from app.http import asgi_app as a
        from internal.service import WorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error",
                message="工作流名称不能为空",
                data={"name": ["工作流名称不能为空"]},
                status=400,
            )
        req = a.SimpleNamespace(
            name=a._field(name),
            tool_call_name=a._field(str(payload.get("tool_call_name") or "")),
            icon=a._field(str(payload.get("icon") or "")),
            description=a._field(str(payload.get("description") or "")),
            task_keywords=a._field(payload.get("task_keywords") or []),
        )
        workflow = await a._to_thread(
            a._get_service(WorkflowService).create_workflow,
            req,
            created_by_admin=a._ADMIN_USER_ID if hasattr(a, "_ADMIN_USER_ID") else None,
        )
        return a._ok({"id": str(workflow.id)})

    @quart_app.delete("/admin/workflows/<uuid:workflow_id>")
    async def async_admin_workflow_delete(workflow_id):
        from app.http import asgi_app as a
        from internal.service import WorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        await a._to_thread(
            a._get_service(WorkflowService).delete_workflow_for_admin,
            workflow_id,
            retention_days=payload.get("retention_days"),
            deleted_by=None,
        )
        return a._ok_msg("删除工作流成功")

    @quart_app.get("/admin/workflows/<uuid:workflow_id>/draft-graph")
    async def async_admin_workflow_get_draft_graph(workflow_id):
        from app.http import asgi_app as a
        from internal.service import WorkflowService

        draft_graph = await a._to_thread(
            a._get_service(WorkflowService).get_draft_graph_for_admin, workflow_id
        )
        return a._ok(draft_graph)

    @quart_app.post("/admin/workflows/<uuid:workflow_id>/draft-graph")
    async def async_admin_workflow_update_draft_graph(workflow_id):
        from app.http import asgi_app as a
        from internal.service import WorkflowService

        draft_graph_dict = (
            await request.get_json(force=True, silent=True)
        ) or {"nodes": [], "edges": []}
        await a._to_thread(
            a._get_service(WorkflowService).update_draft_graph_for_admin,
            workflow_id,
            draft_graph_dict,
        )
        return a._ok_msg("更新工作流草稿配置成功")

    @quart_app.post("/admin/workflows/<uuid:workflow_id>/publish")
    async def async_admin_workflow_publish(workflow_id):
        from app.http import asgi_app as a
        from internal.service import WorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        summary = str(payload.get("summary") or "")
        await a._to_thread(
            a._get_service(WorkflowService).publish_workflow_for_admin,
            workflow_id,
            summary=summary,
        )
        return a._ok_msg("发布工作流成功")

    @quart_app.get("/admin/workflows/<uuid:workflow_id>/versions")
    async def async_admin_workflow_get_versions(workflow_id):
        from app.http import asgi_app as a
        from internal.lib.helper import datetime_to_timestamp
        from internal.schema.admin_workflow_schema import WorkflowVersionListResp
        from internal.service import WorkflowService

        versions = await a._to_thread(
            a._get_service(WorkflowService).get_workflow_versions_for_admin,
            workflow_id,
        )
        payload = {
            "list": [
                {
                    "id": str(v.id),
                    "workflow_id": str(v.workflow_id),
                    "version": v.version,
                    "is_current_published": v.is_current_published,
                    "summary": v.summary or "",
                    "created_at": datetime_to_timestamp(v.created_at),
                    "updated_at": datetime_to_timestamp(v.updated_at),
                }
                for v in versions
            ]
        }
        return a._ok(WorkflowVersionListResp().dump(payload))

    @quart_app.post("/admin/workflows/<uuid:workflow_id>/versions/<uuid:version_id>/rollback")
    async def async_admin_workflow_rollback_version(workflow_id, version_id):
        from app.http import asgi_app as a
        from internal.service import WorkflowService

        await a._to_thread(
            a._get_service(WorkflowService).rollback_workflow_version_for_admin,
            workflow_id,
            version_id,
        )
        return a._ok_msg("回滚工作流版本成功")

    @quart_app.post("/admin/workflows/batch/publish")
    async def async_admin_workflow_batch_publish():
        from uuid import UUID

        from app.http import asgi_app as a
        from internal.schema.admin_workflow_schema import BatchOperationResp
        from internal.service import WorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        workflow_ids = payload.get("workflow_ids")
        if not isinstance(workflow_ids, list) or len(workflow_ids) == 0:
            return a._json_resp(
                code="validate_error",
                message="工作流ID列表不能为空",
                data={"workflow_ids": ["工作流ID列表不能为空"]},
                status=400,
            )
        succeeded = []
        failed = []
        for wid in workflow_ids:
            try:
                await a._to_thread(
                    a._get_service(WorkflowService).publish_workflow_for_admin,
                    UUID(str(wid)),
                )
                succeeded.append(str(wid))
            except Exception as exc:
                failed.append({"id": str(wid), "reason": str(exc)})
        return a._ok(
            BatchOperationResp().dump({"succeeded": succeeded, "failed": failed})
        )

    @quart_app.post("/admin/workflows/batch/offline")
    async def async_admin_workflow_batch_offline():
        from uuid import UUID

        from app.http import asgi_app as a
        from internal.schema.admin_workflow_schema import BatchOperationResp
        from internal.service.admin_workflow_service import AdminWorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        workflow_ids = payload.get("workflow_ids")
        if not isinstance(workflow_ids, list) or len(workflow_ids) == 0:
            return a._json_resp(
                code="validate_error",
                message="工作流ID列表不能为空",
                data={"workflow_ids": ["工作流ID列表不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(AdminWorkflowService).batch_offline_workflows,
            [UUID(str(wid)) for wid in workflow_ids],
        )
        return a._ok(BatchOperationResp().dump(result))

    @quart_app.post("/admin/workflows/import")
    async def async_admin_workflow_import():
        from app.http import asgi_app as a
        from internal.schema.workflow_schema import ImportWorkflowResp
        from internal.service import WorkflowService

        body = await request.get_json(force=True, silent=True)
        if not isinstance(body, dict):
            return a._json_resp(
                code="validate_error",
                message="请求体必须是 JSON 对象",
                data={"json_data": ["请求体必须是 JSON 对象"]},
                status=400,
            )
        if isinstance(body.get("json_data"), dict):
            json_data = body["json_data"]
            overwrite_name = bool(body.get("overwrite_name", False))
        elif body.get("format") in {"openagent-workflow", "yuxin-ai-workflow"}:
            json_data = body
            overwrite_name = request.args.get("overwrite_name", "").lower() in ("true", "1", "yes")
        else:
            return a._json_resp(
                code="validate_error",
                message="无法识别的导入数据格式，缺少 json_data 字段或 format 字段不正确",
                data={"json_data": ["无法识别的导入数据格式，缺少 json_data 字段或 format 字段不正确"]},
                status=400,
            )
        workflow = await a._to_thread(
            a._get_service(WorkflowService).import_workflow,
            json_data,
            overwrite_name=overwrite_name,
            created_by_admin=None,
        )
        return a._ok(ImportWorkflowResp().dump(workflow))

    @quart_app.get("/admin/workflows/<uuid:workflow_id>/export")
    async def async_admin_workflow_export(workflow_id):
        from app.http import asgi_app as a
        from internal.service import WorkflowService

        include_versions = request.args.get("include_versions", "").lower() in ("true", "1", "yes")
        data = await a._to_thread(
            a._get_service(WorkflowService).export_workflow_for_admin,
            workflow_id,
            include_versions=include_versions,
        )
        return a._ok(data)

    # ------------------------------------------------------------------
    # AdminSystemKnowledgeHandler 端点
    # ------------------------------------------------------------------

    @quart_app.get("/admin/system-knowledge")
    async def async_admin_system_knowledge_list():
        from app.http import asgi_app as a
        from internal.schema.admin_system_knowledge_schema import SystemKnowledgeListResp
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        def _int_arg(name, default):
            raw = request.args.get(name)
            try:
                return int(raw) if raw is not None else default
            except ValueError:
                return default

        result = await a._to_thread(
            a._get_service(SystemKnowledgeService).list_system_knowledge,
            page=_int_arg("page", 1),
            page_size=_int_arg("page_size", 20),
            search_word=request.args.get("search_word") or "",
        )
        return a._ok(SystemKnowledgeListResp().dump(result))

    @quart_app.post("/admin/system-knowledge")
    async def async_admin_system_knowledge_create():
        from app.http import asgi_app as a
        from internal.schema.admin_system_knowledge_schema import SystemKnowledgeResp
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return a._json_resp(
                code="validate_error",
                message="知识库名称不能为空",
                data={"name": ["知识库名称不能为空"]},
                status=400,
            )
        admin_user = a.SimpleNamespace(id="00000000-0000-0000-0000-000000000000")
        knowledge_base = await a._to_thread(
            a._get_service(SystemKnowledgeService).create_system_knowledge,
            name=name,
            description=str(payload.get("description") or ""),
            admin_user=admin_user,
            visibility_scope=str(payload.get("visibility_scope") or "internal"),
        )
        return a._ok(SystemKnowledgeResp().dump(knowledge_base))

    @quart_app.get("/admin/system-knowledge/<uuid:knowledge_base_id>")
    async def async_admin_system_knowledge_get(knowledge_base_id):
        from app.http import asgi_app as a
        from internal.schema.admin_system_knowledge_schema import SystemKnowledgeResp
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        knowledge_base = await a._to_thread(
            a._get_service(SystemKnowledgeService).get_system_knowledge, knowledge_base_id
        )
        return a._ok(SystemKnowledgeResp().dump(knowledge_base))

    @quart_app.post("/admin/system-knowledge/<uuid:knowledge_base_id>")
    async def async_admin_system_knowledge_update(knowledge_base_id):
        from app.http import asgi_app as a
        from internal.schema.admin_system_knowledge_schema import SystemKnowledgeResp
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        payload = await request.get_json(force=True, silent=True) or {}
        admin_user = a.SimpleNamespace(id="00000000-0000-0000-0000-000000000000")
        knowledge_base = await a._to_thread(
            a._get_service(SystemKnowledgeService).update_system_knowledge,
            knowledge_base_id,
            name=payload.get("name") if "name" in payload else None,
            description=payload.get("description") if "description" in payload else None,
            enabled=payload.get("enabled") if "enabled" in payload else None,
            visibility_scope=payload.get("visibility_scope") if "visibility_scope" in payload else None,
            admin_user=admin_user,
        )
        return a._ok(SystemKnowledgeResp().dump(knowledge_base))

    @quart_app.delete("/admin/system-knowledge/<uuid:knowledge_base_id>")
    async def async_admin_system_knowledge_delete(knowledge_base_id):
        from app.http import asgi_app as a
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        payload = await request.get_json(force=True, silent=True) or {}
        admin_user = a.SimpleNamespace(id="00000000-0000-0000-0000-000000000000")
        await a._to_thread(
            a._get_service(SystemKnowledgeService).delete_system_knowledge,
            knowledge_base_id,
            admin_user=admin_user,
            retention_days=payload.get("retention_days"),
        )
        return a._ok({"id": str(knowledge_base_id)})

    @quart_app.get("/admin/system-knowledge/<uuid:knowledge_base_id>/documents")
    async def async_admin_system_knowledge_get_documents(knowledge_base_id):
        from app.http import asgi_app as a
        from internal.schema.knowledge_base_schema import GetKnowledgeDocumentsWithPageResp
        from internal.service.scoped_knowledge_service import SystemKnowledgeService
        from pkg.paginator import PageModel

        def _int_arg(name, default):
            raw = request.args.get(name)
            try:
                return int(raw) if raw is not None else default
            except ValueError:
                return default

        req = a.SimpleNamespace(
            current_page=a._field(_int_arg("current_page", 1), 1),
            page_size=a._field(_int_arg("page_size", 20), 20),
            search_word=a._field(request.args.get("search_word"), None),
        )
        documents, paginator = await a._to_thread(
            a._get_service(SystemKnowledgeService).list_documents_for_admin,
            knowledge_base_id,
            req,
        )
        resp = GetKnowledgeDocumentsWithPageResp(many=True)
        return a._ok(a.asdict(PageModel(list=resp.dump(documents), paginator=paginator)))

    @quart_app.post("/admin/system-knowledge/<uuid:knowledge_base_id>/documents/upload")
    async def async_admin_system_knowledge_upload_document(knowledge_base_id):
        from app.http import asgi_app as a
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        files = await request.files
        file = files.get("file")
        if file is None or not file.filename:
            return a._json_resp(
                code="validate_error",
                message="请选择要上传的文件",
                data={"file": ["请选择要上传的文件"]},
                status=400,
            )
        document = await a._to_thread(
            a._get_service(SystemKnowledgeService).upload_document_for_admin,
            knowledge_base_id,
            file,
        )
        return a._ok({"id": str(document.id), "name": document.name})

    @quart_app.post("/admin/system-knowledge/<uuid:knowledge_base_id>/documents/text")
    async def async_admin_system_knowledge_create_text_document(knowledge_base_id):
        from app.http import asgi_app as a
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        content = str(payload.get("content") or "")
        if not name:
            return a._json_resp(
                code="validate_error",
                message="文档名称不能为空",
                data={"name": ["文档名称不能为空"]},
                status=400,
            )
        if not content:
            return a._json_resp(
                code="validate_error",
                message="文档内容不能为空",
                data={"content": ["文档内容不能为空"]},
                status=400,
            )
        document = await a._to_thread(
            a._get_service(SystemKnowledgeService).create_text_document_for_admin,
            knowledge_base_id,
            name=name,
            content=content,
        )
        return a._ok({"id": str(document.id), "name": document.name})

    @quart_app.get("/admin/system-knowledge/<uuid:knowledge_base_id>/documents/<uuid:document_id>")
    async def async_admin_system_knowledge_get_document(knowledge_base_id, document_id):
        from app.http import asgi_app as a
        from internal.schema.knowledge_base_schema import GetKnowledgeDocumentResp
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        document = await a._to_thread(
            a._get_service(SystemKnowledgeService).get_document_for_admin,
            knowledge_base_id,
            document_id,
        )
        return a._ok(GetKnowledgeDocumentResp().dump(document))

    @quart_app.post("/admin/system-knowledge/<uuid:knowledge_base_id>/documents/<uuid:document_id>")
    async def async_admin_system_knowledge_update_document(knowledge_base_id, document_id):
        from app.http import asgi_app as a
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        content = str(payload.get("content") or "")
        if not name:
            return a._json_resp(
                code="validate_error",
                message="文档名称不能为空",
                data={"name": ["文档名称不能为空"]},
                status=400,
            )
        if not content:
            return a._json_resp(
                code="validate_error",
                message="文档内容不能为空",
                data={"content": ["文档内容不能为空"]},
                status=400,
            )
        document = await a._to_thread(
            a._get_service(SystemKnowledgeService).update_text_document_for_admin,
            knowledge_base_id,
            document_id,
            name=name,
            content=content,
        )
        return a._ok({"id": str(document.id), "name": document.name})

    @quart_app.delete("/admin/system-knowledge/<uuid:knowledge_base_id>/documents/<uuid:document_id>")
    async def async_admin_system_knowledge_delete_document(knowledge_base_id, document_id):
        from app.http import asgi_app as a
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        payload = await request.get_json(force=True, silent=True) or {}
        admin_user = a.SimpleNamespace(id="00000000-0000-0000-0000-000000000000")
        await a._to_thread(
            a._get_service(SystemKnowledgeService).delete_document_for_admin,
            knowledge_base_id,
            document_id,
            admin_user=admin_user,
            retention_days=payload.get("retention_days"),
        )
        return a._ok_msg("删除文档成功")

    @quart_app.get("/admin/system-knowledge/<uuid:knowledge_base_id>/documents/<uuid:document_id>/segments")
    async def async_admin_system_knowledge_get_segments(knowledge_base_id, document_id):
        from app.http import asgi_app as a
        from internal.schema.knowledge_base_schema import GetKnowledgeSegmentsWithPageResp
        from internal.service.scoped_knowledge_service import SystemKnowledgeService
        from pkg.paginator import PageModel

        def _int_arg(name, default):
            raw = request.args.get(name)
            try:
                return int(raw) if raw is not None else default
            except ValueError:
                return default

        req = a.SimpleNamespace(
            current_page=a._field(_int_arg("current_page", 1), 1),
            page_size=a._field(_int_arg("page_size", 20), 20),
            search_word=a._field(request.args.get("search_word"), None),
        )
        segments, paginator = await a._to_thread(
            a._get_service(SystemKnowledgeService).get_segments_for_admin,
            knowledge_base_id,
            document_id,
            req,
        )
        resp = GetKnowledgeSegmentsWithPageResp(many=True)
        return a._ok(a.asdict(PageModel(list=resp.dump(segments), paginator=paginator)))

    @quart_app.post("/admin/system-knowledge/<uuid:knowledge_base_id>/hit-test")
    async def async_admin_system_knowledge_hit_test(knowledge_base_id):
        from app.http import asgi_app as a
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        payload = await request.get_json(force=True, silent=True) or {}
        query = str(payload.get("query") or "")
        retrieval_strategy = str(payload.get("retrieval_strategy") or "")
        raw_k = payload.get("k")
        if not query:
            return a._json_resp(
                code="validate_error",
                message="查询语句不能为空",
                data={"query": ["查询语句不能为空"]},
                status=400,
            )
        if not retrieval_strategy:
            return a._json_resp(
                code="validate_error",
                message="检索策略不能为空",
                data={"retrieval_strategy": ["检索策略不能为空"]},
                status=400,
            )
        try:
            k = int(raw_k)
        except (TypeError, ValueError):
            return a._json_resp(
                code="validate_error",
                message="最大召回数量不能为空",
                data={"k": ["最大召回数量不能为空"]},
                status=400,
            )
        req = a.SimpleNamespace(
            query=a._field(query),
            retrieval_strategy=a._field(retrieval_strategy),
            k=a._field(k),
            score=a._field(payload.get("score"), None),
        )
        hit_result = await a._to_thread(
            a._get_service(SystemKnowledgeService).hit_test_for_admin,
            knowledge_base_id,
            req,
        )
        return a._ok(hit_result)
