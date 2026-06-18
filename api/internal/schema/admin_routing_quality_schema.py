from marshmallow import Schema, fields
from wtforms import Form, IntegerField, StringField


class CreateRoutingQualityFeedbackReq(Form):
    routing_log_id = StringField("routing_log_id")
    rating = IntegerField("rating")
    comment = StringField("comment")


class DismissSuggestionReq(Form):
    reason = StringField("reason", default="")


class RollbackPolicyChangeReq(Form):
    reason = StringField("reason", default="")


class RoutingQualityFeedbackResp(Schema):
    id = fields.String(allow_none=True)
    routing_log_id = fields.String()
    source = fields.String()
    rating = fields.Integer()
    dimension_scores = fields.Dict()
    comment = fields.String()
    metadata = fields.Dict()
    created_by = fields.String(allow_none=True)
    created_at = fields.String(allow_none=True)


class RoutingQualityMetricsResp(Schema):
    total_count = fields.Integer()
    feedback_count = fields.Integer()
    avg_rating = fields.Float()
    fallback_rate = fields.Float()
    avg_latency_ms = fields.Float()
    avg_cost_credits = fields.Float()
    quality_by_task_type = fields.Dict()
    quality_by_agent_pool = fields.Dict()
    quality_by_tool_pool = fields.Dict()
    quality_by_model = fields.Dict()


class RoutingOptimizationSuggestionResp(Schema):
    id = fields.String(allow_none=True)
    target_type = fields.String()
    target_id = fields.String()
    suggestion_type = fields.String()
    severity = fields.String()
    reason = fields.String()
    evidence = fields.Dict()
    status = fields.String()
    dismiss_reason = fields.String(allow_none=True)
    applied_by = fields.String(allow_none=True)
    applied_at = fields.String(allow_none=True)
    policy_change_draft_id = fields.String(allow_none=True)


class SuggestionActionResp(Schema):
    suggestion_id = fields.String()
    status = fields.String()


class PolicyChangePreviewResp(Schema):
    suggestion_id = fields.String()
    policy_type = fields.String()
    target_id = fields.String()
    before_config = fields.Dict()
    after_config = fields.Dict()
    diff = fields.Dict()
    impact = fields.Dict()
    status = fields.String()


class PolicyChangeDraftResp(Schema):
    id = fields.String(allow_none=True)
    suggestion_id = fields.String()
    policy_type = fields.String()
    target_id = fields.String()
    before_config = fields.Dict()
    after_config = fields.Dict()
    diff = fields.Dict()
    impact = fields.Dict()
    status = fields.String()
    applied_by = fields.String(allow_none=True)
    applied_at = fields.String(allow_none=True)
    rolled_back_at = fields.String(allow_none=True)
    rollback_reason = fields.String(allow_none=True)


class PolicyChangeListResp(Schema):
    items = fields.List(fields.Nested(PolicyChangeDraftResp))
    total = fields.Integer()
