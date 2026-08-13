from internal.entity.orchestration_feature_flag_entity import (
    ORCHESTRATION_FEATURE_FLAG_CODES,
    OrchestrationFeatureFlag,
    get_default_orchestration_feature_flags,
    get_disabled_orchestration_feature_flag,
)


def test_default_feature_flags_should_include_all_phase8_codes():
    flags = get_default_orchestration_feature_flags()

    assert [flag.code for flag in flags] == ORCHESTRATION_FEATURE_FLAG_CODES
    assert len(flags) == len(ORCHESTRATION_FEATURE_FLAG_CODES)


def test_feature_flag_should_serialize_stable_shape():
    flag = OrchestrationFeatureFlag(
        code="ENABLE_ORCHESTRATOR",
        name="Orchestrator",
        description="Enable orchestration router",
        enabled=True,
        risk_level="medium",
        fallback_behavior="direct_answer",
    )

    assert flag.to_dict() == {
        "code": "ENABLE_ORCHESTRATOR",
        "name": "Orchestrator",
        "description": "Enable orchestration router",
        "enabled": True,
        "risk_level": "medium",
        "fallback_behavior": "direct_answer",
    }


def test_default_feature_flags_should_use_safe_defaults():
    flags = {flag.code: flag for flag in get_default_orchestration_feature_flags()}

    assert flags["ENABLE_ORCHESTRATOR"].enabled is True
    assert flags["ENABLE_MULTI_AGENT_EXECUTION"].enabled is True
    assert flags["ENABLE_ROUTING_LOGS"].enabled is True


def test_unknown_feature_flag_should_return_disabled_default():
    flag = get_disabled_orchestration_feature_flag("UNKNOWN_FLAG")

    assert flag.code == "UNKNOWN_FLAG"
    assert flag.enabled is False
    assert flag.risk_level == "unknown"
    assert flag.fallback_behavior == "disabled"
