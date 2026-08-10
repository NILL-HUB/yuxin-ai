import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Generator
from uuid import UUID
from internal.context import current_app
from injector import inject
from sqlalchemy import desc
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from internal.core.workflow.entities.edge_entity import BaseEdgeData
from internal.core.workflow.entities.node_entity import NodeType, BaseNodeData
from internal.core.workflow.entities.workflow_entity import WorkflowConfig
from internal.core.workflow.graph_engine import GraphEngine
from internal.core.workflow.real_node_executor import RealNodeExecutor
from internal.core.workflow.variable_pool import VariablePool
from internal.core.workflow.nodes import (
    CodeNodeData,
    DatasetRetrievalNodeData,
    EndNodeData,
    HttpRequestNodeData,
    IfElseNodeData,
    LLMNodeData,
    ParameterExtractorNodeData,
    StartNodeData,
    TemplateTransformNodeData,
    TextProcessorNodeData,
    ToolNodeData,
    VariableAssignerNodeData,
)
from internal.entity.workflow_entity import WorkflowStatus, DEFAULT_WORKFLOW_CONFIG, WorkflowResultStatus
from internal.exception import ValidateErrorException, NotFoundException, ForbiddenException, FailException
from internal.lib.helper import convert_model_to_dict, escape_like_pattern, datetime_to_timestamp
from internal.model import Account, Workflow, ApiTool, WorkflowResult, WorkflowVersion, KnowledgeBase
from internal.schema.workflow_schema import CreateWorkflowReq, GetWorkflowsWithPageReq
from pkg.paginator import Paginator
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .icon_generator_service import IconGeneratorService


logger = logging.getLogger(__name__)


