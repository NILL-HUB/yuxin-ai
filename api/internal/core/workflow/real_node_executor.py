"""真实节点执行器模块，桥接 GraphEngine 与 BaseNode.invoke。"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import BaseNodeData, NodeType
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode, NodeClasses
from internal.core.workflow.nodes.dataset_retrieval.dataset_retrieval_node import DatasetRetrievalNode
from internal.core.workflow.variable_pool import VariablePool

logger = logging.getLogger(__name__)


class RealNodeExecutor:
    """桥接 GraphEngine 与 BaseNode.invoke 的真实节点执行器。

    GraphEngine 的 node_executor 期望签名 (BaseNodeData, VariablePool) -> dict，
    而真实节点继承 BaseNode，invoke 签名为 (WorkflowState, config) -> WorkflowState。
    本适配器负责：
    1. 按 node_type 实例化对应 BaseNode 子类（缓存复用）
    2. 从 VariablePool 投影出 WorkflowState（含累积的 node_results）
    3. 调用真实 invoke 方法
    4. 提取 outputs 返回给 GraphEngine
    """

    def __init__(
        self,
        flask_app=None,
        account_id: Optional[UUID] = None,
        account: Any = None,
        app_id: Optional[UUID] = None,
    ) -> None:
        self.flask_app = flask_app
        self.account_id = account_id
        self.account = account
        self.app_id = app_id
        self._node_instances: dict[UUID, BaseNode] = {}
        self._accumulated_results: list = []  # 累积的 NodeResult 列表

    def __call__(self, node_data: BaseNodeData, pool: VariablePool) -> dict[str, Any]:
        """符合 GraphEngine.node_executor 签名的入口。"""
        # 1. 懒加载节点实例
        node = self._get_or_create_node(node_data)

        # 2. 从 VariablePool 投影出 WorkflowState
        state = self._build_state_from_pool(pool)

        # 3. 调用真实 invoke（通过 config 传递 pool，供节点解析 {{#...#}} 引用）
        config = self._build_runnable_config(pool)
        new_state = node.invoke(state, config)

        # 4. 提取最新 NodeResult，累积到内部 list 供后续节点引用
        new_results = new_state.get("node_results", [])
        self._accumulated_results.extend(new_results)

        # 5. 返回 outputs dict（GraphEngine 会用 node_id 写入 pool）
        #    同时添加 node_type 别名，支持 {{#node_type.field#}} 引用语法
        if new_results:
            outputs = new_results[-1].outputs or {}
            node_type = node_data.node_type
            node_type_str = node_type.value if hasattr(node_type, "value") else str(node_type)
            pool.set_node_output(node_type_str, outputs)
            return outputs
        return {}

    def _get_or_create_node(self, node_data: BaseNodeData) -> BaseNode:
        """按 node_type 实例化节点，缓存复用。"""
        if node_data.id in self._node_instances:
            return self._node_instances[node_data.id]

        node_type = node_data.node_type
        # 处理 NodeType 枚举与字符串两种形式
        node_type_str = node_type.value if hasattr(node_type, "value") else str(node_type)

        if node_type_str == NodeType.DATASET_RETRIEVAL.value:
            node = DatasetRetrievalNode(
                flask_app=self.flask_app,
                account_id=self.account_id,
                node_data=node_data,
            )
        else:
            node_cls = NodeClasses.get(node_type_str)
            if node_cls is None:
                raise ValueError(f"不支持的节点类型: {node_type_str}")
            node = node_cls(node_data=node_data)

        self._node_instances[node_data.id] = node
        return node

    def _build_state_from_pool(self, pool: VariablePool) -> WorkflowState:
        """从 VariablePool 投影出 WorkflowState。"""
        inputs = pool.get_system_variable("inputs") or {}
        return {
            "inputs": inputs,
            "outputs": {},
            "node_results": list(self._accumulated_results),
        }

    def _build_runnable_config(self, pool: VariablePool | None = None) -> RunnableConfig:
        """构建 RunnableConfig，传递 account_id、variable_pool 等上下文。

        Args:
            pool: GraphEngine 的 VariablePool，供节点解析 {{#...#}} 引用语法
        """
        configurable: dict[str, Any] = {}
        if self.account_id is not None:
            configurable["account_id"] = str(self.account_id)
        if self.app_id is not None:
            configurable["app_id"] = str(self.app_id)
        if self.account is not None:
            configurable["account"] = self.account
        if pool is not None:
            configurable["variable_pool"] = pool
        return {"configurable": configurable}
