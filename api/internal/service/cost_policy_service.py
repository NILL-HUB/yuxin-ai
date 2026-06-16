from dataclasses import dataclass


@dataclass
class CostPolicyService:
    minimum_balance_credits: float = 0

    def build_policy(
        self,
        *,
        task_complexity: str,
        budget_level: str,
        balance_credits: float,
        deep_thinking_requested: bool,
    ) -> dict:
        if balance_credits < self.minimum_balance_credits:
            return {
                "allowed": False,
                "model_tier": "cheap",
                "max_agent_count": 0,
                "max_tool_count": 0,
                "deep_thinking": False,
                "reason": "insufficient_balance",
            }
        if budget_level == "low":
            return {
                "allowed": True,
                "model_tier": "cheap",
                "max_agent_count": 2,
                "max_tool_count": 4,
                "deep_thinking": False,
                "reason": "budget_downgraded",
            }
        if task_complexity == "complex":
            return {
                "allowed": True,
                "model_tier": "strong",
                "max_agent_count": 5,
                "max_tool_count": 10,
                "deep_thinking": deep_thinking_requested,
                "reason": "complex_task_full_reasoning",
            }
        if task_complexity == "medium":
            return {
                "allowed": True,
                "model_tier": "standard",
                "max_agent_count": 3,
                "max_tool_count": 6,
                "deep_thinking": False,
                "reason": "medium_task_standard_cost",
            }
        return {
            "allowed": True,
            "model_tier": "cheap",
            "max_agent_count": 1,
            "max_tool_count": 3,
            "deep_thinking": False,
            "reason": "simple_task_low_cost",
        }
