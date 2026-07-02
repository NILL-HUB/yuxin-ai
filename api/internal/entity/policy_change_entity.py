from dataclasses import dataclass, field

from .base_entity import SerializableMixin


POLICY_CHANGE_DRAFT_STATUSES = ["pending", "applied", "rolled_back"]
POLICY_CHANGE_TYPES = ["model_routing", "tool_policy", "agent_policy"]


@dataclass
class PolicyChangeDraft(SerializableMixin):
    suggestion_id: str
    policy_type: str
    target_id: str
    before_config: dict = field(default_factory=dict)
    after_config: dict = field(default_factory=dict)
    diff: dict = field(default_factory=dict)
    impact: dict = field(default_factory=dict)
    status: str = "pending"

    def __post_init__(self):
        if self.status not in POLICY_CHANGE_DRAFT_STATUSES:
            raise ValueError(
                "Unsupported policy change draft status: "
                f"{self.status}"
            )
        if self.policy_type not in POLICY_CHANGE_TYPES:
            raise ValueError(
                "Unsupported policy change type: "
                f"{self.policy_type}"
            )
