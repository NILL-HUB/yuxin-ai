from marshmallow import Schema, fields


class MyAppResp(Schema):
    id = fields.String()
    assignment_id = fields.String()
    name = fields.String()
    icon = fields.String()
    description = fields.String()
    assigned_at = fields.Integer(allow_none=True)


class MyAppListResp(Schema):
    list = fields.List(fields.Nested(MyAppResp))
