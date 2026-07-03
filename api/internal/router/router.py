from dataclasses import dataclass
from flask import Flask, Blueprint
from injector import inject

from internal.handler import (
    AppHandler,
    BuiltinToolHandler,
    ApiToolHandler,
    UploadFileHandler,
    DatasetHandler,
    DocumentHandler,
    SegmentHandler,
    OAuthHandler,
    AccountHandler,
    AuthHandler,
    AdminAgentPoolHandler,
    AdminAppHandler,
    AdminAppAssignmentHandler,
    AdminApiToolHandler,
    AdminAuditLogHandler,
    AdminAuthHandler,
    AdminBillingPlanHandler,
    AdminDatasetHandler,
    AdminOrchestrationFlagHandler,
    AdminOrchestrationReleaseHandler,
    AdminModelPoolHandler,
    AdminCostStatsHandler,
    AdminCustomerUserHandler,
    AdminMcpHandler,
    AdminRbacHandler,
    AdminRedeemCodeHandler,
    AdminResourceEntryHandler,
    AdminRoutingLogHandler,
    AdminSubPoolHandler,
    RoutingLogHandler,
    AdminRoutingQualityHandler,
    AdminSystemKnowledgeHandler,
    AdminToolGovernanceHandler,
    AdminUserHandler,
    AdminWorkflowHandler,
    AIHandler,
    ApiKeyHandler,
    OpenAPIHandler,
    WorkflowHandler,
    LanguageModelHandler,
    AssistantAgentHandler,
    AnalysisHandler,
    WebAppHandler,
    ConversationHandler,
    AudioHandler,
    PlatformHandler,
    WechatHandler,
    PublicAppHandler,
    PublicWorkflowHandler,
    RedeemCodeHandler,
    ShowcaseHandler,
    McpHandler,
    MemoryCandidateHandler,
    ExternalDataSourceHandler,
    ToolConfirmationHandler,
    ToolInventoryHandler,
    MyAppHandler,
    SkillHandler,
    HomeHandler,
    NotificationHandler,
    TagHandler,
    UserMemoryHandler,
)


