"""意图识别节点实体定义模块。"""
from pydantic import BaseModel, Field, field_validator

from internal.core.workflow.entities.node_entity import BaseNodeData
from internal.core.workflow.entities.variable_entity import VariableEntity
from internal.exception import ValidateErrorException


class IntentClass(BaseModel):
    """意图分类配置"""
    name: str  # 分类名称（用于路由匹配）
    description: str = ""  # 分类描述（帮助 LLM 理解分类标准）


class IntentClassifierNodeData(BaseNodeData):
    """意图识别节点数据，对输入文本进行意图分类。

    参考 Dify 的 Question Classifier 节点设计：
    - input_variable: 待分类的输入文本变量（ref 类型）
    - classes: 意图分类列表，每个分类含 name 和 description
    - llm_config: 分类使用的 LLM 配置（可选，默认继承应用配置）
    - outputs: 输出变量（class_name 和 confidence）

    注意：
    - 原计划使用 ``model_config`` 作为字段名，但 Pydantic v2 中 ``model_config``
      是 BaseModel 的保留 ClassVar（用于配置 ConfigDict），声明为字段会与父类冲突，
      因此改用 ``llm_config``。
    - ``IntentClass`` 设计为顶层 BaseModel（参考 ``Condition`` 在 if_else_entity.py
      中的设计），而非内部类，便于复用与校验。
    """

    input_variable: VariableEntity  # 待分类的输入文本
    classes: list[IntentClass] = Field(default_factory=list)  # 意图分类列表
    llm_config: dict = Field(default_factory=dict)  # LLM 配置（可选，字段名避让 pydantic 保留的 model_config）
    outputs: list[VariableEntity] = Field(default_factory=list)  # 输出变量

    @field_validator("classes")
    def validate_classes(cls, v: list) -> list:
        """校验分类列表：至少2个分类，且名称唯一"""
        if not v or len(v) == 0:
            raise ValidateErrorException("意图识别节点至少需要1个分类")
        if len(v) < 2:
            raise ValidateErrorException("意图识别节点至少需要2个分类")
        # 校验分类名称唯一
        names = [c.name for c in v]
        if len(names) != len(set(names)):
            raise ValidateErrorException("意图识别节点的分类名称不能重复")
        return v
