"""意图识别节点执行器模块。"""
import json
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
    3. 调用 LLM 返回分类名称与置信度
    4. 输出 class_name 和 confidence
    """

    node_data: IntentClassifierNodeData

    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        """对输入文本进行意图分类"""
        start_at = time.perf_counter()

        # 1.校验 classes 列表（实体层已校验，这里防御性二次校验）
        if not self.node_data.classes:
            raise FailException("意图识别节点至少需要1个分类")

        # 2.从 state 中解析 input_variable 引用的文本
        input_text = self._resolve_variable(self.node_data.input_variable, state)
        if not input_text or not str(input_text).strip():
            raise FailException("意图识别节点的输入文本不能为空")

        # 3.构建分类提示词
        classes_desc = "\n".join(
            f"- {c.name}: {c.description}" if c.description else f"- {c.name}"
            for c in self.node_data.classes
        )
        class_names = [c.name for c in self.node_data.classes]

        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        template = SystemPromptLibraryService().get_prompt_or_default(
            "workflow_intent_classifier_prompt"
        )
        prompt = template.format(
            classes_desc=classes_desc,
            input_text=input_text,
            class_names=class_names,
        )

        # 4.调用 LLM 进行分类
        class_name, confidence = self._call_llm(prompt, class_names)

        # 5.构建输出数据
        outputs: dict[str, Any] = {
            "class_name": class_name,
            "confidence": confidence,
        }

        # 6.构建状态数据并返回
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

    def _call_llm(self, prompt: str, valid_names: list[str]) -> tuple[str, float]:
        """调用 LLM 进行意图分类，返回 (class_name, confidence)。

        降级策略：LLM 调用失败或解析失败时，返回第一个分类，confidence=0.0。
        """
        try:
            from app.http.app import injector
            from internal.service import LanguageModelService

            language_model_service = injector.get(LanguageModelService)
            llm_config = self.node_data.llm_config or {}
            llm = language_model_service.load_language_model(llm_config)

            content = ""
            for chunk in llm.stream(prompt):
                content += chunk.content

            # 解析 LLM 返回的 JSON
            result = self._parse_llm_response(content, valid_names)
            return result
        except Exception:
            # 降级：返回第一个分类，confidence=0.0 表示不确定
            return valid_names[0], 0.0

    @staticmethod
    def _parse_llm_response(content: str, valid_names: list[str]) -> tuple[str, float]:
        """解析 LLM 返回的 JSON 响应。

        尝试从 LLM 输出中提取 JSON 对象，兼容模型可能添加的 markdown 代码块。
        """
        # 1.尝试直接解析
        try:
            data = json.loads(content)
            name = str(data.get("class_name", "")).strip()
            conf = float(data.get("confidence", 0.0))
            if name in valid_names:
                return name, max(0.0, min(1.0, conf))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # 2.尝试从 markdown 代码块中提取
        import re
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                name = str(data.get("class_name", "")).strip()
                conf = float(data.get("confidence", 0.0))
                if name in valid_names:
                    return name, max(0.0, min(1.0, conf))
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # 3.尝试从纯文本中匹配分类名称
        content_lower = content.lower()
        for name in valid_names:
            if name.lower() in content_lower:
                return name, 0.5

        # 4.兜底：返回第一个分类
        return valid_names[0], 0.0

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
