from marshmallow import Schema, fields, pre_dump

from internal.entity.orchestrator_entity import RoutingDecision


class RoutingDecisionResp(Schema):
    intent = fields.String(dump_default="")
    complexity = fields.String(dump_default="")
    execution_mode = fields.String(dump_default="")
    needs_tools = fields.Boolean(dump_default=False)
    needs_agent = fields.Boolean(dump_default=False)
    needs_multi_agent = fields.Boolean(dump_default=False)
    needs_deep_thinking = fields.Boolean(dump_default=False)
    recommended_model_tier = fields.String(dump_default="cheap")
    risk_level = fields.String(dump_default="safe")
    reason = fields.String(dump_default="")
    agent_subset = fields.Dict(dump_default=None)
    tool_subset = fields.Dict(dump_default=None)
    cost_policy = fields.Dict(dump_default=None)
    billing_events = fields.List(fields.Dict(), dump_default=None)
    task_plan_summary = fields.Dict(dump_default=None)
    synthesis_summary = fields.Dict(dump_default=None)

    @pre_dump
    def process_data(self, data: RoutingDecision | dict, **kwargs):
        if isinstance(data, RoutingDecision):
            return data.to_dict()
        return data
