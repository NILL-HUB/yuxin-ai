# 应用默认配置项
DEFAULT_CONFIG = {
    # wft配置
    "WTF_CSRF_ENABLED": "True",
    # CORS 配置
    "CORS_ALLOW_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
    "CORS_SUPPORTS_CREDENTIALS": "True",
    # OAuth 回调来源白名单（逗号分隔）
    "OAUTH_ALLOWED_ORIGINS": "",
    # WebApp 访客 Cookie 配置
    "WEB_APP_VISITOR_COOKIE_SECURE": "False",
    "WEB_APP_VISITOR_COOKIE_SECRET": "",

    # SQLAlchemy数据库配置
    "SQLALCHEMY_DATABASE_URI": "",
    "SQLALCHEMY_POOL_SIZE": 30,
    "SQLALCHEMY_MAX_OVERFLOW": 20,
    "SQLALCHEMY_POOL_RECYCLE": 3600,
    "SQLALCHEMY_POOL_TIMEOUT": 10,
    "SQLALCHEMY_POOL_PRE_PING": "True",
    "SQLALCHEMY_CONNECT_TIMEOUT": 5,
    "SQLALCHEMY_STATEMENT_TIMEOUT_MS": 30000,
    "SQLALCHEMY_ECHO": "False",

    # Redis数据库配置
    "REDIS_HOST": "localhost",
    "REDIS_PORT": 6379,
    "REDIS_USERNAME": "",
    "REDIS_PASSWORD": "",
    "REDIS_DB": 0,
    "REDIS_USE_SSL": "False",
    "REDIS_SOCKET_CONNECT_TIMEOUT": 5,
    "REDIS_SOCKET_TIMEOUT": 5,
    "REDIS_HEALTH_CHECK_INTERVAL": 30,

    # Celery默认配置
    "CELERY_BROKER_DB": 1,
    "CELERY_RESULT_BACKEND_DB": 1,
    "CELERY_TASK_IGNORE_RESULT": "False",
    "CELERY_RESULT_EXPIRES": 3600,
    "CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP": "True",
    # Redis broker visibility timeout（秒）：acks_late 长任务需大于最长任务时长，
    # 否则正常执行超时未 ack 会被 broker 误重投；默认 24h
    "CELERY_BROKER_VISIBILITY_TIMEOUT": 86400,
    # worker 处理该任务数后重启子进程（进程级防泄漏保险丝，非并发限制）；默认 0 = 不限制
    "CELERY_WORKER_MAX_TASKS_PER_CHILD": 2000,
    # worker 预取倍数（1 = 每次只取一个任务，减少长事务堆积）；默认 4
    "CELERY_WORKER_PREFETCH_MULTIPLIER": 4,

    # 辅助Agent智能体应用id
    "ASSISTANT_AGENT_ID": "6774fcef-b594-8008-b30c-a05b8190afe6",
    # 首页助手可用的 MCP 绑定（JSON 字符串或列表，默认空）
    "ASSISTANT_MCP_BINDINGS": [],
    "SKILL_CATALOG_SYNC_ENABLED": False,
    # 多模态请求策略
    "IMAGE_REQUEST_POLICY": "strict",
    "VISION_FALLBACK_PROVIDER": "",
    "VISION_FALLBACK_MODEL": "",
}
