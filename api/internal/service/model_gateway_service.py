import logging
from injector import inject
from internal.entity.orchestrator_entity import RequestContext, RoutingDecision
from internal.service.language_model_service import LanguageModelService
from internal.service.model_assignment_policy_service import ModelAssignmentPolicy
from internal.service.runtime_model_pool_service import RuntimeModelPoolService

logger = logging.getLogger(__name__)


@inject
class ModelGatewayService:
    """模型池治理门面，统一模型选择入口。"""
    def __init__(
        self,
        language_model_service: LanguageModelService = None,
        model_assignment_policy: ModelAssignmentPolicy = None,
        runtime_model_pool_service: RuntimeModelPoolService = None,
    ):
        self.language_model_service = language_model_service
        self.model_assignment_policy = model_assignment_policy or ModelAssignmentPolicy()
        self.runtime_model_pool_service = runtime_model_pool_service

    def resolve_model_tier(self, decision: RoutingDecision, context: RequestContext = None) -> str:
        try:
            tier = self.model_assignment_policy.assign(decision, context)
        except Exception:
            logger.warning("模型档位策略解析失败，回退 cheap", exc_info=True)
            return "cheap"
        if self.runtime_model_pool_service is not None:
            try:
                model, _fallbacks = self.runtime_model_pool_service.select_model_with_fallback(tier)
                if model is not None:
                    return getattr(model, "tier", tier) or tier
            except Exception:
                logger.warning("RuntimeModelPool 查询失败，使用策略档位", exc_info=True)
        return tier

    def get_model(self, decision: RoutingDecision = None, context: RequestContext = None):
        tier = self.resolve_model_tier(decision, context) if decision else "cheap"
        try:
            if self.language_model_service is not None:
                return self.language_model_service.get_chat_model_by_tier(tier)
            return LanguageModelService.get_chat_model_by_tier(tier)
        except Exception:
            logger.warning("模型实例化失败，回退默认", exc_info=True)
            return LanguageModelService.get_chat_model_by_tier("cheap")
