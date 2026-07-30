from flask_migrate import Migrate
from injector import Module, Binder, singleton
from internal.extension.database_extension import db
from internal.extension.migrate_extension import migrate
from internal.extension.redis_extension import redis_client
from pkg.sqlalchemy import SQLAlchemy
from redis import Redis
from injector import Injector
from flask_login import LoginManager
from internal.extension.login_extension import login_manager
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
from internal.service.conductor_service import ConductorService
from internal.service.prompt_sync_service import PromptSyncService
from internal.service.orchestration_feature_flag_service import OrchestrationFeatureFlagService
from internal.service.task_classifier_service import TaskClassifierService
from internal.service.execution_mode_selector_service import ExecutionModeSelectorService
from internal.service.request_context_builder_service import RequestContextBuilder
from internal.service.cost_policy_service import CostPolicyService
from internal.service.model_assignment_policy_service import ModelAssignmentPolicy
from internal.service.task_planner_service import TaskPlannerService
from internal.service.pool_intent_resolver_service import PoolIntentResolver
from internal.service.language_model_service import LanguageModelService
from internal.service.public_ai_feature_service import PublicAIFeatureService
from internal.service.rerank_service import RerankService
from internal.service.result_synthesizer_service import ResultSynthesizerService
from internal.service.result_quality_checker_service import ResultQualityCheckerService
from internal.service.model_gateway_service import ModelGatewayService
from internal.service.routing_observability_service import RoutingObservabilityService
from internal.service.routing_log_service import RoutingLogService
from internal.service.routing_event_logger import RoutingEventLogger
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
    ToolInventory,
    ToolPolicyFilter,
    ToolRanker,
)
from internal.service.builtin_tool_service import BuiltinToolService
from internal.service.builtin_tool_sync_service import BuiltinToolSyncService
from internal.service.tool_selector_service import ToolSelectorService
from internal.entity.tool_pool_entity import ToolSubPoolRegistry
from internal.service.runtime_tool_mount_service import RuntimeToolMountService
from internal.service.composite_tool_resolver import CompositeToolResolver
from internal.service.conversation_variable_service import ConversationVariableService
from internal.service.runtime_tool_governance_gate import RuntimeToolGovernanceGate
from internal.service.governance_mode_resolver import GovernanceModeResolver
from internal.service.governance_audit_logger import GovernanceAuditLogger
from internal.service.credit_service import CreditService

# 记忆系统服务
from internal.service.memory.entity_extractor import MemoryEntityExtractor
from internal.service.memory.entity_resolution import EntityResolver
from internal.service.memory.ledger_writer import LedgerWriter
from internal.service.memory.memory_write_service import MemoryWriteService
from internal.service.memory.salience_scorer import SalienceScorer
from internal.service.memory.explicit_detector import ExplicitStatementDetector
from internal.service.memory.write_time_conflict_resolver import WriteTimeConflictResolver
from internal.service.memory.digest_manager import DigestManager
from internal.service.memory.policy_router import PolicyRouter
from internal.service.memory.memory_governor import MemoryGovernor
from internal.service.memory.degradation_manager import DegradationManager
from internal.service.memory.skill_emergence import SkillEmergence


