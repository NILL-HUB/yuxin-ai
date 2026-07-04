"""子流程节点实体定义模块。"""
from uuid import UUID

from pydantic import Field, field_validator

from internal.core.workflow.entities.node_entity import BaseNodeData
from internal.core.workflow.entities.variable_entity import VariableEntity
from internal.exception import ValidateErrorException


class SubWorkflowNodeData(BaseNodeData):
    """子流程节点数据，调用另一个已发布的工作流。

    参考 Dify 的 SubWorkflow 节点设计：
    - workflow_id: 要调用的目标工作流 ID
    - inputs: 输入变量列表（传递给子工作流的 start 节点）
    - outputs: 输出变量列表（从子工作流的 end 节点输出中提取）
    """

    workflow_id: UUID  # 目标工作流 ID
    inputs: list[VariableEntity] = Field(default_factory=list)  # 输入变量列表
    outputs: list[VariableEntity] = Field(default_factory=list)  # 输出变量列表

    @field_validator("workflow_id", mode="before")
    def validate_workflow_id(cls, v):
        """校验 workflow_id 不能为空，字符串自动转为 UUID"""
        if v is None or v == "":
            raise ValidateErrorException("子流程节点的 workflow_id 不能为空")
        if isinstance(v, str):
            return UUID(v)
        return v
