"""循环节点实体定义模块。"""
from pydantic import Field, field_validator

from internal.core.workflow.entities.node_entity import BaseNodeData
from internal.core.workflow.entities.variable_entity import VariableEntity
from internal.exception import ValidateErrorException


class IterationNodeData(BaseNodeData):
    """循环节点数据，遍历数组并对每个元素执行子节点链。

    参考 Dify 的循环节点设计：
    - iterator: 待遍历的数组（变量引用）
    - output_variable_name: 当前元素的变量名（默认 "item"）
    - index_variable_name: 当前索引的变量名（默认 "index"）
    - sub_nodes: 循环体内执行的子节点列表
    - sub_edges: 循环体内的边列表
    - outputs: 循环结束后的输出变量（通常是聚合结果）

    注意：
    - sub_edges 类型使用 ``list`` 而非 ``list[BaseEdgeData]``，避免在节点包
      初始化阶段反向导入 ``entities.edge_entity`` 造成循环依赖；运行期校验
      交给 ``WorkflowConfig.validate_workflow_config`` 统一处理。
    """

    iterator: VariableEntity  # 待遍历的数组变量（ref 类型，引用前序节点输出）
    output_variable_name: str = "item"  # 当前元素在子流程中的变量名
    index_variable_name: str = "index"  # 当前索引在子流程中的变量名
    sub_nodes: list[BaseNodeData] = Field(default_factory=list)  # 循环体内的子节点
    sub_edges: list = Field(default_factory=list)  # 循环体内的边（类型为 BaseEdgeData，为避免循环导入用 list）
    outputs: list[VariableEntity] = Field(default_factory=list)  # 循环输出变量

    @field_validator("output_variable_name")
    def validate_output_variable_name(cls, v: str) -> str:
        """校验当前元素变量名不能为空"""
        if not v or not v.strip():
            raise ValidateErrorException("循环节点的输出变量名不能为空")
        return v.strip()

    @field_validator("index_variable_name")
    def validate_index_variable_name(cls, v: str) -> str:
        """校验当前索引变量名不能为空"""
        if not v or not v.strip():
            raise ValidateErrorException("循环节点的索引变量名不能为空")
        return v.strip()

    @field_validator("sub_nodes")
    def validate_sub_nodes(cls, v: list) -> list:
        """校验子节点列表至少包含1个节点"""
        if not v or len(v) == 0:
            raise ValidateErrorException("循环节点至少需要1个子节点")
        return v
