from dataclasses import dataclass

from .base_entity import SerializableMixin


ORCHESTRATION_FEATURE_FLAG_CODES = [
    "ENABLE_ORCHESTRATOR",
    "ENABLE_AGENT_METADATA_ROUTING",
    "ENABLE_TOOL_POOL_RETRIEVAL",
    "ENABLE_COST_MODEL_ROUTING",
    "ENABLE_MODEL_ASSIGNMENT_POLICY",
    "ENABLE_MULTI_AGENT_EXECUTION",
    "ENABLE_RESULT_SYNTHESIZER",
    "ENABLE_ROUTING_LOGS",
    "ENABLE_AUTO_DEEP_THINKING",
    # 池治理渐进式启用三阶段开关（P1-2）
    "ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY",
    "ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE",
    "ENABLE_POOL_GOVERNANCE_BLOCK_ALL",
    # 指挥官决策层开关（默认关闭，启用后由 LLM 指挥官替代规则编排）
    "ENABLE_CONDUCTOR",
]


# 池治理渐进式启用特性 key 常量（供 GovernanceModeResolver 引用）
POOL_GOVERNANCE_FLAG_OBSERVE_ONLY = "ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY"
POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE = "ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE"
POOL_GOVERNANCE_FLAG_BLOCK_ALL = "ENABLE_POOL_GOVERNANCE_BLOCK_ALL"

# 池治理模式取值
POOL_GOVERNANCE_MODE_OBSERVE_ONLY = "observe_only"
POOL_GOVERNANCE_MODE_BLOCK_SENSITIVE = "block_sensitive"
POOL_GOVERNANCE_MODE_BLOCK_ALL = "block_all"


@dataclass
class OrchestrationFeatureFlag(SerializableMixin):
    code: str
    name: str
    description: str
    enabled: bool
    risk_level: str
    fallback_behavior: str


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
            enabled=True,
            risk_level="medium",
            fallback_behavior="skip_agent_subset",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_TOOL_POOL_RETRIEVAL",
            name="Tool pool retrieval",
            description="Use governed tool pool retrieval for tool candidates",
            enabled=True,
            risk_level="high",
            fallback_behavior="skip_tool_subset",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_COST_MODEL_ROUTING",
            name="Cost model routing",
            description="Use cost policy to select model tier and budget hints",
            enabled=True,
            risk_level="medium",
            fallback_behavior="safe_cheap_policy",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_MODEL_ASSIGNMENT_POLICY",
            name="Model assignment policy",
            description="Enable model tier assignment based on routing decision and context",
            enabled=True,
            risk_level="low",
            fallback_behavior="default_tier",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_MULTI_AGENT_EXECUTION",
            name="Multi-agent execution",
            description="Enable multi-agent planning and execution modes",
            enabled=True,
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
            enabled=True,
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
        OrchestrationFeatureFlag(
            code="ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY",
            name="Pool governance observe only",
            description="Stage 1: pool governance gate observes only without blocking (default enabled)",
            enabled=True,
            risk_level="low",
            fallback_behavior="observe_only",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE",
            name="Pool governance block sensitive",
            description="Stage 2: pool governance gate blocks sensitive/dangerous tools only",
            enabled=False,
            risk_level="medium",
            fallback_behavior="observe_only",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_POOL_GOVERNANCE_BLOCK_ALL",
            name="Pool governance block all",
            description="Stage 3: pool governance gate enforces full policy filtering",
            enabled=False,
            risk_level="high",
            fallback_behavior="observe_only",
        ),
        OrchestrationFeatureFlag(
            code="ENABLE_CONDUCTOR",
            name="Conductor decision layer",
            description="Enable LLM conductor to replace rule-based orchestration for task planning and model matching",
            enabled=False,
            risk_level="medium",
            fallback_behavior="orchestrator",
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
