import logging
import os

from flask_migrate import Migrate
from flask_mail import Mail
from redis import Redis
from config import Config
from internal.router import Router
from internal.server import Http
from internal.service import AppService
from pkg.sqlalchemy import SQLAlchemy
from pkg.env_loader import load_project_env
from .module import injector
from flask_login import LoginManager
from internal.middleware import Middleware

load_project_env()


def _graceful_disable_invalid_langsmith_tracing() -> None:
    """LangSmith 链路追踪 graceful 降级。

    链路追踪是系统应有的功能，当配置了有效的 LANGCHAIN_API_KEY 时自动启用。
    当 API key 为占位符或空值时，禁用 tracing 避免每次请求产生 403 WARNING 刷屏。

    降级条件（满足任一即禁用）：
        - LANGCHAIN_API_KEY 为空
        - LANGCHAIN_API_KEY 是占位符（your-*-here 模式）
    """
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

app = Http(
    __name__,
    conf=conf,
    db=injector.get(SQLAlchemy),
    migrate=injector.get(Migrate),
    login_manager=injector.get(LoginManager),
    mail=injector.get(Mail),
    middleware=injector.get(Middleware),
    router=injector.get(Router),
)


def _should_sync_skill_catalog_on_startup() -> bool:
    mode = os.getenv("MODE", "api")
    enabled = app.config.get("SKILL_CATALOG_SYNC_ENABLED", False)
    return mode != "celery" and bool(enabled)


def _is_truthy_env(env_name: str, default: str = "0") -> bool:
    """把常见布尔型环境变量归一化为 Python bool。"""
    return os.getenv(env_name, default).strip().lower() in {"1", "true", "yes", "on"}


def _should_enable_direct_run_debug() -> bool:
    value = os.getenv("FLASK_DEBUG")
    if value is None:
        return True
    normalized = value.strip().lower()
    if normalized == "0" and os.getenv("MODE") == "celery":
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return True


with app.app_context():
    if _should_sync_skill_catalog_on_startup():
        try:
            from internal.service import SkillService

            synced_count = injector.get(SkillService).ensure_local_catalog_synced()
            logging.info("启动时同步技能目录完成，共同步 %s 个技能包", synced_count)
        except Exception:
            logging.exception("启动时同步技能目录失败")

    # 启动时同步 builtin 工具 YAML→DB 镜像表（admin 后台可编辑元数据）
    if os.getenv("MODE", "api") != "celery" and _is_truthy_env("BUILTIN_TOOL_SYNC_ENABLED", "1"):
        try:
            from internal.service import BuiltinToolSyncService

            sync_stats = injector.get(BuiltinToolSyncService).sync_yaml_to_db()
            logging.info("启动时同步 builtin 工具元数据完成: %s", sync_stats)
        except Exception:
            logging.exception("启动时同步 builtin 工具元数据失败")

    # 启动时补齐系统预置的 public_ai_feature_config 记录（如 conductor 指挥官）
    if os.getenv("MODE", "api") != "celery":
        try:
            from internal.service.public_ai_feature_service import PublicAIFeatureService

            inserted = injector.get(PublicAIFeatureService).ensure_builtin_features()
            if inserted > 0:
                logging.info("启动时补齐公共 AI 功能配置 %d 条", inserted)
        except Exception:
            logging.exception("启动时补齐公共 AI 功能配置失败")

    # 启动时同步 prompt 模板 YAML→DB（指挥官等系统 prompt 从 DB 加载）
    if os.getenv("MODE", "api") != "celery" and _is_truthy_env("PROMPT_SYNC_ENABLED", "1"):
        try:
            from internal.service.prompt_sync_service import PromptSyncService

            sync_stats = injector.get(PromptSyncService).sync_yaml_to_db()
            logging.info("启动时同步 prompt 模板完成: %s", sync_stats)
        except Exception:
            logging.exception("启动时同步 prompt 模板失败")

    assistant_mcp_bindings = app.config.get("ASSISTANT_MCP_BINDINGS", [])
    if isinstance(assistant_mcp_bindings, list) and assistant_mcp_bindings:
        try:
            injector.get(AppService).prewarm_assistant_mcp_tool_snapshots()
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

    # 初始化记忆系统降级管理器（启动 Neo4j/pgvector/Redis/Celery 健康检查）
    try:
        from internal.service.memory.degradation_manager import init_degradation_manager
        from internal.extension.neo4j_extension import get_driver as get_neo4j_driver

        init_degradation_manager(
            neo4j_driver=get_neo4j_driver(),
            db=injector.get(SQLAlchemy),
            redis_client=injector.get(Redis),
            celery_app=app.extensions.get("celery"),
            flask_app=app,
        )
        logging.info("记忆系统 DegradationManager 初始化完成")
    except Exception:
        logging.exception("启动时初始化 DegradationManager 失败")

celery = app.extensions['celery']

if __name__ == "__main__":
    from internal.extension.socketio_extension import socketio as socketio_server

    debug_mode = _should_enable_direct_run_debug()

    if os.getenv("MODE", "api") != "celery" and socketio_server is not None and debug_mode:
        socketio_server.run(
            app,
            host="0.0.0.0",
            port=5001,
            debug=True,
            use_reloader=False,
            allow_unsafe_werkzeug=True,
        )
    else:
        app.run(debug=debug_mode, port=5001)
