from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator  # 更新引入方式
from internal.core.workflow.entities.node_entity import BaseNodeData
from internal.core.workflow.entities.variable_entity import VariableEntity, VariableType, VariableValueType
from internal.entity.dataset_entity import RetrievalStrategy
from internal.exception import FailException


class RetrievalConfig(BaseModel):
    """检索配置"""
    retrieval_strategy: RetrievalStrategy = RetrievalStrategy.SEMANTIC.value  # 检索策略
    k: int = 4  # 最大召回数量
    score: float = 0  # 得分阈值


class DatasetRetrievalNodeData(BaseNodeData):
    """知识库检索节点数据

    工作流检索节点已统一切换到新版 KnowledgeBase 系统：
    - knowledge_base_ids 为主字段（新版知识库），必须配置
    """
    knowledge_base_ids: Optional[list[UUID]] = None  # 关联的新版知识库id列表（主字段）
    retrieval_config: RetrievalConfig = RetrievalConfig()  # 检索配置
    inputs: list[VariableEntity] = Field(default_factory=list)  # 输入变量信息
    outputs: list[VariableEntity] = Field(
        default_factory=lambda: [
            VariableEntity(name="combine_documents", value={"type": VariableValueType.GENERATED.value})
        ]
    )

    @model_validator(mode="after")
    def validate_knowledge_base_ids(self) -> "DatasetRetrievalNodeData":
        """校验必须提供 knowledge_base_ids"""
        kb_ids = self.knowledge_base_ids or []
        if not kb_ids:
            raise FailException("知识库检索节点必须配置 knowledge_base_ids")
        return self

    @classmethod
    @field_validator("outputs", mode="before")
    def validate_outputs(cls, value: list[VariableEntity]):
        return [
            VariableEntity(name="combine_documents", value={"type": VariableValueType.GENERATED.value})
        ]

    @classmethod
    @field_validator("inputs")
    def validate_inputs(cls, value: list[VariableEntity]):
        """校验输入变量信息"""
        if len(value) != 1:
            raise FailException("知识库节点输入变量信息出错")

        query_input = value[0]
        if query_input.name != "query" or query_input.type != VariableType.STRING.value or query_input.required is False:
            raise FailException("知识库节点输入变量名字/变量类型/必填属性出错")

        return value
