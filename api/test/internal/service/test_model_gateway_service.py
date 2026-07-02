from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from internal.entity.orchestrator_entity import RequestContext, RoutingDecision
from internal.service.model_gateway_service import ModelGatewayService


def _build_decision() -> RoutingDecision:
    return RoutingDecision(
        intent="chat",
        complexity="medium",
        execution_mode="single_agent",
    )


def _build_context() -> RequestContext:
    return RequestContext(query="hello")


def test_resolve_model_tier_should_return_policy_result_on_success():
    policy = MagicMock()
    policy.assign.return_value = "strong"
    gateway = ModelGatewayService(model_assignment_policy=policy)

    tier = gateway.resolve_model_tier(_build_decision(), _build_context())

    assert tier == "strong"
    policy.assign.assert_called_once()


def test_resolve_model_tier_should_fallback_to_cheap_when_policy_raises():
    policy = MagicMock()
    policy.assign.side_effect = RuntimeError("boom")
    gateway = ModelGatewayService(model_assignment_policy=policy)

    tier = gateway.resolve_model_tier(_build_decision(), None)

    assert tier == "cheap"
    policy.assign.assert_called_once()


def test_get_model_should_return_model_instance_on_success():
    fake_model = MagicMock(name="chat_model")
    language_model_service = MagicMock()
    language_model_service.get_chat_model_by_tier.return_value = fake_model
    policy = MagicMock()
    policy.assign.return_value = "standard"
    gateway = ModelGatewayService(
        language_model_service=language_model_service,
        model_assignment_policy=policy,
    )

    model = gateway.get_model(_build_decision(), _build_context())

    assert model is fake_model
    language_model_service.get_chat_model_by_tier.assert_called_once_with("standard")


def test_get_model_should_work_when_decision_is_none():
    fake_model = MagicMock(name="chat_model")
    language_model_service = MagicMock()
    language_model_service.get_chat_model_by_tier.return_value = fake_model
    policy = MagicMock()
    gateway = ModelGatewayService(
        language_model_service=language_model_service,
        model_assignment_policy=policy,
    )

    model = gateway.get_model(decision=None, context=None)

    assert model is fake_model
    policy.assign.assert_not_called()
    language_model_service.get_chat_model_by_tier.assert_called_once_with("cheap")
