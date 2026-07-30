"""子流程节点执行器模块。"""
import logging
import time
from typing import Any, Optional
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowConfig, WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.exception import FailException
from .sub_workflow_entity import SubWorkflowNodeData

logger = logging.getLogger(__name__)


class SubWorkflowNode(BaseNode):
    """子流程节点执行器，调用另一个已发布的工作流。

    执行逻辑：
    1. 从 inputs 解析输入参数（REF 类型从前序节点输出中提取，LITERAL/GENERATED 直接取值）
    2. 加载目标 workflow 的 graph 配置并构建子 GraphEngine 执行
    3. 提取子工作流 end 节点的输出
    4. 返回输出作为本节点的 outputs
    """

    node_data: SubWorkflowNodeData

    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        """调用子工作流"""
        start_at = time.perf_counter()

        # 1.校验 workflow_id 必须存在
        if self.node_data.workflow_id is None:
            raise FailException("子流程节点的 workflow_id 不能为空")

        # 2.解析 inputs（REF 类型从前序节点输出提取，LITERAL/GENERATED 直接取值）
        resolved_inputs: dict[str, Any] = {}
        for variable in self.node_data.inputs:
            resolved_inputs[variable.name] = self._resolve_variable(variable, state)

        # 3.加载子工作流并执行
        outputs: dict[str, Any] = self._execute_sub_workflow(resolved_inputs, config)

        # 4.构建状态数据并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED.value,
                    inputs=resolved_inputs,
                    outputs=outputs,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }

    def _execute_sub_workflow(
        self, inputs: dict[str, Any], config: Optional[RunnableConfig]
    ) -> dict[str, Any]:
        """加载子工作流图配置并通过 GraphEngine 执行，返回 end 节点输出。

        降级策略：
        - 子工作流不存在或未发布时，返回声明的 outputs 变量值为 None
        - 执行异常时，返回声明的 outputs 变量值为 None
        """
        try:
            from app.http.app import injector
            from internal.model import Workflow
            from internal.service import WorkflowService
            from pkg.sqlalchemy import SQLAlchemy
            from internal.core.workflow.graph_engine import GraphEngine
            from internal.core.workflow.variable_pool import VariablePool
            from internal.core.workflow.real_node_executor import RealNodeExecutor

            db = injector.get(SQLAlchemy)
            workflow_service = injector.get(WorkflowService)

            # 1.加载子工作流（需已发布）
            sub_workflow = db.session.query(Workflow).filter(
                Workflow.id == self.node_data.workflow_id,
            ).first()

            if sub_workflow is None:
                logger.warning("子流程节点: 目标工作流不存在 workflow_id=%s", self.node_data.workflow_id)
                return self._empty_outputs()

            if not sub_workflow.graph:
                logger.warning("子流程节点: 目标工作流未发布 workflow_id=%s", self.node_data.workflow_id)
                return self._empty_outputs()

            # 2.解析子工作流图配置
            graph_data = sub_workflow.graph if isinstance(sub_workflow.graph, dict) else {}
            nodes_data = graph_data.get("nodes", [])
            edges_data = graph_data.get("edges", [])

            if not nodes_data:
                logger.warning("子流程节点: 目标工作流图为空 workflow_id=%s", self.node_data.workflow_id)
                return self._empty_outputs()

            # 3.构建 WorkflowConfig
            sub_config = WorkflowConfig(nodes=nodes_data, edges=edges_data)

            # 4.构建 VariablePool 和 RealNodeExecutor
            variable_pool = VariablePool()

            # 从 config 中提取上下文信息
            configurable = (config or {}).get("configurable", {}) if config else {}
            account_id_str = configurable.get("account_id")
            account = configurable.get("account")
            app_id_str = configurable.get("app_id")

            account_id = UUID(account_id_str) if account_id_str else None
            app_id = UUID(app_id_str) if app_id_str else None

            node_executor = RealNodeExecutor(
                flask_app=workflow_service.db,
                account_id=account_id,
                account=account,
                app_id=app_id,
            )

            # 5.通过 GraphEngine 执行子工作流
            engine = GraphEngine(
                workflow_config=sub_config,
                variable_pool=variable_pool,
                node_executor=node_executor,
            )

            # 收集 end 节点输出
            end_outputs: dict[str, Any] = {}
            for event in engine.execute(inputs):
                if event.get("event") == "node_finished":
                    event_data = event.get("data", {})
                    node_type = event_data.get("node_type", "")
                    if node_type == "end":
                        end_outputs = event_data.get("outputs", {})

            # 6.映射到声明的输出变量
            result: dict[str, Any] = {}
            for output_var in self.node_data.outputs:
                result[output_var.name] = end_outputs.get(output_var.name)

            return result

        except Exception:
            logger.exception("子流程节点执行失败 workflow_id=%s", self.node_data.workflow_id)
            return self._empty_outputs()

    def _empty_outputs(self) -> dict[str, Any]:
        """返回声明的 outputs 变量值为 None（降级用）。"""
        return {output.name: None for output in self.node_data.outputs}

    @staticmethod
    def _resolve_variable(variable, state: WorkflowState) -> Any:
        """从 state 中解析变量引用的值。

        - REF 类型：从 ``state["node_results"]`` 中查找被引用节点的输出字段
        - LITERAL/GENERATED 类型：直接返回 ``content`` 原始值
        """
        # 1.REF 类型：从前序节点输出中查找
        if variable.value.type == VariableValueType.REF.value:
            ref_node_id = variable.value.content.ref_node_id
            ref_var_name = variable.value.content.ref_var_name
            for node_result in state.get("node_results", []):
                if node_result.node_data.id == ref_node_id:
                    return node_result.outputs.get(ref_var_name)
            return None

        # 2.LITERAL/GENERATED 类型：直接返回 content
        return variable.value.content
