"""工作流路由模块（从 asgi_app.py 拆分）：/workflows*。"""
from dataclasses import asdict
from types import SimpleNamespace

from quart import Response, request

from app.http import support as _support
from app.http.support import (
    _field,
    _int_arg,
    _is_sync_iterator,
    _json_resp,
    _ok,
    _ok_msg,
    _resolve_account,
    _sse_response,
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

    @quart_app.get("/workflows")
    async def async_get_workflows_with_page() -> Response:
        """async 获取工作流分页列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.workflow_schema import GetWorkflowsWithPageResp
        from internal.service import WorkflowService

        req = SimpleNamespace(
            current_page=_field(_int_arg("current_page", 1), 1),
            page_size=_field(_int_arg("page_size", 20), 20),
            search_word=_field(request.args.get("search_word"), None),
        )
        workflows, paginator = await _to_thread(
            _get_service(WorkflowService).get_workflows_with_page, req, account
        )
        resp = GetWorkflowsWithPageResp(many=True)
        return _ok({"list": resp.dump(workflows), "paginator": asdict(paginator)})

    @quart_app.post("/workflows")
    async def async_create_workflow() -> Response:
        """async 创建工作流。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="工作流名称不能为空",
                data={"name": ["工作流名称不能为空"]},
                status=400,
            )
        req = SimpleNamespace(
            name=_field(name),
            description=_field(str(payload.get("description") or "")),
            icon=_field(str(payload.get("icon") or "")),
        )
        workflow = await _to_thread(
            _get_service(WorkflowService).create_workflow, req, account
        )
        return _ok({"id": workflow.id})

    @quart_app.get("/workflows/<uuid:workflow_id>")
    async def async_get_workflow(workflow_id) -> Response:
        """async 获取工作流详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.workflow_schema import GetWorkflowResp
        from internal.service import WorkflowService

        workflow = await _to_thread(
            _get_service(WorkflowService).get_workflow, workflow_id, account
        )
        return _ok(GetWorkflowResp().dump(workflow))

    @quart_app.post("/workflows/<uuid:workflow_id>")
    async def async_update_workflow(workflow_id) -> Response:
        """async 更新工作流基础信息。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        await _to_thread(
            _get_service(WorkflowService).update_workflow, workflow_id, account, **payload
        )
        return _ok_msg("修改工作流基础信息成功")

    @quart_app.post("/workflows/<uuid:workflow_id>/delete")
    async def async_delete_workflow(workflow_id) -> Response:
        """async 删除工作流（进入回收站，可指定留存天数；agent 代删默认 7 天）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        await _to_thread(
            _get_service(WorkflowService).delete_workflow,
            workflow_id,
            account,
            retention_days=payload.get("retention_days"),
            agent_id=payload.get("agent_id"),
        )
        return _ok_msg("删除工作流成功")

    @quart_app.post("/workflows/<uuid:workflow_id>/draft-graph")
    async def async_update_draft_graph(workflow_id) -> Response:
        """async 更新工作流草稿图配置。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        draft_graph_dict = (
            await request.get_json(force=True, silent=True)
        ) or {"nodes": [], "edges": []}
        await _to_thread(
            _get_service(WorkflowService).update_draft_graph,
            workflow_id,
            draft_graph_dict,
            account,
        )
        return _ok_msg("更新工作流草稿配置成功")

    @quart_app.get("/workflows/<uuid:workflow_id>/draft-graph")
    async def async_get_draft_graph(workflow_id) -> Response:
        """async 获取工作流草稿配置。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        draft_graph = await _to_thread(
            _get_service(WorkflowService).get_draft_graph, workflow_id, account
        )
        return _ok(draft_graph)

    @quart_app.post("/workflows/<uuid:workflow_id>/publish")
    async def async_publish_workflow(workflow_id) -> Response:
        """async 发布工作流。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        await _to_thread(
            _get_service(WorkflowService).publish_workflow, workflow_id, account
        )
        return _ok_msg("发布工作流成功")

    @quart_app.post("/workflows/<uuid:workflow_id>/cancel-publish")
    async def async_cancel_publish_workflow(workflow_id) -> Response:
        """async 取消发布工作流。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        await _to_thread(
            _get_service(WorkflowService).cancel_publish_workflow, workflow_id, account
        )
        return _ok_msg("取消发布工作流成功")

    @quart_app.post("/workflows/<uuid:workflow_id>/regenerate-icon")
    async def async_workflow_regenerate_icon(workflow_id) -> Response:
        """async 重新生成工作流图标。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        icon_url = await _to_thread(
            _get_service(WorkflowService).regenerate_icon, workflow_id, account
        )
        return _ok({"icon": icon_url})

    @quart_app.post("/workflows/generate-icon-preview")
    async def async_workflow_generate_icon_preview() -> Response:
        """async 生成工作流图标预览。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _json_resp(
                code="validate_error",
                message="工作流名称不能为空",
                data={"name": ["工作流名称不能为空"]},
                status=400,
            )
        icon_url = await _to_thread(
            _get_service(WorkflowService).generate_icon_preview,
            name,
            str(payload.get("description") or ""),
        )
        return _ok({"icon": icon_url})

    @quart_app.post("/workflows/<uuid:workflow_id>/share")
    async def async_share_workflow_to_public(workflow_id) -> Response:
        """async 分享/取消分享工作流到广场。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        payload = await request.get_json(force=True, silent=True) or {}
        is_public = bool(payload.get("is_public", False))
        await _to_thread(
            _get_service(WorkflowService).share_workflow_to_public,
            workflow_id,
            account,
            is_public,
        )
        return _ok_msg("分享工作流到广场成功" if is_public else "取消分享工作流成功")

    @quart_app.get("/workflows/<uuid:workflow_id>/runs")
    async def async_get_workflow_runs_with_page(workflow_id) -> Response:
        """async 分页查询工作流执行历史。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowRunService, WorkflowService

        await _to_thread(
            _get_service(WorkflowService).get_workflow, workflow_id, account
        )

        runs, paginator = await _to_thread(
            _get_service(WorkflowRunService).get_runs_with_page,
            workflow_id=workflow_id,
            account=account,
            page=_int_arg("page", 1),
            page_size=_int_arg("page_size", 10),
            status=request.args.get("status") or None,
            trigger_source=request.args.get("trigger_source") or None,
        )
        list_data = [
            await _to_thread(_get_service(WorkflowRunService).serialize_run, run)
            for run in runs
        ]
        return _ok({"list": list_data, "paginator": asdict(paginator)})

    @quart_app.get("/workflows/<uuid:workflow_id>/runs/<uuid:run_id>")
    async def async_get_workflow_run(workflow_id, run_id) -> Response:
        """async 获取单条执行记录详情。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowRunService, WorkflowService

        await _to_thread(
            _get_service(WorkflowService).get_workflow, workflow_id, account
        )
        run = await _to_thread(
            _get_service(WorkflowRunService).get_run, run_id, account
        )
        if run is None:
            return _ok(None)
        return _ok(await _to_thread(_get_service(WorkflowRunService).serialize_run, run))

    @quart_app.get("/workflows/<uuid:workflow_id>/runs/<uuid:run_id>/node-executions")
    async def async_get_workflow_run_node_executions(workflow_id, run_id) -> Response:
        """async 获取执行记录节点回放数据。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowRunService, WorkflowService

        await _to_thread(
            _get_service(WorkflowService).get_workflow, workflow_id, account
        )
        node_executions = await _to_thread(
            _get_service(WorkflowRunService).get_node_executions, run_id, account
        )
        list_data = [
            await _to_thread(_get_service(WorkflowRunService).serialize_node_execution, node_exec)
            for node_exec in node_executions
        ]
        return _ok({"list": list_data})

    @quart_app.post("/workflows/import")
    async def async_import_workflow() -> Response:
        """async 导入工作流 JSON。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.workflow_schema import ImportWorkflowResp
        from internal.service import WorkflowService

        body = await request.get_json(force=True, silent=True)
        if not isinstance(body, dict):
            return _json_resp(
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
            return _json_resp(
                code="validate_error",
                message="无法识别的导入数据格式",
                data={"json_data": ["无法识别的导入数据格式"]},
                status=400,
            )
        workflow = await _to_thread(
            _get_service(WorkflowService).import_workflow,
            json_data=json_data,
            account_id=account.id,
            overwrite_name=overwrite_name,
        )
        return _ok(ImportWorkflowResp().dump(workflow))

    @quart_app.get("/workflows/<uuid:workflow_id>/export")
    async def async_export_workflow(workflow_id) -> Response:
        """async 导出工作流 JSON。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        await _to_thread(
            _get_service(WorkflowService).get_workflow, workflow_id, account
        )
        include_versions = request.args.get("include_versions", "").lower() in ("true", "1", "yes")
        data = await _to_thread(
            _get_service(WorkflowService).export_workflow,
            workflow_id,
            include_versions=include_versions,
        )
        return _ok(data)

    @quart_app.post("/workflows/<uuid:workflow_id>/debug")
    async def async_debug_workflow(workflow_id) -> Response:
        """async 调试工作流（SSE 流式）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import WorkflowService

        inputs = (await request.get_json(force=True, silent=True)) or {}
        response = await _to_thread(
            _get_service(WorkflowService).debug_workflow, workflow_id, inputs, account
        )
        if _is_sync_iterator(response):
            return _sse_response(response)
        return _ok(response.data)
