"""Workflow 应用类型服务模块。

与 AppService（chatbot/agent）不同，Workflow 应用：
- 不创建 LLM agent，直接调用绑定的 workflow
- 对话输入作为 workflow 的 start 节点输入
- workflow 的 end 节点输出作为对话回复
- 支持 SSE 流式事件（workflow 执行过程，第一版同步执行）

Plan D-4：实现 app_type=workflow 的应用基础逻辑，后续任务才集成到
AppService/AppRuntimeService 中并接入真实节点执行器。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from injector import inject

from internal.core.workflow.entities.workflow_entity import WorkflowConfig
from internal.core.workflow.graph_engine import GraphEngine
from internal.core.workflow.variable_pool import VariablePool
from internal.entity.app_entity import AppType
from internal.exception import NotFoundException, ValidateErrorException
from internal.model import App, Workflow
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
@dataclass
class WorkflowAppService:
    """Workflow 应用类型服务，处理 app_type=workflow 的应用逻辑。

    本服务作为独立组件存在，不修改 AppService / AppRuntimeService，
    后续任务会将其集成到对话调用链路中。
    """

    db: SQLAlchemy

    # ------------------------------------------------------------------
    # 配置读写：workflow_id 提取与校验
    # ------------------------------------------------------------------
    @staticmethod
    def get_workflow_binding(app_config: dict[str, Any]) -> UUID | None:
        """从应用配置中提取绑定的 workflow_id。

        app_config 中 ``workflow_id`` 字段存储 workflow UUID 字符串，
        不存在或为空时返回 None。

        Args:
            app_config: 应用配置字典（draft_app_config 或 app_config）

        Returns:
            workflow_id 的 UUID 对象，不存在时返回 None
        """
        if not isinstance(app_config, dict):
            return None

        raw_workflow_id = app_config.get("workflow_id")
        if not raw_workflow_id:
            return None

        # 兼容字符串与 UUID 两种存储形式
        if isinstance(raw_workflow_id, UUID):
            return raw_workflow_id

        try:
            return UUID(str(raw_workflow_id))
        except (ValueError, AttributeError, TypeError):
            logger.warning("应用配置中的 workflow_id 格式非法: %r", raw_workflow_id)
            return None

    def validate_workflow_binding(self, app_config: dict[str, Any]) -> UUID:
        """校验并返回 workflow_id。

        Args:
            app_config: 应用配置字典

        Returns:
            校验通过的 workflow_id UUID

        Raises:
            ValidateErrorException: 配置中缺少 workflow_id
            NotFoundException: workflow_id 对应的 workflow 不存在
        """
        workflow_id = self.get_workflow_binding(app_config)
        if workflow_id is None:
            raise ValidateErrorException("当前应用未绑定 workflow，请先绑定后再执行")

        workflow = self.db.session.query(Workflow).filter(
            Workflow.id == workflow_id,
        ).one_or_none()
        if workflow is None:
            raise NotFoundException(f"绑定的 workflow 不存在: {workflow_id}")

        return workflow_id

    # ------------------------------------------------------------------
    # 绑定/解绑：返回配置 dict，由调用方（AppService）负责持久化
    # ------------------------------------------------------------------
    def bind_workflow(self, app_id: UUID, workflow_id: UUID) -> dict[str, Any]:
        """为应用绑定 workflow。

        校验 workflow 存在后，返回需要 merge 到 draft_app_config 的配置片段。
        不直接修改数据库，由调用方负责持久化。

        Args:
            app_id: 应用 ID（保留参数，便于后续扩展权限校验）
            workflow_id: 待绑定的 workflow ID

        Returns:
            配置片段字典，形如 ``{"workflow_id": str(workflow_id)}``

        Raises:
            NotFoundException: workflow 不存在
        """
        workflow = self.db.session.query(Workflow).filter(
            Workflow.id == workflow_id,
        ).one_or_none()
        if workflow is None:
            raise NotFoundException(f"待绑定的 workflow 不存在: {workflow_id}")

        return {"workflow_id": str(workflow_id)}

    def unbind_workflow(self, app_id: UUID) -> dict[str, Any]:
        """解绑 workflow。

        返回需要 merge 到 draft_app_config 的配置片段，将 workflow_id 置为 None。
        不直接修改数据库，由调用方负责持久化。

        Args:
            app_id: 应用 ID（保留参数，便于后续扩展权限校验）

        Returns:
            配置片段字典，形如 ``{"workflow_id": None}``
        """
        return {"workflow_id": None}

    # ------------------------------------------------------------------
    # 应用类型判断
    # ------------------------------------------------------------------
    @staticmethod
    def is_workflow_app(app: App) -> bool:
        """判断应用是否为 Workflow 类型。

        Args:
            app: 应用实例

        Returns:
            app_type 为 workflow 时返回 True，否则 False
        """
        if app is None:
            return False
        return getattr(app, "app_type", None) == AppType.WORKFLOW.value

    # ------------------------------------------------------------------
    # 执行入口
    # ------------------------------------------------------------------
    def execute_workflow(
        self,
        app_id: UUID,
        inputs: dict[str, Any],
        account: Any,
    ) -> dict[str, Any]:
        """执行应用绑定的 workflow。

        加载 App + Workflow，构建 WorkflowConfig，调用 GraphEngine 执行，
        返回最终输出与执行状态。

        第一版不实现 SSE 流式，同步执行返回结果；GraphEngine 使用默认节点
        执行器（占位），后续任务才接入真实节点执行器。

        Args:
            app_id: 应用 ID
            inputs: workflow start 节点的输入字典
            account: 触发账号（保留参数，便于后续权限/审计）

        Returns:
            执行结果字典，结构为::
                {
                    "outputs": <end 节点输出 dict>,
                    "elapsed_time": <总耗时（秒）>,
                    "status": "succeeded" | "failed",
                    "error": <错误信息（失败时填充）>,
                }

        Raises:
            NotFoundException: 应用不存在
            ValidateErrorException: 应用类型非 workflow 或未绑定 workflow
        """
        # 1.加载应用并校验类型
        app = self.db.session.query(App).filter(App.id == app_id).one_or_none()
        if app is None:
            raise NotFoundException(f"应用不存在: {app_id}")

        if not self.is_workflow_app(app):
            raise ValidateErrorException(
                f"当前应用类型不是 workflow（实际: {app.app_type}），无法调用 execute_workflow"
            )

        # 2.加载 draft_app_config 并校验 workflow 绑定
        # 注意：此处通过 AppConfigVersion 提供 dict 视图，避免直接依赖具体属性
        draft_app_config = self._load_app_config_dict(app)
        workflow_id = self.validate_workflow_binding(draft_app_config)

        # 3.加载 workflow
        workflow = self.db.session.query(Workflow).filter(
            Workflow.id == workflow_id,
        ).one_or_none()
        if workflow is None:
            # 双重保险：validate_workflow_binding 已校验，但并发删除场景下仍可能为空
            raise NotFoundException(f"绑定的 workflow 不存在: {workflow_id}")

        # 4.构建 WorkflowConfig 并执行
        workflow_config = self._build_workflow_config(workflow, account)
        variable_pool = VariablePool()
        engine = GraphEngine(
            workflow_config=workflow_config,
            variable_pool=variable_pool,
            node_executor=None,  # 使用默认占位执行器，后续任务替换
        )

        start_time = time.perf_counter()
        workflow_status = "succeeded"
        workflow_error = ""
        outputs: dict[str, Any] = {}

        try:
            # GraphEngine.execute 返回生成器，消费事件以推进执行
            for event in engine.execute(inputs or {}):
                event_type = event.get("event")
                data = event.get("data") or {}
                if event_type == "workflow_finished":
                    workflow_status = str(data.get("status") or "succeeded")
                    workflow_error = str(data.get("error") or "")
                    # outputs 通过 VariablePool 获取（end 节点输出）
                    outputs = self._extract_outputs(variable_pool, workflow_config)
        except Exception as exc:  # noqa: BLE001 - 执行期异常需转化为失败结果
            workflow_status = "failed"
            workflow_error = str(exc)
            logger.exception("工作流执行异常: app_id=%s, workflow_id=%s", app_id, workflow_id)

        elapsed_time = time.perf_counter() - start_time

        return {
            "outputs": outputs,
            "elapsed_time": elapsed_time,
            "status": workflow_status,
            "error": workflow_error,
        }

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------
    def _load_app_config_dict(self, app: App) -> dict[str, Any]:
        """加载应用的 draft_app_config 并返回 dict 视图。

        优先使用 ``app.draft_app_config`` 属性返回的 AppConfigVersion 对象，
        通过 ``__dict__`` 或显式字段提取组装成 dict；测试时可通过 monkeypatch
        替换该方法避免触发数据库交互。

        Args:
            app: 应用实例

        Returns:
            应用配置字典
        """
        draft = getattr(app, "draft_app_config", None)
        if draft is None:
            return {}

        # AppConfigVersion 是 SQLAlchemy 模型，提取 workflow_id 字段即可
        # 后续若需要更多字段，可在此处扩展
        return {
            "workflow_id": getattr(draft, "workflow_id", None),
            "app_type": getattr(app, "app_type", None),
        }

    @staticmethod
    def _build_workflow_config(workflow: Workflow, account: Any) -> WorkflowConfig:
        """从 workflow.graph 构建 WorkflowConfig。

        参考 ``internal/core/workflow/workflow.py`` 中 Workflow 类的构建方式，
        将 workflow.graph（dict）转换为 WorkflowConfig 实例。

        Args:
            workflow: 工作流模型实例
            account: 触发账号（用于填充 account_id）

        Returns:
            WorkflowConfig 实例
        """
        graph = getattr(workflow, "graph", None) or {}
        account_id = getattr(account, "id", None)

        # graph 结构：{"account_id", "name", "description", "nodes", "edges"}
        # 兼容 graph 中缺失字段的情况，使用 workflow 自身字段补齐
        payload = {
            "account_id": graph.get("account_id") or account_id,
            "name": graph.get("name") or getattr(workflow, "tool_call_name", "") or "workflow_app",
            "description": graph.get("description") or getattr(workflow, "description", "") or "workflow app",
            "nodes": graph.get("nodes", []),
            "edges": graph.get("edges", []),
        }
        return WorkflowConfig(**payload)

    @staticmethod
    def _extract_outputs(variable_pool: VariablePool, workflow_config: WorkflowConfig) -> dict[str, Any]:
        """从 VariablePool 提取 end 节点的最终输出。

        Args:
            variable_pool: 执行完成后的变量池
            workflow_config: 工作流配置（用于定位 end 节点）

        Returns:
            end 节点输出字典；找不到 end 节点时返回空 dict
        """
        from internal.core.workflow.entities.node_entity import NodeType

        # 查找 end 节点
        end_node = next(
            (node for node in workflow_config.nodes if node.node_type == NodeType.END.value),
            None,
        )
        if end_node is None:
            return {}

        outputs = variable_pool.get_node_output(str(end_node.id))
        if isinstance(outputs, dict):
            return dict(outputs)
        return {}
