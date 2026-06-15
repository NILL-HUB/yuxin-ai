import logging
from dataclasses import dataclass

from injector import inject

from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel, RoutingDecision
from .task_classifier_service import TaskClassifierService


@inject
@dataclass
class OrchestratorService:
    task_classifier_service: TaskClassifierService

    def decide(self, query: str, **context) -> RoutingDecision:
        try:
            return self.task_classifier_service.classify(query)
        except Exception as exc:
            logging.warning("调度决策失败，回退到原 Assistant Agent 流程: %s", exc)
            return RoutingDecision(
                intent="fallback",
                complexity="unknown",
                execution_mode=ExecutionMode.SINGLE_AGENT.value,
                needs_tools=True,
                needs_agent=True,
                needs_multi_agent=False,
                recommended_model_tier="balanced",
                risk_level=RiskLevel.UNKNOWN.value,
                reason="调度决策失败，已回退到原 Assistant Agent 流程",
            )
