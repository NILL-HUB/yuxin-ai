"""管理端 Agent 请求/响应 schema。"""
from marshmallow import Schema, fields


class AdminAgentAssignablePermissionsResp(Schema):
    codes = fields.List(fields.String(), dump_default=[])


class AdminAgentInvokeReq(Schema):
    """执行一个板块动作的请求体。

    `board` / `action` 的合法性由板块动作注册表（`admin_agent_boards.py`）
    判定——未登记即拒绝（fail closed），此处只校验"非空"。
    """

    board = fields.String(required=True)
    action = fields.String(required=True)
    payload = fields.Dict(load_default=dict)


class AdminAgentDraftResp(Schema):
    id = fields.String()
    policy_type = fields.String()
    target_id = fields.String()
    before_config = fields.Dict()
    after_config = fields.Dict()
    diff = fields.Dict()
    impact = fields.Dict()
    status = fields.String()
    created_at = fields.Integer(allow_none=True)


class AdminAgentDraftListResp(Schema):
    items = fields.List(fields.Nested(AdminAgentDraftResp), dump_default=[])
