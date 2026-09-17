"""管理端 Agent 对话/会话/消息 schema。"""
from marshmallow import Schema, fields


class AdminAgentChatReq(Schema):
    query = fields.String(required=True)
    conversation_id = fields.String(load_default=None, allow_none=True)


class AdminAgentConversationResp(Schema):
    id = fields.String()
    admin_agent_id = fields.String()
    title = fields.String()
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)


class AdminAgentConversationListResp(Schema):
    items = fields.List(fields.Nested(AdminAgentConversationResp), dump_default=[])


class AdminAgentChatMessageResp(Schema):
    id = fields.String()
    role = fields.String()
    content = fields.String()
    tool_calls = fields.List(fields.Dict(), dump_default=[])
    created_at = fields.Integer(allow_none=True)


class AdminAgentChatMessageListResp(Schema):
    items = fields.List(fields.Nested(AdminAgentChatMessageResp), dump_default=[])
