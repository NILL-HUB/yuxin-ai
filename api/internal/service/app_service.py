import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from injector import inject
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from internal.entity.audio_entity import ALLOWED_AUDIO_VOICES
from redis import Redis
from sqlalchemy import func, desc
from internal.core.language_model import LanguageModelManager
from internal.core.tools.api_tools.providers import ApiProviderManager
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from internal.entity.ai_entity import OPTIMIZE_PROMPT_TEMPLATE
from internal.entity.app_entity import AppStatus, AppConfigType, DEFAULT_APP_CONFIG
from internal.entity.agent_entity import normalize_agent_metadata
from internal.exception import NotFoundException, ForbiddenException, ValidateErrorException, FailException
from internal.lib.helper import remove_fields, get_value_type, escape_like_pattern
from internal.model import (
    App,
    Account,
    AppConfigVersion,
    ApiTool,
    Dataset,
    AppConfig,
    AppDatasetJoin,
    Workflow,
)
from internal.schema.app_schema import (
    CreateAppReq,
    GetAppsWithPageReq,
    GetPublishHistoriesWithPageReq,
)
from internal.task.app_task import prewarm_mcp_tool_snapshots, sync_public_app_registry
from pkg.paginator import Paginator
from pkg.sqlalchemy import SQLAlchemy
from .app_config_service import AppConfigService
from .app_icon_service import AppIconService
from .base_service import BaseService
from .conversation_service import ConversationService
from .cos_service import CosService
from .language_model_service import LanguageModelService
from .public_agent_registry_service import PublicAgentRegistryService
from .retrieval_service import RetrievalService
from .icon_generator_service import IconGeneratorService
from .skill_service import SkillService
from .workflow_app_service import WorkflowAppService
from ..core.language_model.entities.model_entity import ModelParameterType, ModelFeature
from ..core.language_model.providers.deepseek.chat import Chat
from ..entity.app_entity import AppType
from ..entity.workflow_entity import WorkflowStatus


logger = logging.getLogger(__name__)


