"""意图识别节点执行器模块。"""
import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.exception import FailException
from .intent_classifier_entity import IntentClassifierNodeData


class IntentClassifierNode(BaseNode):
    """意图识别节点执行器，使用 LLM 对输入文本进行意图分类。

    执行逻辑：
    1. 从 input_variable 读取待分类文本
    2. 构建 LLM prompt（包含所有分类的 name + description）
    3. 调用 LLM 返回分类名称
    4. 输出 class_name 和 confidence

    第一版占位实现说明：
    - 当前 ``invoke`` 仅解析 input_variable 并校验 classes 配置，不真正调用 LLM。
    - 占位输出为 ``{"class_name": classes[0].name, "confidence": 1.0}``，
      便于下游节点引用调试。
    - 真正分类需要通过 ``LanguageModelService.load_language_model`` 构建 LLM，
      再用包含所有分类 name + description 的 prompt 进行分类调用，
      该集成由后续任务实现。
    """

    node_data: IntentClassifierNodeData

    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        """对输入文本进行意图分类（第一版占位实现）"""
        start_at = time.perf_counter()

        # 1.校验 classes 列表（实体层已校验，这里防御性二次校验）
        if not self.node_data.classes:
            raise FailException("意图识别节点至少需要1个分类")

        # 2.从 state 中解析 input_variable 引用的文本
        # 占位实现：仅解析并记录到 inputs 字段，不真正传递给 LLM
        input_text = self._resolve_variable(self.node_data.input_variable, state)

        # 3.调用 LLM 进行意图分类（占位实现）
        # 后续任务接入 LanguageModelService 时，在此处：
        #   a) 通过 llm_config（或继承应用配置）构建 LanguageModel
        #   b) 构建 prompt，包含所有分类的 name + description
        #   c) 调用 LLM 返回分类名称与置信度
        # 当前占位输出：直接返回第一个分类，confidence 为 1.0
        class_name = self.node_data.classes[0].name
        confidence = 1.0

        # 4.构建输出数据
        outputs: dict[str, Any] = {
            "class_name": class_name,
            "confidence": confidence,
        }

        # 5.构建状态数据并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED.value,
                    inputs={"input_text": input_text},
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
