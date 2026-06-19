from dataclasses import dataclass


ORCHESTRATION_FEATURE_FLAG_CODES = [
    "ENABLE_ORCHESTRATOR",
    "ENABLE_AGENT_METADATA_ROUTING",
    "ENABLE_TOOL_POOL_RETRIEVAL",
    "ENABLE_COST_MODEL_ROUTING",
    "ENABLE_MULTI_AGENT_EXECUTION",
    "ENABLE_RESULT_SYNTHESIZER",
    "ENABLE_ROUTING_LOGS",
    "ENABLE_AUTO_DEEP_THINKING",
]


@dataclass
class OrchestrationFeatureFlag:
    code: str
    name: str
    description: str
    enabled: bool
    risk_level: str
    fallback_behavior: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "risk_level": self.risk_level,
            "fallback_behavior": self.fallback_behavior,
        }


def get_default_orchestration_feature_flags() -> list[OrchestrationFeatureFlag]:
    return [
        OrchestrationFeatureFlag(
            code="ENABLE_ORCHESTRATOR",
            name="Orchestrator",
            description="Enable orchestration router for /home intent handling",
            enabled=True,
            risk_level="medium",
            fallback_behavior="direct_answer",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_AGENT_METADATA_ROUTING",
            name="Agent metadata routing",
            description="Use agent metadata to select candidate agent pools",
            enabled=False,
            risk_level="medium",
            fallback_behavior="skip_agent_subset",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_TOOL_POOL_RETRIEVAL",
            name="Tool pool retrieval",
            description="Use governed tool pool retrieval for tool candidates",
            enabled=False,
            risk_level="high",
            fallback_behavior="skip_tool_subset",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_COST_MODEL_ROUTING",
            name="Cost model routing",
            description="Use cost policy to select model tier and budget hints",
            enabled=False,
            risk_level="medium",
            fallback_behavior="safe_cheap_policy",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_MULTI_AGENT_EXECUTION",
            name="Multi-agent execution",
            description="Enable multi-agent planning and execution modes",
            enabled=False,
            risk_level="high",
            fallback_behavior="single_or_direct",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_RESULT_SYNTHESIZER",
            name="Result synthesizer",
            description="Enable synthesized final response from agent results",
            enabled=False,
            risk_level="medium",
            fallback_behavior="empty_summary",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_ROUTING_LOGS",
            name="Routing logs",
            description="Enable detailed routing log payload generation",
            enabled=False,
            risk_level="medium",
            fallback_behavior="skip_routing_log_payload",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_AUTO_DEEP_THINKING",
            name="Auto deep thinking",
            description="Enable LLM intent detection to auto-trigger deep thinking (disable to fall back to keywords + manual switch)",
            enabled=True,
            risk_level="medium",
            fallback_behavior="keyword_matching_manual_switch",
        ),
    ]


def get_disabled_orchestration_feature_flag(code: str) -> OrchestrationFeatureFlag:
    return OrchestrationFeatureFlag(
        code=code,
        name=code,
        description="Unknown orchestration feature flag",
        enabled=False,
        risk_level="unknown",
        fallback_behavior="disabled",
    )