@inject
@dataclass
class AppService(BaseService):
    """应用服务逻辑"""
    db: SQLAlchemy
    redis_client: Redis
    cos_service: CosService
    retrieval_service: RetrievalService
    app_config_service: AppConfigService
    api_provider_manager: ApiProviderManager
    conversation_service: ConversationService
    language_model_manager: LanguageModelManager
    language_model_service: LanguageModelService
    builtin_provider_manager: BuiltinProviderManager
    icon_generator_service: IconGeneratorService
    app_icon_service: AppIconService
    public_agent_registry_service: PublicAgentRegistryService | None = None
    workflow_app_service: WorkflowAppService | None = None
    AUTO_CREATE_DEFAULT_TOOLS = [
        {
            "type": "builtin_tool",
            "provider_id": "google",
            "tool_id": "google_serper",
            "params": {},
        },
        {
            "type": "builtin_tool",
            "provider_id": "gaode",
            "tool_id": "gaode_weather",
            "params": {},
        },
        {
            "type": "builtin_tool",
            "provider_id": "qwen",
            "tool_id": "qwen_image_text_to_image",
            "params": {
                "image_size": "1328x1328",
                "num_inference_steps": 50,
                "cfg": 4.0,
            },
        },
    ]

    @classmethod
    def _enqueue_public_app_registry_sync(cls, app_id: UUID) -> None:
        """后台同步公共Agent索引，失败时仅记录日志，不阻塞主流程。"""
        try:
            normalized_app_id = str(app_id)
            apply_async = getattr(sync_public_app_registry, "apply_async", None)
            if callable(apply_async):
                apply_async(
                    args=(normalized_app_id,),
                    ignore_result=True,
                    retry=False,
                )
                return

            sync_public_app_registry.delay(normalized_app_id)
        except Exception:
            logging.exception("公共Agent索引同步任务入队失败: app_id=%s", app_id)

    @classmethod
    def _enqueue_mcp_tool_snapshot_prewarm(cls, app_id: UUID, config_type: str) -> None:
        """后台预热 MCP 工具快照，失败时仅记录日志，不阻塞主流程。"""
        try:
            normalized_app_id = str(app_id)
            normalized_config_type = str(config_type)
            apply_async = getattr(prewarm_mcp_tool_snapshots, "apply_async", None)
            if callable(apply_async):
                apply_async(
                    args=(normalized_app_id, normalized_config_type),
                    ignore_result=True,
                    retry=False,
                )
                return

            prewarm_mcp_tool_snapshots.delay(normalized_app_id, normalized_config_type)
        except Exception:
            logging.exception(
                "MCP 工具快照预热任务入队失败: app_id=%s, config_type=%s",
                app_id,
                config_type,
            )

    def _sync_public_app_registry_after_unpublish(self, app_id: UUID) -> None:
        """取消发布后优先执行本地索引移除，失败时再退回异步任务同步。"""
        if not self.public_agent_registry_service:
            return

        remove_public_app = getattr(self.public_agent_registry_service, "remove_public_app", None)
        if callable(remove_public_app):
            try:
                remove_public_app(app_id)
                return
            except Exception:
                logging.exception("公共Agent索引移除失败，改为异步同步: app_id=%s", app_id)

        self._enqueue_public_app_registry_sync(app_id)

    def refresh_mcp_tool_snapshots(self, app_id: UUID, config_type: str) -> list[dict[str, Any]]:
        """根据应用配置类型刷新 MCP 工具快照，供后台任务调用。"""
        app = self.get(App, app_id)
        if not app:
            raise NotFoundException("该应用不存在，请核实后重试")

        normalized_config_type = str(config_type).strip().lower()
        if normalized_config_type == AppConfigType.DRAFT.value:
            target_config = app.draft_app_config
        elif normalized_config_type == AppConfigType.PUBLISHED.value:
            target_config = app.app_config
        else:
            raise FailException("MCP快照刷新配置类型错误")

        if not target_config:
            return []

        refreshed_snapshots = self.app_config_service.refresh_mcp_tool_snapshots(
            getattr(target_config, "mcp_bindings", []),
            getattr(target_config, "mcp_tool_snapshots", []),
        )
        if getattr(target_config, "mcp_tool_snapshots", []) != refreshed_snapshots:
            self.update(
                target_config,
                updated_at=datetime.now(UTC),
                mcp_tool_snapshots=refreshed_snapshots,
            )

        return refreshed_snapshots

    @classmethod
    def _normalize_opening_questions(cls, questions: list[Any]) -> list[str]:
        """规范化开场建议问题并确保最多返回3条有效内容"""
        normalized_questions = []

        # 1.清理无效问题并去重
        for question in questions:
            if not isinstance(question, str):
                continue
            question = question.strip()
            if not question:
                continue
            if question in normalized_questions:
                continue
            normalized_questions.append(question)
            if len(normalized_questions) >= 3:
                break

        # 2.不足3条时补充兜底问题，保证首屏体验完整
        fallback_questions = [
            "这个Agent可以帮我做什么？",
            "我先提供哪些信息会更高效？",
            "可以先给我一个示例任务吗？",
        ]
        for fallback_question in fallback_questions:
            if len(normalized_questions) >= 3:
                break
            if fallback_question in normalized_questions:
                continue
            normalized_questions.append(fallback_question)

        return normalized_questions

    def _get_skill_service(self) -> SkillService:
        """获取技能服务，兼容测试里传入的简化 app_config_service。"""
        skill_service = getattr(self.app_config_service, "skill_service", None)
        if skill_service is not None:
            return skill_service
        return SkillService(self.db)

    def auto_create_app(self, name: str, description: str, account_id: UUID) -> App:
        """根据传递的应用名称、描述、账号id利用AI创建一个Agent智能体"""
        name = (name or "").strip()
        description = (description or "").strip()

        # 1.创建LLM，用于生成icon提示与预设提示词
        llm = Chat(
            model="deepseek-chat",
            temperature=0.8,
            features=[ModelFeature.TOOL_CALL.value, ModelFeature.AGENT_THOUGHT.value],
            metadata={},
        )

        # 2.生成预设prompt链
        generate_preset_prompt_chain = ChatPromptTemplate.from_messages([
            ("system", OPTIMIZE_PROMPT_TEMPLATE),
            ("human", "应用名称: {name}\n\n应用描述: {description}")
        ]) | llm | StrOutputParser()

        app_config = {
            "preset_prompt": generate_preset_prompt_chain.invoke({
                "name": name,
                "description": description,
            })
        }

        # 5.1 自动生成对话开场白与开场建议问题
        opening_statement = (description or "").strip()
        if not opening_statement:
            opening_statement = f"你好，我是{name}，很高兴为你服务。"
        if len(opening_statement) > 2000:
            opening_statement = opening_statement[:2000]

        opening_questions = []
        try:
            # 使用统一的建议问题能力生成开场建议问题，避免额外维护提示词模板
            histories = (
                f"Human: 我想创建一个名为{name}的Agent，功能描述是：{description}\n"
                f"AI: Agent已创建完成，请开始与我对话。"
            )
            opening_questions = self.conversation_service.generate_suggested_questions(histories)
        except Exception as e:
            logging.exception(
                f"自动创建Agent时生成开场建议问题失败, name: {name}, 错误信息: {str(e)}"
            )
        opening_questions = self._normalize_opening_questions(
            opening_questions if isinstance(opening_questions, list) else []
        )
        default_tools = [
            {
                "type": tool["type"],
                "provider_id": tool["provider_id"],
                "tool_id": tool["tool_id"],
                "params": dict(tool["params"]),
            }
            for tool in self.AUTO_CREATE_DEFAULT_TOOLS
        ]

        # 6.使用共享图标服务生成并上传应用图标
        icon = self.icon_generator_service.generate_icon(
            name=name,
            description=description or "",
        )

        account = self.db.session.query(Account).get(account_id)

        # 7.开启数据库自动提交上下文
        with self.db.auto_commit():
            # 8.创建应用记录并刷新数据，从而可以拿到应用id
            app = App(
                account_id=account.id,
                name=name,
                icon=icon,
                description=description,
                status=AppStatus.DRAFT.value
            )
            self.db.session.add(app)
            self.db.session.flush()

            # 9.添加草稿记录
            app_config_version = AppConfigVersion(
                app_id=app.id,
                version=0,
                config_type=AppConfigType.DRAFT.value,
                **{
                    **DEFAULT_APP_CONFIG,
                    "preset_prompt": app_config.get("preset_prompt", ""),
                    "tools": default_tools,
                    "opening_statement": opening_statement,
                    "opening_questions": opening_questions,
                    # 显式覆盖，确保辅助Agent自动创建场景始终开启语音体验
                    "speech_to_text": {"enable": True},
                    "text_to_speech": {"enable": True, "voice": "alex", "auto_play": True},
                }
            )
            self.db.session.add(app_config_version)
            self.db.session.flush()

            # 10.更新应用配置id
            app.draft_app_config_id = app_config_version.id

        # 11.返回创建的应用
        return app

    def create_app(self, req: CreateAppReq, account: Account) -> App:
        """创建Agent应用服务"""
        # 1. 如果用户未提供图标，自动生成图标
        icon_url = req.icon.data
        if not icon_url:
            try:
                logging.info(f"用户未提供图标，自动生成图标: name={req.name.data}")
                icon_url = self.icon_generator_service.generate_icon(
                    name=req.name.data,
                    description=req.description.data or ""
                )
                logging.info(f"自动生成图标成功: {icon_url}")
            except Exception as e:
                logging.error(f"自动生成图标失败: {str(e)}")
                # 如果生成失败，使用默认图标 - 使用一个彩色的SVG图标
                icon_url = self.app_icon_service._generate_default_icon(req.name.data)

        # 2.开启数据库自动提交上下文
        with self.db.auto_commit():
            # 3.创建应用记录，并刷新数据，从而可以拿到应用id
            app = App(
                account_id=account.id,
                name=req.name.data,
                icon=icon_url,
                description=req.description.data,
                status=AppStatus.DRAFT.value,
            )
            self.db.session.add(app)
            self.db.session.flush()

            # 4.添加草稿记录
            app_config_version = AppConfigVersion(
                app_id=app.id,
                version=0,
                config_type=AppConfigType.DRAFT.value,
                **DEFAULT_APP_CONFIG,
            )
            self.db.session.add(app_config_version)
            self.db.session.flush()

            # 5.为应用添加草稿配置id
            app.draft_app_config_id = app_config_version.id

        # 6.返回创建的应用记录
        return app

    def get_app(self, app_id: UUID, account: Account) -> App:
        """根据传递的id获取应用的基础信息"""
        # 1.查询数据库获取应用基础信息
        app = self.get(App, app_id)

        # 2.判断应用是否存在
        if not app:
            raise NotFoundException("该应用不存在，请核实后重试")

        # 3.判断当前账号是否有权限访问该应用
        if app.account_id != account.id:
            raise ForbiddenException("当前账号无权限访问该应用，请核实后尝试")

        return app

    def delete_app(self, app_id: UUID, account: Account):
        app = self.get_app(app_id, account)
        self.delete(app)
        return app

    def _get_app_for_admin(self, app_id: UUID) -> App:
        """管理员视角：根据应用id获取应用，不校验账号归属"""
        app = self.get(App, app_id)
        if not app:
            raise NotFoundException("该应用不存在，请核实后重试")
        return app

    def _get_owner_account(self, account_id) -> Account:
        """根据账号id加载资源归属账号"""
        account = self.db.session.query(Account).filter(Account.id == account_id).one_or_none()
        if not account:
            raise NotFoundException("资源所属账号不存在")
        return account

    def delete_app_for_admin(self, app_id: UUID):
        """管理员删除应用，不校验账号归属"""
        app = self._get_app_for_admin(app_id)
        self.delete(app)
        return app

    def get_draft_app_config_for_admin(self, app_id: UUID) -> dict[str, Any]:
        """管理员获取应用草稿配置，复用空间端逻辑（以应用归属账号执行）"""
        app = self._get_app_for_admin(app_id)
        account = self._get_owner_account(app.account_id)
        return self.get_draft_app_config(app_id, account)

    def update_draft_app_config_for_admin(
            self,
            app_id: UUID,
            draft_app_config: dict[str, Any],
    ) -> AppConfigVersion:
        """管理员保存应用草稿配置，复用空间端逻辑（以应用归属账号执行）"""
        app = self._get_app_for_admin(app_id)
        account = self._get_owner_account(app.account_id)
        return self.update_draft_app_config(app_id, draft_app_config, account)

    def update_app(self, app_id: UUID, account: Account, **kwargs) -> App:
        """根据传递的应用id+账号+信息,更新指定的应用"""
        app = self.get_app(app_id, account)
        if kwargs.get("agent_metadata") is not None:
            kwargs["agent_metadata"] = normalize_agent_metadata(kwargs["agent_metadata"])
        self.update(app, **kwargs)
        return app

    def copy_app(self, app_id: UUID, account: Account) -> App:
        """根据传递的应用id,拷贝Agent相关信息并创建一个新Agent"""
        # 1.获取App+草稿配置 并校验权限
        app = self.get_app(app_id, account)
        draft_app_config = app.draft_app_config

        # 2.将数据转换为字典并剔除无用数据
        app_dict = app.__dict__.copy()
        draft_app_config_dict = draft_app_config.__dict__.copy()

        # 3.剔除无用字段
        app_remove_fields = [
            "id", "app_config_id", "draft_app_config_id", "debug_conversation_id", "status",
            "updated_at", "created_at", "_sa_instance_state",
        ]
        draft_app_config_remove_fields = [
            "id", "app_id", "version", "updated_at", "created_at", "_sa_instance_state",
        ]
        remove_fields(app_dict, app_remove_fields)
        remove_fields(draft_app_config_dict, draft_app_config_remove_fields)

        # 4.开启数据库自动提交上下文
        with self.db.auto_commit():
            # 5.创建一个新的应用记录
            new_app = App(**app_dict, status=AppStatus.DRAFT.value)
            self.db.session.add(new_app)
            self.db.session.flush()

            # 6.添加草稿配置
            new_draft_app_config = AppConfigVersion(
                **draft_app_config_dict,
                app_id=new_app.id,
                version=0
            )
            self.db.session.add(new_draft_app_config)
            self.db.session.flush()

            # 7.更新应用的草稿配置id
            new_app.draft_app_config_id = new_draft_app_config.id

        # 8.返回创建好的新应用
        return new_app

    def get_apps_with_page(self, req: GetAppsWithPageReq, account: Account) -> tuple[list[App], Paginator]:
        """根据传递的分页参数获取当前登录账号下的应用分页列表数据"""
        # 1.构建分页器
        paginator = Paginator(db=self.db, req=req)

        # 2.构建筛选条件
        filters = [App.account_id == account.id]
        if req.search_word.data:
            filters.append(App.name.ilike(f"%{escape_like_pattern(req.search_word.data)}%"))
        if getattr(req, "published_only", None) and req.published_only.data:
            filters.append(App.status == AppStatus.PUBLISHED.value)

        # 3.执行分页操作
        apps = paginator.paginate(
            self.db.session.query(App).filter(*filters).order_by(desc("created_at"))
        )

        return apps, paginator

    def get_draft_app_config(
        self,
        app_id: UUID,
        account: Account,
        persist_changes: bool = True,
    ) -> dict[str, Any]:
        """根据传递的应用id，获取指定的应用草稿配置信息"""
        app = self.get_app(app_id, account)
        draft_app_config = self.app_config_service.get_draft_app_config(app)
        # 显式补齐 workflow_id 字段，确保前端始终能拿到该字段（即使为 None）
        draft_app_config.setdefault("workflow_id", getattr(getattr(app, "draft_app_config", None), "workflow_id", None))
        if hasattr(self.language_model_service, "describe_runtime_capabilities"):
            draft_app_config["capabilities"] = self.language_model_service.describe_runtime_capabilities(
                draft_app_config.get("model_config", {}),
                entrypoint=LanguageModelService.ENTRYPOINT_DEBUGGER,
            )
        return draft_app_config

    def update_draft_app_config(
            self,
            app_id: UUID,
            draft_app_config: dict[str, Any],
            account: Account,
    ) -> AppConfigVersion:
        """根据传递的应用id+草稿配置修改指定应用的最新草稿"""
        # 1.获取应用信息并校验
        app = self.get_app(app_id, account)

        # 2.校验传递的草稿配置信息
        draft_app_config = self._validate_draft_app_config(draft_app_config, account, app_id)

        # 3.获取当前应用的最新草稿信息
        draft_app_config_record = app.draft_app_config
        self.update(
            draft_app_config_record,
            # todo:由于目前使用server_onupdate，所以该字段暂时需要手动传递
            updated_at=datetime.now(UTC),
            **draft_app_config,
        )

        prepared_mcp_tool_snapshots = self.app_config_service.prepare_mcp_tool_snapshots(
            getattr(draft_app_config_record, "mcp_bindings", []),
            getattr(draft_app_config_record, "mcp_tool_snapshots", []),
        )
        if getattr(draft_app_config_record, "mcp_tool_snapshots", []) != prepared_mcp_tool_snapshots:
            self.update(
                draft_app_config_record,
                updated_at=datetime.now(UTC),
                mcp_tool_snapshots=prepared_mcp_tool_snapshots,
            )

        self._enqueue_mcp_tool_snapshot_prewarm(app.id, AppConfigType.DRAFT.value)

        return draft_app_config_record

    def publish_draft_app_config(self, app_id: UUID, account: Account, share_to_square: bool = True) -> App:
        """根据传递的应用id+账号，发布/更新指定的应用草稿配置为运行时配置

        Args:
            app_id: 应用ID
            account: 账号信息
            share_to_square: 是否同时分享到应用广场，默认为True（保持向后兼容）
        """
        # 1.获取应用的信息以及草稿信息
        app = self.get_app(app_id, account)
        draft_app_config = self.get_draft_app_config(app_id, account)

        # 2.创建应用运行配置（在这里暂时不删除历史的运行配置）
        app_config = self.create(
            AppConfig,
            app_id=app_id,
            model_config=draft_app_config["model_config"],
            dialog_round=draft_app_config["dialog_round"],
            preset_prompt=draft_app_config["preset_prompt"],
            tools=[
                {
                    "type": tool["type"],
                    "provider_id": tool["provider"]["id"],
                    "tool_id": tool["tool"]["name"],
                    "params": tool["tool"]["params"],
                }
                for tool in draft_app_config["tools"]
            ],
            mcp_bindings=draft_app_config.get("mcp_bindings", []),
            mcp_tool_snapshots=draft_app_config.get("mcp_tool_snapshots", []),
            skills=[{"skill_id": skill["skill_id"]} for skill in draft_app_config.get("skills", [])],
            agent_bindings=draft_app_config.get("agent_bindings", []),
            workflows=[workflow["id"] for workflow in draft_app_config["workflows"]],
            retrieval_config=draft_app_config["retrieval_config"],
            long_term_memory=draft_app_config["long_term_memory"],
            opening_statement=draft_app_config["opening_statement"],
            opening_questions=draft_app_config["opening_questions"],
            speech_to_text=draft_app_config["speech_to_text"],
            text_to_speech=draft_app_config["text_to_speech"],
            suggested_after_answer=draft_app_config["suggested_after_answer"],
            review_config=draft_app_config["review_config"],
            workflow_id=draft_app_config.get("workflow_id"),
        )

        # 3.更新应用关联的运行时配置、状态
        update_data = {
            "app_config_id": app_config.id,
            "status": AppStatus.PUBLISHED.value,
        }

        # 如果指定分享到广场，则设置 is_public
        if share_to_square:
            update_data["is_public"] = True

        # 如果是首次发布，设置发布时间
        if not app.published_at:
            update_data["published_at"] = datetime.now(UTC).replace(tzinfo=None)

        self.update(app, **update_data)

        # 4.先删除原有的知识库关联记录
        with self.db.auto_commit():
            self.db.session.query(AppDatasetJoin).filter(
                AppDatasetJoin.app_id == app_id,
            ).delete()

        # 5.新增新的知识库关联记录
        for dataset in draft_app_config["datasets"]:
            self.create(AppDatasetJoin, app_id=app_id, dataset_id=dataset["id"])

        # 6.获取应用草稿记录，并移除id、version、config_type、updated_at、created_at字段
        draft_app_config_copy = app.draft_app_config.__dict__.copy()
        remove_fields(
            draft_app_config_copy,
            ["id", "version", "config_type", "updated_at", "created_at", "_sa_instance_state"]
        )

        # 7.获取当前最大的发布版本
        max_version = self.db.session.query(func.coalesce(func.max(AppConfigVersion.version), 0)).filter(
            AppConfigVersion.app_id == app_id,
            AppConfigVersion.config_type == AppConfigType.PUBLISHED.value,
        ).scalar()

        # 8.新增发布历史配置
        self.create(
            AppConfigVersion,
            version=max_version + 1,
            config_type=AppConfigType.PUBLISHED.value,
            **draft_app_config_copy,
        )

        self._enqueue_mcp_tool_snapshot_prewarm(app.id, AppConfigType.PUBLISHED.value)

        if self.public_agent_registry_service:
            self._enqueue_public_app_registry_sync(app.id)
        logging.info(f"应用已发布: app_id={app_id}, share_to_square={share_to_square}")
        return app

    def cancel_publish_app_config(self, app_id: UUID, account: Account) -> App:
        """根据传递的应用id+账号，取消发布指定的应用配置，并从应用广场移除"""
        # 1.获取应用信息并校验权限
        app = self.get_app(app_id, account)

        # 2.检测下当前应用的状态是否为已发布
        if app.status != AppStatus.PUBLISHED.value:
            raise FailException("当前应用未发布，请核实后重试")

        # 3.修改账号的发布状态，清空关联配置id，并从应用广场移除
        self.update(
            app,
            status=AppStatus.DRAFT.value,
            app_config_id=None,
            is_public=False,  # 从应用广场移除
            published_at=None,  # 清空发布时间
        )

        if self.public_agent_registry_service:
            self._sync_public_app_registry_after_unpublish(app.id)
        logging.info(f"应用已取消发布并从应用广场移除: app_id={app_id}")
        return app

    def get_publish_histories_with_page(
            self,
            app_id: UUID,
            req: GetPublishHistoriesWithPageReq,
            account: Account
    ) -> tuple[list[AppConfigVersion], Paginator]:
        """根据传递的应用id+请求数据，获取指定应用的发布历史配置列表信息"""
        # 1.获取应用信息并校验权限
        self.get_app(app_id, account)

        # 2.构建分页器
        paginator = Paginator(db=self.db, req=req)

        # 3.执行分页并获取数据
        app_config_versions = paginator.paginate(
            self.db.session.query(AppConfigVersion).filter(
                AppConfigVersion.app_id == app_id,
                AppConfigVersion.config_type == AppConfigType.PUBLISHED.value,
            ).order_by(desc("version"))
        )

        return app_config_versions, paginator

    def get_versions(self, app_id: UUID, account: Account) -> list[AppConfigVersion]:
        """获取指定应用的版本对比数据，包含当前草稿和全部发布历史。"""
        app = self.get_app(app_id, account)
        display_config_loader = getattr(self.app_config_service, "get_version_display_config", None)

        draft_version = app.draft_app_config
        draft_version.is_current_published = False
        if callable(display_config_loader):
            draft_version.display_config = display_config_loader(
                draft_version,
                current_account_id=account.id,
                current_app_id=app_id,
            )

        published_versions = (
            self.db.session.query(AppConfigVersion)
            .filter(
                AppConfigVersion.app_id == app_id,
                AppConfigVersion.config_type == AppConfigType.PUBLISHED.value,
            )
            .order_by(desc("version"))
            .all()
        )

        current_published_version = None
        if app.status == AppStatus.PUBLISHED.value and published_versions:
            current_published_version = published_versions[0].version

        for published_version in published_versions:
            published_version.is_current_published = (
                current_published_version is not None
                and published_version.version == current_published_version
            )
            if callable(display_config_loader):
                published_version.display_config = display_config_loader(
                    published_version,
                    current_account_id=account.id,
                    current_app_id=app_id,
                )

        return [draft_version, *published_versions]

    def fallback_history_to_draft(
            self,
            app_id: UUID,
            app_config_version_id: UUID,
            account: Account,
    ) -> AppConfigVersion:
        """根据传递的应用id、历史配置版本id、账号信息，回退特定配置到草稿"""
        # 1.校验应用权限并获取信息
        app = self.get_app(app_id, account)

        # 2.查询指定的历史版本配置id
        app_config_version = self.get(AppConfigVersion, app_config_version_id)
        if not app_config_version:
            raise NotFoundException("该历史版本配置不存在，请核实后重试")

        # 3.校验历史版本配置信息（剔除已删除的工具、知识库、工作流）
        draft_app_config_dict = app_config_version.__dict__.copy()
        remove_fields(
            draft_app_config_dict,
            ["id", "app_id", "version", "config_type", "updated_at", "created_at", "_sa_instance_state"]
        )

        # 4.校验历史版本配置信息
        draft_app_config_dict = self._validate_draft_app_config(draft_app_config_dict, account, app_id)

        # 5.更新草稿配置信息
        draft_app_config_record = app.draft_app_config
        self.update(
            draft_app_config_record,
            # todo:更新时间补丁信息
            updated_at=datetime.now(UTC),
            **draft_app_config_dict,
        )

        prepared_mcp_tool_snapshots = self.app_config_service.prepare_mcp_tool_snapshots(
            getattr(draft_app_config_record, "mcp_bindings", []),
            getattr(draft_app_config_record, "mcp_tool_snapshots", []),
        )
        if getattr(draft_app_config_record, "mcp_tool_snapshots", []) != prepared_mcp_tool_snapshots:
            self.update(
                draft_app_config_record,
                updated_at=datetime.now(UTC),
                mcp_tool_snapshots=prepared_mcp_tool_snapshots,
            )

        self._enqueue_mcp_tool_snapshot_prewarm(app.id, AppConfigType.DRAFT.value)

        return draft_app_config_record

    def get_published_config(self, app_id: UUID, account: Account) -> dict[str, Any]:
        """根据传递的应用id+账号 获取应用的发布配置"""
        # 1.获取应用信息并校验权限
        app = self.get_app(app_id, account)

        # 2.构建发布配置并返回
        return {
            "web_app": {
                "token": app.token_with_default,
                "status": app.status
            },
            "is_public": app.is_public,
            "category": getattr(app, "category", "general"),
        }

    def regenerate_web_app_token(self, app_id: UUID, account: Account) -> str:
        return self.app_icon_service.regenerate_web_app_token(app_id, account)

    def regenerate_icon(self, app_id: UUID, account: Account) -> str:
        return self.app_icon_service.regenerate_icon(app_id, account)

    def generate_icon_preview(self, name: str, description: str) -> str:
        return self.app_icon_service.generate_icon_preview(name, description)

    def _validate_draft_app_config(
        self,
        draft_app_config: dict[str, Any],
        account: Account,
        app_id: UUID | None = None,
    ) -> dict[str, Any]:
        """校验传递的应用草稿配置信息，返回校验后的数据"""
        # 1.校验上传的草稿配置中对应的字段，至少拥有一个可以更新的配置
        acceptable_fields = [
            "model_config", "dialog_round", "preset_prompt",
            "tools", "mcp_bindings", "mcp_tool_snapshots", "skills", "agent_bindings", "workflows", "datasets", "retrieval_config",
            "long_term_memory", "opening_statement", "opening_questions",
            "speech_to_text", "text_to_speech", "suggested_after_answer", "review_config",
            "workflow_id",
        ]

        # 2.判断传递的草稿配置是否在可接受字段内
        if (
                not draft_app_config
                or not isinstance(draft_app_config, dict)
                or set(draft_app_config.keys()) - set(acceptable_fields)
        ):
            raise ValidateErrorException("草稿配置字段出错，请核实后重试")

        # 3.校验model_config字段，provider/model使用严格校验(出错时直接抛出) parameters使用宽松校验 出错时使用默认值
        if "model_config" in draft_app_config:
            # 3.1 获取模型配置并判断数据是否为字典
            model_config = draft_app_config["model_config"]
            if not isinstance(model_config, dict):
                raise ValidateErrorException("模型配置格式错误 请核实后重试")

            # 3.2 判断model_config键信息是否正确
            if set(model_config.keys()) != {"provider", "model", "parameters"}:
                raise ValidateErrorException("模型键配置格式错误 请核实后重试")

            # 3.3 判断模型提供者信息是否正确
            if not model_config["provider"] or not isinstance(model_config["provider"], str):
                raise ValidateErrorException("模型服务提供商类型必须为字符串")
            provider = self.language_model_manager.get_provider(model_config["provider"])
            if not provider:
                raise ValidateErrorException("该模型服务提供商不存在 请核实后重试")

            # 3.3 判断模型信息是否正确
            if not model_config["model"] or not isinstance(model_config["model"], str):
                raise ValidateErrorException("模型名字类型必须为字符串")
            model_entity = provider.get_model_entity(model_config["model"])
            if not model_entity:
                raise ValidateErrorException("该模型服务提供商下不存在该模型,请核实后重试")

            # 3.5 判断传递的parameters是否正确 如果不正确则设置为默认值 并剔除多余字段 补全未传递的字段
            parameters = {}
            for parameter in model_entity.parameters:
                # 3.6 从model_config中获取参数值，如果不存在则设置为默认值
                parameter_value = model_config["parameters"].get(parameter.name, parameter.default)

                # 3.7 判断参数是否必填
                if parameter.required:
                    # 3.8 参数必填，则值不允许为None，如果为None则设置默认值
                    if parameter_value is None:
                        parameter_value = parameter.default
                    else:
                        # 3.9 值非空则校验数据类型是否正确，不正确则设置默认值
                        if get_value_type(parameter_value) != parameter.type.value:
                            parameter_value = parameter.default
                else:
                    # 3.10 参数非必填，数据非空的情况下需要校验
                    if parameter_value is not None:
                        if get_value_type(parameter_value) != parameter.type.value:
                            parameter_value = parameter.default

                # 3.11 判断参数是否存在options，如果存在则数值必须在options中选择
                if parameter.options and parameter_value not in parameter.options:
                    parameter_value = parameter.default

                # 3.12 参数类型为int/float，如果存在min/max时候需要校验
                if parameter.type in [ModelParameterType.INT.value,
                                      ModelParameterType.FLOAT.value] and parameter_value is not None:
                    # 3.13 校验数值的min/max
                    if (
                            (parameter.min and parameter_value < parameter.min)
                            or (parameter.max and parameter_value > parameter.max)
                    ):
                        parameter_value = parameter.default

                parameters[parameter.name] = parameter_value

            # 3.13 覆盖Agent配置中的模型配置
            model_config["parameters"] = parameters
            draft_app_config["model_config"] = model_config

        # 4.校验dialog_round上下文轮数，校验数据类型以及范围
        if "dialog_round" in draft_app_config:
            dialog_round = draft_app_config["dialog_round"]
            if not isinstance(dialog_round, int) or not (0 <= dialog_round <= 100):
                raise ValidateErrorException("携带上下文轮数范围为0-100")

        # 5.校验preset_prompt
        if "preset_prompt" in draft_app_config:
            preset_prompt = draft_app_config["preset_prompt"]
            if not isinstance(preset_prompt, str) or len(preset_prompt) > 5000:
                raise ValidateErrorException("人设与回复逻辑必须是字符串，长度在0-5000个字符")

        # 6.校验tools工具
        if "tools" in draft_app_config:
            tools = draft_app_config["tools"]
            validate_tools = []

            # 6.1 tools类型必须为列表，空列表则代表不绑定任何工具
            if not isinstance(tools, list):
                raise ValidateErrorException("工具列表必须是列表型数据")
            # 6.2 tools的长度不能超过5
            if len(tools) > 5:
                raise ValidateErrorException("Agent绑定的工具数不能超过5")
            # 6.3 循环校验工具里的每一个参数
            for tool in tools:
                # 6.4 校验tool非空并且类型为字典
                if not tool or not isinstance(tool, dict):
                    raise ValidateErrorException("绑定插件工具参数出错")
                # 6.5 校验工具的参数是不是type、provider_id、tool_id、params
                if set(tool.keys()) != {"type", "provider_id", "tool_id", "params"}:
                    raise ValidateErrorException("绑定插件工具参数出错")
                # 6.6 校验type类型是否为builtin_tool以及api_tool
                if tool["type"] not in ["builtin_tool", "api_tool"]:
                    raise ValidateErrorException("绑定插件工具参数出错")
                # 6.7 校验provider_id和tool_id
                if (
                        not tool["provider_id"]
                        or not tool["tool_id"]
                        or not isinstance(tool["provider_id"], str)
                        or not isinstance(tool["tool_id"], str)
                ):
                    raise ValidateErrorException("插件提供者或者插件标识参数出错")
                # 6.8 校验params参数，类型为字典
                if not isinstance(tool["params"], dict):
                    raise ValidateErrorException("插件自定义参数格式错误")
                # 6.9 校验对应的工具是否存在，而且需要划分成builtin_tool和api_tool
                if tool["type"] == "builtin_tool":
                    builtin_tool = self.builtin_provider_manager.get_tool(tool["provider_id"], tool["tool_id"])
                    if not builtin_tool:
                        continue
                else:
                    api_tool = self.db.session.query(ApiTool).filter(
                        ApiTool.provider_id == tool["provider_id"],
                        ApiTool.name == tool["tool_id"],
                        ApiTool.account_id == account.id,
                    ).one_or_none()
                    if not api_tool:
                        continue

                validate_tools.append(tool)

            # 6.10 校验绑定的工具是否重复
            check_tools = [f"{tool['provider_id']}_{tool['tool_id']}" for tool in validate_tools]
            if len(set(check_tools)) != len(validate_tools):
                raise ValidateErrorException("绑定插件存在重复")

            # 6.11 重新赋值工具
            draft_app_config["tools"] = validate_tools

        # 7.校验workflow 提取已发布+权限正确的工作流列表进行绑定(更新配置阶段不校验工作流是否可以正确运行)
        if "workflows" in draft_app_config:
            workflows = draft_app_config["workflows"]

            # 7.1 判断workflows是否为列表
            if not isinstance(workflows, list):
                raise ValidateErrorException("绑定工作流列表参数错误")

            # 7.2 判断关联的工作流列表是否超过五个
            if len(workflows) > 5:
                raise ValidateErrorException("Agent绑定的工作流数量不能超过5个")

            # 7.3 循环校验工作流的每个参数 类型必须是UUID
            for workflow in workflows:
                try:
                    UUID(workflow)
                except Exception as e:
                    raise ValidateErrorException("工作流参数必须是UUID")

            # 7.4 判断是否重复关联了工作流
            if len(set(workflows)) != len(workflows):
                raise ValidateErrorException("绑定工作流存在重复")

            # 7.5 校验关联工作流权限 剔除不属于当前账号 亦或者未发布的工作流
            workflow_records = self.db.session.query(Workflow).filter(
                Workflow.id.in_(workflows),
                Workflow.account_id == account.id,
                Workflow.status == WorkflowStatus.PUBLISHED.value
            ).all()

            workflow_sets = set([str(workflow_record.id) for workflow_record in workflow_records])
            draft_app_config["workflows"] = [workflow_id for workflow_id in workflows if workflow_id in workflow_sets]

        # 7.6 校验 workflow_id（仅 workflow 类型应用有效，单值字段，区别于多选 workflows）
        if "workflow_id" in draft_app_config:
            # 加载应用实例以判断 app_type（fallback_history_to_draft/update_draft_app_config 均会传 app_id）
            app_record = self.db.session.get(App, app_id) if app_id is not None else None
            if app_record is not None and app_record.app_type == AppType.WORKFLOW.value:
                workflow_id = draft_app_config.get("workflow_id")
                if workflow_id:
                    # 校验 workflow_id 必须是有效 UUID
                    try:
                        wf_id = UUID(str(workflow_id)) if not isinstance(workflow_id, UUID) else workflow_id
                    except (ValueError, TypeError):
                        raise ValidateErrorException("workflow_id 必须是有效的 UUID")
                    # 校验 workflow 存在且属于当前账号、且为已发布状态
                    workflow = self.db.session.get(Workflow, wf_id)
                    if not workflow or workflow.account_id != account.id:
                        raise NotFoundException("工作流不存在或无权访问")
                    if workflow.status != WorkflowStatus.PUBLISHED.value:
                        raise ValidateErrorException("只能绑定已发布的工作流")
                    # 规范化为字符串形式存储
                    draft_app_config["workflow_id"] = str(wf_id)
                else:
                    # 显式 None 表示解绑
                    draft_app_config["workflow_id"] = None
            else:
                # 非 workflow 类型应用不允许设置 workflow_id
                draft_app_config["workflow_id"] = None

        # 8.校验MCP绑定配置
        if "mcp_bindings" in draft_app_config:
            mcp_bindings = draft_app_config["mcp_bindings"]

            if not isinstance(mcp_bindings, list):
                raise ValidateErrorException("MCP绑定列表参数格式错误")
            if len(mcp_bindings) > 5:
                raise ValidateErrorException("Agent绑定的MCP数量不能超过5个")

            validate_mcp_bindings = []
            seen_binding_targets: set[str] = set()
            for binding in mcp_bindings:
                if not binding or not isinstance(binding, dict):
                    raise ValidateErrorException("MCP绑定参数出错")

                allowed_keys = {
                    "name", "description", "transport", "url", "enabled",
                    "headers", "tool_names", "timeout_seconds", "command",
                    "args", "env", "provider_key", "source_type",
                    "source_key", "source_url", "label", "icon", "category",
                }
                if set(binding.keys()) - allowed_keys:
                    raise ValidateErrorException("MCP绑定参数出错")

                name = str(binding.get("name", "")).strip()
                description = str(binding.get("description", "")).strip()
                transport = str(binding.get("transport", "streamable_http")).strip().lower() or "streamable_http"
                url = str(binding.get("url", "")).strip()
                command = str(binding.get("command", "")).strip()
                enabled = binding.get("enabled", True)
                headers = binding.get("headers", [])
                tool_names = binding.get("tool_names", [])
                timeout_seconds = binding.get("timeout_seconds", 30)
                args = binding.get("args", [])
                env = binding.get("env", {})
                provider_key = str(binding.get("provider_key", "")).strip()
                source_type = str(binding.get("source_type", "")).strip()
                source_key = str(binding.get("source_key", "")).strip()
                source_url = str(binding.get("source_url", "")).strip()
                label = str(binding.get("label", "")).strip()
                icon = str(binding.get("icon", "")).strip()
                category = str(binding.get("category", "")).strip()

                if not name or not isinstance(name, str):
                    raise ValidateErrorException("MCP绑定名称不能为空")
                if not isinstance(enabled, bool):
                    raise ValidateErrorException("MCP绑定启用状态格式错误")

                if transport in {"http", "sse", "streamable_http", "streamable-http"}:
                    if not url:
                        raise ValidateErrorException("MCP绑定URL不能为空")
                elif transport == "stdio":
                    if not command:
                        raise ValidateErrorException("MCP绑定命令不能为空")
                else:
                    raise ValidateErrorException("MCP transport格式错误")

                if not isinstance(headers, list):
                    raise ValidateErrorException("MCP headers格式错误")
                if not isinstance(tool_names, list):
                    raise ValidateErrorException("MCP tool_names格式错误")
                if not isinstance(args, list):
                    raise ValidateErrorException("MCP args格式错误")
                if not isinstance(env, dict):
                    raise ValidateErrorException("MCP env格式错误")
                if timeout_seconds is not None and (
                    not isinstance(timeout_seconds, int)
                    or isinstance(timeout_seconds, bool)
                    or timeout_seconds <= 0
                ):
                    raise ValidateErrorException("MCP timeout_seconds格式错误")

                normalized_headers = []
                for header in headers:
                    if not isinstance(header, dict):
                        raise ValidateErrorException("MCP headers格式错误")
                    if not str(header.get("key", "")).strip():
                        raise ValidateErrorException("MCP headers格式错误")
                    normalized_headers.append({
                        "key": str(header.get("key", "")).strip(),
                        "value": str(header.get("value", "")).strip(),
                    })

                normalized_tool_names = []
                for tool_name in tool_names:
                    normalized_tool_name = str(tool_name).strip()
                    if not normalized_tool_name:
                        continue
                    normalized_tool_names.append(normalized_tool_name)

                normalized_args = [str(arg).strip() for arg in args if str(arg).strip()]
                normalized_env = {
                    str(key).strip(): str(value).strip()
                    for key, value in env.items()
                    if str(key).strip()
                }

                binding_identity = provider_key or f"{transport}:{url or command}:{name}"
                if binding_identity in seen_binding_targets:
                    raise ValidateErrorException("MCP绑定存在重复")
                seen_binding_targets.add(binding_identity)

                validate_mcp_bindings.append({
                    "name": name,
                    "description": description,
                    "transport": transport,
                    "url": url,
                    "command": command,
                    "enabled": enabled,
                    "headers": normalized_headers,
                    "tool_names": normalized_tool_names,
                    "timeout_seconds": timeout_seconds or 30,
                    "args": normalized_args,
                    "env": normalized_env,
                    "provider_key": provider_key,
                    "source_type": source_type,
                    "source_key": source_key,
                    "source_url": source_url,
                    "label": label,
                    "icon": icon,
                    "category": category,
                })

            draft_app_config["mcp_bindings"] = validate_mcp_bindings

        # 9.校验skills技能列表
        if "skills" in draft_app_config:
            skills = draft_app_config["skills"]

            if not isinstance(skills, list):
                raise ValidateErrorException("绑定技能列表参数格式错误")

            skill_service = self._get_skill_service()
            _, validate_skills = skill_service.process_and_validate_skill_bindings(skills)
            draft_app_config["skills"] = validate_skills

        # 10.校验datasets知识库列表
        if "datasets" in draft_app_config:
            datasets = draft_app_config["datasets"]

            # 8.1 判断datasets类型是否为列表
            if not isinstance(datasets, list):
                raise ValidateErrorException("绑定知识库列表参数格式错误")
            # 8.2 判断关联的知识库列表是否超过5个
            if len(datasets) > 5:
                raise ValidateErrorException("Agent绑定的知识库数量不能超过5个")
            # 8.3 循环校验知识库的每个参数
            for dataset_id in datasets:
                try:
                    UUID(dataset_id)
                except Exception as e:
                    raise ValidateErrorException("知识库列表参数必须是UUID")
            # 8.4 判断是否传递了重复的知识库
            if len(set(datasets)) != len(datasets):
                raise ValidateErrorException("绑定知识库存在重复")
            # 8.5 校验绑定的知识库权限，剔除不属于当前账号的知识库
            dataset_records = self.db.session.query(Dataset).filter(
                Dataset.id.in_(datasets),
                Dataset.account_id == account.id,
            ).all()
            dataset_sets = set([str(dataset_record.id) for dataset_record in dataset_records])
            draft_app_config["datasets"] = [dataset_id for dataset_id in datasets if dataset_id in dataset_sets]

        # 11.校验retrieval_config检索配置
        if "retrieval_config" in draft_app_config:
            retrieval_config = draft_app_config["retrieval_config"]

            # 9.1 判断检索配置非空且类型为字典
            if not retrieval_config or not isinstance(retrieval_config, dict):
                raise ValidateErrorException("检索配置格式错误")
            # 9.2 校验检索配置的字段类型
            if set(retrieval_config.keys()) != {"retrieval_strategy", "k", "score"}:
                raise ValidateErrorException("检索配置格式错误")
            # 9.3 校验检索策略是否正确
            if retrieval_config["retrieval_strategy"] not in ["semantic", "full_text", "hybrid"]:
                raise ValidateErrorException("检测策略格式错误")
            # 9.4 校验最大召回数量
            if not isinstance(retrieval_config["k"], int) or not (0 <= retrieval_config["k"] <= 10):
                raise ValidateErrorException("最大召回数量范围为0-10")
            # 9.5 校验得分/最小匹配度
            if not isinstance(retrieval_config["score"], float) or not (0 <= retrieval_config["score"] <= 1):
                raise ValidateErrorException("最小匹配范围为0-1")

        # 12.校验long_term_memory长期记忆配置
        if "long_term_memory" in draft_app_config:
            long_term_memory = draft_app_config["long_term_memory"]

            # 10.1 校验长期记忆格式
            if not long_term_memory or not isinstance(long_term_memory, dict):
                raise ValidateErrorException("长期记忆设置格式错误")
            # 10.2 校验长期记忆属性
            if (
                    set(long_term_memory.keys()) != {"enable"}
                    or not isinstance(long_term_memory["enable"], bool)
            ):
                raise ValidateErrorException("长期记忆设置格式错误")

        # 13.校验opening_statement对话开场白
        if "opening_statement" in draft_app_config:
            opening_statement = draft_app_config["opening_statement"]

            # 11.1 校验对话开场白类型以及长度
            if not isinstance(opening_statement, str) or len(opening_statement) > 2000:
                raise ValidateErrorException("对话开场白的长度范围是0-2000")

        # 14.校验opening_questions开场建议问题列表
        if "opening_questions" in draft_app_config:
            opening_questions = draft_app_config["opening_questions"]

            # 12.1 校验是否为列表，并且长度不超过3
            if not isinstance(opening_questions, list) or len(opening_questions) > 3:
                raise ValidateErrorException("开场建议问题不能超过3个")
            # 12.2 开场建议问题每个元素都是一个字符串
            for opening_question in opening_questions:
                if not isinstance(opening_question, str):
                    raise ValidateErrorException("开场建议问题必须是字符串")

        # 15.校验speech_to_text语音转文本
        if "speech_to_text" in draft_app_config:
            speech_to_text = draft_app_config["speech_to_text"]

            # 13.1 校验语音转文本格式
            if not speech_to_text or not isinstance(speech_to_text, dict):
                raise ValidateErrorException("语音转文本设置格式错误")
            # 13.2 校验语音转文本属性
            if (
                    set(speech_to_text.keys()) != {"enable"}
                    or not isinstance(speech_to_text["enable"], bool)
            ):
                raise ValidateErrorException("语音转文本设置格式错误")

        # 16.校验text_to_speech文本转语音设置
        if "text_to_speech" in draft_app_config:
            text_to_speech = draft_app_config["text_to_speech"]

            # 14.1 校验字典格式
            if not isinstance(text_to_speech, dict):
                raise ValidateErrorException("文本转语音设置格式错误")
            # 14.2 校验字段类型
            if (
                    set(text_to_speech.keys()) != {"enable", "voice", "auto_play"}
                    or not isinstance(text_to_speech["enable"], bool)
                    or text_to_speech["voice"] not in ALLOWED_AUDIO_VOICES
                    or not isinstance(text_to_speech["auto_play"], bool)
            ):
                raise ValidateErrorException("文本转语音设置格式错误")

        # 17.校验回答后生成建议问题
        if "suggested_after_answer" in draft_app_config:
            suggested_after_answer = draft_app_config["suggested_after_answer"]

            # 10.1 校验回答后建议问题格式
            if not suggested_after_answer or not isinstance(suggested_after_answer, dict):
                raise ValidateErrorException("回答后建议问题设置格式错误")
            # 10.2 校验回答后建议问题格式
            if (
                    set(suggested_after_answer.keys()) != {"enable"}
                    or not isinstance(suggested_after_answer["enable"], bool)
            ):
                raise ValidateErrorException("回答后建议问题设置格式错误")

        # 17.校验review_config审核配置
        if "review_config" in draft_app_config:
            review_config = draft_app_config["review_config"]

            # 16.1 校验字段格式，非空
            if not review_config or not isinstance(review_config, dict):
                raise ValidateErrorException("审核配置格式错误")
            # 16.2 校验字段信息
            if set(review_config.keys()) != {"enable", "keywords", "inputs_config", "outputs_config"}:
                raise ValidateErrorException("审核配置格式错误")
            # 16.3 校验enable
            if not isinstance(review_config["enable"], bool):
                raise ValidateErrorException("review.enable格式错误")
            # 16.4 校验keywords
            if (
                    not isinstance(review_config["keywords"], list)
                    or (review_config["enable"] and len(review_config["keywords"]) == 0)
                    or len(review_config["keywords"]) > 100
            ):
                raise ValidateErrorException("review.keywords非空且不能超过100个关键词")
            for keyword in review_config["keywords"]:
                if not isinstance(keyword, str):
                    raise ValidateErrorException("review.keywords敏感词必须是字符串")
            # 16.5 校验inputs_config输入配置
            if (
                    not review_config["inputs_config"]
                    or not isinstance(review_config["inputs_config"], dict)
                    or set(review_config["inputs_config"].keys()) != {"enable", "preset_response"}
                    or not isinstance(review_config["inputs_config"]["enable"], bool)
                    or not isinstance(review_config["inputs_config"]["preset_response"], str)
            ):
                raise ValidateErrorException("review.inputs_config必须是一个字典")
            # 16.6 校验outputs_config输出配置
            if (
                    not review_config["outputs_config"]
                    or not isinstance(review_config["outputs_config"], dict)
                    or set(review_config["outputs_config"].keys()) != {"enable"}
                    or not isinstance(review_config["outputs_config"]["enable"], bool)
            ):
                raise ValidateErrorException("review.outputs_config格式错误")
            # 16.7 在开启审核模块的时候，必须确保inputs_config或者是outputs_config至少有一个是开启的
            if review_config["enable"]:
                if (
                        review_config["inputs_config"]["enable"] is False
                        and review_config["outputs_config"]["enable"] is False
                ):
                    raise ValidateErrorException("输入审核和输出审核至少需要开启一项")

                if (
                        review_config["inputs_config"]["enable"]
                        and review_config["inputs_config"]["preset_response"].strip() == ""
                ):
                    raise ValidateErrorException("输入审核预设响应不能为空")

        # 18.校验Agent绑定
        if "agent_bindings" in draft_app_config:
            if app_id is None:
                raise ValidateErrorException("Agent绑定校验缺少应用ID")

            agent_bindings = draft_app_config["agent_bindings"]
            if not isinstance(agent_bindings, list):
                raise ValidateErrorException("Agent绑定列表必须是列表型数据")

            _, validate_agent_bindings = self.app_config_service.process_and_validate_agent_bindings(
                agent_bindings,
                current_account_id=account.id,
                current_app_id=app_id,
                strict=True,
            )
            draft_app_config["agent_bindings"] = validate_agent_bindings

        return draft_app_config
