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


def _parse_partition_id_arg(raw) -> "UUID | None":
    """解析分区 id query 参数：非法或缺失返回 None。"""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return UUID(str(raw).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _get_service(cls):
    return _support._get_service(cls)


async def _resolve_confirmation_actor():
    """解析工具确认主体：统一要求登录（WebApp 游客通道已下线）。"""
    return await _resolve_account()


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    def _masked_data_source(row) -> dict:
        """序列化单条数据源并对 config 脱敏，避免密钥回传前端。"""
        from internal.schema.external_data_source_schema import ExternalDataSourceResp
        from internal.service.external_data_source_credentials import mask_config

        payload = ExternalDataSourceResp().dump(row)
        payload["config"] = mask_config(getattr(row, "config", None))
        return payload

    @quart_app.get("/external-data-sources")
    async def async_external_data_source_list() -> Response:
        """async 获取外部数据源列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.external_data_source_service import ExternalDataSourceService

        data_sources = await _to_thread(
            _get_service(ExternalDataSourceService).list_data_sources,
            account=account,
            status=request.args.get("status") or "",
        )
        items = [_masked_data_source(row) for row in data_sources]
        return _ok({"items": items, "total": len(items)})

    @quart_app.post("/external-data-sources")
    async def async_external_data_source_create() -> Response:
        """async 创建外部数据源连接。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

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
        return _ok(_masked_data_source(data_source))

    @quart_app.get("/external-data-sources/<uuid:data_source_id>")
    async def async_external_data_source_get(data_source_id) -> Response:
        """async 获取外部数据源详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.external_data_source_service import ExternalDataSourceService

        data_source = await _to_thread(
            _get_service(ExternalDataSourceService).get_data_source,
            data_source_id,
            account,
        )
        return _ok(_masked_data_source(data_source))

    @quart_app.delete("/external-data-sources/<uuid:data_source_id>")
    async def async_external_data_source_delete(data_source_id) -> Response:
        """async 删除外部数据源连接（进入回收站，可指定留存天数；agent 代删默认 7 天）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.external_data_source_service import ExternalDataSourceService

        payload = await request.get_json(force=True, silent=True) or {}
        await _to_thread(
            _get_service(ExternalDataSourceService).delete_data_source,
            data_source_id,
            account,
            retention_days=payload.get("retention_days"),
            agent_id=payload.get("agent_id"),
        )
        return _ok({"deleted": True})

    @quart_app.post("/external-data-sources/<uuid:data_source_id>/authorize")
    async def async_external_data_source_authorize(data_source_id) -> Response:
        """async 授权外部数据源。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.external_data_source_service import ExternalDataSourceService

        payload = await request.get_json(force=True, silent=True) or {}
        data_source = await _to_thread(
            _get_service(ExternalDataSourceService).authorize_data_source,
            data_source_id,
            account,
            payload.get("auth_config") or {},
        )
        return _ok(_masked_data_source(data_source))

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
        account, err = await _resolve_confirmation_actor()
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
        account, err = await _resolve_confirmation_actor()
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

    @quart_app.post("/tool-confirmations/<uuid:confirmation_id>/redirect")
    async def async_tool_confirmation_redirect(confirmation_id) -> Response:
        """async 执行中纠正：确认等待期把用户新消息注入当前轮。"""
        account, err = await _resolve_confirmation_actor()
        if err is not None:
            return err

        payload = await request.get_json(force=True, silent=True) or {}
        message = str(payload.get("message") or "").strip()
        if not message:
            return _json_resp(
                code="validate_error",
                message="redirect message 不能为空",
                status=400,
            )

        from internal.core.agent.adapters.hermes.midturn_redirect import set_redirect
        from internal.service.tool_confirmation_service import ToolConfirmationService

        # 校验确认归属后再写纠正消息，避免任意 confirmation_id 被污染。
        confirmation = await _to_thread(
            _get_service(ToolConfirmationService).get_confirmation,
            confirmation_id,
            account,
        )
        if confirmation.status != "pending":
            return _json_resp(
                code="invalid_state",
                message="该确认已结束，无法再发送纠正",
                status=400,
            )
        ok = await _to_thread(set_redirect, str(confirmation_id), message)
        if not ok:
            return _json_resp(code="internal_error", message="纠正消息暂存失败", status=500)
        return _ok({"redirected": True, "confirmation_id": str(confirmation_id)})

    @quart_app.get("/subtasks/<string:request_id>")
    async def async_subtask_snapshot(request_id) -> Response:
        """async 查询一次 Agent 执行的子任务实时状态（Hermes /agents 对齐）。"""
        account, err = await _resolve_confirmation_actor()
        if err is not None:
            return err

        from internal.service.subtask_registry_service import SubtaskRegistryService

        snapshot = await _to_thread(
            _get_service(SubtaskRegistryService).snapshot,
            str(request_id),
        )
        if snapshot is None:
            return _json_resp(
                code="not_found",
                message="subtask run not found",
                status=404,
            )
        return _ok(snapshot)

    @quart_app.post("/subtasks/<string:request_id>/cancel")
    async def async_subtask_cancel(request_id) -> Response:
        """async 取消一次 Agent 执行（公共子代理生命周期 API）。"""
        account, err = await _resolve_confirmation_actor()
        if err is not None:
            return err

        from internal.service.subtask_registry_service import SubtaskRegistryService

        registry = _get_service(SubtaskRegistryService)
        snapshot = await _to_thread(registry.snapshot, str(request_id))
        if snapshot is None:
            return _json_resp(
                code="not_found",
                message="subtask run not found",
                status=404,
            )
        cancelled = await _to_thread(registry.cancel, str(request_id))
        return _ok({
            "cancelled": cancelled,
            "reason": "" if cancelled else "no_cancel_token_in_this_worker",
        })

    @quart_app.post("/subtasks/<string:request_id>/redirect")
    async def async_subtask_redirect(request_id) -> Response:
        """async 执行中纠正：向一次执行注入用户新指令（任意工具执行阶段）。"""
        account, err = await _resolve_confirmation_actor()
        if err is not None:
            return err

        payload = await request.get_json(force=True, silent=True) or {}
        message = str(payload.get("message") or "").strip()
        if not message:
            return _json_resp(
                code="validate_error",
                message="redirect message 不能为空",
                status=400,
            )

        from internal.core.agent.adapters.hermes.midturn_redirect import (
            set_request_redirect,
        )
        from internal.service.subtask_registry_service import SubtaskRegistryService

        registry = _get_service(SubtaskRegistryService)
        snapshot = await _to_thread(registry.snapshot, str(request_id))
        if snapshot is None:
            return _json_resp(
                code="not_found",
                message="subtask run not found",
                status=404,
            )
        ok = await _to_thread(set_request_redirect, str(request_id), message)
        if not ok:
            return _json_resp(code="internal_error", message="纠正消息暂存失败", status=500)
        return _ok({"redirected": True, "request_id": str(request_id)})

    @quart_app.get("/space/storage/usage")
    async def async_get_storage_usage() -> Response:
        """async 获取用户端存储用量概览（供用量面板）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.storage_quota_service import StorageQuotaService

        summary = await _to_thread(
            _get_service(StorageQuotaService).get_usage_summary, account.id
        )
        return _ok(summary)

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
            base_type=_field(str(payload.get("base_type") or "mixed")),
            partition_mode=_field(str(payload.get("partition_mode") or "none")),
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
        """async 删除知识库（进入回收站，可指定留存天数；agent 代删默认 7 天）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        payload = await request.get_json(force=True, silent=True) or {}
        await _to_thread(
            _get_service(KnowledgeBaseService).delete_user_content_base,
            knowledge_base_id,
            account,
            retention_days=payload.get("retention_days"),
            agent_id=payload.get("agent_id"),
        )
        return _ok_msg("删除知识库成功")

    @quart_app.get("/space/knowledge-bases/<uuid:knowledge_base_id>/partitions")
    async def async_list_partitions(knowledge_base_id) -> Response:
        """async 列出知识库分区（两级树，供前端导航）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.knowledge_base_service import KnowledgeBaseService
        from internal.service.knowledge_partition_service import KnowledgePartitionService

        # 先校验板块归属，避免越权读取他人分区结构
        await _to_thread(
            _get_service(KnowledgeBaseService).get_accessible_base,
            knowledge_base_id,
            account,
        )
        partitions = await _to_thread(
            _get_service(KnowledgePartitionService).list_partitions,
            knowledge_base_id,
        )
        return _ok([
            {
                "id": str(partition.id),
                "name": partition.name,
                "partition_key": partition.partition_key,
                "parent_id": str(partition.parent_id) if partition.parent_id else "",
                "description": partition.description or "",
                "sort_order": partition.sort_order or 0,
            }
            for partition in partitions
        ])

    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>/partitions")
    async def async_create_partition(knowledge_base_id) -> Response:
        """async 创建知识库分区（最多两级）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.knowledge_base_service import KnowledgeBaseService
        from internal.service.knowledge_partition_service import KnowledgePartitionService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="分区名称不能为空",
                data={"name": ["分区名称不能为空"]},
                status=400,
            )

        parent_id_raw = str(payload.get("parent_id") or "").strip()
        parent_id = None
        if parent_id_raw:
            try:
                parent_id = UUID(parent_id_raw)
            except (TypeError, ValueError):
                return _json_resp(
                    code="validate_error",
                    message="父分区标识非法",
                    data={"parent_id": ["父分区标识非法"]},
                    status=400,
                )

        # partition_key 未传时由名称派生（唯一约束要求非空）
        partition_key = str(payload.get("partition_key") or "").strip() or name

        # sort_order 来自 JSON body（注意不能用 _int_arg，它只读 query 参数）
        try:
            sort_order = int(payload.get("sort_order") or 0)
        except (TypeError, ValueError):
            sort_order = 0

        await _to_thread(
            _get_service(KnowledgeBaseService).get_accessible_base,
            knowledge_base_id,
            account,
        )
        partition = await _to_thread(
            _get_service(KnowledgePartitionService).create_partition,
            knowledge_base_id=knowledge_base_id,
            name=name,
            partition_key=partition_key,
            parent_id=parent_id,
            description=str(payload.get("description") or ""),
            sort_order=sort_order,
        )
        return _ok({"id": str(partition.id), "name": partition.name})

    @quart_app.post(
        "/space/knowledge-bases/<uuid:knowledge_base_id>/partitions/<uuid:partition_id>/delete"
    )
    async def async_delete_partition(knowledge_base_id, partition_id) -> Response:
        """async 删除分区（分区非空时拒绝）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.knowledge_base_service import KnowledgeBaseService
        from internal.service.knowledge_partition_service import KnowledgePartitionService

        await _to_thread(
            _get_service(KnowledgeBaseService).get_accessible_base,
            knowledge_base_id,
            account,
        )
        await _to_thread(
            _get_service(KnowledgePartitionService).delete_partition,
            knowledge_base_id,
            partition_id,
        )
        return _ok_msg("删除分区成功")

    @quart_app.get(
        "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/tags"
    )
    async def async_list_document_tags(knowledge_base_id, document_id) -> Response:
        """async 列出素材标签。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.knowledge_base_service import KnowledgeBaseService
        from internal.service.knowledge_tag_service import KnowledgeTagService

        # 先校验板块归属，避免越权读取他人素材标签
        await _to_thread(
            _get_service(KnowledgeBaseService).get_accessible_base,
            knowledge_base_id,
            account,
        )
        tags = await _to_thread(
            _get_service(KnowledgeTagService).list_document_tags,
            document_id,
        )
        return _ok([{"id": str(tag.id), "name": tag.name} for tag in tags])

    @quart_app.post(
        "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/tags"
    )
    async def async_attach_document_tag(knowledge_base_id, document_id) -> Response:
        """async 为素材打标签。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.knowledge_base_service import KnowledgeBaseService
        from internal.service.knowledge_tag_service import KnowledgeTagService

        payload = await request.get_json(force=True, silent=True) or {}
        tag_id_raw = str(payload.get("tag_id") or "").strip()
        if not tag_id_raw:
            return _json_resp(
                code="validate_error",
                message="标签标识不能为空",
                data={"tag_id": ["标签标识不能为空"]},
                status=400,
            )
        try:
            tag_id = UUID(tag_id_raw)
        except (TypeError, ValueError):
            return _json_resp(
                code="validate_error",
                message="标签标识非法",
                data={"tag_id": ["标签标识非法"]},
                status=400,
            )

        # 先校验板块归属，避免越权修改他人素材
        await _to_thread(
            _get_service(KnowledgeBaseService).get_accessible_base,
            knowledge_base_id,
            account,
        )
        link = await _to_thread(
            _get_service(KnowledgeTagService).attach_document_tag,
            account.id,
            document_id,
            tag_id,
            verify_document=True,
        )
        return _ok({"id": str(link.id)})

    @quart_app.post(
        "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>"
        "/tags/<uuid:tag_id>/delete"
    )
    async def async_detach_document_tag(knowledge_base_id, document_id, tag_id) -> Response:
        """async 移除素材标签。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.knowledge_base_service import KnowledgeBaseService
        from internal.service.knowledge_tag_service import KnowledgeTagService

        # 先校验板块归属，避免越权修改他人素材
        await _to_thread(
            _get_service(KnowledgeBaseService).get_accessible_base,
            knowledge_base_id,
            account,
        )
        await _to_thread(
            _get_service(KnowledgeTagService).detach_document_tag,
            document_id,
            tag_id,
        )
        return _ok_msg("移除标签成功")

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
            partition_id=_field(_parse_partition_id_arg(request.args.get("partition_id")), None),
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
        """async 删除文档（进入回收站，可指定留存天数；agent 代删默认 7 天）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        payload = await request.get_json(force=True, silent=True) or {}
        await _to_thread(
            _get_service(KnowledgeBaseService).delete_document,
            knowledge_base_id,
            document_id,
            account,
            retention_days=payload.get("retention_days"),
            agent_id=payload.get("agent_id"),
        )
        return _ok_msg("删除文档成功")

    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/l2")
    async def async_trigger_document_l2(knowledge_base_id, document_id) -> Response:
        """async 触发某素材的 L2 深度解析（按需，不做定时轮询）。

        请求体可选 `start_sec` / `end_sec`：给出时按显式区间密抽，
        否则由 L1 命中帧自动推导窗口。
        """
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        payload = await request.get_json(force=True, silent=True) or {}
        await _to_thread(
            _get_service(KnowledgeBaseService).trigger_document_l2,
            knowledge_base_id,
            document_id,
            account,
            start_sec=payload.get("start_sec"),
            end_sec=payload.get("end_sec"),
        )
        return _ok_msg("L2 深度解析已触发")

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
        """async 删除 MCP（进入回收站，可指定留存天数；agent 代删默认 7 天）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.mcp_service import McpService

        payload = await request.get_json(force=True, silent=True) or {}
        await _to_thread(
            _get_service(McpService).delete_mcp_provider,
            provider_id,
            account,
            retention_days=payload.get("retention_days"),
            agent_id=payload.get("agent_id"),
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
