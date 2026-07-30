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
                "model_tier": "1",
                "max_agent_count": 0,
                "max_tool_count": 0,
                "deep_thinking": False,
                "reason": "insufficient_balance",
            }
        if budget_level == "low":
            return {
                "allowed": True,
                "model_tier": "1",
                "max_agent_count": 2,
                "max_tool_count": 4,
                "deep_thinking": False,
                "reason": "budget_downgraded",
            }
        if task_complexity == "complex":
            return {
                "allowed": True,
                "model_tier": "3",
                "max_agent_count": 5,
                "max_tool_count": 10,
                "deep_thinking": deep_thinking_requested,
                "reason": "complex_task_full_reasoning",
            }
        if task_complexity == "medium":
            return {
                "allowed": True,
                "model_tier": "2",
                "max_agent_count": 3,
                "max_tool_count": 6,
                "deep_thinking": False,
                "reason": "medium_task_standard_cost",
            }
        return {
            "allowed": True,
            "model_tier": "1",
            "max_agent_count": 1,
            "max_tool_count": 3,
            "deep_thinking": False,
            "reason": "simple_task_low_cost",
        }


# 档位排序：数字标识越大通常档位越高（1=经济型, 2=标准型, 3=强力型）
_TIER_RANK = {"1": 0, "2": 1, "3": 2}


@dataclass
class EscalationPolicy:
    minimum_balance_credits: float = 0
    token_escalation_threshold: int = 4000
    balance_downgrade_threshold: float = 100.0
    complexity_escalation: dict = None
    budget_downgrade_map: dict = None

    def __post_init__(self):
        if self.complexity_escalation is None:
            self.complexity_escalation = {
                "simple": "1",
                "medium": "2",
                "complex": "3",
            }
        if self.budget_downgrade_map is None:
            self.budget_downgrade_map = {
                "low": "1",
                "medium": "2",
                "high": "3",
            }


class EscalationPolicyService:
    def __init__(self, policy: EscalationPolicy = None):
        self.policy = policy or EscalationPolicy()

    def should_escalate(self, current_tier: str, token_count: int, task_complexity: str) -> bool:
        target_tier = self.policy.complexity_escalation.get(task_complexity, "2")
        if self._tier_rank(target_tier) > self._tier_rank(current_tier):
            return True
        if token_count > self.policy.token_escalation_threshold:
            return True
        return False

    def should_downgrade(
        self, current_tier: str, balance_credits: float, budget_level: str
    ) -> tuple:
        if balance_credits < self.policy.balance_downgrade_threshold:
            return True, "1"
        target_tier = self.policy.budget_downgrade_map.get(budget_level, "2")
        if self._tier_rank(target_tier) < self._tier_rank(current_tier):
            return True, target_tier
        return False, current_tier

    def resolve_tier(
        self,
        current_tier: str,
        token_count: int = 0,
        task_complexity: str = "simple",
        balance_credits: float = float("inf"),
        budget_level: str = "medium",
    ) -> str:
        should_downgrade, downgrade_tier = self.should_downgrade(
            current_tier, balance_credits, budget_level
        )
        if should_downgrade:
            return downgrade_tier
        if self.should_escalate(current_tier, token_count, task_complexity):
            target_tier = self.policy.complexity_escalation.get(task_complexity, "2")
            return target_tier
        return current_tier

    @staticmethod
    def _tier_rank(tier: str) -> int:
        return _TIER_RANK.get(tier, 1)