@inject
@dataclass
class Router:
    """路由"""
    app_handler: AppHandler
    builtin_tool_handler: BuiltinToolHandler
    api_tool_handler: ApiToolHandler
    upload_file_handler: UploadFileHandler
    dataset_handler: DatasetHandler
    document_handler: DocumentHandler
    segment_handler: SegmentHandler
    oauth_handler: OAuthHandler
    account_handler: AccountHandler
    auth_handler: AuthHandler
    admin_agent_pool_handler: AdminAgentPoolHandler
    admin_sub_pool_handler: AdminSubPoolHandler
    admin_app_handler: AdminAppHandler
    admin_app_assignment_handler: AdminAppAssignmentHandler
    admin_api_tool_handler: AdminApiToolHandler
    admin_audit_log_handler: AdminAuditLogHandler
    admin_auth_handler: AdminAuthHandler
    admin_billing_plan_handler: AdminBillingPlanHandler
    admin_dataset_handler: AdminDatasetHandler
    admin_orchestration_flag_handler: AdminOrchestrationFlagHandler
    admin_orchestration_release_handler: AdminOrchestrationReleaseHandler
    admin_customer_user_handler: AdminCustomerUserHandler
    admin_mcp_handler: AdminMcpHandler
    admin_rbac_handler: AdminRbacHandler
    admin_redeem_code_handler: AdminRedeemCodeHandler
    admin_resource_entry_handler: AdminResourceEntryHandler
    admin_routing_log_handler: AdminRoutingLogHandler
    admin_routing_quality_handler: AdminRoutingQualityHandler
    routing_log_handler: RoutingLogHandler
    admin_system_knowledge_handler: AdminSystemKnowledgeHandler
    admin_tool_governance_handler: AdminToolGovernanceHandler
    admin_user_handler: AdminUserHandler
    admin_workflow_handler: AdminWorkflowHandler
    admin_model_pool_handler: AdminModelPoolHandler
    admin_cost_stats_handler: AdminCostStatsHandler
    ai_handler: AIHandler
    api_key_handler: ApiKeyHandler
    openapi_handler: OpenAPIHandler
    workflow_handler: WorkflowHandler
    language_model_handler: LanguageModelHandler
    assistant_agent_handler: AssistantAgentHandler
    analysis_handler: AnalysisHandler
    web_app_handler: WebAppHandler
    conversation_handler: ConversationHandler
    audio_handler: AudioHandler
    platform_handler: PlatformHandler
    wechat_handler: WechatHandler
    public_app_handler: PublicAppHandler
    public_workflow_handler: PublicWorkflowHandler
    redeem_code_handler: RedeemCodeHandler
    mcp_handler: McpHandler
    memory_candidate_handler: MemoryCandidateHandler
    external_data_source_handler: ExternalDataSourceHandler
    tool_confirmation_handler: ToolConfirmationHandler
    tool_inventory_handler: ToolInventoryHandler
    my_app_handler: MyAppHandler
    user_memory_handler: UserMemoryHandler
    skill_handler: SkillHandler
    home_handler: HomeHandler
    notification_handler: NotificationHandler
    tag_handler: TagHandler
    showcase_handler: ShowcaseHandler

    def register_router(self, app: Flask):
        """注册路由"""
        # 1.创建一个蓝图
        bp = Blueprint("llmops", __name__, url_prefix="")
        openapi_bp = Blueprint("openapi", __name__, url_prefix="")

        # 2.将url与对应的控制器方法做绑定
        bp.add_url_rule("/health", view_func=self.app_handler.health)
        bp.add_url_rule("/healthz", view_func=self.app_handler.healthz)
        bp.add_url_rule("/ping", view_func=self.app_handler.ping)
        bp.add_url_rule("/apps", view_func=self.app_handler.get_apps_with_page)
        bp.add_url_rule("/apps", methods=["POST"], view_func=self.app_handler.create_app)
        bp.add_url_rule("/apps/<uuid:app_id>", view_func=self.app_handler.get_app)
        bp.add_url_rule("/apps/<uuid:app_id>", methods=["POST"], view_func=self.app_handler.update_app)
        bp.add_url_rule("/apps/<uuid:app_id>/delete", methods=["POST"], view_func=self.app_handler.delete_app)
        bp.add_url_rule("/apps/<uuid:app_id>/copy", methods=["POST"], view_func=self.app_handler.copy_app)
        bp.add_url_rule("/apps/<uuid:app_id>/draft-app-config", view_func=self.app_handler.get_draft_app_config)
        bp.add_url_rule(
            "/apps/<uuid:app_id>/draft-app-config",
            methods=["POST"],
            view_func=self.app_handler.update_draft_app_config,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/publish",
            methods=["POST"],
            view_func=self.app_handler.publish,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/cancel-publish",
            methods=["POST"],
            view_func=self.app_handler.cancel_publish,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/publish-histories",
            view_func=self.app_handler.get_publish_histories_with_page,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/versions",
            view_func=self.app_handler.get_versions,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/fallback-history",
            methods=["POST"],
            view_func=self.app_handler.fallback_history_to_draft,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/summary",
            view_func=self.app_handler.get_debug_conversation_summary,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/summary",
            methods=["POST"],
            view_func=self.app_handler.update_debug_conversation_summary,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/conversations/delete-debug-conversation",
            methods=["POST"],
            view_func=self.app_handler.delete_debug_conversation,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/conversations",
            methods=["POST"],
            view_func=self.app_handler.debug_chat,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/prompt-compare/chat",
            methods=["POST"],
            view_func=self.app_handler.prompt_compare_chat,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/conversations/tasks/<uuid:task_id>/stop",
            methods=["POST"],
            view_func=self.app_handler.stop_debug_chat,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/prompt-compare/tasks/<uuid:task_id>/stop",
            methods=["POST"],
            view_func=self.app_handler.stop_prompt_compare_chat,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/conversations/messages",
            view_func=self.app_handler.get_debug_conversation_messages_with_page,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/published-config",
            view_func=self.app_handler.get_published_config,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/published-config/regenerate-web-app-token",
            methods=["POST"],
            view_func=self.app_handler.regenerate_web_app_token,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/regenerate-icon",
            methods=["POST"],
            view_func=self.app_handler.regenerate_icon,
            endpoint="app_regenerate_icon",
        )
        bp.add_url_rule(
            "/apps/generate-icon-preview",
            methods=["POST"],
            view_func=self.app_handler.generate_icon_preview,
            endpoint="app_generate_icon_preview",
        )

        # 3.内置插件广场模块
        bp.add_url_rule("/builtin-tools", view_func=self.builtin_tool_handler.get_builtin_tools)
        bp.add_url_rule(
            "/builtin-tools/<string:provider_name>/tools/<string:tool_name>",
            view_func=self.builtin_tool_handler.get_provider_tool,
        )
        bp.add_url_rule(
            "/builtin-tools/<string:provider_name>/icon",
            view_func=self.builtin_tool_handler.get_provider_icon,
        )
        bp.add_url_rule(
            "/builtin-tools/categories",
            view_func=self.builtin_tool_handler.get_categories,
        )
        bp.add_url_rule(
            "/tool-inventory",
            view_func=self.tool_inventory_handler.get_tool_inventory,
        )

        # 3.1技能包广场模块
        bp.add_url_rule("/skills/categories", view_func=self.skill_handler.get_skill_categories)
        bp.add_url_rule("/skills", view_func=self.skill_handler.get_skills_with_page)
        bp.add_url_rule("/skills/<uuid:skill_id>", view_func=self.skill_handler.get_skill_package)
        bp.add_url_rule("/skills/<uuid:skill_id>/icon", view_func=self.skill_handler.get_skill_package_icon)
        bp.add_url_rule("/skills/<uuid:skill_id>/versions", view_func=self.skill_handler.get_skill_package_versions)
        bp.add_url_rule(
            "/skills/<uuid:skill_id>/enable",
            methods=["POST"],
            view_func=self.skill_handler.enable_skill_package,
        )
        bp.add_url_rule(
            "/skills/<uuid:skill_id>/disable",
            methods=["POST"],
            view_func=self.skill_handler.disable_skill_package,
        )
        bp.add_url_rule(
            "/skills/<uuid:skill_id>/sync",
            methods=["POST"],
            view_func=self.skill_handler.sync_skill_package,
        )
        bp.add_url_rule(
            "/skills/<uuid:skill_id>/rollback",
            methods=["POST"],
            view_func=self.skill_handler.rollback_skill_package,
        )

        # 4.自定义API插件模块
        bp.add_url_rule(
            "/api-tools",
            view_func=self.api_tool_handler.get_api_tool_providers_with_page,
        )
        bp.add_url_rule(
            "/api-tools/validate-openapi-schema",
            methods=["POST"],
            view_func=self.api_tool_handler.validate_openapi_schema,
        )
        bp.add_url_rule(
            "/api-tools",
            methods=["POST"],
            view_func=self.api_tool_handler.create_api_tool_provider,
        )
        bp.add_url_rule(
            "/api-tools/<uuid:provider_id>",
            view_func=self.api_tool_handler.get_api_tool_provider,
        )
        bp.add_url_rule(
            "/api-tools/<uuid:provider_id>",
            methods=["POST"],
            view_func=self.api_tool_handler.update_api_tool_provider,
        )
        bp.add_url_rule(
            "/api-tools/<uuid:provider_id>/tools/<string:tool_name>",
            view_func=self.api_tool_handler.get_api_tool,
        )
        bp.add_url_rule(
            "/api-tools/<uuid:provider_id>/delete",
            methods=["POST"],
            view_func=self.api_tool_handler.delete_api_tool_provider,
        )
        bp.add_url_rule(
            "/api-tools/<uuid:provider_id>/regenerate-icon",
            methods=["POST"],
            view_func=self.api_tool_handler.regenerate_icon,
            endpoint="api_tool_regenerate_icon",
        )
        bp.add_url_rule(
            "/api-tools/generate-icon-preview",
            methods=["POST"],
            view_func=self.api_tool_handler.generate_icon_preview,
            endpoint="api_tool_generate_icon_preview",
        )

        # 4.上传文件模块
        bp.add_url_rule("/upload-files/file", methods=["POST"], view_func=self.upload_file_handler.upload_file)
        bp.add_url_rule("/upload-files/image", methods=["POST"], view_func=self.upload_file_handler.upload_image)

        # 5.知识库模块
        bp.add_url_rule("/datasets", view_func=self.dataset_handler.get_datasets_with_page)
        bp.add_url_rule("/datasets", methods=["POST"], view_func=self.dataset_handler.create_dataset)
        bp.add_url_rule("/datasets/<uuid:dataset_id>", view_func=self.dataset_handler.get_dataset)
        bp.add_url_rule("/datasets/<uuid:dataset_id>", methods=["POST"], view_func=self.dataset_handler.update_dataset)
        bp.add_url_rule("/datasets/<uuid:dataset_id>/queries", view_func=self.dataset_handler.get_dataset_queries)
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/delete",
            methods=["POST"],
            view_func=self.dataset_handler.delete_dataset,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents",
            view_func=self.document_handler.get_documents_with_page,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents",
            methods=["POST"],
            view_func=self.document_handler.create_documents,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/<uuid:document_id>",
            view_func=self.document_handler.get_document,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/<uuid:document_id>/name",
            methods=["POST"],
            view_func=self.document_handler.update_document_name,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/<uuid:document_id>/enabled",
            methods=["POST"],
            view_func=self.document_handler.update_document_enabled,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/<uuid:document_id>/delete",
            methods=["POST"],
            view_func=self.document_handler.delete_document,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/batch/<string:batch>",
            view_func=self.document_handler.get_documents_status,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/<uuid:document_id>/segments",
            view_func=self.segment_handler.get_segments_with_page,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/<uuid:document_id>/segments",
            methods=["POST"],
            view_func=self.segment_handler.create_segment,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/<uuid:document_id>/segments/<uuid:segment_id>",
            view_func=self.segment_handler.get_segment,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/<uuid:document_id>/segments/<uuid:segment_id>",
            methods=["POST"],
            view_func=self.segment_handler.update_segment,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/<uuid:document_id>/segments/<uuid:segment_id>/enabled",
            methods=["POST"],
            view_func=self.segment_handler.update_segment_enabled,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/documents/<uuid:document_id>/segments/<uuid:segment_id>/delete",
            methods=["POST"],
            view_func=self.segment_handler.delete_segment,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/hit",
            methods=["POST"],
            view_func=self.dataset_handler.hit,
        )
        bp.add_url_rule(
            "/datasets/<uuid:dataset_id>/regenerate-icon",
            methods=["POST"],
            view_func=self.dataset_handler.regenerate_icon,
            endpoint="dataset_regenerate_icon",
        )
        bp.add_url_rule(
            "/datasets/generate-icon-preview",
            methods=["POST"],
            view_func=self.dataset_handler.generate_icon_preview,
            endpoint="dataset_generate_icon_preview",
        )

        # 6.授权认证模块
        bp.add_url_rule(
            "/oauth/<string:provider_name>",
            view_func=self.oauth_handler.provider,
        )
        bp.add_url_rule(
            "/oauth/authorize/<string:provider_name>",
            methods=["POST"],
            view_func=self.oauth_handler.authorize,
        )
        bp.add_url_rule(
            "/auth/password-login",
            methods=["POST"],
            view_func=self.auth_handler.password_login,
        )
        bp.add_url_rule(
            "/admin/auth/login",
            endpoint="admin_auth_login",
            methods=["POST"],
            view_func=self.admin_auth_handler.login,
        )
        bp.add_url_rule(
            "/admin/auth/me",
            endpoint="admin_auth_me",
            methods=["GET"],
            view_func=self.admin_auth_handler.me,
        )
        bp.add_url_rule(
            "/admin/auth/logout",
            endpoint="admin_auth_logout",
            methods=["POST"],
            view_func=self.admin_auth_handler.logout,
        )
        bp.add_url_rule(
            "/admin/auth/password",
            endpoint="admin_auth_change_password",
            methods=["POST"],
            view_func=self.admin_auth_handler.change_password,
        )
        bp.add_url_rule(
            "/admin/admin-users",
            endpoint="admin_user_list",
            methods=["GET"],
            view_func=self.admin_user_handler.list,
        )
        bp.add_url_rule(
            "/admin/admin-users",
            endpoint="admin_user_create",
            methods=["POST"],
            view_func=self.admin_user_handler.create,
        )
        bp.add_url_rule(
            "/admin/admin-users/<uuid:admin_id>",
            endpoint="admin_user_get",
            methods=["GET"],
            view_func=self.admin_user_handler.get,
        )
        bp.add_url_rule(
            "/admin/admin-users/<uuid:admin_id>",
            endpoint="admin_user_update",
            methods=["PATCH"],
            view_func=self.admin_user_handler.update,
        )
        bp.add_url_rule(
            "/admin/admin-users/<uuid:admin_id>/disable",
            endpoint="admin_user_disable",
            methods=["POST"],
            view_func=self.admin_user_handler.disable,
        )
        bp.add_url_rule(
            "/admin/users",
            endpoint="admin_customer_user_list",
            methods=["GET"],
            view_func=self.admin_customer_user_handler.list,
        )
        bp.add_url_rule(
            "/admin/users/<uuid:account_id>",
            endpoint="admin_customer_user_get",
            methods=["GET"],
            view_func=self.admin_customer_user_handler.get,
        )
        bp.add_url_rule(
            "/admin/users/<uuid:account_id>/disable",
            endpoint="admin_customer_user_disable",
            methods=["POST"],
            view_func=self.admin_customer_user_handler.disable,
        )
        bp.add_url_rule(
            "/admin/users/<uuid:account_id>/enable",
            endpoint="admin_customer_user_enable",
            methods=["POST"],
            view_func=self.admin_customer_user_handler.enable,
        )
        bp.add_url_rule(
            "/admin/users/<uuid:account_id>/sessions/revoke",
            endpoint="admin_customer_user_revoke_sessions",
            methods=["POST"],
            view_func=self.admin_customer_user_handler.revoke_sessions,
        )
        bp.add_url_rule(
            "/admin/users/<uuid:account_id>/app-assignments",
            endpoint="admin_app_assignment_list",
            methods=["GET"],
            view_func=self.admin_app_assignment_handler.list_assignments,
        )
        bp.add_url_rule(
            "/admin/users/<uuid:account_id>/app-assignments",
            endpoint="admin_app_assignment_assign",
            methods=["POST"],
            view_func=self.admin_app_assignment_handler.assign_apps,
        )
        bp.add_url_rule(
            "/admin/users/<uuid:account_id>/app-assignments/<uuid:assignment_id>/revoke",
            endpoint="admin_app_assignment_revoke",
            methods=["POST"],
            view_func=self.admin_app_assignment_handler.revoke_assignment,
        )
        bp.add_url_rule(
            "/admin/roles",
            endpoint="admin_role_list",
            methods=["GET"],
            view_func=self.admin_rbac_handler.list_roles,
        )
        bp.add_url_rule(
            "/admin/roles",
            endpoint="admin_role_create",
            methods=["POST"],
            view_func=self.admin_rbac_handler.create_role,
        )
        bp.add_url_rule(
            "/admin/roles/<uuid:role_id>",
            endpoint="admin_role_get",
            methods=["GET"],
            view_func=self.admin_rbac_handler.get_role,
        )
        bp.add_url_rule(
            "/admin/roles/<uuid:role_id>",
            endpoint="admin_role_update",
            methods=["PATCH"],
            view_func=self.admin_rbac_handler.update_role,
        )
        bp.add_url_rule(
            "/admin/roles/<uuid:role_id>",
            endpoint="admin_role_delete",
            methods=["DELETE"],
            view_func=self.admin_rbac_handler.delete_role,
        )
        bp.add_url_rule(
            "/admin/permissions",
            endpoint="admin_permission_list",
            methods=["GET"],
            view_func=self.admin_rbac_handler.list_permissions,
        )
        bp.add_url_rule(
            "/admin/audit-logs",
            endpoint="admin_audit_log_list",
            methods=["GET"],
            view_func=self.admin_audit_log_handler.list,
        )
        bp.add_url_rule(
            "/admin/routing-logs",
            endpoint="admin_routing_log_list",
            methods=["GET"],
            view_func=self.admin_routing_log_handler.list,
        )
        bp.add_url_rule(
            "/admin/routing-logs/retention",
            endpoint="admin_routing_log_retention_get",
            methods=["GET"],
            view_func=self.admin_routing_log_handler.get_retention,
        )
        bp.add_url_rule(
            "/admin/routing-logs/retention",
            endpoint="admin_routing_log_retention_set",
            methods=["POST"],
            view_func=self.admin_routing_log_handler.set_retention,
        )
        bp.add_url_rule(
            "/admin/orchestration-flags",
            endpoint="admin_orchestration_flag_list",
            methods=["GET"],
            view_func=self.admin_orchestration_flag_handler.list,
        )
        bp.add_url_rule(
            "/admin/orchestration-flags/<string:code>",
            endpoint="admin_orchestration_flag_update",
            methods=["POST"],
            view_func=self.admin_orchestration_flag_handler.update,
        )
        bp.add_url_rule(
            "/admin/orchestration-release-check",
            endpoint="admin_orchestration_release_check",
            methods=["GET"],
            view_func=self.admin_orchestration_release_handler.get,
        )
        bp.add_url_rule(
            "/admin/routing-quality/feedback",
            endpoint="admin_routing_quality_feedback_create",
            methods=["POST"],
            view_func=self.admin_routing_quality_handler.create_feedback,
        )
        bp.add_url_rule(
            "/admin/routing-quality/feedback",
            endpoint="admin_routing_quality_feedback_list",
            methods=["GET"],
            view_func=self.admin_routing_quality_handler.list_feedback,
        )
        bp.add_url_rule(
            "/admin/routing-quality/metrics",
            endpoint="admin_routing_quality_metrics",
            methods=["GET"],
            view_func=self.admin_routing_quality_handler.metrics,
        )
        bp.add_url_rule(
            "/admin/routing-quality/suggestions",
            endpoint="admin_routing_quality_suggestions",
            methods=["GET"],
            view_func=self.admin_routing_quality_handler.suggestions,
        )
        bp.add_url_rule(
            "/admin/routing-quality/suggestions/<uuid:suggestion_id>/accept",
            endpoint="admin_routing_quality_suggestion_accept",
            methods=["POST"],
            view_func=self.admin_routing_quality_handler.accept_suggestion,
        )
        bp.add_url_rule(
            "/admin/routing-quality/suggestions/<uuid:suggestion_id>/dismiss",
            endpoint="admin_routing_quality_suggestion_dismiss",
            methods=["POST"],
            view_func=self.admin_routing_quality_handler.dismiss_suggestion,
        )
        bp.add_url_rule(
            "/admin/routing-quality/suggestions/<uuid:suggestion_id>/preview",
            endpoint="admin_routing_quality_suggestion_preview",
            methods=["GET"],
            view_func=self.admin_routing_quality_handler.preview_policy_change,
        )
        bp.add_url_rule(
            "/admin/routing-quality/suggestions/<uuid:suggestion_id>/apply",
            endpoint="admin_routing_quality_suggestion_apply",
            methods=["POST"],
            view_func=self.admin_routing_quality_handler.apply_policy_change,
        )
        bp.add_url_rule(
            "/admin/routing-quality/policy-changes",
            endpoint="admin_routing_quality_policy_change_list",
            methods=["GET"],
            view_func=self.admin_routing_quality_handler.list_policy_changes,
        )
        bp.add_url_rule(
            "/admin/routing-quality/policy-changes/<uuid:draft_id>/rollback",
            endpoint="admin_routing_quality_policy_change_rollback",
            methods=["POST"],
            view_func=self.admin_routing_quality_handler.rollback_policy_change,
        )
        bp.add_url_rule(
            "/admin/plans",
            endpoint="admin_plan_list",
            methods=["GET"],
            view_func=self.admin_billing_plan_handler.list,
        )
        bp.add_url_rule(
            "/admin/plans",
            endpoint="admin_plan_create",
            methods=["POST"],
            view_func=self.admin_billing_plan_handler.create,
        )
        bp.add_url_rule(
            "/admin/plans/<uuid:plan_id>",
            endpoint="admin_plan_get",
            methods=["GET"],
            view_func=self.admin_billing_plan_handler.get,
        )
        bp.add_url_rule(
            "/admin/plans/<uuid:plan_id>",
            endpoint="admin_plan_update",
            methods=["POST"],
            view_func=self.admin_billing_plan_handler.update,
        )
        bp.add_url_rule(
            "/admin/plans/<uuid:plan_id>/status",
            endpoint="admin_plan_status",
            methods=["POST"],
            view_func=self.admin_billing_plan_handler.set_status,
        )
        bp.add_url_rule(
            "/admin/redeem-code-batches",
            endpoint="admin_redeem_code_batch_list",
            methods=["GET"],
            view_func=self.admin_redeem_code_handler.list_batches,
        )
        bp.add_url_rule(
            "/admin/redeem-code-batches",
            endpoint="admin_redeem_code_batch_generate",
            methods=["POST"],
            view_func=self.admin_redeem_code_handler.generate,
        )
        bp.add_url_rule(
            "/admin/redeem-codes",
            endpoint="admin_redeem_code_list",
            methods=["GET"],
            view_func=self.admin_redeem_code_handler.list_codes,
        )
        bp.add_url_rule(
            "/admin/redeem-codes/<uuid:code_id>/disable",
            endpoint="admin_redeem_code_disable",
            methods=["POST"],
            view_func=self.admin_redeem_code_handler.disable,
        )
        bp.add_url_rule(
            "/admin/redeem-code-batches/<uuid:batch_id>/disable",
            endpoint="admin_redeem_code_batch_disable",
            methods=["POST"],
            view_func=self.admin_redeem_code_handler.disable_batch,
        )
        bp.add_url_rule(
            "/admin/apps",
            endpoint="admin_app_list",
            methods=["GET"],
            view_func=self.admin_app_handler.list,
        )
        bp.add_url_rule(
            "/admin/apps/<uuid:app_id>",
            endpoint="admin_app_get",
            methods=["GET"],
            view_func=self.admin_app_handler.get,
        )
        bp.add_url_rule(
            "/admin/apps/<uuid:app_id>",
            endpoint="admin_app_update",
            methods=["PATCH"],
            view_func=self.admin_app_handler.update,
        )
        bp.add_url_rule(
            "/admin/apps/<uuid:app_id>/offline",
            endpoint="admin_app_offline",
            methods=["POST"],
            view_func=self.admin_app_handler.offline,
        )
        bp.add_url_rule(
            "/admin/apps",
            endpoint="admin_app_create",
            methods=["POST"],
            view_func=self.admin_app_handler.create,
        )
        bp.add_url_rule(
            "/admin/apps/<uuid:app_id>",
            endpoint="admin_app_delete",
            methods=["DELETE"],
            view_func=self.admin_app_handler.delete,
        )
        bp.add_url_rule(
            "/admin/apps/<uuid:app_id>/draft-app-config",
            endpoint="admin_app_draft_config_get",
            methods=["GET"],
            view_func=self.admin_app_handler.get_draft_app_config,
        )
        bp.add_url_rule(
            "/admin/apps/<uuid:app_id>/draft-app-config",
            endpoint="admin_app_draft_config_update",
            methods=["POST"],
            view_func=self.admin_app_handler.update_draft_app_config,
        )
        bp.add_url_rule(
            "/admin/workflows",
            endpoint="admin_workflow_list",
            methods=["GET"],
            view_func=self.admin_workflow_handler.list,
        )
        bp.add_url_rule(
            "/admin/workflows/<uuid:workflow_id>",
            endpoint="admin_workflow_get",
            methods=["GET"],
            view_func=self.admin_workflow_handler.get,
        )
        bp.add_url_rule(
            "/admin/workflows/<uuid:workflow_id>",
            endpoint="admin_workflow_update",
            methods=["PATCH"],
            view_func=self.admin_workflow_handler.update,
        )
        bp.add_url_rule(
            "/admin/workflows/<uuid:workflow_id>/offline",
            endpoint="admin_workflow_offline",
            methods=["POST"],
            view_func=self.admin_workflow_handler.offline,
        )
        bp.add_url_rule(
            "/admin/workflows",
            endpoint="admin_workflow_create",
            methods=["POST"],
            view_func=self.admin_workflow_handler.create,
        )
        bp.add_url_rule(
            "/admin/workflows/<uuid:workflow_id>",
            endpoint="admin_workflow_delete",
            methods=["DELETE"],
            view_func=self.admin_workflow_handler.delete,
        )
        bp.add_url_rule(
            "/admin/workflows/<uuid:workflow_id>/draft-graph",
            endpoint="admin_workflow_draft_graph_get",
            methods=["GET"],
            view_func=self.admin_workflow_handler.get_draft_graph,
        )
        bp.add_url_rule(
            "/admin/workflows/<uuid:workflow_id>/draft-graph",
            endpoint="admin_workflow_draft_graph_update",
            methods=["POST"],
            view_func=self.admin_workflow_handler.update_draft_graph,
        )
        bp.add_url_rule(
            "/admin/workflows/<uuid:workflow_id>/publish",
            endpoint="admin_workflow_publish",
            methods=["POST"],
            view_func=self.admin_workflow_handler.publish,
        )
        bp.add_url_rule(
            "/admin/datasets",
            endpoint="admin_dataset_entry",
            methods=["GET"],
            view_func=self.admin_dataset_handler.list,
        )
        bp.add_url_rule(
            "/admin/tools",
            endpoint="admin_tool_entry",
            methods=["GET"],
            view_func=self.admin_resource_entry_handler.tools,
        )
        bp.add_url_rule(
            "/admin/mcp",
            endpoint="admin_mcp_entry",
            methods=["GET"],
            view_func=self.admin_resource_entry_handler.mcp,
        )
        bp.add_url_rule(
            "/admin/skills",
            endpoint="admin_skill_entry",
            methods=["GET"],
            view_func=self.admin_resource_entry_handler.skills,
        )
        bp.add_url_rule(
            "/admin/api-tools",
            endpoint="admin_api_tool_list",
            methods=["GET"],
            view_func=self.admin_api_tool_handler.list,
        )
        bp.add_url_rule(
            "/admin/api-tools",
            endpoint="admin_api_tool_create",
            methods=["POST"],
            view_func=self.admin_api_tool_handler.create,
        )
        bp.add_url_rule(
            "/admin/api-tools/<uuid:provider_id>",
            endpoint="admin_api_tool_get",
            methods=["GET"],
            view_func=self.admin_api_tool_handler.get,
        )
        bp.add_url_rule(
            "/admin/api-tools/<uuid:provider_id>",
            endpoint="admin_api_tool_update",
            methods=["PATCH"],
            view_func=self.admin_api_tool_handler.update,
        )
        bp.add_url_rule(
            "/admin/api-tools/<uuid:provider_id>",
            endpoint="admin_api_tool_delete",
            methods=["DELETE"],
            view_func=self.admin_api_tool_handler.delete,
        )
        bp.add_url_rule(
            "/admin/mcp",
            endpoint="admin_mcp_create",
            methods=["POST"],
            view_func=self.admin_mcp_handler.create,
        )
        bp.add_url_rule(
            "/admin/mcp/<uuid:provider_id>",
            endpoint="admin_mcp_delete",
            methods=["DELETE"],
            view_func=self.admin_mcp_handler.delete,
        )
        bp.add_url_rule(
            "/admin/system-knowledge",
            endpoint="admin_system_knowledge_list",
            methods=["GET"],
            view_func=self.admin_system_knowledge_handler.list,
        )
        bp.add_url_rule(
            "/admin/system-knowledge",
            endpoint="admin_system_knowledge_create",
            methods=["POST"],
            view_func=self.admin_system_knowledge_handler.create,
        )
        bp.add_url_rule(
            "/admin/system-knowledge/<uuid:knowledge_base_id>",
            endpoint="admin_system_knowledge_get",
            methods=["GET"],
            view_func=self.admin_system_knowledge_handler.get,
        )
        bp.add_url_rule(
            "/admin/system-knowledge/<uuid:knowledge_base_id>",
            endpoint="admin_system_knowledge_update",
            methods=["POST"],
            view_func=self.admin_system_knowledge_handler.update,
        )
        bp.add_url_rule(
            "/admin/system-knowledge/<uuid:knowledge_base_id>",
            endpoint="admin_system_knowledge_delete",
            methods=["DELETE"],
            view_func=self.admin_system_knowledge_handler.delete,
        )
        bp.add_url_rule(
            "/admin/models",
            endpoint="admin_model_pool_list",
            methods=["GET"],
            view_func=self.admin_model_pool_handler.list_models,
        )
        bp.add_url_rule(
            "/admin/models",
            endpoint="admin_model_pool_create",
            methods=["POST"],
            view_func=self.admin_model_pool_handler.create_model,
        )
        bp.add_url_rule(
            "/admin/models/<uuid:model_id>",
            endpoint="admin_model_pool_get",
            methods=["GET"],
            view_func=self.admin_model_pool_handler.get_model,
        )
        bp.add_url_rule(
            "/admin/models/<uuid:model_id>",
            endpoint="admin_model_pool_update",
            methods=["PATCH"],
            view_func=self.admin_model_pool_handler.update_model,
        )
        bp.add_url_rule(
            "/admin/models/<uuid:model_id>",
            endpoint="admin_model_pool_delete",
            methods=["DELETE"],
            view_func=self.admin_model_pool_handler.delete_model,
        )
        bp.add_url_rule(
            "/admin/models/<uuid:model_id>/status",
            endpoint="admin_model_pool_status",
            methods=["POST"],
            view_func=self.admin_model_pool_handler.set_model_status,
        )
        bp.add_url_rule(
            "/admin/model-keys",
            endpoint="admin_model_key_list",
            methods=["GET"],
            view_func=self.admin_model_pool_handler.list_keys,
        )
        bp.add_url_rule(
            "/admin/model-keys",
            endpoint="admin_model_key_create",
            methods=["POST"],
            view_func=self.admin_model_pool_handler.create_key,
        )
        bp.add_url_rule(
            "/admin/model-keys/<uuid:key_id>",
            endpoint="admin_model_key_update",
            methods=["PATCH"],
            view_func=self.admin_model_pool_handler.update_key,
        )
        bp.add_url_rule(
            "/admin/model-keys/<uuid:key_id>",
            endpoint="admin_model_key_delete",
            methods=["DELETE"],
            view_func=self.admin_model_pool_handler.delete_key,
        )
        bp.add_url_rule(
            "/admin/model-keys/<uuid:key_id>/status",
            endpoint="admin_model_key_status",
            methods=["POST"],
            view_func=self.admin_model_pool_handler.set_key_status,
        )
        bp.add_url_rule(
            "/admin/model-tiers",
            endpoint="admin_model_tier_list",
            methods=["GET"],
            view_func=self.admin_model_pool_handler.list_tier_policies,
        )
        bp.add_url_rule(
            "/admin/model-tiers/<string:tier_code>",
            endpoint="admin_model_tier_update",
            methods=["PUT"],
            view_func=self.admin_model_pool_handler.update_tier_policy,
        )
        bp.add_url_rule(
            "/admin/cost-policies",
            endpoint="admin_cost_policy_list",
            methods=["GET"],
            view_func=self.admin_model_pool_handler.list_cost_policies,
        )
        bp.add_url_rule(
            "/admin/cost-policies",
            endpoint="admin_cost_policy_create",
            methods=["POST"],
            view_func=self.admin_model_pool_handler.create_cost_policy,
        )
        bp.add_url_rule(
            "/admin/cost-policies/<uuid:policy_id>",
            endpoint="admin_cost_policy_update",
            methods=["PUT"],
            view_func=self.admin_model_pool_handler.update_cost_policy,
        )
        bp.add_url_rule(
            "/admin/cost-stats/overview",
            endpoint="admin_cost_stats_overview",
            methods=["GET"],
            view_func=self.admin_cost_stats_handler.overview,
        )
        bp.add_url_rule(
            "/admin/cost-stats/by-dimension",
            endpoint="admin_cost_stats_by_dimension",
            methods=["GET"],
            view_func=self.admin_cost_stats_handler.by_dimension,
        )
        bp.add_url_rule(
            "/admin/cost-stats/timeseries",
            endpoint="admin_cost_stats_timeseries",
            methods=["GET"],
            view_func=self.admin_cost_stats_handler.timeseries,
        )
        bp.add_url_rule(
            "/admin/tool-governance",
            endpoint="admin_tool_governance_list",
            methods=["GET"],
            view_func=self.admin_tool_governance_handler.list_policies,
        )
        bp.add_url_rule(
            "/admin/tool-governance",
            endpoint="admin_tool_governance_create",
            methods=["POST"],
            view_func=self.admin_tool_governance_handler.create_policy,
        )
        bp.add_url_rule(
            "/admin/tool-governance/<uuid:policy_id>",
            endpoint="admin_tool_governance_get",
            methods=["GET"],
            view_func=self.admin_tool_governance_handler.get_policy,
        )
        bp.add_url_rule(
            "/admin/tool-governance/<uuid:policy_id>",
            endpoint="admin_tool_governance_update",
            methods=["PATCH"],
            view_func=self.admin_tool_governance_handler.update_policy,
        )
        bp.add_url_rule(
            "/admin/tool-governance/<uuid:policy_id>",
            endpoint="admin_tool_governance_delete",
            methods=["DELETE"],
            view_func=self.admin_tool_governance_handler.delete_policy,
        )
        bp.add_url_rule(
            "/admin/tool-governance/<uuid:policy_id>/status",
            endpoint="admin_tool_governance_status",
            methods=["POST"],
            view_func=self.admin_tool_governance_handler.set_status,
        )
        bp.add_url_rule(
            "/admin/tool-governance/batch-risk",
            endpoint="admin_tool_governance_batch_risk",
            methods=["POST"],
            view_func=self.admin_tool_governance_handler.batch_update_risk,
        )
        bp.add_url_rule(
            "/admin/tool-governance/audit",
            endpoint="admin_tool_governance_audit",
            methods=["GET"],
            view_func=self.admin_tool_governance_handler.list_audit_logs,
        )
        bp.add_url_rule(
            "/admin/tool-governance/stats",
            endpoint="admin_tool_governance_stats",
            methods=["GET"],
            view_func=self.admin_tool_governance_handler.stats,
        )
        bp.add_url_rule(
            "/admin/agent-pool",
            endpoint="admin_agent_pool_list",
            methods=["GET"],
            view_func=self.admin_agent_pool_handler.list,
        )
        bp.add_url_rule(
            "/admin/agent-pool",
            endpoint="admin_agent_pool_create",
            methods=["POST"],
            view_func=self.admin_agent_pool_handler.create,
        )
        bp.add_url_rule(
            "/admin/agent-pool/stats",
            endpoint="admin_agent_pool_stats",
            methods=["GET"],
            view_func=self.admin_agent_pool_handler.list_stats,
        )
        bp.add_url_rule(
            "/admin/agent-pool/<uuid:config_id>",
            endpoint="admin_agent_pool_get",
            methods=["GET"],
            view_func=self.admin_agent_pool_handler.get,
        )
        bp.add_url_rule(
            "/admin/agent-pool/<uuid:config_id>",
            endpoint="admin_agent_pool_update",
            methods=["PATCH"],
            view_func=self.admin_agent_pool_handler.update,
        )
        bp.add_url_rule(
            "/admin/agent-pool/<uuid:config_id>",
            endpoint="admin_agent_pool_delete",
            methods=["DELETE"],
            view_func=self.admin_agent_pool_handler.delete,
        )
        bp.add_url_rule(
            "/admin/agent-pool/<uuid:config_id>/status",
            endpoint="admin_agent_pool_status",
            methods=["POST"],
            view_func=self.admin_agent_pool_handler.set_status,
        )
        bp.add_url_rule(
            "/admin/agent-pool/<uuid:config_id>/health",
            endpoint="admin_agent_pool_health",
            methods=["POST"],
            view_func=self.admin_agent_pool_handler.check_health,
        )
        bp.add_url_rule(
            "/admin/sub-pool-definitions",
            endpoint="admin_sub_pool_list",
            methods=["GET"],
            view_func=self.admin_sub_pool_handler.list,
        )
        bp.add_url_rule(
            "/admin/sub-pool-definitions",
            endpoint="admin_sub_pool_create",
            methods=["POST"],
            view_func=self.admin_sub_pool_handler.create,
        )
        bp.add_url_rule(
            "/admin/sub-pool-definitions/<uuid:def_id>",
            endpoint="admin_sub_pool_get",
            methods=["GET"],
            view_func=self.admin_sub_pool_handler.get,
        )
        bp.add_url_rule(
            "/admin/sub-pool-definitions/<uuid:def_id>",
            endpoint="admin_sub_pool_update",
            methods=["PATCH"],
            view_func=self.admin_sub_pool_handler.update,
        )
        bp.add_url_rule(
            "/admin/sub-pool-definitions/<uuid:def_id>",
            endpoint="admin_sub_pool_delete",
            methods=["DELETE"],
            view_func=self.admin_sub_pool_handler.delete,
        )
        bp.add_url_rule(
            "/admin/sub-pool-definitions/<uuid:def_id>/status",
            endpoint="admin_sub_pool_status",
            methods=["POST"],
            view_func=self.admin_sub_pool_handler.set_status,
        )
        bp.add_url_rule(
            "/auth/register/prepare",
            methods=["POST"],
            view_func=self.auth_handler.prepare_register,
        )
        bp.add_url_rule(
            "/auth/register/direct",
            methods=["POST"],
            view_func=self.auth_handler.direct_register,
        )
        bp.add_url_rule(
            "/auth/register/verify",
            methods=["POST"],
            view_func=self.auth_handler.verify_register,
        )
        bp.add_url_rule(
            "/auth/logout",
            methods=["POST"],
            view_func=self.auth_handler.logout,
        )
        bp.add_url_rule(
            "/auth/send-reset-code",
            methods=["POST"],
            view_func=self.auth_handler.send_reset_code,
        )
        bp.add_url_rule(
            "/auth/reset-password",
            methods=["POST"],
            view_func=self.auth_handler.reset_password,
        )
        bp.add_url_rule(
            "/auth/login-challenge/verify",
            methods=["POST"],
            view_func=self.auth_handler.verify_login_challenge,
        )
        bp.add_url_rule(
            "/auth/login-challenge/resend",
            methods=["POST"],
            view_func=self.auth_handler.resend_login_challenge,
        )

        # 7.账号设置模块
        bp.add_url_rule("/account", view_func=self.account_handler.get_current_user)
        bp.add_url_rule("/account/email/send-code", methods=["POST"], view_func=self.account_handler.send_change_email_code)
        bp.add_url_rule("/account/email", methods=["POST"], view_func=self.account_handler.update_email)
        bp.add_url_rule("/account/password", methods=["POST"], view_func=self.account_handler.update_password)
        bp.add_url_rule("/account/name", methods=["POST"], view_func=self.account_handler.update_name)
        bp.add_url_rule("/account/avatar", methods=["POST"], view_func=self.account_handler.update_avatar)
        bp.add_url_rule("/account/sessions", view_func=self.account_handler.get_account_sessions)
        bp.add_url_rule("/account/login-history", view_func=self.account_handler.get_account_login_history)
        bp.add_url_rule("/account/sessions/revoke-others", methods=["POST"], view_func=self.account_handler.revoke_other_account_sessions)
        bp.add_url_rule("/account/sessions/<uuid:session_id>/revoke", methods=["POST"], view_func=self.account_handler.revoke_account_session)
        bp.add_url_rule(
            "/account/oauth/<string:provider_name>/unbind",
            methods=["POST"],
            view_func=self.account_handler.unbind_oauth,
        )
        bp.add_url_rule("/redeem-codes/redeem", methods=["POST"], view_func=self.redeem_code_handler.redeem)
        bp.add_url_rule("/membership/summary", view_func=self.redeem_code_handler.summary)
        bp.add_url_rule("/membership/redeem-records", view_func=self.redeem_code_handler.records)
        bp.add_url_rule(
            "/memory-candidates",
            endpoint="memory_candidate_list",
            methods=["GET"],
            view_func=self.memory_candidate_handler.list,
        )
        bp.add_url_rule(
            "/memory-candidates/<uuid:candidate_id>/confirm",
            endpoint="memory_candidate_confirm",
            methods=["POST"],
            view_func=self.memory_candidate_handler.confirm,
        )
        bp.add_url_rule(
            "/memory-candidates/<uuid:candidate_id>/ignore",
            endpoint="memory_candidate_ignore",
            methods=["POST"],
            view_func=self.memory_candidate_handler.ignore,
        )
        bp.add_url_rule(
            "/user/memory",
            endpoint="user_memory_list",
            methods=["GET"],
            view_func=self.user_memory_handler.list,
        )
        bp.add_url_rule(
            "/user/memory",
            endpoint="user_memory_create",
            methods=["POST"],
            view_func=self.user_memory_handler.create,
        )
        bp.add_url_rule(
            "/user/memory/<uuid:memory_id>",
            endpoint="user_memory_get",
            methods=["GET"],
            view_func=self.user_memory_handler.get,
        )
        bp.add_url_rule(
            "/user/memory/<uuid:memory_id>",
            endpoint="user_memory_update",
            methods=["POST"],
            view_func=self.user_memory_handler.update,
        )
        bp.add_url_rule(
            "/user/memory/<uuid:memory_id>",
            endpoint="user_memory_delete",
            methods=["DELETE"],
            view_func=self.user_memory_handler.delete,
        )
        bp.add_url_rule(
            "/external-data-sources",
            endpoint="external_data_source_list",
            methods=["GET"],
            view_func=self.external_data_source_handler.list,
        )
        bp.add_url_rule(
            "/external-data-sources",
            endpoint="external_data_source_create",
            methods=["POST"],
            view_func=self.external_data_source_handler.create,
        )
        bp.add_url_rule(
            "/external-data-sources/<uuid:data_source_id>",
            endpoint="external_data_source_get",
            methods=["GET"],
            view_func=self.external_data_source_handler.get,
        )
        bp.add_url_rule(
            "/external-data-sources/<uuid:data_source_id>",
            endpoint="external_data_source_delete",
            methods=["DELETE"],
            view_func=self.external_data_source_handler.delete,
        )
        bp.add_url_rule(
            "/external-data-sources/<uuid:data_source_id>/authorize",
            endpoint="external_data_source_authorize",
            methods=["POST"],
            view_func=self.external_data_source_handler.authorize,
        )
        bp.add_url_rule(
            "/external-data-sources/<uuid:data_source_id>/sync",
            endpoint="external_data_source_sync",
            methods=["POST"],
            view_func=self.external_data_source_handler.sync,
        )
        bp.add_url_rule(
            "/tool-confirmations",
            endpoint="tool_confirmation_list",
            methods=["GET"],
            view_func=self.tool_confirmation_handler.list,
        )
        bp.add_url_rule(
            "/tool-confirmations/<uuid:confirmation_id>",
            endpoint="tool_confirmation_get",
            methods=["GET"],
            view_func=self.tool_confirmation_handler.get,
        )
        bp.add_url_rule(
            "/tool-confirmations",
            endpoint="tool_confirmation_create",
            methods=["POST"],
            view_func=self.tool_confirmation_handler.create,
        )
        bp.add_url_rule(
            "/tool-confirmations/<uuid:confirmation_id>/confirm",
            endpoint="tool_confirmation_confirm",
            methods=["POST"],
            view_func=self.tool_confirmation_handler.confirm,
        )
        bp.add_url_rule(
            "/tool-confirmations/<uuid:confirmation_id>/cancel",
            endpoint="tool_confirmation_cancel",
            methods=["POST"],
            view_func=self.tool_confirmation_handler.cancel,
        )
        bp.add_url_rule("/my/apps", view_func=self.my_app_handler.list_my_apps)
        bp.add_url_rule("/my/apps/<uuid:app_id>/chat", methods=["POST"], view_func=self.my_app_handler.chat)

        # 7.1 首页模块
        bp.add_url_rule("/home/intent", view_func=self.home_handler.get_intent)

        # 8.AI辅助模块
        bp.add_url_rule("/ai/optimize-prompt", methods=["POST"], view_func=self.ai_handler.optimize_prompt)
        bp.add_url_rule(
            "/ai/suggested-questions",
            methods=["POST"],
            view_func=self.ai_handler.generate_suggested_questions
        )
        bp.add_url_rule("/ai/chat", methods=["POST"], view_func=self.ai_handler.code_assistant_chat)
        bp.add_url_rule(
            "/ai/openapi-schema-chat",
            methods=["POST"],
            view_func=self.ai_handler.openapi_schema_assistant_chat,
        )
        bp.add_url_rule(
            "/ai/mcp-schema-chat",
            methods=["POST"],
            view_func=self.ai_handler.mcp_schema_assistant_chat,
        )

        # 8.1.MCP模块
        bp.add_url_rule(
            "/public/mcp-providers/categories",
            view_func=self.mcp_handler.get_mcp_categories,
        )
        bp.add_url_rule(
            "/public/mcp-providers",
            view_func=self.mcp_handler.get_public_mcp_providers_with_page,
        )
        bp.add_url_rule(
            "/public/mcp-providers/<string:provider_key>",
            view_func=self.mcp_handler.get_public_mcp_provider,
        )
        bp.add_url_rule(
            "/mcp-providers/categories",
            view_func=self.mcp_handler.get_mcp_categories_for_space,
        )
        bp.add_url_rule(
            "/mcp-providers",
            view_func=self.mcp_handler.get_mcp_providers_with_page,
        )
        bp.add_url_rule(
            "/mcp-providers",
            methods=["POST"],
            view_func=self.mcp_handler.create_mcp_provider,
        )
        bp.add_url_rule(
            "/mcp-providers/<uuid:provider_id>",
            view_func=self.mcp_handler.get_mcp_provider,
        )
        bp.add_url_rule(
            "/mcp-providers/<uuid:provider_id>",
            methods=["POST"],
            view_func=self.mcp_handler.update_mcp_provider,
        )
        bp.add_url_rule(
            "/mcp-providers/<uuid:provider_id>/delete",
            methods=["POST"],
            view_func=self.mcp_handler.delete_mcp_provider,
        )
        bp.add_url_rule(
            "/mcp-providers/<uuid:provider_id>/publish",
            methods=["POST"],
            view_func=self.mcp_handler.publish_mcp_provider,
        )
        bp.add_url_rule(
            "/mcp-providers/<uuid:provider_id>/unpublish",
            methods=["POST"],
            view_func=self.mcp_handler.unpublish_mcp_provider,
        )
        bp.add_url_rule(
            "/mcp-providers/<uuid:provider_id>/regenerate-icon",
            methods=["POST"],
            view_func=self.mcp_handler.regenerate_icon,
            endpoint="mcp_provider_regenerate_icon",
        )
        bp.add_url_rule(
            "/mcp-providers/generate-icon-preview",
            methods=["POST"],
            view_func=self.mcp_handler.generate_icon_preview,
            endpoint="mcp_provider_generate_icon_preview",
        )

        # 9.API秘钥模块
        bp.add_url_rule("/openapi/api-keys", view_func=self.api_key_handler.get_api_keys_with_page)
        bp.add_url_rule(
            "/openapi/api-keys",
            methods=["POST"],
            view_func=self.api_key_handler.create_api_key,
        )
        bp.add_url_rule(
            "/openapi/api-keys/<uuid:api_key_id>",
            methods=["POST"],
            view_func=self.api_key_handler.update_api_key,
        )
        bp.add_url_rule(
            "/openapi/api-keys/<uuid:api_key_id>/is-active",
            methods=["POST"],
            view_func=self.api_key_handler.update_api_key_is_active,
        )
        bp.add_url_rule(
            "/openapi/api-keys/<uuid:api_key_id>/delete",
            methods=["POST"],
            view_func=self.api_key_handler.delete_api_key,
        )
        openapi_bp.add_url_rule(
            "/openapi/chat",
            methods=["POST"],
            view_func=self.openapi_handler.chat,
        )

        # 10.工作流模块
        bp.add_url_rule("/workflows", view_func=self.workflow_handler.get_workflows_with_page)
        bp.add_url_rule("/workflows", methods=["POST"], view_func=self.workflow_handler.create_workflow)
        bp.add_url_rule("/workflows/<uuid:workflow_id>", view_func=self.workflow_handler.get_workflow)
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>",
            methods=["POST"],
            view_func=self.workflow_handler.update_workflow,
        )
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>/delete",
            methods=["POST"],
            view_func=self.workflow_handler.delete_workflow,
        )
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>/draft-graph",
            methods=["POST"],
            view_func=self.workflow_handler.update_draft_graph,
        )
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>/draft-graph",
            view_func=self.workflow_handler.get_draft_graph,
        )
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>/debug",
            methods=["POST"],
            view_func=self.workflow_handler.debug_workflow,
        )
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>/publish",
            methods=["POST"],
            view_func=self.workflow_handler.publish_workflow,
        )
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>/cancel-publish",
            methods=["POST"],
            view_func=self.workflow_handler.cancel_publish_workflow,
        )
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>/regenerate-icon",
            methods=["POST"],
            view_func=self.workflow_handler.regenerate_icon,
            endpoint="workflow_regenerate_icon",
        )
        bp.add_url_rule(
            "/workflows/generate-icon-preview",
            methods=["POST"],
            view_func=self.workflow_handler.generate_icon_preview,
            endpoint="workflow_generate_icon_preview",
        )
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>/share",
            methods=["POST"],
            view_func=self.workflow_handler.share_workflow_to_public,
        )

        # 12.语言模型模块
        bp.add_url_rule("/language-models", view_func=self.language_model_handler.get_language_models)
        bp.add_url_rule(
            "/language-models/<string:provider_name>/icon",
            view_func=self.language_model_handler.get_language_model_icon,
        )
        bp.add_url_rule(
            "/language-models/<string:provider_name>/<string:model_name>",
            view_func=self.language_model_handler.get_language_model,
        )

        # 13.辅助Agent模块
        bp.add_url_rule(
            "/assistant-agent/chat",
            methods=["POST"],
            view_func=self.assistant_agent_handler.assistant_agent_chat,
        )
        bp.add_url_rule(
            "/assistant-agent/introduction",
            methods=["POST"],
            view_func=self.assistant_agent_handler.generate_assistant_agent_introduction,
        )
        bp.add_url_rule(
            "/assistant-agent/capabilities",
            view_func=self.assistant_agent_handler.get_assistant_agent_capabilities,
        )
        bp.add_url_rule(
            "/assistant-agent/chat/<uuid:task_id>/stop",
            methods=["POST"],
            view_func=self.assistant_agent_handler.stop_assistant_agent_chat,
        )
        bp.add_url_rule(
            "/assistant-agent/messages",
            view_func=self.assistant_agent_handler.get_assistant_agent_messages_with_page,
        )
        bp.add_url_rule(
            "/assistant-agent/conversations",
            view_func=self.assistant_agent_handler.get_assistant_agent_conversations,
        )
        bp.add_url_rule(
            "/assistant-agent/delete-conversation",
            methods=["POST"],
            view_func=self.assistant_agent_handler.delete_assistant_agent_conversation,
        )

        # 14.应用统计模块
        bp.add_url_rule(
            "/analysis/<uuid:app_id>",
            view_func=self.analysis_handler.get_app_analysis,
        )

        # 15.WebApp模块
        bp.add_url_rule("/web-apps/<string:token>", view_func=self.web_app_handler.get_web_app)
        bp.add_url_rule(
            "/web-apps/<string:token>/chat",
            methods=["POST"],
            view_func=self.web_app_handler.web_app_chat,
        )
        bp.add_url_rule(
            "/web-apps/<string:token>/chat/<uuid:task_id>/stop",
            methods=["POST"],
            view_func=self.web_app_handler.stop_web_app_chat,
        )
        bp.add_url_rule("/web-apps/<string:token>/conversations", view_func=self.web_app_handler.get_conversations)

        # 16.会话模块
        bp.add_url_rule(
            "/conversations/recent",
            view_func=self.conversation_handler.get_recent_conversations,
        )
        bp.add_url_rule(
            "/conversations/<uuid:conversation_id>/messages",
            view_func=self.conversation_handler.get_conversation_messages_with_page,
        )
        bp.add_url_rule(
            "/conversations/<uuid:conversation_id>/delete",
            methods=["POST"],
            view_func=self.conversation_handler.delete_conversation,
        )
        bp.add_url_rule(
            "/conversations/<uuid:conversation_id>/messages/<uuid:message_id>/delete",
            methods=["POST"],
            view_func=self.conversation_handler.delete_message,
        )
        # 兼容历史客户端：保留无 /delete 后缀的删除消息路由。
        bp.add_url_rule(
            "/conversations/<uuid:conversation_id>/messages/<uuid:message_id>",
            methods=["POST"],
            view_func=self.conversation_handler.delete_message,
        )
        bp.add_url_rule(
            "/conversations/<uuid:conversation_id>/name",
            view_func=self.conversation_handler.get_conversation_name,
        )
        bp.add_url_rule(
            "/conversations/<uuid:conversation_id>/name",
            methods=["POST"],
            view_func=self.conversation_handler.update_conversation_name,
        )
        bp.add_url_rule(
            "/conversations/<uuid:conversation_id>/is-pinned",
            methods=["POST"],
            view_func=self.conversation_handler.update_conversation_is_pinned,
        )
        bp.add_url_rule(
            "/conversations/search",
            view_func=self.conversation_handler.search_conversations,
        )

        # 17.语音转换模块
        bp.add_url_rule(
            "/audio/audio-to-text",
            methods=["POST"],
            view_func=self.audio_handler.audio_to_text,
        )
        bp.add_url_rule(
            "/audio/message-to-audio",
            methods=["POST"],
            view_func=self.audio_handler.message_to_audio,
        )
        bp.add_url_rule(
            "/audio/text-to-audio",
            methods=["POST"],
            view_func=self.audio_handler.text_to_audio,
        )
        # 18.第三方平台配置模块
        bp.add_url_rule(
            "/platform/<uuid:app_id>/wechat-config",
            view_func=self.platform_handler.get_wechat_config,
        )
        bp.add_url_rule(
            "/platform/<uuid:app_id>/wechat-config",
            methods=["POST"],
            view_func=self.platform_handler.update_wechat_config,
        )
        bp.add_url_rule(
            "/wechat/<uuid:app_id>",
            methods=["GET", "POST"],
            view_func=self.wechat_handler.wechat,
        )

        # 19.公共应用广场模块
        bp.add_url_rule(
            "/public/apps",
            view_func=self.public_app_handler.get_public_apps_with_page,
        )
        bp.add_url_rule(
            "/public/apps/<string:app_id>",
            view_func=self.public_app_handler.get_public_app_detail,
        )
        bp.add_url_rule(
            "/public/apps/<string:app_id>/a2a/agent-card",
            view_func=self.public_app_handler.get_public_app_a2a_card,
        )
        bp.add_url_rule(
            "/public/apps/<string:app_id>/a2a/messages",
            methods=["POST"],
            view_func=self.public_app_handler.send_public_app_a2a_message,
        )
        bp.add_url_rule(
            "/public/apps/<string:app_id>/a2a/conversations/<string:conversation_id>/messages",
            methods=["GET"],
            view_func=self.public_app_handler.get_public_app_a2a_conversation_messages,
        )
        bp.add_url_rule(
            "/public/apps/<string:app_id>/a2a/conversations/latest",
            methods=["GET"],
            view_func=self.public_app_handler.get_latest_public_app_a2a_conversation,
        )
        bp.add_url_rule(
            "/public/apps/tags",
            view_func=self.public_app_handler.get_app_tags,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/share-to-square",
            methods=["POST"],
            view_func=self.public_app_handler.share_app_to_square,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/unshare-from-square",
            methods=["POST"],
            view_func=self.public_app_handler.unshare_app_from_square,
        )
        bp.add_url_rule(
            "/public/apps/<string:app_id>/fork",
            methods=["POST"],
            view_func=self.public_app_handler.fork_public_app,
        )
        # 20.公共工作流广场模块
        bp.add_url_rule(
            "/public/workflows",
            view_func=self.public_workflow_handler.get_public_workflows_with_page,
        )
        bp.add_url_rule(
            "/public/workflows/<uuid:workflow_id>",
            view_func=self.public_workflow_handler.get_public_workflow_detail,
        )
        bp.add_url_rule(
            "/public/workflows/<uuid:workflow_id>/draft-graph",
            view_func=self.public_workflow_handler.get_public_workflow_draft_graph,
        )
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>/share-to-square",
            methods=["POST"],
            view_func=self.public_workflow_handler.share_workflow_to_square,
        )
        bp.add_url_rule(
            "/workflows/<uuid:workflow_id>/unshare-from-square",
            methods=["POST"],
            view_func=self.public_workflow_handler.unshare_workflow_from_square,
        )
        bp.add_url_rule(
            "/public/workflows/<uuid:workflow_id>/fork",
            methods=["POST"],
            view_func=self.public_workflow_handler.fork_public_workflow,
        )
        # 21.标签模块
        bp.add_url_rule("/tags", view_func=self.tag_handler.list_tags)
        bp.add_url_rule("/tags", methods=["POST"], view_func=self.tag_handler.create_tag)
        bp.add_url_rule("/tags/hot", view_func=self.tag_handler.get_hot_tags)
        bp.add_url_rule("/tags/dimensions", view_func=self.tag_handler.get_dimensions)
        bp.add_url_rule("/tags/<uuid:tag_id>", view_func=self.tag_handler.get_tag)
        bp.add_url_rule("/tags/<uuid:tag_id>", methods=["POST"], view_func=self.tag_handler.update_tag)
        bp.add_url_rule("/tags/<uuid:tag_id>/delete", methods=["POST"], view_func=self.tag_handler.delete_tag)

        # 22.通知模块
        bp.add_url_rule("/notifications", view_func=self.notification_handler.get_notifications)
        bp.add_url_rule(
            "/notifications/<string:notification_id>/read",
            methods=["POST"],
            view_func=self.notification_handler.mark_notification_as_read,
        )
        bp.add_url_rule(
            "/notifications/<string:notification_id>",
            methods=["DELETE"],
            view_func=self.notification_handler.delete_notification,
        )

        # 23.路由日志用户侧简化视图
        bp.add_url_rule(
            "/routing-logs/summary",
            endpoint="routing_log_summary",
            methods=["GET"],
            view_func=self.routing_log_handler.summary,
        )

        # 25.展示案例模块
        bp.add_url_rule(
            "/showcase/cases",
            endpoint="showcase_case_create",
            methods=["POST"],
            view_func=self.showcase_handler.create_case,
        )
        bp.add_url_rule(
            "/showcase/cases",
            endpoint="showcase_case_list",
            methods=["GET"],
            view_func=self.showcase_handler.list_cases,
        )
        bp.add_url_rule(
            "/showcase/cases/<uuid:case_id>",
            endpoint="showcase_case_get",
            methods=["GET"],
            view_func=self.showcase_handler.get_case,
        )
        bp.add_url_rule(
            "/admin/showcase/cases",
            endpoint="admin_showcase_case_list",
            methods=["GET"],
            view_func=self.showcase_handler.admin_list_cases,
        )
        bp.add_url_rule(
            "/admin/showcase/cases/<uuid:case_id>/approve",
            endpoint="admin_showcase_case_approve",
            methods=["POST"],
            view_func=self.showcase_handler.approve_case,
        )
        bp.add_url_rule(
            "/admin/showcase/cases/<uuid:case_id>/reject",
            endpoint="admin_showcase_case_reject",
            methods=["POST"],
            view_func=self.showcase_handler.reject_case,
        )
        bp.add_url_rule(
            "/admin/showcase/cases/<uuid:case_id>/offline",
            endpoint="admin_showcase_case_offline",
            methods=["POST"],
            view_func=self.showcase_handler.offline_case,
        )

        # 24.在应用上注册蓝图
        app.register_blueprint(bp)
        app.register_blueprint(openapi_bp)
