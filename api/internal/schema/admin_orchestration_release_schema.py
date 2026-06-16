from marshmallow import Schema, fields


class OrchestrationReleaseCheckResp(Schema):
    test_status = fields.Dict()
    migration_status = fields.Dict()
    feature_flags = fields.List(fields.Dict())
    security_checklist = fields.Dict()
    cost_metrics = fields.Dict()
    routing_metrics = fields.Dict()
    rollback_plan = fields.Dict()
    warnings = fields.List(fields.String())
