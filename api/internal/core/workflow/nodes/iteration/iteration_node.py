"""循环节点执行器模块。"""
import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.exception import FailException
from .iteration_entity import IterationNodeData


class IterationNode(BaseNode):
    """循环节点执行器，遍历数组并对每个元素执行子节点链。

    执行逻辑：
    1. 从 iterator 变量引用读取待遍历数组
    2. 对每个元素创建局部 VariablePool（继承父 pool + 当前元素/索引）
    3. 顺序执行 sub_nodes（按 sub_edges 拓扑顺序）
    4. 收集每次迭代的结果
    5. 聚合输出（默认输出 "result" 为所有迭代输出的列表）

    第一版占位实现说明：
    - 当前 ``invoke`` 仅遍历数组并将元素/索引记录到 outputs，不真正执行 ``sub_nodes``。
    - 子节点链的真正执行需要接入 GraphEngine 递归编译子图，由后续任务实现。
    - 占位输出的 ``result`` 为原始数组的副本，便于下游节点引用调试。
    """

    node_data: IterationNodeData

    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        """遍历 iterator 数组并对每个元素执行子节点链（第一版占位实现）"""
        start_at = time.perf_counter()

        # 1.从 state 中解析 iterator 引用的数组
        iterator_value = self._resolve_iterator(self.node_data.iterator, state)

        # 2.校验数组类型（必须是 list）
        if not isinstance(iterator_value, list):
            raise FailException("循环节点的iterator必须是数组类型")

        # 3.遍历数组，收集每次迭代的元素与索引
        # 占位实现：不真正执行 sub_nodes，仅记录 item/index
        # 后续任务接入 GraphEngine 时，在此处创建局部 VariablePool 并递归执行子节点链
        iter_items: list[Any] = []
        iter_indices: list[int] = []
        result: list[Any] = []
        for index, item in enumerate(iterator_value):
            iter_items.append(item)
            iter_indices.append(index)
            # 占位输出：直接将原始元素追加到 result
            result.append(item)

        # 4.构建输出数据
        # - result: 聚合输出（占位为原始数组副本）
        # - output_variable_name: 记录所有迭代的当前元素（便于测试与调试）
        # - index_variable_name: 记录所有迭代的当前索引
        outputs: dict[str, Any] = {
            "result": result,
            self.node_data.output_variable_name: iter_items,
            self.node_data.index_variable_name: iter_indices,
        }

        # 5.构建状态数据并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED.value,
                    inputs={"iterator": iterator_value},
                    outputs=outputs,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }

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
