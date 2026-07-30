import logging
from dataclasses import dataclass
from copy import deepcopy
from inspect import Parameter, signature
from typing import Any, Union
from uuid import UUID

from flask import g, has_app_context
from injector import inject
from langchain_core.tools import BaseTool
from internal.core.language_model import LanguageModelManager
from internal.core.tools.api_tools.entities import ToolEntity
from internal.core.tools.api_tools.providers import ApiProviderManager
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from internal.core.tools.mcp_tools.providers import McpToolFactory
from .skill_service import SkillService
from internal.lib.helper import datetime_to_timestamp, get_value_type
from internal.model import App, ApiTool, KnowledgeBase, AppConfig, AppConfigVersion, Workflow
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from internal.core.language_model.entities.model_entity import ModelParameterType
from internal.entity.app_entity import DEFAULT_APP_CONFIG, AppStatus
from internal.entity.workflow_entity import WorkflowStatus
from internal.core.workflow.workflow import WorkflowToolAdapter as WorkflowTool
from ..core.workflow.entities.workflow_entity import WorkflowConfig
from internal.exception import NotFoundException, ValidateErrorException

logger = logging.getLogger(__name__)


def call_config_loader(loader: Any, app: App, *, persist_changes: bool) -> dict[str, Any]:
    """调用 app 配置读取函数。

    兼容旧的单参数调用方，同时允许支持 `persist_changes` 的新实现显式关闭读时写回。
    """
    try:
        loader_signature = signature(loader)
    except (TypeError, ValueError):
        loader_signature = None

    if loader_signature is not None:
        parameters = loader_signature.parameters
        accepts_persist_changes = (
            "persist_changes" in parameters
            or any(param.kind == Parameter.VAR_KEYWORD for param in parameters.values())
        )
        if accepts_persist_changes:
            return loader(app, persist_changes=persist_changes)

    return loader(app)


