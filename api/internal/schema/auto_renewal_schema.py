from marshmallow import Schema, fields


class AutoRenewalResp(Schema):
    id = fields.String()
    plan_id = fields.String()
    plan_name = fields.String()
    plan_type = fields.String()
    pay_method = fields.String()
    status = fields.String()
    trigger = fields.String()
    threshold_percent = fields.Integer(allow_none=True)
    threshold_days = fields.Integer(allow_none=True)
    next_renew_at = fields.Integer(allow_none=True)
    last_renewed_at = fields.Integer(allow_none=True)
    renew_count = fields.Integer()
    fail_count = fields.Integer()


class AutoRenewalListResp(Schema):
    list = fields.List(fields.Nested(AutoRenewalResp))


class AutoRenewalActionResp(Schema):
    id = fields.String()
    status = fields.String()