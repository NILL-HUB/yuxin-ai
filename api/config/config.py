import json
import os
from typing import Any
from kombu import Queue
from celery.schedules import crontab
from .default_config import DEFAULT_CONFIG


def _get_env(key: str) -> Any:
    """从环境变量中获取配置项，如果找不到则返回默认值"""
    return os.getenv(key, DEFAULT_CONFIG.get(key))


def _get_bool_env(key: str) -> bool:
    """从环境变量中获取布尔值型的配置项，如果找不到则返回默认值"""
    value = _get_env(key)
    if value is None:
        return False

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return False


def _get_list_env(key: str) -> list[str]:
    """从环境变量中获取字符串列表配置，逗号分隔。"""
    value = _get_env(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _get_json_env(key: str, default: Any = None) -> Any:
    """从环境变量中获取 JSON 配置，解析失败时回退到默认值。"""
    value = os.getenv(key)
    if value is None or str(value).strip() == "":
        return DEFAULT_CONFIG.get(key, default)
    try:
        return json.loads(value)
    except Exception:
        return DEFAULT_CONFIG.get(key, default)


def _build_redis_auth(username: Any, password: Any) -> str:
    """构建 Redis 认证片段，兼容空用户名或空密码。"""
    redis_username = str(username or "")
    redis_password = str(password or "")

    if redis_username and redis_password:
        return f"{redis_username}:{redis_password}@"
    if redis_username:
        return f"{redis_username}@"
    if redis_password:
        return f":{redis_password}@"
    return ""


def _build_redis_url(*, host: Any, port: Any, db: Any, use_ssl: bool, username: Any, password: Any) -> str:
    """统一构建 Redis 连接 URL。"""
    protocol = "rediss" if use_ssl else "redis"
    auth = _build_redis_auth(username, password)
    return f"{protocol}://{auth}{host}:{port}/{db}"


class Config:
    def __init__(self):
        # 关闭wtf的csrf保护
        self.WTF_CSRF_ENABLED = _get_bool_env("WTF_CSRF_ENABLED")
        self.CORS_ALLOW_ORIGINS = _get_list_env("CORS_ALLOW_ORIGINS")
        self.CORS_SUPPORTS_CREDENTIALS = _get_bool_env("CORS_SUPPORTS_CREDENTIALS")
        self.OAUTH_ALLOWED_ORIGINS = _get_list_env("OAUTH_ALLOWED_ORIGINS")
        self.WEB_APP_VISITOR_COOKIE_SECURE = _get_bool_env("WEB_APP_VISITOR_COOKIE_SECURE")
        self.WEB_APP_VISITOR_COOKIE_SECRET = _get_env("WEB_APP_VISITOR_COOKIE_SECRET")

        # SQLAlchemy数据库配置
        self.SQLALCHEMY_DATABASE_URI = _get_env("SQLALCHEMY_DATABASE_URI")
        if os.getenv("POSTGRES_HOST"):
            self.SQLALCHEMY_DATABASE_URI = (
                f"postgresql://{_get_env('POSTGRES_USER')}:{_get_env('POSTGRES_PASSWORD')}@"
                f"{_get_env('POSTGRES_HOST')}:{_get_env('POSTGRES_PORT')}/{_get_env('POSTGRES_DB')}?client_encoding=utf8"
            )
        self.SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": int(_get_env("SQLALCHEMY_POOL_SIZE")),
            "max_overflow": int(_get_env("SQLALCHEMY_MAX_OVERFLOW")),
            "pool_recycle": int(_get_env("SQLALCHEMY_POOL_RECYCLE")),
            "pool_timeout": int(_get_env("SQLALCHEMY_POOL_TIMEOUT")),
            "pool_pre_ping": _get_bool_env("SQLALCHEMY_POOL_PRE_PING"),
        }
        # 强制数据库会话使用UTC，避免CURRENT_TIMESTAMP受连接时区影响
        if self.SQLALCHEMY_DATABASE_URI and self.SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
            statement_timeout_ms = int(_get_env("SQLALCHEMY_STATEMENT_TIMEOUT_MS"))
            options = ["-c timezone=UTC"]
            if statement_timeout_ms > 0:
                options.append(f"-c statement_timeout={statement_timeout_ms}")
            self.SQLALCHEMY_ENGINE_OPTIONS["connect_args"] = {
                "connect_timeout": int(_get_env("SQLALCHEMY_CONNECT_TIMEOUT")),
                "options": " ".join(options),
            }
        self.SQLALCHEMY_ECHO = _get_bool_env("SQLALCHEMY_ECHO")

        # Redis配置
        self.REDIS_HOST = _get_env("REDIS_HOST")
        self.REDIS_PORT = _get_env("REDIS_PORT")
        self.REDIS_USERNAME = _get_env("REDIS_USERNAME")
        self.REDIS_PASSWORD = _get_env("REDIS_PASSWORD")
        self.REDIS_DB = _get_env("REDIS_DB")
        self.REDIS_USE_SSL = _get_bool_env("REDIS_USE_SSL")
        self.REDIS_SOCKET_CONNECT_TIMEOUT = float(_get_env("REDIS_SOCKET_CONNECT_TIMEOUT"))
        self.REDIS_SOCKET_TIMEOUT = float(_get_env("REDIS_SOCKET_TIMEOUT"))
        self.REDIS_HEALTH_CHECK_INTERVAL = int(_get_env("REDIS_HEALTH_CHECK_INTERVAL"))

        # 构建 Redis URL
        self.REDIS_URL = _build_redis_url(
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            db=self.REDIS_DB,
            use_ssl=self.REDIS_USE_SSL,
            username=self.REDIS_USERNAME,
            password=self.REDIS_PASSWORD,
        )

        # Celery配置
        self.CELERY = {
            "broker_url": _build_redis_url(
                host=self.REDIS_HOST,
                port=self.REDIS_PORT,
                db=int(_get_env("CELERY_BROKER_DB")),
                use_ssl=self.REDIS_USE_SSL,
                username=self.REDIS_USERNAME,
                password=self.REDIS_PASSWORD,
            ),
            "result_backend": _build_redis_url(
                host=self.REDIS_HOST,
                port=self.REDIS_PORT,
                db=int(_get_env("CELERY_RESULT_BACKEND_DB")),
                use_ssl=self.REDIS_USE_SSL,
                username=self.REDIS_USERNAME,
                password=self.REDIS_PASSWORD,
            ),
            "task_ignore_result": _get_bool_env("CELERY_TASK_IGNORE_RESULT"),
            "result_expires": int(_get_env("CELERY_RESULT_EXPIRES")),
            "broker_connection_retry_on_startup": _get_bool_env("CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP"),
            "task_default_queue": "celery",
            "task_queues": (
                Queue("celery"),
                Queue("mail"),
                Queue("consolidation"),
            ),
            "task_routes": {
                "internal.task.email_task.send_verification_email_task": {"queue": "mail"},
                "internal.task.consolidation_tasks.*": {"queue": "consolidation"},
            },
            "beat_schedule": {
                "daily-consolidation": {
                    "task": "internal.task.consolidation_tasks.run_daily_consolidation",
                    "schedule": crontab(hour=3, minute=0),
                },
                "weight-scan": {
                    "task": "internal.task.consolidation_tasks.run_weight_scan",
                    "schedule": crontab(hour="*/6", minute=30),
                },
                "recycle-bin-expiration": {
                    "task": "internal.task.recycle_bin_tasks.run_recycle_bin_expiration",
                    "schedule": crontab(minute=0),
                },
                "run-scheduled-tasks": {
                    "task": "internal.task.schedule_tasks.run_scheduled_tasks",
                    "schedule": crontab(minute="*"),
                },
            },
        }

        # 辅助Agent应用id标识
        self.ASSISTANT_AGENT_ID = _get_env("ASSISTANT_AGENT_ID")
        self.ASSISTANT_MCP_BINDINGS = _get_json_env("ASSISTANT_MCP_BINDINGS", [])
        self.SKILL_CATALOG_SYNC_ENABLED = os.getenv("SKILL_CATALOG_SYNC_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.IMAGE_REQUEST_POLICY = _get_env("IMAGE_REQUEST_POLICY")
        self.VISION_FALLBACK_PROVIDER = _get_env("VISION_FALLBACK_PROVIDER")
        self.VISION_FALLBACK_MODEL = _get_env("VISION_FALLBACK_MODEL")

        # 文件存储后端配置（local/cos/oss）
        # 详见 docs/prd/architecture-design.md 第 17 节「文件存储与对象存储架构」
        self.STORAGE_BACKEND = _get_env("STORAGE_BACKEND") or "local"

        # 本地文件存储配置（STORAGE_BACKEND=local 时生效）
        self.LOCAL_STORAGE_ROOT = _get_env("LOCAL_STORAGE_ROOT") or "storage/uploads"
        self.LOCAL_STORAGE_BASE_URL = _get_env("LOCAL_STORAGE_BASE_URL") or ""

        # 腾讯云 COS 配置（STORAGE_BACKEND=cos 时生效）
        self.COS_SECRET_ID = _get_env("COS_SECRET_ID")
        self.COS_SECRET_KEY = _get_env("COS_SECRET_KEY")
        self.COS_BUCKET = _get_env("COS_BUCKET")
        self.COS_REGION = _get_env("COS_REGION")
        self.COS_DOMAIN = _get_env("COS_DOMAIN")

        # 阿里云 OSS 配置（STORAGE_BACKEND=oss 时生效）
        self.OSS_ACCESS_KEY_ID = _get_env("OSS_ACCESS_KEY_ID")
        self.OSS_ACCESS_KEY_SECRET = _get_env("OSS_ACCESS_KEY_SECRET")
        self.OSS_ENDPOINT = _get_env("OSS_ENDPOINT")
        self.OSS_BUCKET = _get_env("OSS_BUCKET")
        self.OSS_DOMAIN = _get_env("OSS_DOMAIN")

        # SMTP 邮件服务配置
        self.MAIL_SERVER = _get_env("MAIL_SERVER")
        self.MAIL_PORT = int(_get_env("MAIL_PORT")) if _get_env("MAIL_PORT") else 587
        self.MAIL_USE_TLS = _get_bool_env("MAIL_USE_TLS")
        self.MAIL_USE_SSL = _get_bool_env("MAIL_USE_SSL")
        self.MAIL_USERNAME = _get_env("MAIL_USERNAME")
        self.MAIL_PASSWORD = _get_env("MAIL_PASSWORD")
        self.MAIL_DEFAULT_SENDER = _get_env("MAIL_DEFAULT_SENDER")
        self.MAIL_TIMEOUT = int(_get_env("MAIL_TIMEOUT"))
