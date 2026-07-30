from .base_node import BaseNode
from .code.code_node import CodeNode, CodeNodeData
from .dataset_retrieval.dataset_retrieval_node import DatasetRetrievalNode, DatasetRetrievalNodeData
from .end.end_node import EndNode, EndNodeData
from .http_request.http_request_node import HttpRequestNode, HttpRequestNodeData
from .if_else.if_else_node import IfElseNode, IfElseNodeData
from .intent_classifier.intent_classifier_node import IntentClassifierNode, IntentClassifierNodeData
from .iteration.iteration_node import IterationNode, IterationNodeData
from .llm.llm_node import LLMNode, LLMNodeData
from .parameter_extractor.parameter_extractor_node import ParameterExtractorNode, ParameterExtractorNodeData
from .start.start_node import StartNode, StartNodeData
from .sub_workflow.sub_workflow_node import SubWorkflowNode, SubWorkflowNodeData
from .template_transform.template_transform_node import TemplateTransformNode, TemplateTransformNodeData
from .text_processor.text_processor_node import TextProcessorNode, TextProcessorNodeData
from .tool.tool_node import ToolNode, ToolNodeData
from .variable_assigner.variable_assigner_node import VariableAssignerNode, VariableAssignerNodeData

# 节点类映射（按 node_type 字符串 -> BaseNode 子类）
# 供 RealNodeExecutor 及其他模块按类型实例化节点，避免循环导入
from ..entities.node_entity import NodeType

NodeClasses = {
    NodeType.START.value: StartNode,
    NodeType.END.value: EndNode,
    NodeType.LLM.value: LLMNode,
    NodeType.TEMPLATE_TRANSFORM.value: TemplateTransformNode,
    NodeType.DATASET_RETRIEVAL.value: DatasetRetrievalNode,
    NodeType.CODE.value: CodeNode,
    NodeType.TOOL.value: ToolNode,
    NodeType.HTTP_REQUEST.value: HttpRequestNode,
    NodeType.TEXT_PROCESSOR.value: TextProcessorNode,
    NodeType.VARIABLE_ASSIGNER.value: VariableAssignerNode,
    NodeType.PARAMETER_EXTRACTOR.value: ParameterExtractorNode,
    NodeType.IF_ELSE.value: IfElseNode,
    NodeType.ITERATION.value: IterationNode,
    NodeType.SUB_WORKFLOW.value: SubWorkflowNode,
    NodeType.INTENT_CLASSIFIER.value: IntentClassifierNode,
}

__all__ = [
    "BaseNode",
    "NodeClasses",
    "StartNode", "StartNodeData",
    "LLMNode", "LLMNodeData",
    "ParameterExtractorNode", "ParameterExtractorNodeData",
    "TemplateTransformNode", "TemplateTransformNodeData",
    "DatasetRetrievalNode", "DatasetRetrievalNodeData",
    "CodeNode", "CodeNodeData",
    "ToolNode", "ToolNodeData",
    "HttpRequestNode", "HttpRequestNodeData",
    "TextProcessorNode", "TextProcessorNodeData",
    "VariableAssignerNode", "VariableAssignerNodeData",
    "IfElseNode", "IfElseNodeData",
    "IterationNode", "IterationNodeData",
    "SubWorkflowNode", "SubWorkflowNodeData",
    "IntentClassifierNode", "IntentClassifierNodeData",
    "EndNode", "EndNodeData",
]
