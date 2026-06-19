import logging
from injector import inject
from internal.entity.orchestrator_entity import RequestContext, RoutingDecision
from internal.service.language_model_service import LanguageModelService
from internal.service.model_assignment_policy_service import ModelAssignmentPolicy
from internal.service.model_pool_service import ModelPoolService
from internal.service.key_pool_service import KeyPoolService

logger = logging.getLogger(__name__)


@inject
class ModelGatewayService:
    """模型池治理门面，统一模型选择入口。"""
    def __init__(
        self,
        language_model_service: LanguageModelService = None,
        model_assignment_policy: ModelAssignmentPolicy = None,
        model_pool_service: ModelPoolService = None,
        key_pool_service: KeyPoolService = None,
    ):
        self.language_model_service = language_model_service
        self.model_assignment_policy = model_assignment_policy or ModelAssignmentPolicy()
        self.model_pool_service = model_pool_service
        self.key_pool_service = key_pool_service

    def resolve_model_tier(self, decision: RoutingDecision, context: RequestContext = None) -> str:
        try:
            tier = self.model_assignment_policy.assign(decision, context)
        except Exception:
            logger.warning("模型档位策略解析失败，回退 cheap", exc_info=True)
            return "cheap"
        if self.model_pool_service is not None:
            try:
                selected = self.model_pool_service.select_model(
                    required_capabilities=getattr(decision, "required_capabilities", []) or [],
                    preferred_tier=tier,
                )
                if selected is not None:
                    return getattr(selected, "tier", tier)
            except Exception:
                logger.warning("ModelPool 档位校验失败，使用策略档位", exc_info=True)
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

    def select_key(self, provider: str):
        if self.key_pool_service is None:
            return None
        try:
            return self.key_pool_service.select_key(provider)
        except Exception:
            logger.warning("Key 池选择失败", exc_info=True)
            return None