class ExtensionModule(Module):
    """扩展模块的依赖注入"""

    def configure(self, binder: Binder) -> None:
        binder.bind(SQLAlchemy, to=db, scope=singleton)
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
        binder.bind(PublicAIFeatureService, to=PublicAIFeatureService, scope=singleton)
        binder.bind(RerankService, to=RerankService, scope=singleton)

        # 注册端口绑定（反转 core→service 反向依赖）
        # 根据 STORAGE_BACKEND 环境变量动态选择存储后端实现
        from internal.service.storage.factory import get_storage_service_class
        storage_service_class = get_storage_service_class()
        binder.bind(ObjectStoragePort, to=storage_service_class)
        # 同时绑定 CosService 到当前后端，兼容现有注入 CosService 的代码
        binder.bind(CosService, to=storage_service_class)

        # 注册编排子系统依赖（激活主调度链）
        binder.bind(OrchestrationFeatureFlagService, to=OrchestrationFeatureFlagService)
        binder.bind(RoutingLogService, to=RoutingLogService)
        binder.bind(RoutingEventLogger, to=RoutingEventLogger)
        binder.bind(TaskClassifierService, to=TaskClassifierService)
        binder.bind(ExecutionModeSelectorService, to=ExecutionModeSelectorService)
        binder.bind(RequestContextBuilder, to=RequestContextBuilder)
        binder.bind(CostPolicyService, to=CostPolicyService)
        binder.bind(ModelAssignmentPolicy, to=ModelAssignmentPolicy)
        binder.bind(TaskPlannerService, to=TaskPlannerService)
        binder.bind(PoolIntentResolver, to=PoolIntentResolver)
        binder.bind(OrchestratorService, to=OrchestratorService)
        binder.bind(ConductorService, to=ConductorService)
        binder.bind(PromptSyncService, to=PromptSyncService)

        # 注册结果汇总层依赖（激活 L7 结果合成与质量检查）
        binder.bind(ResultQualityCheckerService, to=ResultQualityCheckerService)
        binder.bind(ResultSynthesizerService, to=ResultSynthesizerService)

        # 注册模型池治理层（激活 L5 ModelGateway 门面）
        binder.bind(ModelGatewayService, to=ModelGatewayService)

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
        binder.bind(ToolSubPoolRegistry, to=ToolSubPoolRegistry)
        binder.bind(ToolInventory, to=ToolInventory)
        binder.bind(ToolCandidateCollector, to=ToolCandidateCollector)
        binder.bind(ToolPolicyFilter, to=ToolPolicyFilter)
        binder.bind(ToolRanker, to=ToolRanker)
        binder.bind(CrossPoolToolSubsetBuilder, to=CrossPoolToolSubsetBuilder)
        binder.bind(RuntimeToolMountService, to=RuntimeToolMountService)
        # 注册 LLM 工具选择器（替代硬编码关键词映射，实现语义化工具选择）
        binder.bind(ToolSelectorService, to=ToolSelectorService)

        # 注册 builtin 工具 YAML→DB 同步服务（启动时调用，admin 后台元数据编辑依赖）
        binder.bind(BuiltinToolSyncService, to=BuiltinToolSyncService, scope=singleton)

        # 注册工具治理门依赖（激活 P0-4 池治理与运行时打通）
        binder.bind(CompositeToolResolver, to=CompositeToolResolver)
        binder.bind(RuntimeToolGovernanceGate, to=RuntimeToolGovernanceGate)

        # 注册池治理模式解析器（激活 P1-2 渐进式启用开关）
        binder.bind(GovernanceModeResolver, to=GovernanceModeResolver)

        # 注册治理审计日志器（激活阶段1渐进式启用观测期：路由日志中工具治理决策覆盖率 ≥ 95%）
        binder.bind(GovernanceAuditLogger, to=GovernanceAuditLogger)

        # 注册额度计费服务（支持消息上下文与非消息上下文扣费）
        binder.bind(CreditService, to=CreditService, scope=singleton)

        # 注册会话变量服务（Plan D-3 ConversationVariable CRUD）
        binder.bind(ConversationVariableService, to=ConversationVariableService)

        # 注册记忆系统服务（Track A 写入路径）
        binder.bind(SalienceScorer, to=SalienceScorer, scope=singleton)
        binder.bind(LedgerWriter, to=LedgerWriter, scope=singleton)
        binder.bind(EntityResolver, to=EntityResolver, scope=singleton)
        binder.bind(MemoryEntityExtractor, to=MemoryEntityExtractor, scope=singleton)
        binder.bind(ExplicitStatementDetector, to=ExplicitStatementDetector, scope=singleton)
        binder.bind(WriteTimeConflictResolver, to=WriteTimeConflictResolver, scope=singleton)
        binder.bind(MemoryWriteService, to=MemoryWriteService, scope=singleton)

        # 注册记忆系统服务（Track B/C 检索与巩固路径）
        binder.bind(DigestManager, to=DigestManager, scope=singleton)

        # 注册记忆系统服务（Track D/E 策略治理与技能池）
        binder.bind(PolicyRouter, to=PolicyRouter, scope=singleton)
        binder.bind(MemoryGovernor, to=MemoryGovernor, scope=singleton)
        binder.bind(DegradationManager, to=DegradationManager, scope=singleton)
        binder.bind(SkillEmergence, to=SkillEmergence, scope=singleton)

injector = Injector([ExtensionModule])
