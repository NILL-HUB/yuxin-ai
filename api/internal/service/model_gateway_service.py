import logging
from injector import inject
from internal.entity.orchestrator_entity import RequestContext, RoutingDecision
from internal.service.language_model_service import LanguageModelService
from internal.service.model_assignment_policy_service import ModelAssignmentPolicy

logger = logging.getLogger(__name__)


@inject
class ModelGatewayService:
    """模型池治理门面，统一模型选择入口。"""
    def __init__(self, language_model_service: LanguageModelService = None, model_assignment_policy: ModelAssignmentPolicy = None):
        self.language_model_service = language_model_service
        self.model_assignment_policy = model_assignment_policy or ModelAssignmentPolicy()

    def resolve_model_tier(self, decision: RoutingDecision, context: RequestContext = None) -> str:
        """根据路由决策和上下文解析推荐模型档位。"""
        try:
            return self.model_assignment_policy.assign(decision, context)
        except Exception:
            logger.warning("模型档位策略解析失败，回退 cheap", exc_info=True)
            return "cheap"

    def get_model(self, decision: RoutingDecision = None, context: RequestContext = None):
        """获取模型实例，优先按档位选择，回退到 cheap 档。"""
        tier = self.resolve_model_tier(decision, context) if decision else "cheap"
        try:
            if self.language_model_service is not None:
                return self.language_model_service.get_cheap_chat_model()
            return LanguageModelService.get_cheap_chat_model()
        except Exception:
            logger.warning("模型实例化失败，回退默认", exc_info=True)
            return LanguageModelService.get_cheap_chat_model()
