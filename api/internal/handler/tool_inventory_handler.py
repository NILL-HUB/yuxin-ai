from dataclasses import dataclass

from flask import request
from flask_login import current_user
from injector import inject

from internal.service.tool_inventory_service import (
    ToolCandidateCollector,
    ToolPolicyFilter,
)
from pkg.response import success_json


@inject
@dataclass
class ToolInventoryHandler:
    collector: ToolCandidateCollector
    policy_filter: ToolPolicyFilter

    def get_tool_inventory(self, current_account=None):
        account = current_account or current_user
        account_id = getattr(account, "id", None)
        if account_id is None:
            return success_json({"candidates": [], "filtered_out_tools": []})
        candidates = self.collector.collect(account_id)
        result = self.policy_filter.filter(
            candidates,
            account_id=str(account_id),
            agent_pool=request.args.get("agent_pool") or None,
            budget_level=request.args.get("budget_level") or "medium",
            allow_confirmation=request.args.get("allow_confirmation") == "true",
        )
        tool_pool = request.args.get("tool_pool") or ""
        risk_level = request.args.get("risk_level") or ""
        result["candidates"] = self._filter_candidates(
            result["candidates"], tool_pool=tool_pool, risk_level=risk_level
        )
        return success_json(result)

    @staticmethod
    def _filter_candidates(
        candidates: list[dict], *, tool_pool: str, risk_level: str
    ) -> list[dict]:
        result = []
        for candidate in candidates:
            metadata = candidate.get("metadata") or {}
            if tool_pool and metadata.get("tool_pool") != tool_pool:
                continue
            if risk_level and metadata.get("risk_level") != risk_level:
                continue
            result.append(candidate)
        return result
