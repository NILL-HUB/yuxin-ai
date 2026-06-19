from pydantic import BaseModel, Field


class DeepRouteDecision(BaseModel):
    """深度思考阶段的运行时能力判断结果。"""

    need_sandbox: bool = False
    need_file_io: bool = False
    need_execute: bool = False
    need_subagent: bool = False
    need_artifact_output: bool = False
    reason: str = ""
    summary: str = ""


class StructuredDocumentSectionPlan(BaseModel):
    """结构化文档章节规划。"""

    title: str = Field(description="章节标题")
    purpose: str = Field(default="", description="章节写作目的")
    key_points: list[str] = Field(default_factory=list, description="章节需要覆盖的关键点")
    target_length_hint: str = Field(default="", description="章节长度提示")


class StructuredDocumentOutlinePlan(BaseModel):
    """结构化文档大纲。"""

    document_title: str = Field(default="", description="文档标题")
    sections: list[StructuredDocumentSectionPlan] = Field(default_factory=list, description="文档章节列表")


class DeepThinkingIntent(BaseModel):
    """LLM 判断的深度思考意图结果。"""

    needs_deep_thinking: bool = False
    reason: str = ""
