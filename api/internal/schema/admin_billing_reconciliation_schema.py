from marshmallow import Schema, fields


class AdminReconciliationResp(Schema):
    class Meta:
        ordered = True

    id = fields.String()
    task_id = fields.String()
    account_id = fields.String()
    estimated_credits = fields.Integer()
    actual_credits = fields.Integer()
    cost_credits = fields.Integer()
    diff_credits = fields.Integer()
    status = fields.String()
    alert_flags = fields.List(fields.String())
    created_at = fields.Integer()