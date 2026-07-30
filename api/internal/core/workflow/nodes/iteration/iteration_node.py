"""循环节点执行器模块。"""
import logging
import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowConfig, WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.exception import FailException
from .iteration_entity import IterationNodeData

logger = logging.getLogger(__name__)


class IterationNode(BaseNode):
    """循环节点执行器，遍历数组并对每个元素执行子节点链。

    执行逻辑：
    1. 从 iterator 变量引用读取待遍历数组
    2. 对每个元素创建局部 VariablePool（继承父 pool + 当前元素/索引）
    3. 通过 GraphEngine 递归执行 sub_nodes（按 sub_edges 拓扑顺序）
    4. 收集每次迭代的结果
    5. 聚合输出（默认输出 "result" 为所有迭代输出的列表）
    """

    node_data: IterationNodeData

    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        """遍历 iterator 数组并对每个元素执行子节点链"""
        start_at = time.perf_counter()

        # 1.从 state 中解析 iterator 引用的数组
        iterator_value = self._resolve_iterator(self.node_data.iterator, state)

        # 2.校验数组类型（必须是 list）
        if not isinstance(iterator_value, list):
            raise FailException("循环节点的iterator必须是数组类型")

        # 3.遍历数组，对每个元素执行子节点链
        iter_results: list[dict[str, Any]] = []
        for index, item in enumerate(iterator_value):
            try:
                iteration_output = self._execute_iteration_body(item, index, state, config)
                iter_results.append(iteration_output)
            except Exception:
                logger.exception("循环节点第 %d 次迭代执行失败", index)
                # 单次迭代失败记录空输出，继续下一次迭代
                iter_results.append({})

        # 4.构建输出数据
        # - result: 聚合输出（所有迭代输出的列表）
        # - output_variable_name: 所有迭代的当前元素列表
        # - index_variable_name: 所有迭代的当前索引列表
        outputs: dict[str, Any] = {
            "result": iter_results,
            self.node_data.output_variable_name: [item for item in iterator_value],
            self.node_data.index_variable_name: list(range(len(iterator_value))),
        }

        # 5.构建状态数据并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED.value,
                    inputs={"iterator": iterator_value, "count": len(iterator_value)},
                    outputs=outputs,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }

    def _execute_iteration_body(
        self,
        item: Any,
        index: int,
        parent_state: WorkflowState,
        config: Optional[RunnableConfig],
    ) -> dict[str, Any]:
        """执行单次迭代体（子节点链）。

        构建 GraphEngine 执行 sub_nodes + sub_edges，
        将当前 item/index 注入 VariablePool 作为系统变量。
        """
        if not self.node_data.sub_nodes:
            return {}

        try:
            from internal.core.workflow.graph_engine import GraphEngine
            from internal.core.workflow.variable_pool import VariablePool
            from internal.core.workflow.real_node_executor import RealNodeExecutor

            # 1.构建子图配置
            sub_config = WorkflowConfig(
                nodes=self.node_data.sub_nodes,
                edges=self.node_data.sub_edges or [],
            )

            # 2.构建局部 VariablePool
            variable_pool = VariablePool()

            # 注入系统变量：当前迭代的元素和索引
            sys_inputs = {
                self.node_data.output_variable_name: item,
                self.node_data.index_variable_name: index,
            }
            # 继承父级 sys.inputs（如有）
            parent_inputs = parent_state.get("inputs", {})
            if isinstance(parent_inputs, dict):
                sys_inputs.update(parent_inputs)

            variable_pool.set_system_variable("inputs", sys_inputs)

            # 3.构建执行器（复用父级上下文）
            configurable = (config or {}).get("configurable", {}) if config else {}
            from uuid import UUID
            account_id_str = configurable.get("account_id")
            account = configurable.get("account")
            app_id_str = configurable.get("app_id")

            account_id = UUID(account_id_str) if account_id_str else None
            app_id = UUID(app_id_str) if app_id_str else None

            node_executor = RealNodeExecutor(
                account_id=account_id,
                account=account,
                app_id=app_id,
            )

            # 4.通过 GraphEngine 执行子节点链
            engine = GraphEngine(
                workflow_config=sub_config,
                variable_pool=variable_pool,
                node_executor=node_executor,
            )

            # 5.收集 end 节点输出（或最后一个节点的输出）
            end_outputs: dict[str, Any] = {}
            last_outputs: dict[str, Any] = {}
            for event in engine.execute(sys_inputs):
                if event.get("event") == "node_finished":
                    event_data = event.get("data", {})
                    node_type = event_data.get("node_type", "")
                    last_outputs = event_data.get("outputs", {})
                    if node_type == "end":
                        end_outputs = last_outputs

            return end_outputs if end_outputs else last_outputs

        except Exception:
            logger.exception("循环节点迭代体执行失败 index=%d", index)
            return {}

    @staticmethod
    def _resolve_iterator(iterator, state: WorkflowState) -> Any:
        """从 state 中解析 iterator 变量引用的值。

        - REF 类型：从 ``state["node_results"]`` 中查找被引用节点的输出字段
        - LITERAL/GENERATED 类型：直接返回 ``content`` 原始值
        """
        # 1.REF 类型：从前序节点输出中查找
        if iterator.value.type == VariableValueType.REF.value:
            ref_node_id = iterator.value.content.ref_node_id
            ref_var_name = iterator.value.content.ref_var_name
            for node_result in state.get("node_results", []):
                if node_result.node_data.id == ref_node_id:
                    return node_result.outputs.get(ref_var_name)
            return None

        # 2.LITERAL/GENERATED 类型：直接返回 content
        return iterator.value.content