@inject
@dataclass
class WorkflowService(BaseService):
    """工作流服务"""
    db: SQLAlchemy
    builtin_provider_manager: BuiltinProviderManager
    icon_generator_service: IconGeneratorService

    def create_workflow(self, req: CreateWorkflowReq, account: Account = None, *, created_by_admin=None) -> Workflow:
        """根据传递的请求信息创建工作流（管理端创建时 account 为空，记录 created_by_admin）"""
        # 1.根据传递的工作流工具名称查询工作流信息
        check_workflow = self.db.session.query(Workflow).filter(
            Workflow.tool_call_name == req.tool_call_name.data.strip(),
            Workflow.account_id == (account.id if account is not None else None),
        ).one_or_none()
        if check_workflow:
            raise ValidateErrorException(f"在当前账号下已创建[{req.tool_call_name.data}]工作流，不支持重名")

        # 2.调用数据库服务创建工作流
        return self.create(Workflow, **{
            **req.data,
            **DEFAULT_WORKFLOW_CONFIG,
            "account_id": account.id if account is not None else None,
            "created_by_admin": created_by_admin,
            "is_debug_passed": False,
            "status": WorkflowStatus.DRAFT.value,
            "tool_call_name": req.tool_call_name.data.strip(),
        })

    def get_workflow(self, workflow_id: UUID, account: Account) -> Workflow:
        """根据传递的工作流id，获取指定的工作流基础信息"""
        # 1.查询数据库获取工作流基础信息
        workflow = self.get(Workflow, workflow_id)

        # 2.判断工作流是否存在
        if not workflow:
            raise NotFoundException("该工作流不存在，请核实后重试")

        # 3.判断当前账号是否有权限访问该应用
        if workflow.account_id != account.id:
            raise ForbiddenException("当前账号无权限访问该应用，请核实后尝试")

        return workflow

    def delete_workflow(self, workflow_id: UUID, account: Account) -> Workflow:
        """根据传递的工作流id+账号信息，删除指定的工作流（进入回收站，默认留存 30 天）"""
        # 1.获取工作流基础信息并校验权限
        workflow = self.get_workflow(workflow_id, account)

        # 2.写入回收站并物理删除原记录
        from internal.service.recycle_bin_service import RecycleBinService
        deleted = RecycleBinService().delete_resource(
            resource_type="workflow",
            resource_id=workflow.id,
            resource_key=str(workflow.id),
            resource_name=workflow.name,
            deleted_by=account.id,
            deleted_by_type="user",
        )
        if not deleted:
            raise NotFoundException("该工作流不存在，请核实后重试")

        return workflow

    def _get_workflow_for_admin(self, workflow_id: UUID) -> Workflow:
        """管理员视角：根据工作流id获取工作流，不校验账号归属"""
        workflow = self.get(Workflow, workflow_id)
        if not workflow:
            raise NotFoundException("该工作流不存在，请核实后重试")
        return workflow

    def _get_owner_account(self, account_id) -> Account:
        """根据账号id加载资源归属账号（平台级资源 account_id 为空时返回 None）"""
        if not account_id:
            return None
        account = self.db.session.query(Account).filter(Account.id == account_id).one_or_none()
        if not account:
            raise NotFoundException("资源所属账号不存在")
        return account

    def delete_workflow_for_admin(
        self,
        workflow_id: UUID,
        *,
        retention_days: int | None = None,
        deleted_by=None,
    ) -> Workflow:
        """管理员删除工作流，不校验账号归属"""
        workflow = self._get_workflow_for_admin(workflow_id)
        from internal.service.recycle_bin_service import RecycleBinService
        deleted = RecycleBinService().delete_resource(
            resource_type="workflow",
            resource_id=workflow.id,
            resource_key=str(workflow.id),
            resource_name=workflow.name,
            deleted_by=deleted_by,
            retention_days=retention_days,
        )
        if not deleted:
            raise NotFoundException("该工作流不存在，请核实后重试")
        return workflow

    def get_draft_graph_for_admin(self, workflow_id: UUID) -> dict[str, Any]:
        """管理员获取工作流草稿图，复用空间端逻辑（以工作流归属账号执行）"""
        workflow = self._get_workflow_for_admin(workflow_id)
        account = self._get_owner_account(workflow.account_id)
        return self.get_draft_graph(workflow_id, account)

    def update_draft_graph_for_admin(self, workflow_id: UUID, draft_graph: dict[str, Any]) -> Workflow:
        """管理员保存工作流草稿图，复用空间端逻辑（以工作流归属账号执行）"""
        workflow = self._get_workflow_for_admin(workflow_id)
        account = self._get_owner_account(workflow.account_id)
        return self.update_draft_graph(workflow_id, draft_graph, account)

    def publish_workflow_for_admin(self, workflow_id: UUID, summary: str = "") -> Workflow:
        """管理员发布工作流，复用空间端逻辑（以工作流归属账号执行）"""
        workflow = self._get_workflow_for_admin(workflow_id)
        account = self._get_owner_account(workflow.account_id)
        return self.publish_workflow(workflow_id, account, summary=summary)

    def get_workflow_versions(self, workflow_id: UUID, account: Account) -> list[WorkflowVersion]:
        """获取工作流的版本历史列表（按版本号倒序）"""
        workflow = self.get_workflow(workflow_id, account)
        return (
            self.db.session.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == workflow.id)
            .order_by(WorkflowVersion.version.desc())
            .all()
        )

    def get_workflow_versions_for_admin(self, workflow_id: UUID) -> list[WorkflowVersion]:
        """管理员获取工作流版本历史列表，不校验账号归属"""
        workflow = self._get_workflow_for_admin(workflow_id)
        return (
            self.db.session.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == workflow.id)
            .order_by(WorkflowVersion.version.desc())
            .all()
        )

    def rollback_workflow_version(self, workflow_id: UUID, version_id: UUID, account: Account) -> Workflow:
        """回滚工作流到指定历史版本

        策略：将历史版本的 graph 复制回 draft_graph 与 graph，同时状态置为 PUBLISHED，
        并创建一条新的版本记录标记为当前发布版本（历史版本 is_current_published 全部置 False）。
        """
        # 1.获取工作流并校验权限
        workflow = self.get_workflow(workflow_id, account)

        # 2.查询目标历史版本
        target_version = self.db.session.query(WorkflowVersion).filter(
            WorkflowVersion.id == version_id,
            WorkflowVersion.workflow_id == workflow.id,
        ).one_or_none()
        if target_version is None:
            raise NotFoundException("目标工作流版本不存在")

        # 3.将历史版本 graph 复制回 workflow 的 draft_graph 与 graph
        historical_graph = target_version.graph or {}
        self.update(workflow, **{
            "draft_graph": historical_graph,
            "graph": historical_graph,
            "status": WorkflowStatus.PUBLISHED.value,
            "is_debug_passed": False,
            "published_at": datetime.now(UTC),
        })

        # 4.创建新版本记录（基于历史版本内容），并将其他版本标记为非当前发布
        try:
            latest_version = self.db.session.query(WorkflowVersion).filter(
                WorkflowVersion.workflow_id == workflow.id
            ).order_by(WorkflowVersion.version.desc()).first()
            new_version_no = (latest_version.version + 1) if latest_version else 1

            self.db.session.query(WorkflowVersion).filter(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.is_current_published.is_(True),
            ).update({WorkflowVersion.is_current_published: False}, synchronize_session=False)

            self.create(WorkflowVersion, **{
                "workflow_id": workflow.id,
                "version": new_version_no,
                "graph": historical_graph,
                "is_current_published": True,
                "summary": f"回滚自版本 v{target_version.version}",
            })
        except Exception as e:
            logger.warning("回滚创建工作流版本记录失败: workflow_id=%s, error=%s", workflow.id, e)

        return workflow

    def rollback_workflow_version_for_admin(self, workflow_id: UUID, version_id: UUID) -> Workflow:
        """管理员回滚工作流到指定历史版本，不校验账号归属"""
        workflow = self._get_workflow_for_admin(workflow_id)
        account = self._get_owner_account(workflow.account_id)
        return self.rollback_workflow_version(workflow_id, version_id, account)

    def update_workflow(self, workflow_id: UUID, account: Account, **kwargs) -> Workflow:
        """根据传递的工作流id+请求更新工作流基础信息"""
        # 1.获取工作流基础信息并校验权限
        workflow = self.get_workflow(workflow_id, account)

        # 2.根据传递的工具调用名字查询是否存在重名工作流
        check_workflow = self.db.session.query(Workflow).filter(
            Workflow.tool_call_name == kwargs.get("tool_call_name", "").strip(),
            Workflow.account_id == account.id,
            Workflow.id != workflow.id,
        ).one_or_none()
        if check_workflow:
            raise ValidateErrorException(f"在当前账号下已创建[{kwargs.get('tool_call_name', '')}]工作流，不支持重名")

        # 3.更新工作流基础信息
        self.update(workflow, **kwargs)

        return workflow

    def get_workflows_with_page(
            self, req: GetWorkflowsWithPageReq, account: Account
    ) -> tuple[list[Workflow], Paginator]:
        """根据传递的信息获取工作流分页列表数据"""
        # 1.构建分页器
        paginator = Paginator(db=self.db, req=req)

        # 2.构建筛选器
        filters = [Workflow.account_id == account.id]
        if req.search_word.data:
            filters.append(Workflow.name.ilike(f"%{escape_like_pattern(req.search_word.data)}%"))
        if req.status.data:
            filters.append(Workflow.status == req.status.data)

        # 3.分页查询数据
        workflows = paginator.paginate(
            self.db.session.query(Workflow).filter(*filters).order_by(desc("created_at"))
        )

        return workflows, paginator

    def update_draft_graph(self, workflow_id: UUID, draft_graph: dict[str, Any], account: Account) -> Workflow:
        """根据传递的工作流id+草稿图配置+账号更新工作流的草稿图"""
        # 1.根据传递的id获取工作流并校验权限
        workflow = self.get_workflow(workflow_id, account)

        # 2.校验传递的草稿图配置，因为有可能边有可能还未建立，所以需要校验关联的数据
        validate_draft_graph = self._validate_graph(draft_graph, account, workflow_id=workflow.id)

        # 3.更新工作流草稿图配置，每次修改都将is_debug_passed的值重置为False，该处可以优化对比字典里除position的其他属性
        self.update(workflow, **{
            "draft_graph": validate_draft_graph,
            "is_debug_passed": False,
        })

        return workflow

    def get_draft_graph(self, workflow_id: UUID, account: Account) -> dict[str, Any]:
        """根据传递的工作流id+账号信息，获取指定工作流的草稿配置信息"""
        # 1.根据传递的id获取工作流并校验权限
        workflow = self.get_workflow(workflow_id, account)

        # 2.提取草稿图结构信息并校验(不更新校验后的数据到数据库)
        draft_graph = workflow.draft_graph
        validate_draft_graph = self._validate_graph(draft_graph, account, workflow_id=workflow.id)

        # 3.循环遍历节点信息，为工具节点/知识库节点附加元数据
        for node in validate_draft_graph["nodes"]:
            if node.get("node_type") == NodeType.TOOL.value:
                # 4.判断工具的类型执行不同的操作
                if node.get("tool_type") == "builtin_tool":
                    # 5.节点类型为工具，则附加工具的名称、图标、参数等额外信息
                    provider = self.builtin_provider_manager.get_provider(node.get("provider_id"))
                    if not provider:
                        continue

                    # 6.获取提供者下的工具实体，并检测是否存在
                    tool_entity = provider.get_tool_entity(node.get("tool_id"))
                    if not tool_entity:
                        continue

                    # 7.判断工具的params和草稿中的params是否一致，如果不一致则全部重置为默认值（或者考虑删除这个工具的引用）
                    param_keys = set([param.name for param in tool_entity.params])
                    params = node.get("params")
                    if set(params.keys()) - param_keys:
                        params = {
                            param.name: param.default
                            for param in tool_entity.params
                            if param.default is not None
                        }

                    # 8.数据校验成功附加展示信息
                    provider_entity = provider.provider_entity
                    node["meta"] = {
                        "type": "builtin_tool",
                        "provider": {
                            "id": provider_entity.name,
                            "name": provider_entity.name,
                            "label": provider_entity.label,
                            "icon": f"/builtin-tools/{provider_entity.name}/icon",
                            "description": provider_entity.description,
                        },
                        "tool": {
                            "id": tool_entity.name,
                            "name": tool_entity.name,
                            "label": tool_entity.label,
                            "description": tool_entity.description,
                            "params": params,
                        }
                    }
                elif node.get("tool_type") == "api_tool":
                    # 9.查询数据库获取对应的工具记录，并检测是否存在
                    provider_id = node.get("provider_id")
                    tool_id = node.get("tool_id")

                    # 检查 provider_id 和 tool_id 是否为空，避免 UUID 转换错误
                    if not provider_id or not tool_id:
                        node["meta"] = {
                            "type": "api_tool",
                            "provider": {
                                "id": "",
                                "name": "",
                                "label": "",
                                "icon": "",
                                "description": "",
                            },
                            "tool": {
                                "id": "",
                                "name": "",
                                "label": "",
                                "description": "",
                                "params": {},
                            },
                        }
                        continue

                    tool_record = self.db.session.query(ApiTool).filter(
                        ApiTool.provider_id == provider_id,
                        ApiTool.name == tool_id,
                        ApiTool.account_id == account.id,
                    ).one_or_none()
                    if not tool_record:
                        node["meta"] = {
                            "type": "api_tool",
                            "provider": {
                                "id": "",
                                "name": "",
                                "label": "",
                                "icon": "",
                                "description": "",
                            },
                            "tool": {
                                "id": "",
                                "name": "",
                                "label": "",
                                "description": "",
                                "params": {},
                            },
                        }
                        continue

                    # 10.组装api工具展示信息
                    provider = tool_record.provider
                    node["meta"] = {
                        "type": "api_tool",
                        "provider": {
                            "id": str(provider.id),
                            "name": provider.name,
                            "label": provider.name,
                            "icon": provider.icon,
                            "description": provider.description,
                        },
                        "tool": {
                            "id": str(tool_record.id),
                            "name": tool_record.name,
                            "label": tool_record.name,
                            "description": tool_record.description,
                            "params": {},
                        },
                    }
                else:
                    node["meta"] = {
                        "type": "api_tool",
                        "provider": {
                            "id": "",
                            "name": "",
                            "label": "",
                            "icon": "",
                            "description": "",
                        },
                        "tool": {
                            "id": "",
                            "name": "",
                            "label": "",
                            "description": "",
                            "params": {},
                        },
                    }
            elif node.get("node_type") == NodeType.DATASET_RETRIEVAL.value:
                # 5.节点类型为知识库检索，附加知识库的名称、图标等信息
                # 使用新版 KnowledgeBase 元数据填充
                knowledge_base_ids = node.get("knowledge_base_ids", []) or []
                if knowledge_base_ids:
                    knowledge_bases = self.db.session.query(KnowledgeBase).filter(
                        KnowledgeBase.id.in_(knowledge_base_ids),
                    ).all()
                    node["meta"] = {
                        "knowledge_bases": [{
                            "id": str(kb.id),
                            "name": kb.name,
                            "description": kb.description or "",
                        } for kb in knowledge_bases]
                    }

        return validate_draft_graph

    def debug_workflow(self, workflow_id: UUID, inputs: dict[str, Any], account: Account) -> Generator:
        """调试指定的工作流API接口，基于 GraphEngine 流式事件输出。

        统一采用 GraphEngine 执行（与 WorkflowAppService 一致），
        消费 GraphEngine 的 SSE 事件并转发给前端，同时持久化调试结果。
        """
        # 1.根据传递的id获取工作流并校验权限
        workflow = self.get_workflow(workflow_id, account)
        executable_graph = self._build_executable_graph(workflow.draft_graph)

        # 2.构建 WorkflowConfig + GraphEngine
        workflow_config = WorkflowConfig(
            account_id=account.id,
            name=workflow.tool_call_name,
            description=workflow.description,
            nodes=executable_graph.get("nodes", []),
            edges=executable_graph.get("edges", []),
        )
        variable_pool = VariablePool()
        try:
            flask_app = current_app._get_current_object()
        except RuntimeError:
            flask_app = None
        executor = RealNodeExecutor(
            flask_app=flask_app,
            account_id=account.id,
            account=account,
        )
        engine = GraphEngine(
            workflow_config=workflow_config,
            variable_pool=variable_pool,
            node_executor=executor,
        )

        def handle_stream() -> Generator:
            # 3.添加数据库工作流运行结果记录
            node_results: list[dict[str, Any]] = []
            workflow_result = self.create(WorkflowResult, **{
                "app_id": None,
                "account_id": account.id,
                "workflow_id": workflow.id,
                "graph": workflow.draft_graph,
                "state": [],
                "latency": 0,
                "status": WorkflowResultStatus.RUNNING.value,
            })

            start_at = time.perf_counter()
            final_status = WorkflowResultStatus.SUCCEEDED.value
            try:
                for event in engine.execute(inputs or {}):
                    event_type = event.get("event", "message")
                    data = event.get("data") or {}

                    # 收集节点执行结果（兼容旧版 state 结构）
                    if event_type in ("node_finished", "node_failed"):
                        node_results.append({
                            "id": str(uuid.uuid4()),
                            "node_id": data.get("node_id", ""),
                            "node_type": data.get("node_type", ""),
                            "title": data.get("title", ""),
                            "inputs": data.get("inputs", {}),
                            "outputs": data.get("outputs", {}),
                            "status": "succeeded" if event_type == "node_finished" else "failed",
                            "latency": data.get("elapsed_time", 0),
                            "error": data.get("error", ""),
                        })

                    # 转发 SSE 事件给前端
                    yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

                    # 工作流结束时记录最终状态
                    if event_type == "workflow_finished":
                        wf_status = str(data.get("status") or "succeeded")
                        if wf_status == "succeeded":
                            final_status = WorkflowResultStatus.SUCCEEDED.value
                        else:
                            final_status = WorkflowResultStatus.FAILED.value

                # 更新调试结果
                self.update(workflow_result, **{
                    "status": final_status,
                    "state": node_results,
                    "latency": (time.perf_counter() - start_at),
                })

                # 调试成功时更新 workflow.is_debug_passed
                if final_status == WorkflowResultStatus.SUCCEEDED.value:
                    workflow.is_debug_passed = True
                    self.db.session.add(workflow)
                    self.db.session.commit()

            except Exception as e:
                logging.error(f"工作流调试失败: {str(e)}", exc_info=True)
                self.update(workflow_result, **{
                    "status": WorkflowResultStatus.FAILED.value,
                    "state": node_results,
                    "latency": (time.perf_counter() - start_at),
                })
                # 推送失败事件给前端
                error_data = {"status": "failed", "error": str(e)}
                yield f"event: workflow_finished\ndata: {json.dumps(error_data, ensure_ascii=False, default=str)}\n\n"

        return handle_stream()

    def publish_workflow(self, workflow_id: UUID, account: Account, summary: str = "") -> Workflow:
        """根据传递的工作流id，发布指定的工作流

        发布时同时创建一条 WorkflowVersion 记录，标记为当前发布版本，
        并将历史版本的 is_current_published 置为 False。
        """
        # 1.根据传递的id获取工作流并校验权限
        workflow = self.get_workflow(workflow_id, account)

        # 2.构建可执行图配置
        executable_graph = self._build_executable_graph(workflow.draft_graph)

        # 3.使用WorkflowConfig二次校验，如果校验失败则不发布
        try:
            WorkflowConfig(
                account_id=account.id,
                name=workflow.tool_call_name,
                description=workflow.description,
                nodes=executable_graph.get("nodes", []),
                edges=executable_graph.get("edges", []),
            )
        except Exception:
            self.update(workflow, **{
                "is_debug_passed": False,
            })
            raise ValidateErrorException("工作流配置校验失败，请核实后重试")

        # 4.更新工作流的发布状态
        self.update(workflow, **{
            "graph": executable_graph,
            "status": WorkflowStatus.PUBLISHED.value,
            "is_debug_passed": False,
            "published_at": datetime.now(UTC),
        })

        # 5.创建版本记录：计算新版本号，并将历史版本的 is_current_published 置为 False
        try:
            latest_version = self.db.session.query(WorkflowVersion).filter(
                WorkflowVersion.workflow_id == workflow.id
            ).order_by(WorkflowVersion.version.desc()).first()
            new_version_no = (latest_version.version + 1) if latest_version else 1

            if latest_version is not None:
                # 将所有历史版本标记为非当前发布
                self.db.session.query(WorkflowVersion).filter(
                    WorkflowVersion.workflow_id == workflow.id,
                    WorkflowVersion.is_current_published.is_(True),
                ).update({WorkflowVersion.is_current_published: False}, synchronize_session=False)

            self.create(WorkflowVersion, **{
                "workflow_id": workflow.id,
                "version": new_version_no,
                "graph": executable_graph,
                "is_current_published": True,
                "summary": summary or "",
            })
        except Exception as e:
            logger.warning("创建工作流版本记录失败: workflow_id=%s, error=%s", workflow.id, e)

        return workflow

    @staticmethod
    def _collect_reachable_node_ids(root_id: str, adjacency: dict[str, set[str]]) -> set[str]:
        """根据传递的根节点与邻接关系，收集所有可达节点id"""
        visited = set()
        queue = deque([root_id])

        while queue:
            node_id = queue.popleft()
            if node_id in visited:
                continue

            visited.add(node_id)
            for next_node_id in adjacency.get(node_id, set()):
                if next_node_id not in visited:
                    queue.append(next_node_id)

        return visited

    def _build_executable_graph(self, graph: dict[str, Any]) -> dict[str, Any]:
        """构建可执行图：仅保留从start可达且可到达end的节点与边"""
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return graph

        node_map: dict[str, dict[str, Any]] = {}
        start_node = None
        end_node = None
        for node in nodes:
            if not isinstance(node, dict):
                continue

            node_id = str(node.get("id", ""))
            if not node_id:
                continue

            node_map[node_id] = node
            if node.get("node_type") == NodeType.START.value:
                start_node = node
            elif node.get("node_type") == NodeType.END.value:
                end_node = node

        # start/end 缺失时保持原始图结构，交由WorkflowConfig继续做完整校验。
        if not start_node or not end_node:
            return graph

        start_node_id = str(start_node.get("id"))
        end_node_id = str(end_node.get("id"))

        forward_adj = {node_id: set() for node_id in node_map.keys()}
        reverse_adj = {node_id: set() for node_id in node_map.keys()}
        valid_edges = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue

            source_id = str(edge.get("source", ""))
            target_id = str(edge.get("target", ""))
            if source_id not in node_map or target_id not in node_map:
                continue

            forward_adj[source_id].add(target_id)
            reverse_adj[target_id].add(source_id)
            valid_edges.append(edge)

        reachable_from_start = self._collect_reachable_node_ids(start_node_id, forward_adj)
        if end_node_id not in reachable_from_start:
            raise ValidateErrorException("工作流中开始节点无法到达结束节点，请完善连线后重试")

        reachable_to_end = self._collect_reachable_node_ids(end_node_id, reverse_adj)
        executable_node_ids = reachable_from_start & reachable_to_end

        executable_nodes = [
            node for node in nodes if isinstance(node, dict) and str(node.get("id", "")) in executable_node_ids
        ]
        executable_edges = [
            edge for edge in valid_edges
            if str(edge.get("source", "")) in executable_node_ids
            and str(edge.get("target", "")) in executable_node_ids
        ]

        return {
            "nodes": executable_nodes,
            "edges": executable_edges,
        }

    def cancel_publish_workflow(self, workflow_id: UUID, account: Account) -> Workflow:
        """取消发布指定的工作流"""
        # 1.根据传递的id获取工作流并校验权限
        workflow = self.get_workflow(workflow_id, account)

        # 2.校验工作流是否为已发布的状态
        if workflow.status != WorkflowStatus.PUBLISHED.value:
            raise FailException("该工作流未发布无法取消发布")

        # 3.更新发布状态并删除运行图草稿配置
        self.update(workflow, **{
            "graph": {},
            "status": WorkflowStatus.DRAFT.value,
            "is_debug_passed": False,
        })

        return workflow

    def regenerate_icon(self, workflow_id: UUID, account: Account) -> str:
        """根据传递的工作流id重新生成工作流图标"""
        # 1.获取工作流信息并校验权限
        workflow = self.get_workflow(workflow_id, account)

        # 2.使用图标生成服务生成新图标
        try:
            logging.info(f"重新生成工作流图标: workflow_id={workflow_id}, name={workflow.name}")
            icon_url = self.icon_generator_service.generate_icon(
                name=workflow.name,
                description=workflow.description or ""
            )
            logging.info(f"重新生成图标成功: {icon_url}")
        except Exception as e:
            logging.exception("重新生成图标失败: workflow_id=%s", workflow_id, exc_info=e)
            raise FailException("重新生成图标失败，请稍后重试")

        # 3.更新工作流图标
        self.update(workflow, icon=icon_url)

        return icon_url

    def generate_icon_preview(self, name: str, description: str) -> str:
        """生成图标预览（不保存到工作流）"""
        try:
            logging.info(f"生成工作流图标预览: name={name}")
            icon_url = self.icon_generator_service.generate_icon(
                name=name,
                description=description or ""
            )
            logging.info(f"生成图标预览成功: {icon_url}")
            return icon_url
        except Exception as e:
            logging.exception("生成图标预览失败: name=%s", name, exc_info=e)
            raise FailException("生成图标预览失败，请稍后重试")

    def share_workflow_to_public(self, workflow_id: UUID, account: Account, is_public: bool) -> Workflow:
        """分享或取消分享工作流到广场"""
        # 1.获取工作流信息并校验权限
        workflow = self.get_workflow(workflow_id, account)

        # 2.校验工作流是否已发布
        if is_public and workflow.status != WorkflowStatus.PUBLISHED.value:
            raise FailException("只有已发布的工作流才能分享到广场")

        # 3.更新工作流的公开状态
        self.update(workflow, is_public=is_public)

        return workflow

    # ------------------------------------------------------------------
    # 工作流导入导出（阶段 6）
    # ------------------------------------------------------------------
    EXPORT_FORMAT = "yuxin-ai-workflow"
    LEGACY_EXPORT_FORMATS = frozenset({"openagent-workflow"})
    EXPORT_VERSION = "1.0"

    @classmethod
    def _is_supported_export_format(cls, fmt: str | None) -> bool:
        return fmt == cls.EXPORT_FORMAT or fmt in cls.LEGACY_EXPORT_FORMATS

    def export_workflow(self, workflow_id: UUID, *, include_versions: bool = False) -> dict[str, Any]:
        """导出工作流为 JSON 字典结构（不含权限校验，调用方需先验证权限）。

        返回结构：
            {
                "format": "yuxin-ai-workflow",
                "version": "1.0",
                "exported_at": "2026-07-27T...",
                "workflow": {
                    "name": "...",
                    "tool_call_name": "...",
                    "icon": "...",
                    "description": "...",
                    "graph": {...},
                    "draft_graph": {...},
                    "tags": [...],
                    "task_keywords": [...]
                },
                "versions": [...]  # 仅当 include_versions=True
            }
        """
        # 1.加载工作流（不校验账号归属，由调用方负责）
        workflow = self.get(Workflow, workflow_id)
        if not workflow:
            raise NotFoundException("该工作流不存在，请核实后重试")

        # 2.构建导出结构（不包含 account_id、is_public 等敏感/环境相关信息）
        payload: dict[str, Any] = {
            "format": self.EXPORT_FORMAT,
            "version": self.EXPORT_VERSION,
            "exported_at": datetime.now(UTC).isoformat(),
            "workflow": {
                "name": workflow.name or "",
                "tool_call_name": workflow.tool_call_name or "",
                "icon": workflow.icon or "",
                "description": workflow.description or "",
                "graph": workflow.graph or {},
                "draft_graph": workflow.draft_graph or {},
                "tags": workflow.tags or [],
                "task_keywords": workflow.task_keywords or [],
            },
        }

        # 3.可选附带版本元数据（不含 graph 内容，仅元数据）
        if include_versions:
            versions = self.db.session.query(WorkflowVersion).filter(
                WorkflowVersion.workflow_id == workflow.id
            ).order_by(WorkflowVersion.version.desc()).all()
            payload["versions"] = [
                {
                    "version": v.version,
                    "is_current_published": v.is_current_published,
                    "summary": v.summary or "",
                    "created_at": datetime_to_timestamp(v.created_at),
                    "updated_at": datetime_to_timestamp(v.updated_at),
                }
                for v in versions
            ]

        return payload

    def export_workflow_for_admin(self, workflow_id: UUID, *, include_versions: bool = False) -> dict[str, Any]:
        """管理员端导出工作流，不校验账号归属"""
        # 复用 _get_workflow_for_admin 做存在性校验
        self._get_workflow_for_admin(workflow_id)
        return self.export_workflow(workflow_id, include_versions=include_versions)

    def import_workflow(
            self,
            json_data: dict[str, Any],
            account_id: UUID | None = None,
            *,
            overwrite_name: bool = False,
            created_by_admin=None,
    ) -> Workflow:
        """从 JSON 字典导入工作流，创建新的工作流记录（status=draft）。

        参数：
            json_data: 导出的工作流 JSON 字典
            account_id: 新工作流归属账号 ID（为空表示平台级资源，管理端导入）
            overwrite_name: True 时若 tool_call_name 冲突则覆盖现有工作流（需归属同一账号）；
                           False 时自动加 `_imported_{8位hex}` 后缀
        """
        # 1.加载归属账号（_validate_graph 需要 Account 对象；平台级资源为空）
        account = self._get_owner_account(account_id)

        # 2.校验导出格式
        if not isinstance(json_data, dict):
            raise ValidateErrorException("导入数据格式错误，必须是JSON对象")

        fmt = json_data.get("format")
        if not self._is_supported_export_format(fmt):
            raise ValidateErrorException(
                f"不支持的工作流导出格式: {fmt}，应为 {self.EXPORT_FORMAT}"
            )

        # 3.校验版本兼容性（当前仅支持 1.x）
        version = str(json_data.get("version", "") or "")
        if not version:
            raise ValidateErrorException("导入数据缺少 version 字段")
        if not version.startswith("1."):
            raise ValidateErrorException(f"不支持的工作流导出版本: {version}")

        # 4.提取 workflow 字段
        wf_data = json_data.get("workflow")
        if not isinstance(wf_data, dict):
            raise ValidateErrorException("导入数据缺少 workflow 字段")

        name = str(wf_data.get("name") or "").strip()
        tool_call_name = str(wf_data.get("tool_call_name") or "").strip()
        icon = str(wf_data.get("icon") or "")
        description = str(wf_data.get("description") or "")
        graph = wf_data.get("graph") or {}
        draft_graph = wf_data.get("draft_graph") or {}
        tags = wf_data.get("tags") or []
        task_keywords = wf_data.get("task_keywords") or []

        if not name:
            raise ValidateErrorException("导入工作流名称不能为空")
        if not tool_call_name:
            raise ValidateErrorException("导入工作流英文名称（tool_call_name）不能为空")

        # 5.处理 tool_call_name 冲突
        existing = self.db.session.query(Workflow).filter(
            Workflow.tool_call_name == tool_call_name,
            Workflow.account_id == account_id,
        ).one_or_none()

        if existing:
            if overwrite_name:
                # 直接覆盖：需校验归属（已在查询条件中限制 account_id）
                # 覆盖图与基本信息，状态置为 draft
                validated_draft_graph = self._safe_validate_graph(draft_graph, account)
                self.update(existing, **{
                    "name": name,
                    "icon": icon,
                    "description": description,
                    "graph": {},  # 覆盖后重置为 draft 状态，清空已发布图
                    "draft_graph": validated_draft_graph,
                    "tags": tags,
                    "task_keywords": task_keywords,
                    "is_debug_passed": False,
                    "status": WorkflowStatus.DRAFT.value,
                    "is_public": False,
                })
                logger.info(
                    "工作流导入覆盖: workflow_id=%s, tool_call_name=%s, account_id=%s",
                    existing.id, tool_call_name, account_id,
                )
                return existing
            else:
                # 自动加后缀避免冲突
                suffix = f"_imported_{uuid.uuid4().hex[:8]}"
                tool_call_name = f"{tool_call_name}{suffix}"
                # 加后缀后可能仍超长，做截断保护
                if len(tool_call_name) > 255:
                    tool_call_name = tool_call_name[:255]

        # 6.校验并清洗导入的草稿图（复用 _validate_graph）
        validated_draft_graph = self._safe_validate_graph(draft_graph, account)

        # 7.创建新的工作流记录（status=draft，is_debug_passed=False）
        new_workflow = self.create(Workflow, **{
            "account_id": account_id,
            "created_by_admin": created_by_admin,
            "name": name,
            "tool_call_name": tool_call_name,
            "icon": icon,
            "description": description,
            "graph": {},  # 导入后为 draft 状态，清空已发布图
            "draft_graph": validated_draft_graph,
            "tags": tags,
            "task_keywords": task_keywords,
            "is_debug_passed": False,
            "status": WorkflowStatus.DRAFT.value,
            "is_public": False,
        })

        logger.info(
            "工作流导入创建: workflow_id=%s, tool_call_name=%s, account_id=%s",
            new_workflow.id, tool_call_name, account_id,
        )
        return new_workflow

    def _safe_validate_graph(self, graph: dict[str, Any], account: Account) -> dict[str, Any]:
        """安全地校验图结构，校验失败时回退到原始图（避免导入时因工具引用缺失而阻断）"""
        if not isinstance(graph, dict) or not graph:
            return {"nodes": [], "edges": []}
        try:
            return self._validate_graph(graph, account)
        except Exception as e:
            logger.warning("导入工作流图校验失败，使用原始图: %s", e)
            return graph

    def _validate_graph(
            self,
            graph: dict[str, Any],
            account: Account,
            workflow_id: UUID | None = None,
    ) -> dict[str, Any]:
        """校验工作流图结构，包括节点和边的验证"""
        # 提取节点和边数据
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        # 节点类型与数据类映射
        node_data_classes = {
            NodeType.START.value: StartNodeData,
            NodeType.END.value: EndNodeData,
            NodeType.LLM.value: LLMNodeData,
            NodeType.TEMPLATE_TRANSFORM.value: TemplateTransformNodeData,
            NodeType.DATASET_RETRIEVAL.value: DatasetRetrievalNodeData,
            NodeType.CODE.value: CodeNodeData,
            NodeType.TOOL.value: ToolNodeData,
            NodeType.HTTP_REQUEST.value: HttpRequestNodeData,
            NodeType.TEXT_PROCESSOR.value: TextProcessorNodeData,
            NodeType.VARIABLE_ASSIGNER.value: VariableAssignerNodeData,
            NodeType.PARAMETER_EXTRACTOR.value: ParameterExtractorNodeData,
            NodeType.IF_ELSE.value: IfElseNodeData,
        }

        # 校验节点
        node_data_dict: dict[UUID, BaseNodeData] = {}
        start_nodes = 0
        end_nodes = 0

        for node in nodes:
            node_type = ""
            node_id = None
            try:
                if not isinstance(node, dict):
                    raise ValidateErrorException("节点数据必须是字典类型")

                node_id = node.get("id")
                node_type = node.get("node_type", "")
                if not node_type:
                    raise ValidateErrorException("节点缺少类型定义")

                # 特殊处理工具节点
                if node_type == NodeType.TOOL.value:
                    node = self._prepare_tool_node(node)

                node_data_cls = node_data_classes.get(node_type)
                if not node_data_cls:
                    raise ValidateErrorException(f"不支持的节点类型: {node_type}")

                # 验证节点数据
                node_data = node_data_cls(**node)

                # 检查节点ID唯一性
                if node_data.id in node_data_dict:
                    raise ValidateErrorException(f"重复的节点ID: {node_data.id}")

                # 检查节点标题唯一性
                if any(n.title == node_data.title for n in node_data_dict.values()):
                    raise ValidateErrorException(f"重复的节点标题: {node_data.title}")

                # 特殊节点数量检查
                if node_type == NodeType.START.value:
                    start_nodes += 1
                    if start_nodes > 1:
                        raise ValidateErrorException("工作流只能有一个开始节点")

                elif node_type == NodeType.END.value:
                    end_nodes += 1
                    if end_nodes > 1:
                        raise ValidateErrorException("工作流只能有一个结束节点")

                elif node_type == NodeType.DATASET_RETRIEVAL.value:
                    # 验证知识库权限：校验 knowledge_base_ids（新版 KnowledgeBase）
                    if node_data.knowledge_base_ids:
                        knowledge_bases = self.db.session.query(KnowledgeBase).filter(
                            KnowledgeBase.id.in_(node_data.knowledge_base_ids),
                            KnowledgeBase.enabled.is_(True),
                        ).all()
                        node_data.knowledge_base_ids = [str(kb.id) for kb in knowledge_bases]

                node_data_dict[node_data.id] = node_data

            except Exception as e:
                if node_id is None and isinstance(node, dict):
                    node_id = node.get("id")
                if node_id is None:
                    node_getter = getattr(node, "get", None)
                    node_id = node_getter("id") if callable(node_getter) else None
                error_message = str(e) if isinstance(e, ValidateErrorException) else "节点数据格式错误"
                logger.warning(
                    "工作流节点校验失败: workflow_id=%s, node_id=%s, node_type=%s, error=%s",
                    workflow_id,
                    node_id,
                    node_type,
                    error_message,
                )
                raise ValidateErrorException(
                    f"节点验证失败(id={node_id}, node_type={node_type}): {error_message}"
                )

        # 校验边
        edge_data_dict: dict[UUID, BaseEdgeData] = {}
        for edge in edges:
            edge_id = None
            try:
                if not isinstance(edge, dict):
                    raise ValidateErrorException("边数据必须是字典类型")

                edge_id = edge.get("id")
                edge_data = BaseEdgeData(**edge)

                # 检查边ID唯一性
                if edge_data.id in edge_data_dict:
                    raise ValidateErrorException(f"重复的边ID: {edge_data.id}")

                # 检查边连接的节点是否存在
                if edge_data.source not in node_data_dict:
                    raise ValidateErrorException(f"源节点不存在: {edge_data.source}")

                if edge_data.target not in node_data_dict:
                    raise ValidateErrorException(f"目标节点不存在: {edge_data.target}")

                # 检查边是否重复
                if any(
                        e.source == edge_data.source and e.target == edge_data.target
                        for e in edge_data_dict.values()
                ):
                    raise ValidateErrorException("重复的边连接")

                edge_data_dict[edge_data.id] = edge_data

            except Exception as e:
                if edge_id is None and isinstance(edge, dict):
                    edge_id = edge.get("id")
                if edge_id is None:
                    edge_getter = getattr(edge, "get", None)
                    edge_id = edge_getter("id") if callable(edge_getter) else None
                error_message = str(e) if isinstance(e, ValidateErrorException) else "边数据格式错误"
                logger.warning(
                    "工作流边校验失败: workflow_id=%s, edge_id=%s, error=%s",
                    workflow_id,
                    edge_id,
                    error_message,
                )
                raise ValidateErrorException(
                    f"边验证失败(id={edge_id}): {error_message}"
                )

        return {
            "nodes": [convert_model_to_dict(node) for node in node_data_dict.values()],
            "edges": [convert_model_to_dict(edge) for edge in edge_data_dict.values()],
        }

    def _prepare_tool_node(self, node: dict) -> dict:
        """预处理工具节点数据，确保所有必需字段存在"""
        # 从meta中获取tool_type，如果不存在则默认为builtin_tool
        tool_type = node.get("meta", {}).get("type", "builtin_tool")

        # 设置默认值
        node.setdefault("tool_type", tool_type)
        node.setdefault("provider_id", "default_provider")
        node.setdefault("tool_id", "default_tool")
        node.setdefault("params", {})
        node.setdefault("inputs", [])
        node.setdefault("outputs", [])
        node.setdefault("meta", {})

        # 确保outputs至少有默认值
        if not node["outputs"]:
            node["outputs"] = [{
                "name": "text",
                "type": "string",
                "value": {"type": "generated"}
            }]

        return node
