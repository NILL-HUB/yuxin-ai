import asyncio
import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Generator
from uuid import UUID

from internal.context import current_app, g, has_app_context
from injector import inject
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from internal.core.agent.agents import FunctionCallAgent, ReACTAgent, DeepThinkingAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.core.agent.usage_utils import summarize_agent_thoughts
from internal.core.language_model import LanguageModelManager
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from internal.entity.app_entity import AppStatus, DEFAULT_APP_CONFIG
from internal.entity.conversation_entity import InvokeFrom
from internal.entity.dataset_entity import RetrievalStrategy
from internal.model import App, Account
from pkg.sqlalchemy import SQLAlchemy
from .app_config_service import AppConfigService, call_config_loader
from .base_service import BaseService
from .conversation_service import ConversationService
from .language_model_service import LanguageModelService
from .public_agent_registry_service import PublicAgentRegistryService
from .retrieval_service import RetrievalService
from .runtime_tool_governance_gate import RuntimeToolGovernanceGate
from .skill_service import SkillService
from .tool_inventory_service import build_tool_id
from ..core.language_model.entities.model_entity import ModelFeature


logger = logging.getLogger(__name__)


@inject
@dataclass
class AppRuntimeService(BaseService):
    """应用运行时服务：共享运行时工具工厂与 Agent 绑定执行。

    从 AppService 抽取的运行时方法集合，作为公共 API 供 AppDebugService、
    WebAppService、WechatService、OpenAPIService、PublicAgentA2AService 等复用。
    本服务不依赖 AppService 或 AppDebugService，保持单向依赖。
    """
    db: SQLAlchemy
    app_config_service: AppConfigService
    retrieval_service: RetrievalService
    language_model_service: LanguageModelService
    language_model_manager: LanguageModelManager
    builtin_provider_manager: BuiltinProviderManager
    conversation_service: ConversationService
    public_agent_registry_service: PublicAgentRegistryService | None = None
    runtime_tool_governance_gate: RuntimeToolGovernanceGate | None = None

    def get_skill_service(self) -> SkillService:
        """获取技能服务，兼容测试里传入的简化 app_config_service。"""
        skill_service = getattr(self.app_config_service, "skill_service", None)
        if skill_service is not None:
            return skill_service
        return SkillService(self.db)

    def build_runtime_tools(
        self,
        app_id: UUID,
        account: Account,
        draft_app_config: dict[str, Any],
        flask_app: Any | None = None,
        runtime_context: dict[str, Any] | None = None,
        governance_gate: Any | None = None,
        governance_context: dict[str, Any] | None = None,
    ) -> list[Any]:
        """根据应用草稿配置构建运行时工具列表"""
        return self.build_runtime_tools_for_config(
            app_config_service=self.app_config_service,
            retrieval_service=self.retrieval_service,
            skill_service=self.get_skill_service(),
            app_service=self,
            account=account,
            app_id=app_id,
            draft_app_config=draft_app_config,
            flask_app=flask_app,
            runtime_context=runtime_context,
            governance_gate=governance_gate or self.runtime_tool_governance_gate,
            governance_context=governance_context,
        )

    @staticmethod
    def build_skill_prompt_appendix(skill_bindings: list[dict[str, Any]] | None) -> str:
        """把已绑定 Skill 的正文拼成一段额外提示词。"""
        if not isinstance(skill_bindings, list) or not skill_bindings:
            return ""

        sections: list[str] = []
        for binding in skill_bindings:
            if not isinstance(binding, dict):
                continue

            title = str(binding.get("label") or binding.get("name") or binding.get("source_key") or "Skill").strip()
            readme = str(binding.get("readme") or binding.get("description") or "").strip()
            if not readme:
                continue

            sections.append(f"### {title}\n{readme}")

        if not sections:
            return ""

        return "## 已绑定 Skills\n\n" + "\n\n---\n\n".join(sections)

    @staticmethod
    def build_mcp_prompt_appendix(mcp_bindings: list[dict[str, Any]] | None) -> str:
        """把已绑定 MCP 的基础信息拼成一段额外提示词。"""
        if not isinstance(mcp_bindings, list) or not mcp_bindings:
            return ""

        sections: list[str] = []
        for binding in mcp_bindings:
            if not isinstance(binding, dict) or not binding.get("enabled", True):
                continue

            title = str(binding.get("label") or binding.get("name") or binding.get("source_key") or "MCP").strip()
            description = str(binding.get("description") or "").strip()
            if not description:
                continue

            bullet = f"- {title}：{description}"
            source_key = str(binding.get("source_key") or "").strip()
            if source_key:
                bullet += f"（来源：{source_key}）"
            sections.append(bullet)

        if not sections:
            return ""

        appendix = [
            "## 已绑定 MCP",
            "",
            "如果用户的问题明显需要实时数据、外部服务或某个已绑定 MCP 的专长，请优先调用对应 MCP，不要用无关工具代替，也不要仅凭常识编造实时结果。",
            "",
            *sections,
        ]
        return "\n".join(appendix)

    @staticmethod
    def build_mcp_snapshot_prompt_appendix(mcp_tool_snapshots: list[dict[str, Any]] | None) -> str:
        """把 MCP 快照状态拼成一段额外提示词。"""
        if not isinstance(mcp_tool_snapshots, list) or not mcp_tool_snapshots:
            return ""

        sections: list[str] = []
        for snapshot in mcp_tool_snapshots:
            if not isinstance(snapshot, dict):
                continue

            binding = snapshot.get("binding") if isinstance(snapshot.get("binding"), dict) else {}
            title = str(
                binding.get("label")
                or binding.get("name")
                or binding.get("source_key")
                or snapshot.get("binding_identity")
                or "MCP"
            ).strip()
            status = str(snapshot.get("status") or "").strip().lower() or "unknown"
            tool_count = int(snapshot.get("tool_count") or len(snapshot.get("tool_definitions") or []) or 0)
            last_error = str(snapshot.get("last_error") or "").strip()
            retryable = bool(snapshot.get("retryable", False))
            bullet = f"- {title}：状态 {status}"
            if tool_count:
                bullet += f"，工具数 {tool_count}"
            if retryable:
                bullet += "，可重试"
            if last_error and status in {"failed", "stale"}:
                bullet += f"，最近错误：{last_error}"
            sections.append(bullet)

        if not sections:
            return ""

        appendix = [
            "## MCP 快照状态",
            "",
            "只有状态为 ready 或 stale 且对应工具已进入运行时列表时，才优先按完整工具名调用；warming、failed、unsupported、empty 状态下不要假设该 MCP 可直接可用。",
            "",
            *sections,
        ]
        return "\n".join(appendix)

    @staticmethod
    def build_runtime_mcp_tools_prompt_appendix(tools: list[Any] | None) -> str:
        """把运行时已经展开出来的 MCP 工具名拼成一段额外提示词。"""
        if not isinstance(tools, list) or not tools:
            return ""

        sections: list[str] = []
        for tool in tools:
            tool_name = str(getattr(tool, "name", "") or "").strip()
            if not tool_name.startswith("mcp__"):
                continue
            tool_description = str(getattr(tool, "description", "") or "").strip()
            if not tool_description:
                continue
            sections.append(f"- {tool_name}：{tool_description}")

        if not sections:
            return ""

        appendix = [
            "## 运行时可用的 MCP 工具",
            "",
            "调用 MCP 时请使用下面列出的**完整工具名**，不要自己猜工具名或缩写。",
            "",
            *sections,
        ]
        return "\n".join(appendix)

    @staticmethod
    def build_runtime_tools_for_config(
        *,
        app_config_service: AppConfigService,
        retrieval_service: RetrievalService,
        skill_service: SkillService | None = None,
        app_service: Any | None = None,
        account: Account,
        app_id: UUID | None = None,
        draft_app_config: dict[str, Any],
        flask_app: Any | None = None,
        runtime_context: dict[str, Any] | None = None,
        governance_gate: Any | None = None,
        governance_context: dict[str, Any] | None = None,
    ) -> list[Any]:
        """根据应用配置构建运行时工具列表，供多入口复用。"""
        tools = app_config_service.get_langchain_tools_by_tools_config(draft_app_config.get("tools", []))
        get_mcp_tools = getattr(app_config_service, "get_langchain_tools_by_mcp_bindings", None)
        if callable(get_mcp_tools):
            tools.extend(
                get_mcp_tools(
                    draft_app_config.get("mcp_bindings", []),
                    draft_app_config.get("mcp_tool_snapshots", []),
                )
            )

        if skill_service is not None and app_id is not None:
            tools.extend(
                skill_service.get_langchain_tools_by_skill_bindings(
                    draft_app_config.get("skills", []),
                    runtime_context={
                        "app_id": str(app_id),
                        "account_id": str(account.id),
                    },
                )
            )

        # 知识库检索工具构建：仅使用新版 knowledge_base_ids 调用分层检索
        knowledge_base_ids = list(draft_app_config.get("knowledge_base_ids") or [])

        if knowledge_base_ids:
            runtime_flask_app = flask_app or current_app._get_current_object()
            retrieval_config = draft_app_config.get("retrieval_config", {}) or {}
            # 统一转换为 UUID 以兼容底层数据库查询
            kb_uuid_ids: list[UUID] = []
            for kb_id in knowledge_base_ids:
                if isinstance(kb_id, UUID):
                    kb_uuid_ids.append(kb_id)
                    continue
                try:
                    kb_uuid_ids.append(UUID(str(kb_id)))
                except Exception:
                    # 非法 id 直接跳过，不阻断工具构建
                    continue
            if kb_uuid_ids:
                knowledge_retrieval = retrieval_service.create_knowledge_retrieval_tool(
                    flask_app=runtime_flask_app,
                    knowledge_base_ids=kb_uuid_ids,
                    account_id=account.id,
                    retrieval_strategy=retrieval_config.get(
                        "retrieval_strategy", RetrievalStrategy.HYBRID.value
                    ),
                    k=retrieval_config.get("k", 4),
                )
                tools.append(knowledge_retrieval)

        if draft_app_config.get("workflows"):
            workflow_tools = app_config_service.get_langchain_tools_by_workflow_ids(
                [workflow["id"] for workflow in draft_app_config.get("workflows", [])]
            )
            tools.extend(workflow_tools)

        if app_service is not None and app_id is not None:
            get_agent_binding_tools = getattr(app_service, "get_langchain_tools_by_agent_bindings", None)
            if callable(get_agent_binding_tools):
                tools.extend(
                    get_agent_binding_tools(
                        draft_app_config.get("agent_bindings", []),
                        account=account,
                        app_id=app_id,
                        flask_app=flask_app,
                        runtime_context=runtime_context,
                    )
                )

        # 治理注入门：在 return 前过滤 BaseTool 列表（governance_gate=None 时行为不变）
        if governance_gate is not None:
            tool_id_hints = AppRuntimeService.build_tool_id_hints(draft_app_config)
            if governance_context is None:
                # 未显式提供 context 时，按 OrchestrationFeatureFlag 解析当前治理模式
                ctx = AppRuntimeService.resolve_default_governance_context(
                    app_id=str(app_id) if app_id else None
                )
            else:
                ctx = governance_context
            # mode=disabled 时完全跳过治理（OBSERVE_ONLY 开关关闭且未开启阻断）
            if ctx.get("mode") == "disabled":
                return tools
            tools, audit_context = governance_gate.apply(
                tools,
                account_id=ctx.get("account_id"),
                app_id=str(app_id) if app_id else None,
                agent_pool=ctx.get("agent_pool"),
                budget_level=ctx.get("budget_level", "medium"),
                allow_confirmation=ctx.get("allow_confirmation", False),
                tool_id_hints=tool_id_hints,
                observe_only=bool(ctx.get("observe_only", True)),
                block_sensitive_only=bool(ctx.get("block_sensitive_only", False)),
            )
            # 阶段1渐进式启用：将治理决策持久化到路由日志（观测期覆盖率 ≥ 95%）
            # 写入失败不阻断主流程（GovernanceAuditLogger 内部 try/except 降级为 warning）
            AppRuntimeService.log_governance_audit(
                audit_context,
                runtime_context=runtime_context,
                account_id=str(account.id) if account else None,
                app_id=str(app_id) if app_id else None,
            )

        return tools

    @staticmethod
    def resolve_default_governance_context(app_id: str | None = None) -> dict[str, Any]:
        """governance_gate 启用但未显式提供 governance_context 时，按 OrchestrationFeatureFlag
        解析当前池治理模式（阶段1/2/3），构建默认 context。

        解析异常或表缺失时降级为 {"observe_only": True}（阶段1，安全默认），
        保证向后兼容：governance_gate=None 时本方法不会被调用。
        """
        try:
            from internal.extension.database_extension import db as _db
            from .governance_mode_resolver import GovernanceModeResolver

            return GovernanceModeResolver(db=_db).build_governance_context(
                app_id=app_id
            )
        except Exception:
            # 任何异常都降级为阶段1（只观测不阻断），避免阻断主链路
            return {"observe_only": True, "block_sensitive_only": False, "mode": "observe_only"}

    @staticmethod
    def log_governance_audit(
        audit_context: dict[str, Any] | None,
        *,
        runtime_context: dict[str, Any] | None = None,
        account_id: str | None = None,
        app_id: str | None = None,
    ) -> None:
        """将治理决策持久化到路由日志（阶段1渐进式启用观测期）。

        best-effort：从 runtime_context 或 flask g 获取 request_id/conversation_id/message_id，
        写入失败不阻断主流程（GovernanceAuditLogger 内部 try/except 降级为 warning）。
        governance_gate=None 时本方法不会被调用。

        字段语义：
            - account_id: 写入 routing_log.account_id FK（必须是 account 表中的真实账号）
            - actor_id: 实际触发治理决策的 actor（如 WebApp 访客 ID），仅写入 routing_decision 上下文
            - conversation_id: 写入 routing_decision 上下文，便于按会话追溯
            - message_id: 写入 routing_log.message_id 字段，关联具体消息记录

        WebApp 访客场景：account_id 参数可能是访客 ID（不在 account 表中），
        runtime_context.governance_account_id 是 app owner 的 account_id（FK 有效）。
        此时用 governance_account_id 作为 FK，原 account_id 作为 actor_id 用于追溯。
        """
        if not audit_context:
            logger.debug("governance_audit_log skipped: empty audit_context (app_id=%s)", app_id)
            return
        try:
            from .governance_audit_logger import GovernanceAuditLogger

            runtime_context = runtime_context or {}
            request_id = runtime_context.get("request_id")
            conversation_id = runtime_context.get("conversation_id")
            message_id = runtime_context.get("message_id")

            # WebApp 访客场景：governance_account_id 是 app owner（FK 有效）
            # 优先使用 governance_account_id 作为 routing_log.account_id FK，
            # 原 account_id 降级为 actor_id 写入 routing_decision 上下文用于追溯
            governance_account_id = runtime_context.get("governance_account_id")
            if governance_account_id:
                fk_account_id = governance_account_id
                actor_id = account_id
            else:
                fk_account_id = account_id
                actor_id = None

            # best-effort：runtime_context 没有时尝试 flask g
            if request_id is None and has_app_context():
                try:
                    request_id = getattr(g, "request_id", None)
                except Exception:
                    request_id = None

            GovernanceAuditLogger().log_governance_decision(
                audit_context,
                request_id=request_id,
                conversation_id=conversation_id,
                message_id=message_id,
                account_id=fk_account_id,
                app_id=app_id,
                actor_id=actor_id,
            )
        except Exception:
            # 双重保险：即使 GovernanceAuditLogger 内部异常漏出也不阻断主流程
            logger.warning("governance_audit_log skipped: logger invocation failed", exc_info=True)

    @staticmethod
    def build_tool_id_hints(draft_app_config: dict[str, Any]) -> dict[str, str]:
        """从 draft_app_config 提取 {runtime_name: tool_id} 映射，供治理门精确匹配。

        仅提取 runtime_name 可靠确定的类别：
        - agent_bindings: runtime_name = f"agent_app_{app_id去横线}"（与 AppConfigService._build_agent_runtime_tool_name 一致）

        其余类别（workflows/skills/mcp_bindings/tools/datasets）因 runtime_name 依赖运行时
        展开或 DB 查询（如 workflow 的 tool_call_name、skill 的 source_key+tool_name、mcp 的
        binding_name+raw_tool_name），暂时跳过，治理门会降级到 name 模式匹配或默认策略。
        每类提取均包裹 try/except，失败时跳过该类不报错。
        """
        hints: dict[str, str] = {}
        if not isinstance(draft_app_config, dict):
            return hints

        # agent_bindings: runtime_name = f"agent_app_{app_id去横线}"
        try:
            for item in draft_app_config.get("agent_bindings", []) or []:
                if not isinstance(item, dict):
                    continue
                bound_app_id = str(item.get("app_id", "") or "").strip()
                if not bound_app_id:
                    continue
                runtime_name = f"agent_app_{bound_app_id.replace('-', '')}"
                hints[runtime_name] = build_tool_id("agent_binding", bound_app_id)
        except Exception:
            pass

        return hints

    @staticmethod
    def build_agent_binding_prompt_appendix(agent_bindings: list[dict[str, Any]] | None) -> str:
        """把已绑定 Agent 的名称、描述和调用模式拼成一段额外提示词。"""
        if not isinstance(agent_bindings, list) or not agent_bindings:
            return ""

        sections: list[str] = []
        for binding in agent_bindings:
            if not isinstance(binding, dict):
                continue

            title = str(binding.get("name") or binding.get("description") or binding.get("app_id") or "Agent").strip()
            description = str(binding.get("description") or "").strip()
            runtime_tool_name = str(binding.get("tool_name") or "").strip()
            invoke_mode = str(binding.get("invoke_mode") or "tool").strip().lower() or "tool"
            source_scope = str(binding.get("source_scope") or "").strip()

            bullet = f"- {title}"
            if description:
                bullet += f"：{description}"
            if source_scope:
                bullet += f"（{source_scope}）"
            bullet += "；"
            bullet += "通过 A2A 协议委派" if invoke_mode == "a2a" else "通过内部工具包装委派"
            if runtime_tool_name:
                bullet += f"；工具名：{runtime_tool_name}"
            sections.append(bullet)

        if not sections:
            return ""

        return (
            "## 已绑定 Agent 子应用\n\n"
            "如果用户的问题明显适合交给子应用处理，请优先调用对应工具，不要自己凭空编造结果。\n\n"
            + "\n".join(sections)
        )

    @staticmethod
    def push_runtime_context(runtime_context: dict[str, Any] | None, next_app_id: UUID | str) -> dict[str, Any]:
        """把下一跳 app_id 压入运行时上下文调用栈。"""
        context = dict(runtime_context or {})
        normalized_next_app_id = str(next_app_id).strip()
        call_stack = [
            str(app_id).strip()
            for app_id in (context.get("call_stack") or [])
            if str(app_id).strip()
        ]
        if not call_stack:
            root_app_id = str(context.get("root_app_id") or normalized_next_app_id).strip() or normalized_next_app_id
            call_stack = [root_app_id]
            context["root_app_id"] = root_app_id

        if normalized_next_app_id and (not call_stack or call_stack[-1] != normalized_next_app_id):
            call_stack.append(normalized_next_app_id)

        context["call_stack"] = call_stack
        context["root_app_id"] = str(context.get("root_app_id") or call_stack[0]).strip() or call_stack[0]
        return context

    @staticmethod
    def extract_a2a_answer_text(response: dict[str, Any]) -> str:
        """从公共 A2A 响应中提取可返回给工具的纯文本答案。"""
        if not isinstance(response, dict):
            return ""

        message = response.get("message", {})
        if isinstance(message, dict):
            parts = message.get("parts", [])
            if isinstance(parts, list):
                text_parts: list[str] = []
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    if str(part.get("type", "")).strip() != "text":
                        continue
                    text = str(part.get("text", "")).strip()
                    if text:
                        text_parts.append(text)
                if text_parts:
                    return "\n".join(text_parts).strip()

        metadata = response.get("metadata", {})
        if isinstance(metadata, dict):
            error = str(metadata.get("error", "")).strip()
            if error:
                return error
            status = str(metadata.get("status", "")).strip()
            if status:
                return status

        return ""

    def get_langchain_tools_by_agent_bindings(
        self,
        agent_bindings: list[dict[str, Any]] | None,
        *,
        account: Account | None,
        app_id: UUID,
        flask_app: Any | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> list[BaseTool]:
        """根据 Agent 绑定列表生成 LangChain 工具。"""
        if not isinstance(agent_bindings, list) or not agent_bindings:
            return []

        tools: list[BaseTool] = []
        normalized_runtime_context = self.push_runtime_context(runtime_context, app_id)
        runtime_account_id_text = str(
            normalized_runtime_context.get("account_id")
            or getattr(account, "id", "")
            or ""
        ).strip()
        normalized_runtime_context["account_id"] = runtime_account_id_text
        runtime_account_id: UUID | str | None = None
        if runtime_account_id_text:
            try:
                runtime_account_id = UUID(runtime_account_id_text)
            except Exception:
                runtime_account_id = runtime_account_id_text
        runtime_account = SimpleNamespace(id=runtime_account_id)

        for binding in agent_bindings:
            if not isinstance(binding, dict):
                continue

            target_app_id = str(binding.get("app_id") or "").strip()
            if not target_app_id:
                continue

            tool_name = str(
                binding.get("tool_name") or self.app_config_service._build_agent_runtime_tool_name(target_app_id)
            ).strip()
            binding_title = str(binding.get("name") or binding.get("description") or target_app_id).strip()
            binding_description = str(binding.get("description") or "").strip()
            binding_invoke_mode = str(binding.get("invoke_mode") or "tool").strip().lower() or "tool"

            class AgentBindingQuery(BaseModel):
                """Agent 子应用输入结构。"""

                query: str = Field(description=f"需要委派给子应用 {binding_title} 处理的问题")

            def _invoke_agent_binding(query: str, *, _binding=binding, _tool_name=tool_name) -> str:
                """封装 Agent 子应用调用逻辑。"""
                try:
                    return self.invoke_agent_binding_target(
                        binding=_binding,
                        query=query,
                        account=runtime_account,
                        flask_app=flask_app,
                        runtime_context=normalized_runtime_context,
                    )
                except Exception as exc:
                    logging.exception("调用子 Agent 工具失败: tool_name=%s, error=%s", _tool_name, str(exc))
                    return f"调用子应用失败: {str(exc)}"

            delegate_tool = tool(tool_name, args_schema=AgentBindingQuery)(_invoke_agent_binding)
            delegate_tool.description = (
                f"委派给子应用 {binding_title} 执行。"
                f"{f' 描述: {binding_description}。' if binding_description else ''}"
                f" 调用模式: {'A2A' if binding_invoke_mode == 'a2a' else '内部工具'}。"
            ).strip()
            tools.append(delegate_tool)

        return tools

    def invoke_agent_binding_target(
        self,
        *,
        binding: dict[str, Any],
        query: str,
        account: Account | SimpleNamespace | None,
        flask_app: Any | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> str:
        """实际执行一个 Agent 子应用绑定。"""
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "用户问题为空，无法委派子应用"

        target_app_id = str(binding.get("app_id") or "").strip()
        if not target_app_id:
            return "子应用绑定缺少有效的 app_id"

        normalized_runtime_context = self.push_runtime_context(runtime_context, target_app_id)
        call_stack = [str(app_id).strip() for app_id in normalized_runtime_context.get("call_stack", []) if str(app_id).strip()]
        if len(call_stack) != len(set(call_stack)):
            return f"检测到 Agent 调用循环，已停止调用子应用 {target_app_id}"

        try:
            target_app_uuid = UUID(target_app_id)
        except Exception:
            return "子应用绑定的 app_id 格式错误"

        target_app = self.db.session.query(App).filter(
            App.id == target_app_uuid,
            App.status == AppStatus.PUBLISHED.value,
        ).one_or_none()
        if not target_app:
            return f"子应用 {target_app_id} 不存在或未发布，已自动跳过"

        caller_account_id = str(
            normalized_runtime_context.get("account_id")
            or getattr(account, "id", "")
            or ""
        ).strip()
        effective_invoke_mode = "a2a" if target_app.is_public else "tool"
        if effective_invoke_mode == "a2a":
            from .public_agent_a2a_service import PublicAgentA2AService

            public_agent_a2a_service = PublicAgentA2AService(
                db=self.db,
                app_runtime_service=self,
                app_config_service=self.app_config_service,
                language_model_service=self.language_model_service,
                public_agent_registry_service=self.public_agent_registry_service,
                conversation_service=self.conversation_service,
            )
            response = public_agent_a2a_service.send_message(
                target_app_id,
                {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": normalized_query}],
                    },
                    "metadata": {
                        "runtime_context": normalized_runtime_context,
                        **({"caller_account_id": caller_account_id} if caller_account_id else {}),
                    },
                },
                flask_app=flask_app,
            )
            return self.extract_a2a_answer_text(response) or "子应用已处理完成，但未返回文本答案"

        target_app_config = call_config_loader(
            self.app_config_service.get_app_config,
            target_app,
            persist_changes=False,
        )
        if hasattr(self.language_model_service, "resolve_runtime_language_model"):
            model_resolution = self.language_model_service.resolve_runtime_language_model(
                target_app_config.get("model_config", {}),
                image_urls=[],
                entrypoint=LanguageModelService.ENTRYPOINT_DEBUGGER,
            )
            llm = model_resolution.llm
        else:
            llm = self.language_model_service.load_language_model(target_app_config.get("model_config", {}))

        tools = self.build_runtime_tools(
            target_app.id,
            account,
            target_app_config,
            flask_app=flask_app,
            runtime_context=normalized_runtime_context,
        )
        agent = self.create_runtime_agent(
            llm,
            account,
            target_app_config,
            tools,
            flask_app=flask_app,
            language_model_service=self.language_model_service,
            invoke_from=InvokeFrom.DEBUGGER.value,
        )
        agent_result = agent.invoke(
            {
                "messages": [llm.convert_to_human_message(normalized_query, [])],
                "history": [],
                "long_term_memory": "",
            }
        )
        return str(getattr(agent_result, "answer", "") or "").strip() or "子应用已处理完成，但未返回文本答案"

    @classmethod
    def create_runtime_agent(
        cls,
        llm: Any,
        account: Account,
        draft_app_config: dict[str, Any],
        tools: list[Any],
        enable_deep_thinking: bool = False,
        flask_app: Any | None = None,
        language_model_service: Any | None = None,
        invoke_from: InvokeFrom = InvokeFrom.DEBUGGER.value,
    ) -> FunctionCallAgent | ReACTAgent | DeepThinkingAgent:
        """根据运行时配置创建Agent实例

        enable_deep_thinking=True 时选择 DeepThinkingAgent，
        否则按模型能力选择 FunctionCallAgent 或 ReACTAgent。
        """
        if enable_deep_thinking:
            agent_class = DeepThinkingAgent
        else:
            agent_class = FunctionCallAgent if ModelFeature.TOOL_CALL.value in (getattr(llm, "features", None) or []) else ReACTAgent

        skill_prompt_appendix = cls.build_skill_prompt_appendix(draft_app_config.get("skills", []))
        agent_binding_prompt_appendix = cls.build_agent_binding_prompt_appendix(
            draft_app_config.get("agent_bindings", [])
        )
        mcp_prompt_appendix = cls.build_mcp_prompt_appendix(draft_app_config.get("mcp_bindings", []))
        mcp_snapshot_prompt_appendix = cls.build_mcp_snapshot_prompt_appendix(
            draft_app_config.get("mcp_tool_snapshots", [])
        )
        runtime_mcp_tools_prompt_appendix = cls.build_runtime_mcp_tools_prompt_appendix(tools)
        preset_prompt = draft_app_config["preset_prompt"]
        prompt_parts = [preset_prompt.strip()]
        if skill_prompt_appendix:
            prompt_parts.append(skill_prompt_appendix.strip())
        if agent_binding_prompt_appendix:
            prompt_parts.append(agent_binding_prompt_appendix.strip())
        if mcp_prompt_appendix:
            prompt_parts.append(mcp_prompt_appendix.strip())
        if mcp_snapshot_prompt_appendix:
            prompt_parts.append(mcp_snapshot_prompt_appendix.strip())
        if runtime_mcp_tools_prompt_appendix:
            prompt_parts.append(runtime_mcp_tools_prompt_appendix.strip())
        preset_prompt = "\n\n".join(part for part in prompt_parts if part)

        # 规范化 review_config：DB 默认可能是 {}，需合并默认值确保 enable/inputs_config 等键存在
        review_config = dict(DEFAULT_APP_CONFIG["review_config"])
        review_config.update(draft_app_config.get("review_config") or {})

        return agent_class(
            llm=llm,
            agent_config=AgentConfig(
                user_id=account.id,
                invoke_from=invoke_from,
                preset_prompt=preset_prompt,
                enable_long_term_memory=(draft_app_config.get("long_term_memory") or {}).get("enable", False),
                enable_deep_thinking=enable_deep_thinking,
                runtime_flask_app=flask_app,
                language_model_service=language_model_service,
                tools=tools,
                review_config=review_config,
            ),
        )

    def stream_agent_events(
        self,
        app_id: UUID,
        account: Account,
        draft_app_config: dict[str, Any],
        llm: Any,
        query: str,
        image_urls: list[str],
        history: list[Any],
        long_term_memory: str,
        conversation_id: str = "",
        message_id: str = "",
        agent_thoughts: dict[str, Any] | None = None,
        enable_deep_thinking: bool = False,
        flask_app: Any | None = None,
    ) -> Generator[str, None, None]:
        """统一流式执行应用Agent并输出事件"""
        tools = self.build_runtime_tools(app_id, account, draft_app_config, flask_app=flask_app)
        agent = self.create_runtime_agent(
            llm,
            account,
            draft_app_config,
            tools,
            enable_deep_thinking,
            flask_app=flask_app,
            language_model_service=self.language_model_service,
        )
        agent_thoughts = agent_thoughts if agent_thoughts is not None else {}

        for agent_thought in agent.stream({
            "messages": [llm.convert_to_human_message(query, image_urls)],
            "history": history,
            "long_term_memory": long_term_memory,
        }):
            event_id = str(agent_thought.id)

            if agent_thought.event != QueueEvent.PING.value:
                if agent_thought.event == QueueEvent.AGENT_MESSAGE.value:
                    if event_id not in agent_thoughts:
                        agent_thoughts[event_id] = agent_thought
                    else:
                        agent_thoughts[event_id] = agent_thoughts[event_id].model_copy(update={
                            "thought": agent_thoughts[event_id].thought + agent_thought.thought,
                            "message": agent_thought.message,
                            "message_token_count": agent_thought.message_token_count,
                            "message_unit_price": agent_thought.message_unit_price,
                            "message_price_unit": agent_thought.message_price_unit,
                            "answer": agent_thoughts[event_id].answer + agent_thought.answer,
                            "answer_token_count": agent_thought.answer_token_count,
                            "answer_unit_price": agent_thought.answer_unit_price,
                            "answer_price_unit": agent_thought.answer_price_unit,
                            "total_token_count": agent_thought.total_token_count,
                            "total_price": agent_thought.total_price,
                            "latency": agent_thought.latency,
                        })
                else:
                    agent_thoughts[event_id] = agent_thought

            usage_summary = summarize_agent_thoughts(agent_thoughts.values())
            data = {
                **agent_thought.model_dump(include={
                    "event", "thought", "observation", "tool", "tool_input", "answer",
                    "total_token_count", "total_price", "latency",
                }),
                "aggregate_total_token_count": usage_summary.total_token_count,
                "aggregate_total_price": usage_summary.total_price,
                "aggregate_latency": usage_summary.latency,
                "id": event_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "task_id": str(agent_thought.task_id),
            }
            yield f"event: {agent_thought.event.value}\ndata:{json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    async def stream_agent_events_async(
        self,
        app_id: UUID,
        account: Account,
        draft_app_config: dict[str, Any],
        llm: Any,
        query: str,
        image_urls: list[str],
        history: list[Any],
        long_term_memory: str,
        conversation_id: str = "",
        message_id: str = "",
        agent_thoughts: dict[str, Any] | None = None,
        enable_deep_thinking: bool = False,
        flask_app: Any | None = None,
    ) -> AsyncGenerator[str, None]:
        """统一流式执行应用Agent并输出事件（async 版，供 ASGI/Quart 链路使用）。

        与 stream_agent_events 逻辑一致，但消费 agent.astream（事件循环中执行，
        LLM 节点已 async 化），不占用额外子线程，是并发承载优化的推荐路径。
        """
        tools = await asyncio.to_thread(
            self.build_runtime_tools,
            app_id,
            account,
            draft_app_config,
            flask_app=flask_app,
        )
        agent = self.create_runtime_agent(
            llm,
            account,
            draft_app_config,
            tools,
            enable_deep_thinking,
            flask_app=flask_app,
            language_model_service=self.language_model_service,
        )
        agent_thoughts = agent_thoughts if agent_thoughts is not None else {}

        async for agent_thought in agent.astream({
            "messages": [llm.convert_to_human_message(query, image_urls)],
            "history": history,
            "long_term_memory": long_term_memory,
        }):
            event_id = str(agent_thought.id)

            if agent_thought.event != QueueEvent.PING.value:
                if agent_thought.event == QueueEvent.AGENT_MESSAGE.value:
                    if event_id not in agent_thoughts:
                        agent_thoughts[event_id] = agent_thought
                    else:
                        agent_thoughts[event_id] = agent_thoughts[event_id].model_copy(update={
                            "thought": agent_thoughts[event_id].thought + agent_thought.thought,
                            "message": agent_thought.message,
                            "message_token_count": agent_thought.message_token_count,
                            "message_unit_price": agent_thought.message_unit_price,
                            "message_price_unit": agent_thought.message_price_unit,
                            "answer": agent_thoughts[event_id].answer + agent_thought.answer,
                            "answer_token_count": agent_thought.answer_token_count,
                            "answer_unit_price": agent_thought.answer_unit_price,
                            "answer_price_unit": agent_thought.answer_price_unit,
                            "total_token_count": agent_thought.total_token_count,
                            "total_price": agent_thought.total_price,
                            "latency": agent_thought.latency,
                        })
                else:
                    agent_thoughts[event_id] = agent_thought

            usage_summary = summarize_agent_thoughts(agent_thoughts.values())
            data = {
                **agent_thought.model_dump(include={
                    "event", "thought", "observation", "tool", "tool_input", "answer",
                    "total_token_count", "total_price", "latency",
                }),
                "aggregate_total_token_count": usage_summary.total_token_count,
                "aggregate_total_price": usage_summary.total_price,
                "aggregate_latency": usage_summary.latency,
                "id": event_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "task_id": str(agent_thought.task_id),
            }
            yield f"event: {agent_thought.event.value}\ndata:{json.dumps(data, ensure_ascii=False, default=str)}\n\n"
