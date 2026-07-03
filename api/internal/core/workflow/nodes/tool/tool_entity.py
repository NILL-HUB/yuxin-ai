from typing import Any, Literal
from pydantic import Field, field_validator
from internal.core.workflow.entities.node_entity import BaseNodeData
from internal.core.workflow.entities.variable_entity import VariableEntity

class ToolNodeData(BaseNodeData):
    """工具节点数据

    tool_type 扩展为支持 7 种工具类型，让 workflow 成为真正的"组合工具"：
    - builtin_tool: 内置工具，使用 provider_id + tool_id 定位
    - api_tool: API 工具，使用 tool_id(name) + provider_id 定位
    - mcp: MCP 工具，provider_id 存 provider_key，tool_id 存 tool_name，meta 存 binding 详情
    - knowledge: 知识库检索，tool_id 存 knowledge_base_id / dataset_id
    - skill: 技能包，tool_id 存 skill_id
    - workflow: 嵌套工作流，tool_id 存 workflow_id（带环检测）
    - agent_binding: Agent 子应用，tool_id 存 app_id（带环检测）
    """
    node_type: Literal["tool"] = "tool"  # 明确指定节点类型
    tool_type: Literal[
        "builtin_tool",
        "api_tool",
        "mcp",
        "knowledge",
        "skill",
        "workflow",
        "agent_binding",
        "",
    ] = Field(default="", alias="type")
    provider_id: str = ""
    tool_id: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: list[VariableEntity] = Field(default_factory=list)
    outputs: list[VariableEntity] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)  # 添加meta字段

    model_config = {
        "populate_by_name": True
    }

    @field_validator("outputs", mode="before")
    def validate_outputs(cls, outputs: list[VariableEntity]):
        # 处理各种可能的输入情况
        if outputs is None:
            return [VariableEntity(name="text", type="string", value={"type": "generated"})]
        if isinstance(outputs, list):
            if not outputs:
                return [VariableEntity(name="text", type="string", value={"type": "generated"})]
            return outputs
        return [VariableEntity(name="text", type="string", value={"type": "generated"})]