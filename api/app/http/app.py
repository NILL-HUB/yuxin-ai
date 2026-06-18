import logging
import os

from flask_migrate import Migrate
from flask_mail import Mail
from config import Config
from internal.router import Router
from internal.server import Http
from internal.service import AppService
from pkg.sqlalchemy import SQLAlchemy
from pkg.env_loader import load_project_env
from flask_weaviate import FlaskWeaviate
from .module import injector
from flask_login import LoginManager
from internal.middleware import Middleware

load_project_env()


conf = Config()

app = Http(
    __name__,
    conf=conf,
    db=injector.get(SQLAlchemy),
    weaviate=injector.get(FlaskWeaviate),
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
