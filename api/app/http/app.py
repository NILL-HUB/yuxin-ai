import logging
import os

from config import Config
from internal.server import Http
from internal.context import init_runtime
from pkg.env_loader import load_project_env
from .module import injector

load_project_env()


def _graceful_disable_invalid_langsmith_tracing() -> None:
    """LangSmith 链路追踪 graceful 降级。"""
    if os.getenv("LANGCHAIN_TRACING_V2", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return

    api_key = (os.getenv("LANGCHAIN_API_KEY") or "").strip()
    if api_key and not api_key.lower().startswith("your-") and "-here" not in api_key.lower():
        return

    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    logging.warning(
        "LangSmith tracing disabled: LANGCHAIN_API_KEY is empty or placeholder. "
        "Configure a valid API key in .env to enable tracing."
    )


_graceful_disable_invalid_langsmith_tracing()


conf = Config()

# 纯容器（无 Flask 依赖）：承载配置 + db/mail/redis/neo4j/logging 扩展单例
app = Http(
    __name__,
    conf=conf,
)
# 将 injector 挂载到容器，供 service 层获取依赖（上传/索引等链路必需）
app.injector = injector

# 注册全局运行时上下文（替代 Flask current_app）
init_runtime(app)


def _should_sync_skill_catalog_on_startup() -> bool:
    mode = os.getenv("MODE", "api")
    enabled = app.config.get("SKILL_CATALOG_SYNC_ENABLED", False)
    return mode != "celery" and bool(enabled)


def _is_truthy_env(env_name: str, default: str = "0") -> bool:
    """把常见布尔型环境变量归一化为 Python bool。"""
    return os.getenv(env_name, default).strip().lower() in {"1", "true", "yes", "on"}


def _should_enable_direct_run_debug() -> bool:
    value = os.getenv("APP_DEBUG")
    if value is None:
        return True
    normalized = value.strip().lower()
    if normalized == "0" and os.getenv("MODE") == "celery":
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return True


def run_startup_sync_initialization() -> None:
    """启动时的同步初始化（skill/builtin/prompt/RBAC/存储/记忆降级管理等）。

    使用同步 session（db.sync_session_factory），不依赖任何 Web 框架上下文。
    """
    # 启动时同步技能目录（MODE=api 且开启时）
    if _should_sync_skill_catalog_on_startup():
        try:
            from internal.service import SkillService

            synced_count = injector.get(SkillService).ensure_local_catalog_synced()
            logging.info("启动时同步技能目录完成，共同步 %s 个技能包", synced_count)
        except Exception:
            logging.exception("启动时同步技能目录失败")

    # 启动时同步 builtin 工具 YAML→DB 镜像表
    if os.getenv("MODE", "api") != "celery" and _is_truthy_env("BUILTIN_TOOL_SYNC_ENABLED", "1"):
        try:
            from internal.service import BuiltinToolSyncService

            sync_stats = injector.get(BuiltinToolSyncService).sync_yaml_to_db()
            logging.info("启动时同步 builtin 工具元数据完成: %s", sync_stats)
        except Exception:
            logging.exception("启动时同步 builtin 工具元数据失败")

    # 启动时补齐系统预置的 public_ai_feature_config 记录
    if os.getenv("MODE", "api") != "celery":
        try:
            from internal.service.public_ai_feature_service import PublicAIFeatureService

            inserted = injector.get(PublicAIFeatureService).ensure_builtin_features()
            if inserted > 0:
                logging.info("启动时补齐公共 AI 功能配置 %d 条", inserted)
        except Exception:
            logging.exception("启动时补齐公共 AI 功能配置失败")

    # 启动时同步 prompt 模板 YAML→DB
    if os.getenv("MODE", "api") != "celery" and _is_truthy_env("PROMPT_SYNC_ENABLED", "1"):
        try:
            from internal.service.prompt_sync_service import PromptSyncService

            sync_stats = injector.get(PromptSyncService).sync_yaml_to_db()
            logging.info("启动时同步 prompt 模板完成: %s", sync_stats)
        except Exception:
            logging.exception("启动时同步 prompt 模板失败")

    # 启动时同步系统提示词库 YAML→系统知识库
    if os.getenv("MODE", "api") != "celery" and _is_truthy_env("SYSTEM_PROMPT_SYNC_ENABLED", "1"):
        try:
            from internal.service.system_prompt_library_service import SystemPromptLibraryService

            SystemPromptLibraryService().ensure_seed_prompts()
            logging.info("启动时同步系统提示词库完成")
        except Exception:
            logging.exception("启动时同步系统提示词库失败")

    assistant_mcp_bindings = app.config.get("ASSISTANT_MCP_BINDINGS", [])
    if isinstance(assistant_mcp_bindings, list) and assistant_mcp_bindings:
        try:
            injector.get(__import__("internal.service", fromlist=["AppService"]).AppService).prewarm_assistant_mcp_tool_snapshots()
        except Exception:
            logging.exception("启动时预热首页助手 MCP 快照失败")

    if os.getenv("MODE", "api") != "celery" and _is_truthy_env("ADMIN_BOOTSTRAP_ENABLED", "1"):
        try:
            from internal.service.admin_rbac_service import AdminRbacService
            from internal.service.admin_user_service import AdminUserService

            rbac_service = AdminRbacService()
            rbac_result = rbac_service.initialize_defaults()
            logging.info("启动时初始化 RBAC 默认角色完成: %s", rbac_result)

            admin_service = AdminUserService()
            admin_result = admin_service.initialize_super_admin_from_env()
            logging.info("启动时初始化超级管理员完成: %s", admin_result)
        except Exception:
            logging.exception("启动时初始化 RBAC/超级管理员失败")

    # 启动时确保存储后端配置存在
    if os.getenv("MODE", "api") != "celery":
        try:
            from internal.service.storage.storage_config_service import StorageConfigService

            injector.get(StorageConfigService).ensure_default_config()
        except Exception:
            logging.exception("启动时初始化存储配置失败")

    # 初始化记忆系统降级管理器
    try:
        from internal.service.memory.degradation_manager import init_degradation_manager
        from internal.extension.neo4j_extension import get_driver as get_neo4j_driver

        init_degradation_manager(
            neo4j_driver=get_neo4j_driver(),
            db=injector.get(__import__("pkg.sqlalchemy", fromlist=["SQLAlchemy"]).SQLAlchemy),
            redis_client=app.extensions.get("redis"),
            celery_app=None,
            flask_app=None,
        )
        logging.info("记忆系统 DegradationManager 初始化完成")
    except Exception:
        logging.exception("启动时初始化 DegradationManager 失败")


# 模块导入即执行启动初始化（与旧行为一致，容器/ASGI/Celery 共用）
run_startup_sync_initialization()

# Celery 实例（阶段 C 解耦：独立于容器初始化，见 app.http.celery_app）
from app.http.celery_app import celery_app as celery  # noqa: E402

if __name__ == "__main__":
    debug_mode = _should_enable_direct_run_debug()
    logging.warning(
        "app.http.app 已迁移为纯容器（无 Flask），HTTP 服务由 ASGI 入口 "
        "app.http.asgi_app:app（uvicorn）承载。直接运行仅保留调试语义。"
    )
