from flask_migrate import Migrate
from injector import Module, Binder, singleton
from internal.extension.database_extension import db
from internal.extension.migrate_extension import migrate
from flask_weaviate import FlaskWeaviate
from internal.extension.redis_extension import redis_client
from pkg.sqlalchemy import SQLAlchemy
from redis import Redis
from injector import Injector
from flask_login import LoginManager
from internal.extension.login_extension import login_manager
from internal.extension.weaviate_extension import weaviate
from internal.extension.mail_extension import mail
from flask_mail import Mail
from internal.core.language_model import LanguageModelManager
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from internal.core.tools.api_tools.providers import ApiProviderManager
from internal.core.tools.mcp_tools.providers import McpProviderManager
from internal.service.embeddings_service import EmbeddingsService
from internal.service.faiss_service import FaissService
from internal.service.notification_service import NotificationService
from internal.service.cos_service import CosService
from internal.core.ports.storage_port import ObjectStoragePort
from internal.service.orchestrator_service import OrchestratorService
from internal.service.task_classifier_service import TaskClassifierService
from internal.service.execution_mode_selector_service import ExecutionModeSelectorService
from internal.service.request_context_builder_service import RequestContextBuilder
from internal.service.cost_policy_service import CostPolicyService
from internal.service.model_assignment_policy_service import ModelAssignmentPolicy
from internal.service.task_planner_service import TaskPlannerService
from internal.service.pool_intent_resolver_service import PoolIntentResolver
from internal.service.language_model_service import LanguageModelService
from internal.service.rerank_service import RerankService
from internal.service.result_synthesizer_service import ResultSynthesizerService
from internal.service.result_quality_checker_service import ResultQualityCheckerService
from internal.service.model_gateway_service import ModelGatewayService
from internal.service.model_pool_service import ModelPoolService
from internal.service.key_pool_service import KeyPoolService
from internal.service.routing_observability_service import RoutingObservabilityService
from internal.service.agent_pool_service import (
    CrossPoolAgentSubsetBuilder,
    AgentCandidateCollector,
    AgentPolicyFilter,
    AgentRanker,
)
from internal.service.agent_pool_aggregate_service import (
    AgentPoolService,
    AgentInventory,
)
from internal.service.tool_inventory_service import (
    CrossPoolToolSubsetBuilder,
    ToolCandidateCollector,
    ToolPolicyFilter,
    ToolRanker,
)
from internal.service.runtime_tool_mount_service import RuntimeToolMountService


class ExtensionModule(Module):
    """扩展模块的依赖注入"""

    def configure(self, binder: Binder) -> None:
        binder.bind(SQLAlchemy, to=db, scope=singleton)
        binder.bind(FlaskWeaviate, to=weaviate, scope=singleton)
        binder.bind(Migrate, to=migrate, scope=singleton)
        binder.bind(Redis, to=redis_client, scope=singleton)
        binder.bind(LoginManager, to=login_manager, scope=singleton)
        binder.bind(Mail, to=mail, scope=singleton)

        # 注册核心管理器类为单例
        binder.bind(LanguageModelManager, to=LanguageModelManager, scope=singleton)
        binder.bind(BuiltinProviderManager, to=BuiltinProviderManager, scope=singleton)
        binder.bind(ApiProviderManager, to=ApiProviderManager, scope=singleton)
        binder.bind(McpProviderManager, to=McpProviderManager, scope=singleton)

        # 注册服务类为单例
        binder.bind(EmbeddingsService, to=EmbeddingsService, scope=singleton)
        binder.bind(FaissService, to=FaissService, scope=singleton)
        binder.bind(NotificationService, to=NotificationService, scope=singleton)
        binder.bind(LanguageModelService, to=LanguageModelService, scope=singleton)
        binder.bind(RerankService, to=RerankService, scope=singleton)

        # 注册端口绑定（反转 core→service 反向依赖）
        binder.bind(ObjectStoragePort, to=CosService)

        # 注册编排子系统依赖（激活主调度链）
        binder.bind(TaskClassifierService, to=TaskClassifierService)
        binder.bind(ExecutionModeSelectorService, to=ExecutionModeSelectorService)
        binder.bind(RequestContextBuilder, to=RequestContextBuilder)
        binder.bind(CostPolicyService, to=CostPolicyService)
        binder.bind(ModelAssignmentPolicy, to=ModelAssignmentPolicy)
        binder.bind(TaskPlannerService, to=TaskPlannerService)
        binder.bind(PoolIntentResolver, to=PoolIntentResolver)
        binder.bind(OrchestratorService, to=OrchestratorService)

        # 注册结果汇总层依赖（激活 L7 结果合成与质量检查）
        binder.bind(ResultQualityCheckerService, to=ResultQualityCheckerService)
        binder.bind(ResultSynthesizerService, to=ResultSynthesizerService)

        # 注册模型池治理层（激活 L5 ModelGateway 门面）
        binder.bind(ModelGatewayService, to=ModelGatewayService)
        binder.bind(ModelPoolService, to=ModelPoolService)
        binder.bind(KeyPoolService, to=KeyPoolService)

        # 注册可观测层依赖（激活 L8 路由可观测）
        binder.bind(RoutingObservabilityService, to=RoutingObservabilityService)

        # 注册 Agent 池治理层依赖（激活 L3 子集构建器）
        binder.bind(AgentCandidateCollector, to=AgentCandidateCollector)
        binder.bind(AgentPolicyFilter, to=AgentPolicyFilter)
        binder.bind(AgentRanker, to=AgentRanker)
        binder.bind(CrossPoolAgentSubsetBuilder, to=CrossPoolAgentSubsetBuilder)

        binder.bind(AgentInventory, to=AgentInventory)
        binder.bind(AgentPoolService, to=AgentPoolService)

        # 注册工具池治理层依赖（激活 L4 子集构建器）
        binder.bind(ToolCandidateCollector, to=ToolCandidateCollector)
        binder.bind(ToolPolicyFilter, to=ToolPolicyFilter)
        binder.bind(ToolRanker, to=ToolRanker)
        binder.bind(CrossPoolToolSubsetBuilder, to=CrossPoolToolSubsetBuilder)
        binder.bind(RuntimeToolMountService, to=RuntimeToolMountService)

injector = Injector([ExtensionModule])
