import time
from typing import Any, Optional
from jinja2 import Template
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state
from internal.core.workflow.variable_parser import REFERENCE_PATTERN, VariableParser
from internal.core.workflow.variable_pool import VariablePool
from .llm_entity import LLMNodeData


class LLMNode(BaseNode):
    """大语言模型节点"""
    node_data: LLMNodeData

    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        """大语言模型节点调用工具，根据输入字段+预设prompt生成对应内容后输出"""
        # 1.提取节点中的输入数据
        start_at = time.perf_counter()
        inputs_dict = extract_variables_from_state(self.node_data.inputs, state)

        # 2.解析 prompt 模板
        #    优先使用 VariableParser 解析 {{#node.field#}} 工作流引用语法（架构标准路径）
        #    RealNodeExecutor 通过 config["configurable"]["variable_pool"] 传递 GraphEngine 的 pool
        #    无引用或无 pool 时回退到 jinja2 渲染（向后兼容 {{ var }} 语法）
        prompt_template = self.node_data.prompt
        pool: VariablePool | None = None
        if config is not None:
            pool = config.get("configurable", {}).get("variable_pool")

        if pool is not None and REFERENCE_PATTERN.search(prompt_template):
            prompt_value: Any = VariableParser().parse(prompt_template, pool)
        else:
            template = Template(prompt_template)
            prompt_value = template.render(**inputs_dict)

        # 3.通过依赖管理器获取language_model_service并加载模型
        from app.http.app import injector
        from internal.service import LanguageModelService
        language_model_service = injector.get(LanguageModelService)
        llm = language_model_service.load_language_model(self.node_data.language_model_config)

        # 4.使用stream来代替invoke，避免接口长时间未响应超时
        content = ""
        for chunk in llm.stream(prompt_value):
            content += chunk.content

        # 5.提取并构建输出数据结构
        outputs = {}
        if self.node_data.outputs:
            outputs[self.node_data.outputs[0].name] = content
        else:
            outputs["output"] = content

        # 6.构建响应状态并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED.value,
                    inputs=inputs_dict,
                    outputs=outputs,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }
