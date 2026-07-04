"""子流程节点执行器模块。"""
import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.exception import FailException
from .sub_workflow_entity import SubWorkflowNodeData


class SubWorkflowNode(BaseNode):
    """子流程节点执行器，调用另一个工作流。

    执行逻辑：
    1. 从 inputs 解析输入参数（REF 类型从前序节点输出中提取，LITERAL/GENERATED 直接取值）
    2. 加载目标 workflow 的 graph 配置并执行子工作流
    3. 提取子工作流 end 节点的输出
    4. 返回输出作为本节点的 outputs

    第一版占位实现说明：
    - 当前 ``invoke`` 仅校验 ``workflow_id`` 存在并解析 inputs 结构，不真正加载和执行子工作流。
    - 真正执行子工作流需要通过 ``injector.get(WorkflowService)`` 加载目标 workflow 配置，
      再通过 ``injector.get(GraphEngine)`` 或 ``Workflow`` 工具编译并执行子图，
      该集成由后续任务实现。
    - 占位输出为 ``{output.name: None for output in outputs}``，便于下游节点引用调试。
    """

    node_data: SubWorkflowNodeData

    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        """调用子工作流（第一版占位实现）"""
        start_at = time.perf_counter()

        # 1.校验 workflow_id 必须存在
        if self.node_data.workflow_id is None:
            raise FailException("子流程节点的 workflow_id 不能为空")

        # 2.解析 inputs（REF 类型从前序节点输出提取，LITERAL/GENERATED 直接取值）
        # 占位实现：仅解析并记录到 inputs 字段，不真正传递给子工作流
        resolved_inputs: dict[str, Any] = {}
        for variable in self.node_data.inputs:
            resolved_inputs[variable.name] = self._resolve_variable(variable, state)

        # 3.调用子工作流（占位实现）
        # 后续任务接入 WorkflowService/GraphEngine 时，在此处：
        #   a) 通过 workflow_id 加载目标 WorkflowConfig
        #   b) 构建 Workflow 工具并 invoke 子工作流
        #   c) 提取子工作流 end 节点的输出
        # 当前占位输出：所有声明的 outputs 变量值均为 None
        outputs: dict[str, Any] = {
            output.name: None for output in self.node_data.outputs
        }

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