@inject
@dataclass
class AppConfigService(BaseService):
    """应用配置服务"""
    db: SQLAlchemy
    api_provider_manager: ApiProviderManager
    language_model_manager: LanguageModelManager
    builtin_provider_manager: BuiltinProviderManager
    skill_service: SkillService | None = None

    def __post_init__(self) -> None:
        if self.skill_service is None:
            self.skill_service = SkillService(self.db)

    @staticmethod
    def _build_agent_runtime_tool_name(app_id: UUID | str) -> str:
        """生成子 Agent 工具名，确保在 LangChain 中唯一且稳定。"""
        return f"agent_app_{str(app_id).replace('-', '')}"

    @classmethod
    def _build_runtime_config_cache_key(
        cls,
        kind: str,
        *,
        app_config: AppConfig | AppConfigVersion,
        current_account_id: UUID | None = None,
        current_app_id: UUID | None = None,
    ) -> str:
        record_id = str(getattr(app_config, "id", "") or "")
        updated_at = getattr(app_config, "updated_at", None)
        created_at = getattr(app_config, "created_at", None)
        return "|".join(
            [
                str(kind or "").strip(),
                record_id,
                str(datetime_to_timestamp(updated_at)) if updated_at else "",
                str(datetime_to_timestamp(created_at)) if created_at else "",
                str(current_account_id or ""),
                str(current_app_id or getattr(app_config, "app_id", "") or ""),
            ]
        )

    @staticmethod
    def _get_runtime_config_cache() -> dict[str, dict[str, Any]]:
        """获取请求级配置缓存，避免同一请求重复做运行态校验。"""
        if not has_app_context():
            return {}

        cache = getattr(g, "_app_config_runtime_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            g._app_config_runtime_cache = cache
        return cache

    def _get_runtime_config_from_cache(self, cache_key: str) -> dict[str, Any] | None:
        cache = self._get_runtime_config_cache()
        cached_value = cache.get(cache_key)
        if not isinstance(cached_value, dict):
            return None
        return deepcopy(cached_value)

    def _set_runtime_config_cache(self, cache_key: str, value: dict[str, Any]) -> None:
        cache = self._get_runtime_config_cache()
        cache[cache_key] = deepcopy(value)

    def _has_agent_binding_path(
        self,
        source_app_id: UUID | str,
        target_app_id: UUID | str,
        current_account_id: UUID | None = None,
        visited: set[str] | None = None,
        depth: int = 0,
        max_depth: int = 12,
    ) -> bool:
        """判断 target_app_id 是否能通过已发布的 agent 绑定路径回到 source_app_id。"""
        normalized_source_app_id = str(source_app_id)
        normalized_target_app_id = str(target_app_id)
        if normalized_source_app_id == normalized_target_app_id:
            return True

        if depth >= max_depth:
            return True

        visited = visited or set()
        if normalized_target_app_id in visited:
            return False
        visited.add(normalized_target_app_id)

        try:
            target_uuid = UUID(normalized_target_app_id)
        except Exception:
            return False

        target_app = self.db.session.query(App).filter(
            App.id == target_uuid,
            App.status == AppStatus.PUBLISHED.value,
        ).one_or_none()
        if not target_app:
            return False

        if current_account_id is not None and not target_app.is_public and target_app.account_id != current_account_id:
            return False

        target_app_config = target_app.app_config
        if not target_app_config:
            return False

        for binding in getattr(target_app_config, "agent_bindings", []) or []:
            if not isinstance(binding, dict):
                continue

            nested_app_id = str(binding.get("app_id", "")).strip()
            if not nested_app_id:
                continue

            if nested_app_id == normalized_source_app_id:
                return True

            if self._has_agent_binding_path(
                normalized_source_app_id,
                nested_app_id,
                current_account_id=current_account_id,
                visited=visited,
                depth=depth + 1,
                max_depth=max_depth,
            ):
                return True

        return False

    def process_and_validate_agent_bindings(
        self,
        origin_agent_bindings: list[dict[str, Any]],
        *,
        current_account_id: UUID | None = None,
        current_app_id: UUID | None = None,
        strict: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """校验 Agent 绑定并返回展示信息与可落库信息。"""
        if not isinstance(origin_agent_bindings, list) or not origin_agent_bindings:
            return [], []

        normalized_origin_app_ids: list[UUID] = []
        normalized_origin_app_id_set: set[str] = set()

        for binding in origin_agent_bindings:
            if not isinstance(binding, dict):
                continue

            app_id_text = str(binding.get("app_id", "")).strip()
            if not app_id_text:
                continue

            try:
                app_uuid = UUID(app_id_text)
            except Exception:
                if strict:
                    raise ValidateErrorException("Agent绑定的应用ID必须为UUID")
                continue

            normalized_app_id = str(app_uuid)
            if current_app_id is not None and normalized_app_id == str(current_app_id):
                if strict:
                    raise ValidateErrorException("不能绑定当前应用自身")
                continue

            if normalized_app_id in normalized_origin_app_id_set:
                if strict:
                    raise ValidateErrorException("绑定Agent存在重复")
                continue

            normalized_origin_app_ids.append(app_uuid)
            normalized_origin_app_id_set.add(normalized_app_id)

        if not normalized_origin_app_ids:
            return [], []

        target_records = self.db.session.query(App).filter(
            App.id.in_(normalized_origin_app_ids),
            App.status == AppStatus.PUBLISHED.value,
        ).all()
        target_record_map = {str(target_app.id): target_app for target_app in target_records}

        display_bindings: list[dict[str, Any]] = []
        validate_bindings: list[dict[str, Any]] = []

        for app_uuid in normalized_origin_app_ids:
            target_app = target_record_map.get(str(app_uuid))
            if not target_app:
                continue

            if current_account_id is None:
                if not target_app.is_public:
                    continue
            else:
                if not target_app.is_public and target_app.account_id != current_account_id:
                    continue

            if current_app_id is not None and self._has_agent_binding_path(
                current_app_id,
                target_app.id,
                current_account_id=current_account_id,
            ):
                if strict:
                    raise ValidateErrorException("Agent绑定存在循环引用")
                continue

            invoke_mode = "a2a" if target_app.is_public else "tool"
            normalized_binding = {
                "app_id": str(target_app.id),
                "invoke_mode": invoke_mode,
            }
            validate_bindings.append(normalized_binding)
            display_bindings.append({
                **normalized_binding,
                "name": target_app.name,
                "icon": target_app.icon,
                "description": target_app.description,
                "source_scope": "public" if target_app.is_public else "own",
                "is_public": target_app.is_public,
                "status": target_app.status,
                "tool_name": self._build_agent_runtime_tool_name(target_app.id),
            })

        return display_bindings, validate_bindings

    def get_draft_app_config(self, app: App, persist_changes: bool = True) -> dict[str, Any]:
        """根据传递的应用获取该应用的草稿配置"""
        # 1.提取应用的草稿配置
        draft_app_config = app.draft_app_config
        cache_key = self._build_runtime_config_cache_key(
            "draft",
            app_config=draft_app_config,
            current_account_id=getattr(app, "account_id", None),
            current_app_id=getattr(app, "id", None),
        )
        if not persist_changes:
            cached_value = self._get_runtime_config_from_cache(cache_key)
            if cached_value is not None:
                return cached_value

        # 2.校验model_config配置信息，如果使用了不存在的提供者或者模型 则使用默认值(宽松校验)
        validate_model_config = self._process_and_validate_model_config(draft_app_config.model_config)
        if persist_changes and draft_app_config.model_config != validate_model_config:
            self.update(draft_app_config, model_config=validate_model_config)

        # 3.循环遍历工具列表删除已经被删除的工具信息
        tools, validate_tools = self._process_and_validate_tools(draft_app_config.tools)

        # 4.判断是否需要更新草稿配置中的工具列表信息
        if persist_changes and draft_app_config.tools != validate_tools:
            # 14.更新草稿配置中的工具列表
            self.update(draft_app_config, tools=validate_tools)

        # 5.校验知识库列表，如果引用了不存在/被删除的知识库，需要剔除数据并更新，同时获取知识库的额外信息
        # 新版：优先校验 knowledge_base_ids（App 配置主用字段），并加 owner/scope 权限校验
        knowledge_bases, validate_knowledge_base_ids = self._process_and_validate_knowledge_base_ids(
            getattr(draft_app_config, "knowledge_base_ids", []),
            current_account_id=getattr(app, "account_id", None),
        )
        if persist_changes and set(validate_knowledge_base_ids) != set(
            getattr(draft_app_config, "knowledge_base_ids", [])
        ):
            self.update(draft_app_config, knowledge_base_ids=validate_knowledge_base_ids)

        # 7.校验工作流列表对应的数据
        workflows, validate_workflows = self._process_and_validate_workflows(draft_app_config.workflows)
        if persist_changes and set(validate_workflows) != set(draft_app_config.workflows):
            self.update(draft_app_config, workflows=validate_workflows)

        # 8.读取并规范化 MCP 绑定列表
        mcp_bindings, validate_mcp_bindings = self._process_and_validate_mcp_bindings(
            getattr(draft_app_config, "mcp_bindings", [])
        )
        if getattr(draft_app_config, "mcp_bindings", []) != validate_mcp_bindings:
            self.update(draft_app_config, mcp_bindings=validate_mcp_bindings)

        # 9.读取并规范化 MCP 工具快照
        mcp_tool_snapshots, validate_mcp_tool_snapshots = self._process_and_validate_mcp_tool_snapshots(
            getattr(draft_app_config, "mcp_tool_snapshots", []),
            validate_mcp_bindings,
        )
        if getattr(draft_app_config, "mcp_tool_snapshots", []) != validate_mcp_tool_snapshots:
            self.update(draft_app_config, mcp_tool_snapshots=validate_mcp_tool_snapshots)

        # 10.读取并规范化 Skills 绑定列表
        skills, validate_skills = self.skill_service.process_and_validate_skill_bindings(
            getattr(draft_app_config, "skills", [])
        )
        if getattr(draft_app_config, "skills", []) != validate_skills:
            self.update(draft_app_config, skills=validate_skills)

        # 11.读取并规范化 Agent 绑定列表
        agent_bindings, validate_agent_bindings = self.process_and_validate_agent_bindings(
            getattr(draft_app_config, "agent_bindings", []),
            current_account_id=getattr(app, "account_id", None),
            current_app_id=getattr(app, "id", None),
        )
        if getattr(draft_app_config, "agent_bindings", []) != validate_agent_bindings:
            self.update(draft_app_config, agent_bindings=validate_agent_bindings)

        # 12.将数据转换成字典后返回
        result = self._process_and_transformer_app_config(
            validate_model_config,
            tools,
            workflows,
            mcp_bindings,
            mcp_tool_snapshots,
            skills,
            agent_bindings,
            draft_app_config,
            knowledge_bases,
        )
        if not persist_changes:
            self._set_runtime_config_cache(cache_key, result)
        return result

    def get_app_config(self, app: App, persist_changes: bool = True) -> dict[str, Any]:
        """根据传递的应用获取该应用的运行配置"""
        # 1.提取应用的草稿配置
        app_config = app.app_config
        cache_key = self._build_runtime_config_cache_key(
            "published",
            app_config=app_config,
            current_account_id=getattr(app, "account_id", None),
            current_app_id=getattr(app, "id", None),
        )
        if not persist_changes:
            cached_value = self._get_runtime_config_from_cache(cache_key)
            if cached_value is not None:
                return cached_value

        # 2.校验model_config配置信息，如果使用了不存在的提供者或者模型 则使用默认值(宽松校验)
        validate_model_config = self._process_and_validate_model_config(app_config.model_config)
        if persist_changes and app_config.model_config != validate_model_config:
            self.update(app_config, model_config=validate_model_config)

        # 3.循环遍历工具列表删除已经被删除的工具信息
        tools, validate_tools = self._process_and_validate_tools(app_config.tools)

        # 4.判断是否需要更新草稿配置中的工具列表信息
        if persist_changes and app_config.tools != validate_tools:
            # 14.更新草稿配置中的工具列表
            self.update(app_config, tools=validate_tools)

        # 5.校验知识库列表，如果引用了不存在/被删除的知识库，需要剔除数据并更新，同时获取知识库的额外信息
        # 校验 knowledge_base_ids（AppConfig.knowledge_base_ids 列），并加 owner/scope 权限校验
        knowledge_bases, validate_knowledge_base_ids = self._process_and_validate_knowledge_base_ids(
            getattr(app_config, "knowledge_base_ids", []),
            current_account_id=getattr(app, "account_id", None),
        )
        if persist_changes and set(validate_knowledge_base_ids) != set(
            getattr(app_config, "knowledge_base_ids", [])
        ):
            self.update(app_config, knowledge_base_ids=validate_knowledge_base_ids)

        # 7.校验工作流列表对应的数据
        workflows, validate_workflows = self._process_and_validate_workflows(app_config.workflows)
        if persist_changes and set(validate_workflows) != set(app_config.workflows):
            self.update(app_config, workflows=validate_workflows)

        # 8.读取并规范化 MCP 绑定列表
        mcp_bindings, validate_mcp_bindings = self._process_and_validate_mcp_bindings(
            getattr(app_config, "mcp_bindings", [])
        )
        if getattr(app_config, "mcp_bindings", []) != validate_mcp_bindings:
            self.update(app_config, mcp_bindings=validate_mcp_bindings)

        # 9.读取并规范化 MCP 工具快照
        mcp_tool_snapshots, validate_mcp_tool_snapshots = self._process_and_validate_mcp_tool_snapshots(
            getattr(app_config, "mcp_tool_snapshots", []),
            validate_mcp_bindings,
        )
        if getattr(app_config, "mcp_tool_snapshots", []) != validate_mcp_tool_snapshots:
            self.update(app_config, mcp_tool_snapshots=validate_mcp_tool_snapshots)

        # 10.读取并规范化 Skills 绑定列表
        skills, validate_skills = self.skill_service.process_and_validate_skill_bindings(
            getattr(app_config, "skills", [])
        )
        if getattr(app_config, "skills", []) != validate_skills:
            self.update(app_config, skills=validate_skills)

        # 11.读取并规范化 Agent 绑定列表
        agent_bindings, validate_agent_bindings = self.process_and_validate_agent_bindings(
            getattr(app_config, "agent_bindings", []),
            current_account_id=getattr(app, "account_id", None),
            current_app_id=getattr(app, "id", None),
        )
        if getattr(app_config, "agent_bindings", []) != validate_agent_bindings:
            self.update(app_config, agent_bindings=validate_agent_bindings)

        # 12.将数据转换成字典后返回
        result = self._process_and_transformer_app_config(
            validate_model_config,
            tools,
            workflows,
            mcp_bindings,
            mcp_tool_snapshots,
            skills,
            agent_bindings,
            app_config,
            knowledge_bases,
        )
        if not persist_changes:
            self._set_runtime_config_cache(cache_key, result)
        return result

    def get_version_display_config(
        self,
        app_config_version: AppConfig | AppConfigVersion,
        current_account_id: UUID | None = None,
        current_app_id: UUID | None = None,
    ) -> dict[str, Any]:
        """根据传递的版本配置，返回用于前端展示的完整配置结构。"""
        cache_key = self._build_runtime_config_cache_key(
            "version_display",
            app_config=app_config_version,
            current_account_id=current_account_id,
            current_app_id=current_app_id,
        )
        cached_value = self._get_runtime_config_from_cache(cache_key)
        if cached_value is not None:
            return cached_value

        validate_model_config = self._process_and_validate_model_config(app_config_version.model_config)
        tools, _ = self._process_and_validate_tools(app_config_version.tools)
        # 新版：校验 knowledge_base_ids（AppConfigVersion.knowledge_base_ids 列），并加 owner/scope 权限校验
        knowledge_bases, _ = self._process_and_validate_knowledge_base_ids(
            getattr(app_config_version, "knowledge_base_ids", []),
            current_account_id=current_account_id,
        )
        workflows, _ = self._process_and_validate_workflows(app_config_version.workflows)
        mcp_bindings, _ = self._process_and_validate_mcp_bindings(getattr(app_config_version, "mcp_bindings", []))
        mcp_tool_snapshots, _ = self._process_and_validate_mcp_tool_snapshots(
            getattr(app_config_version, "mcp_tool_snapshots", []),
            mcp_bindings,
        )
        skills, _ = self.skill_service.process_and_validate_skill_bindings(getattr(app_config_version, "skills", []))
        agent_bindings, _ = self.process_and_validate_agent_bindings(
            getattr(app_config_version, "agent_bindings", []),
            current_account_id=current_account_id,
            current_app_id=current_app_id,
        )

        result = self._process_and_transformer_app_config(
            validate_model_config,
            tools,
            workflows,
            mcp_bindings,
            mcp_tool_snapshots,
            skills,
            agent_bindings,
            app_config_version,
            knowledge_bases,
        )
        self._set_runtime_config_cache(cache_key, result)
        return result

    def get_langchain_tools_by_mcp_bindings(
        self,
        mcp_bindings: list[dict],
        mcp_tool_snapshots: list[dict] | None = None,
    ) -> list[BaseTool]:
        """根据传递的 MCP 绑定列表获取 LangChain 工具。"""
        if not isinstance(mcp_bindings, list):
            return []
        return McpToolFactory().get_tools(mcp_bindings, mcp_tool_snapshots=mcp_tool_snapshots)

    def prepare_mcp_tool_snapshots(
        self,
        mcp_bindings: list[dict],
        existing_snapshots: list[dict] | None = None,
    ) -> list[dict]:
        """根据 MCP 绑定生成预热快照，不进行远端发现。"""
        return McpToolFactory().prepare_binding_snapshots(mcp_bindings, existing_snapshots)

    def refresh_mcp_tool_snapshots(
        self,
        mcp_bindings: list[dict],
        existing_snapshots: list[dict] | None = None,
    ) -> list[dict]:
        """根据 MCP 绑定刷新远端快照。"""
        return McpToolFactory().refresh_binding_snapshots(mcp_bindings, existing_snapshots)

    def get_langchain_tools_by_tools_config(self, tools_config: list[dict]) -> list[BaseTool]:
        """根据传递的工具配置列表获取langchain工具列表"""
        # 1.循环遍历所有工具配置列表信息
        tools = []
        for tool in tools_config:
            # 2.根据不同的工具类型执行不同的操作
            if tool["type"] == "builtin_tool":
                # 3.内置工具，通过builtin_provider_manager获取工具实例
                builtin_tool = self.builtin_provider_manager.get_tool(
                    tool["provider"]["id"],
                    tool["tool"]["name"]
                )
                if not builtin_tool:
                    continue
                try:
                    tools.append(builtin_tool(**tool["tool"]["params"]))
                except Exception as exc:
                    # 工具实例化失败（如依赖缺失、凭证无效）时跳过，避免单个工具阻断整个流程
                    logger.warning(
                        "内置工具实例化失败，已跳过 provider=%s tool=%s: %s",
                        tool["provider"].get("id"), tool["tool"].get("name"), exc,
                    )
                    continue
            else:
                # 4.API工具，首先根据id找到ApiTool记录，然后创建示例
                api_tool = self.get(ApiTool, tool["tool"]["id"])
                if not api_tool:
                    continue
                tools.append(
                    self.api_provider_manager.get_tool(
                        ToolEntity(
                            id=str(api_tool.id),
                            name=api_tool.name,
                            url=api_tool.url,
                            method=api_tool.method,
                            description=api_tool.description,
                            headers=api_tool.provider.headers,
                            parameters=api_tool.parameters,
                        )
                    )
                )

        return tools

    def get_langchain_tools_by_workflow_ids(self, workflow_ids: list[UUID]) -> list[BaseTool]:
        """根据传递的工作流配置列表获取langchain工具列表"""
        # 1.根据传递的工作流id查询工作流信息
        workflow_records = self.db.session.query(Workflow).filter(
            Workflow.id.in_(workflow_ids),
            Workflow.status == WorkflowStatus.PUBLISHED.value
        )

        # 2.遍历所有工作流记录列表
        workflows = []
        for workflow_record in workflow_records:
            try:
                # 3.创建工作流工具
                workflow_tool = WorkflowTool(workflow_config=WorkflowConfig(
                    account_id=workflow_record.account_id,
                    name=f"wf_{workflow_record.tool_call_name}",
                    description=workflow_record.description,
                    nodes=workflow_record.graph.get("nodes", []),
                    edges=workflow_record.graph.get("edges", []),
                ))
                workflows.append(workflow_tool)
            except Exception as e:
                continue
        return workflows

    @classmethod
    def _process_and_transformer_app_config(
            cls,
            model_config: dict[str, Any],
            tools: list[dict],
            workflows: list[dict],
            mcp_bindings: list[dict],
            mcp_tool_snapshots: list[dict],
            skills: list[dict],
            agent_bindings: list[dict],
            app_config: Union[AppConfig, AppConfigVersion],
            knowledge_bases: list[dict] | None = None,
    ) -> dict[str, Any]:
        """根据传递的插件列表、工作流列表、知识库列表以及应用配置创建字典信息"""
        return {
            "id": str(app_config.id),
            "model_config": model_config,
            "dialog_round": app_config.dialog_round,
            "preset_prompt": app_config.preset_prompt,
            "tools": tools,
            "mcp_bindings": mcp_bindings,
            "mcp_tool_snapshots": mcp_tool_snapshots,
            "skills": skills,
            "agent_bindings": agent_bindings,
            "workflows": workflows,
            # 新版 knowledge_base_ids + 展示信息（App 配置主用字段）
            "knowledge_base_ids": [
                str(kb["id"]) for kb in (knowledge_bases or [])
            ],
            "knowledge_bases": knowledge_bases or [],
            # App 级别绑定的 embedding 模型 ID（用于按维度路由向量存储）
            "embedding_model_id": str(getattr(app_config, "embedding_model_id", "") or "") or "",
            "retrieval_config": app_config.retrieval_config,
            "long_term_memory": app_config.long_term_memory,
            "opening_statement": app_config.opening_statement,
            "opening_questions": app_config.opening_questions,
            "speech_to_text": app_config.speech_to_text,
            "text_to_speech": app_config.text_to_speech,
            "suggested_after_answer": app_config.suggested_after_answer,
            "review_config": app_config.review_config,
            "updated_at": datetime_to_timestamp(app_config.updated_at),
            "created_at": datetime_to_timestamp(app_config.created_at),
        }

    def _process_and_validate_tools(self, origin_tools: list[dict]) -> tuple[list[dict], list[dict]]:
        """根据传递的原始工具信息进行处理和校验"""
        # 1.循环遍历工具列表删除已被删除的工具
        validate_tools = []
        tools = []
        for tool in origin_tools:
            if tool["type"] == "builtin_tool":
                # 2.查询内置工具提供者，并检测是否存在
                provider = self.builtin_provider_manager.get_provider(tool["provider_id"])
                if not provider:
                    continue

                # 3.获取提供者下的工具实体，并检测是否存在
                tool_entity = provider.get_tool_entity(tool["tool_id"])
                if not tool_entity:
                    continue

                # 4.判断工具的params和草稿中的params是否一致，如果不一致则全部重置为默认值（或者考虑删除这个工具的引用）
                param_keys = set([param.name for param in tool_entity.params])
                params = tool["params"]
                if set(tool["params"].keys()) - param_keys:
                    params = {
                        param.name: param.default
                        for param in tool_entity.params
                        if param.default is not None
                    }

                # 5.数据都存在，并且参数已经校验完毕，可以将数据添加到validate_tools
                validate_tools.append({**tool, "params": params})

                # 6.组装内置工具展示信息
                provider_entity = provider.provider_entity
                tools.append({
                    "type": "builtin_tool",
                    "provider": {
                        "id": provider_entity.name,
                        "name": provider_entity.name,
                        "label": provider_entity.label,
                        "icon": f"/builtin-tools/{provider_entity.name}/icon",
                        "description": provider_entity.description,
                    },
                    "tool": {
                        "id": tool_entity.name,
                        "name": tool_entity.name,
                        "label": tool_entity.label,
                        "description": tool_entity.description,
                        "params": params,
                    }
                })
            elif tool["type"] == "api_tool":
                # 7.查询数据库获取对应的工具记录，并检测是否存在
                tool_record = self.db.session.query(ApiTool).filter(
                    ApiTool.provider_id == tool["provider_id"],
                    ApiTool.name == tool["tool_id"],
                ).one_or_none()
                if not tool_record:
                    continue

                # 8.数据校验通过，往validate_tools中添加数据
                validate_tools.append(tool)

                # 9.组装api工具展示信息
                provider = tool_record.provider
                tools.append({
                    "type": "api_tool",
                    "provider": {
                        "id": str(provider.id),
                        "name": provider.name,
                        "label": provider.name,
                        "icon": provider.icon,
                        "description": provider.description,
                    },
                    "tool": {
                        "id": str(tool_record.id),
                        "name": tool_record.name,
                        "label": tool_record.name,
                        "description": tool_record.description,
                        "params": {},
                    },
                })

        return tools, validate_tools

    def _process_and_validate_mcp_bindings(self, origin_mcp_bindings: list[dict]) -> tuple[list[dict], list[dict]]:
        """根据传递的 MCP 绑定列表并返回展示信息和校验后的数据。"""
        if not isinstance(origin_mcp_bindings, list):
            return [], []

        validate_mcp_bindings: list[dict] = []
        for binding in origin_mcp_bindings:
            if not isinstance(binding, dict):
                continue

            name = str(binding.get("name", "")).strip()
            transport = str(binding.get("transport", "streamable_http")).strip().lower() or "streamable_http"
            description = str(binding.get("description", "")).strip()
            enabled = bool(binding.get("enabled", True))
            headers = binding.get("headers", [])
            tool_names = binding.get("tool_names", [])
            timeout_seconds = binding.get("timeout_seconds", 30)
            url = str(binding.get("url", "")).strip()
            command = str(binding.get("command", "")).strip()
            args = binding.get("args", [])
            env = binding.get("env", {})
            provider_key = str(binding.get("provider_key", "")).strip()
            source_type = str(binding.get("source_type", "")).strip()
            source_key = str(binding.get("source_key", "")).strip()
            source_url = str(binding.get("source_url", "")).strip()
            label = str(binding.get("label", "")).strip()
            icon = str(binding.get("icon", "")).strip()
            category = str(binding.get("category", "")).strip()

            if not name:
                continue
            if transport in {"http", "sse", "streamable_http", "streamable-http"}:
                if not url:
                    continue
            elif transport == "stdio":
                if not command:
                    continue
            else:
                continue

            if not isinstance(headers, list):
                headers = []
            if not isinstance(tool_names, list):
                tool_names = []
            if not isinstance(args, list):
                args = []
            if not isinstance(env, dict):
                env = {}

            cleaned_headers = []
            for header in headers:
                if not isinstance(header, dict):
                    continue
                key = str(header.get("key", "")).strip()
                value = str(header.get("value", "")).strip()
                if key:
                    cleaned_headers.append({"key": key, "value": value})

            cleaned_tool_names = []
            for tool_name in tool_names:
                normalized_tool_name = str(tool_name).strip()
                if normalized_tool_name:
                    cleaned_tool_names.append(normalized_tool_name)

            cleaned_args = [str(arg).strip() for arg in args if str(arg).strip()]
            cleaned_env = {
                str(key).strip(): str(value).strip()
                for key, value in env.items()
                if str(key).strip()
            }
            timeout_value = (
                timeout_seconds
                if isinstance(timeout_seconds, int)
                and not isinstance(timeout_seconds, bool)
                and timeout_seconds > 0
                else 30
            )

            validate_binding = {
                "name": name,
                "description": description,
                "transport": transport,
                "url": url,
                "command": command,
                "args": cleaned_args,
                "env": cleaned_env,
                "enabled": enabled,
                "headers": cleaned_headers,
                "tool_names": cleaned_tool_names,
                "timeout_seconds": timeout_value,
                "provider_key": provider_key,
                "source_type": source_type,
                "source_key": source_key,
                "source_url": source_url,
                "label": label,
                "icon": icon,
                "category": category,
            }
            validate_mcp_bindings.append(validate_binding)

        deduped_validate_mcp_bindings: list[dict] = []
        deduped_mcp_bindings: list[dict] = []
        seen_binding_targets: set[str] = set()
        for binding in validate_mcp_bindings:
            binding_identity = binding.get("provider_key") or f"{binding['transport']}:{binding.get('url') or binding.get('command')}:{binding['name']}"
            if binding_identity in seen_binding_targets:
                continue
            seen_binding_targets.add(binding_identity)
            deduped_validate_mcp_bindings.append(binding)
            deduped_mcp_bindings.append(binding)

        return deduped_mcp_bindings, deduped_validate_mcp_bindings

    def _process_and_validate_mcp_tool_snapshots(
        self,
        origin_mcp_tool_snapshots: list[dict],
        validate_mcp_bindings: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """根据传递的 MCP 快照列表并返回展示信息和校验后的数据。"""
        if not isinstance(origin_mcp_tool_snapshots, list):
            return [], []

        valid_binding_identities = {
            McpToolFactory.build_binding_identity(binding)
            for binding in validate_mcp_bindings
            if isinstance(binding, dict)
        }

        validate_snapshots: list[dict] = []
        for snapshot in origin_mcp_tool_snapshots:
            if not isinstance(snapshot, dict):
                continue

            binding_identity = str(snapshot.get("binding_identity") or "").strip()
            if not binding_identity:
                binding = snapshot.get("binding")
                if isinstance(binding, dict):
                    binding_identity = McpToolFactory.build_binding_identity(binding)
            if not binding_identity or binding_identity not in valid_binding_identities:
                continue

            binding = snapshot.get("binding")
            normalized_binding = binding if isinstance(binding, dict) else {}
            tool_definitions = snapshot.get("tool_definitions", [])
            normalized_tool_definitions = tool_definitions if isinstance(tool_definitions, list) else []
            validate_snapshots.append({
                "binding_identity": binding_identity,
                "binding_hash": str(snapshot.get("binding_hash") or "").strip(),
                "binding": normalized_binding,
                "status": str(snapshot.get("status") or "").strip().lower() or "warming",
                "tool_definitions": [tool for tool in normalized_tool_definitions if isinstance(tool, dict)],
                "tool_names": [
                    str(tool_name).strip()
                    for tool_name in (snapshot.get("tool_names") or [])
                    if str(tool_name).strip()
                ],
                "tool_count": int(snapshot.get("tool_count") or len(normalized_tool_definitions) or 0),
                "schema_hash": str(snapshot.get("schema_hash") or "").strip(),
                "last_attempt_at": snapshot.get("last_attempt_at"),
                "last_success_at": snapshot.get("last_success_at"),
                "last_error": str(snapshot.get("last_error") or "").strip(),
                "retry_count": int(snapshot.get("retry_count") or 0),
                "retryable": bool(snapshot.get("retryable", False)),
            })

        return validate_snapshots, validate_snapshots

    def _process_and_validate_knowledge_base_ids(
        self,
        origin_knowledge_base_ids: list[Any],
        current_account_id: Any = None,
    ) -> tuple[list[dict], list[str]]:
        """校验新版知识库 id 列表，返回展示信息与可落库的 id 字符串列表。

        权限校验规则（防越权引用）：
            - user_content / user_memory 知识库：必须 owner_account_id == current_account_id
            - system 知识库：必须 enabled=True（admin 通过 enabled 开关控制对 Agent 可读）
            - tenant / project 知识库：当前未开放给用户端 App，一律拒绝

        Args:
            origin_knowledge_base_ids: 原始知识库 id 列表
            current_account_id: 当前用户 account.id，用于 user_content/user_memory 库归属校验

        Returns:
            (展示信息列表, 可落库的 id 字符串列表)
        """
        if not isinstance(origin_knowledge_base_ids, list) or not origin_knowledge_base_ids:
            return [], []

        # 1.统一转换为字符串形式，便于去重与比较
        normalized_ids: list[str] = []
        seen: set[str] = set()
        for kb_id in origin_knowledge_base_ids:
            kb_id_str = str(kb_id).strip()
            if not kb_id_str or kb_id_str in seen:
                continue
            seen.add(kb_id_str)
            normalized_ids.append(kb_id_str)

        if not normalized_ids:
            return [], []

        # 2.查询数据库中存在且启用的知识库
        try:
            from uuid import UUID as _UUID
            uuid_ids = [_UUID(kb_id) for kb_id in normalized_ids]
        except Exception:
            # 非法 id 直接返回空
            return [], []

        kb_records = self.db.session.query(KnowledgeBase).filter(
            KnowledgeBase.id.in_(uuid_ids),
            KnowledgeBase.enabled.is_(True),
        ).all()
        kb_dict = {str(kb_record.id): kb_record for kb_record in kb_records}

        # 3.权限校验：仅保留授权可引用的知识库
        from internal.entity.knowledge_entity import KnowledgeScope

        authorized_scopes = {
            KnowledgeScope.SYSTEM.value,
            KnowledgeScope.USER_CONTENT.value,
            KnowledgeScope.USER_MEMORY.value,
        }
        validate_knowledge_base_ids: list[str] = []
        for kb_id in normalized_ids:
            kb = kb_dict.get(kb_id)
            if kb is None:
                continue
            # 拒绝未开放 scope
            if kb.knowledge_scope not in authorized_scopes:
                continue
            # system 库：enabled=True 即授权（admin 控制）
            if kb.knowledge_scope == KnowledgeScope.SYSTEM.value:
                validate_knowledge_base_ids.append(kb_id)
                continue
            # user_content / user_memory 库：必须 owner == 当前用户
            if str(kb.owner_account_id) != str(current_account_id or ""):
                continue
            validate_knowledge_base_ids.append(kb_id)

        # 4.循环获取知识库展示数据
        knowledge_bases: list[dict] = []
        for kb_id in validate_knowledge_base_ids:
            kb = kb_dict.get(kb_id)
            knowledge_bases.append({
                "id": str(kb.id),
                "name": kb.name,
                "description": kb.description or "",
            })

        return knowledge_bases, validate_knowledge_base_ids

    def _process_and_validate_model_config(self, origin_model_config: dict[str, Any]) -> dict[str, Any]:
        """根据传递的模型配置处理并校验，随后返回校验后的信息"""
        # 1.判断model_config是否为字典，如果不是则直接返回默认值
        if not isinstance(origin_model_config, dict):
            return DEFAULT_APP_CONFIG["model_config"]

        # 2.提取origin_model_config中provider、model、parameters对应的信息
        model_config = {
            "provider": origin_model_config.get("provider", ""),
            "model": origin_model_config.get("model", ""),
            "parameters": origin_model_config.get("parameters", {}),
        }

        # 3.判断provider是否存在、类型是否正确，如果不符合规则则返回默认值
        if not model_config["provider"] or not isinstance(model_config["provider"], str):
            return DEFAULT_APP_CONFIG["model_config"]
        try:
            self.language_model_manager.get_or_load_provider(model_config["provider"])
        except NotFoundException:
            return DEFAULT_APP_CONFIG["model_config"]

        # 4.判断model是否存在、类型是否正确，如果不符合规则则返回默认值
        if not model_config["model"] or not isinstance(model_config["model"], str):
            return DEFAULT_APP_CONFIG["model_config"]
        try:
            model_entity = self.language_model_manager.get_or_load_model_entity(
                model_config["provider"], model_config["model"]
            )
        except NotFoundException:
            return DEFAULT_APP_CONFIG["model_config"]

        # 5.判断parameters信息类型是否错误，如果错误则设置为默认值
        if not isinstance(model_config["parameters"], dict):
            model_config["parameters"] = {
                parameter.name: parameter.default for parameter in model_entity.parameters
            }

        # 6.剔除传递的多余的parameter，亦或者是少传递的参数使用默认值补上
        parameters = {}
        for parameter in model_entity.parameters:
            # 7.从model_config中获取参数值，如果不存在则设置为默认值
            parameter_value = model_config["parameters"].get(parameter.name, parameter.default)

            # 8.判断参数是否必填
            if parameter.required:
                # 9.参数必填，则值不允许为None，如果为None则设置默认值
                if parameter_value is None:
                    parameter_value = parameter.default
                else:
                    # 10.值非空则校验数据类型是否正确，不正确则设置默认值
                    if get_value_type(parameter_value) != parameter.type.value:
                        parameter_value = parameter.default
            else:
                # 11.参数非必填，数据非空的情况下需要校验
                if parameter_value is not None:
                    if get_value_type(parameter_value) != parameter.type.value:
                        parameter_value = parameter.default

            # 12.判断参数是否存在options，如果存在则数值必须在options中选择
            if parameter.options and parameter_value not in parameter.options:
                parameter_value = parameter.default

            # 13.参数类型为int/float，如果存在min/max时候需要校验
            if parameter.type in [ModelParameterType.INT.value, ModelParameterType.FLOAT.value] and parameter_value is not None:
                # 14.校验数值的min/max
                if (
                        (parameter.min and parameter_value < parameter.min)
                        or (parameter.max and parameter_value > parameter.max)
                ):
                    parameter_value = parameter.default

            parameters[parameter.name] = parameter_value

        # 15.完成数据校验，赋值parameters参数
        model_config["parameters"] = parameters

        return model_config

    def _process_and_validate_workflows(
            self,
            origin_workflows: list[UUID]
    ) -> tuple[list[dict], list[UUID]]:
        """根据传递的工作流列表并返回工作流配置和校验后的数据"""
        # 1.校验工作流配置列表 如果引用了不存在/被删除的工作流 则需要剔除数据并更新 同时获取工作流的额外信息
        workflows = []
        workflow_records = self.db.session.query(Workflow).filter(
            Workflow.id.in_(origin_workflows),
            Workflow.status == WorkflowStatus.PUBLISHED.value
        ).all()
        workflow_dict = {str(workflow_record.id): workflow_record for workflow_record in workflow_records}
        workflow_sets = set(workflow_dict.keys())

        # 2.计算存在的工作流id列表 为了保留原始顺序 使用列表循环的方式来判断
        validate_workflows = [workflow_id for workflow_id in origin_workflows if workflow_id in workflow_sets]

        # 3.循环获取工作流数据
        for workflow_id in validate_workflows:
            workflow = workflow_dict.get(str(workflow_id))
            workflows.append({
                "id": str(workflow_id),
                "name": workflow.name,
                "icon": workflow.icon,
                "description": workflow.description
            })

        return workflows, validate_workflows



