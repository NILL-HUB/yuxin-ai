from marshmallow import Schema, fields


class MyAppResp(Schema):
    id = fields.String()
    name = fields.String()
    icon = fields.String()
    description = fields.String()
    created_at = fields.Integer(allow_none=True)
    source = fields.String(dump_default="forked")
    status = fields.String(dump_default="")
    can_edit = fields.Boolean(dump_default=False)


class MyAppListResp(Schema):
    list = fields.List(fields.Nested(MyAppResp))
