"""管理端 Agent 请求/响应 schema。"""
from marshmallow import Schema, fields


class AdminAgentAssignablePermissionsResp(Schema):
    codes = fields.List(fields.String(), dump_default=[])
