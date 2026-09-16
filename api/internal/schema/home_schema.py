from marshmallow import Schema, fields


class SuggestedActionSchema(Schema):
    """推荐操作"""
    label = fields.String(required=True)
    action = fields.String(required=True)
    icon = fields.String(required=True)


class RecommendedAgentSchema(Schema):
    """推荐的 Agent 候选（首页意图推荐）"""
    agent_id = fields.String(dump_default="")
    name = fields.String(dump_default="")
    description = fields.String(dump_default="")
    icon = fields.String(dump_default="")
    source_scope = fields.String(dump_default="")
    source_type = fields.String(dump_default="")
    app_id = fields.String(dump_default="")
    pool = fields.String(dump_default="")
    match_reason = fields.String(dump_default="")
    score = fields.Float(dump_default=0.0)


class RecommendedToolSchema(Schema):
    """推荐的工具候选（首页意图推荐）"""
    source_type = fields.String(dump_default="")
    provider_id = fields.String(dump_default="")
    tool_name = fields.String(dump_default="")
    name = fields.String(dump_default="")
    description = fields.String(dump_default="")
    tool_pool = fields.String(dump_default="")
    reason = fields.String(dump_default="")
    match_type = fields.String(dump_default="")


class GetIntentResp(Schema):
    """获取意图识别结果响应"""
    intent = fields.String(dump_default="")
    confidence = fields.Float(dump_default=0.0)
    should_ask_continue = fields.Boolean(dump_default=False)
    resume_question = fields.String(dump_default="")
    suggested_actions = fields.List(fields.Nested(SuggestedActionSchema), dump_default=[])
    is_default = fields.Boolean(dump_default=False)
    matched_agent_pools = fields.List(fields.String(), dump_default=[])
    matched_tool_pools = fields.List(fields.String(), dump_default=[])
    recommended_agents = fields.List(
        fields.Nested(RecommendedAgentSchema), dump_default=[]
    )
    recommended_tools = fields.List(
        fields.Nested(RecommendedToolSchema), dump_default=[]
    )
