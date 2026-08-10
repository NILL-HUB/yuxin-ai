import os
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.orm import sessionmaker

# Python 3.11 兼容：项目使用 from datetime import UTC（3.11+ 语法），
# 本地测试环境若为 3.10 则在导入项目模块前注入 UTC 别名。
import datetime as _dt
if not hasattr(_dt, "UTC"):
    _dt.UTC = _dt.timezone.utc

# 在导入应用前关闭外部 tracing，避免初始化阶段产生联网副作用。
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGCHAIN_API_KEY", None)
os.environ.pop("LANGSMITH_API_KEY", None)

# 测试默认连接本机 Docker 容器内的 PostgreSQL（docker-compose 将 5432 映射到 127.0.0.1），
# 与生产部署（docker）保持一致，真实模拟生产环境。可用环境变量覆盖（如 CI 使用独立实例）。
from pkg.env_loader import load_project_env  # noqa: E402

load_project_env()
if not os.getenv("POSTGRES_HOST"):
    os.environ["POSTGRES_HOST"] = "127.0.0.1"
if os.getenv("POSTGRES_HOST"):
    os.environ["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@"
        f"{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB')}?client_encoding=utf8"
    )


@pytest.fixture(autouse=True)
def _disable_external_tracing(monkeypatch):
    """关闭外部 tracing，上报链路会干扰离线测试且没有业务价值。"""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    yield


@pytest.fixture(autouse=True)
def _reset_socketio_state():
    """每个测试都从干净的 Socket.IO 全局状态开始，避免模块级单例串扰。"""
    from internal.extension import socketio_extension

    socketio_extension.socketio = None
    yield
    socketio_extension.socketio = None


@pytest.fixture
def app():
    """返回 Flask 应用，并开启测试模式。"""
    from app.http.app import app as _app

    _app.config["TESTING"] = True
    # 测试阶段关闭鉴权，聚焦参数校验与 handler/service 逻辑。
    _app.config["LOGIN_DISABLED"] = True
    _app.config["WTF_CSRF_ENABLED"] = False
    return _app


_TEST_FERNET = Fernet(Fernet.generate_key())

_MODEL_POOL_CONFIG_DDL = """
CREATE TABLE model_pool_config (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    provider VARCHAR(128) NOT NULL,
    model_name VARCHAR(255) NOT NULL,
    display_name VARCHAR(255) NOT NULL DEFAULT '',
    description VARCHAR(512) NOT NULL DEFAULT '',
    tier VARCHAR(64) NOT NULL DEFAULT 'standard',
    capabilities TEXT NOT NULL DEFAULT '[]',
    price_per_1k_tokens NUMERIC NOT NULL DEFAULT 0,
    max_tokens INTEGER NOT NULL DEFAULT 0,
    max_input_tokens INTEGER NOT NULL DEFAULT 0,
    max_output_tokens INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(64) NOT NULL DEFAULT 'active',
    model_type VARCHAR(32) NOT NULL DEFAULT 'chat',
    compatible_api VARCHAR(32) NOT NULL DEFAULT 'openai',
    fallback_model_id VARCHAR(36),
    priority INTEGER NOT NULL DEFAULT 0,
    embedding_dimension INTEGER,
    updated_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL
)
"""

_MODEL_KEY_CONFIG_DDL = """
CREATE TABLE model_key_config (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    provider VARCHAR(128) NOT NULL,
    key_alias VARCHAR(255) NOT NULL,
    key_value_encrypted TEXT NOT NULL DEFAULT '',
    tenant_quota NUMERIC NOT NULL DEFAULT 0,
    status VARCHAR(64) NOT NULL DEFAULT 'active',
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_used_at DATETIME,
    effective_at DATETIME,
    expires_at DATETIME,
    used_credits NUMERIC NOT NULL DEFAULT 0,
    model_id VARCHAR(36),
    updated_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL
)
"""

_MODEL_PROVIDER_CONFIG_DDL = """
CREATE TABLE model_provider_config (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    label VARCHAR(255) NOT NULL DEFAULT '',
    description TEXT,
    icon VARCHAR(512),
    background VARCHAR(32) NOT NULL DEFAULT '#FFFFFF',
    default_base_url VARCHAR(512) NOT NULL,
    supported_model_types TEXT NOT NULL DEFAULT '["chat"]',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    updated_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL
)
"""

_MODEL_TIER_POLICY_DDL = """
CREATE TABLE model_tier_policy (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    tier_code VARCHAR(64) NOT NULL,
    tier_name VARCHAR(128) NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    allowed_models TEXT NOT NULL DEFAULT '[]',
    default_model VARCHAR(255) NOT NULL DEFAULT '',
    routing_rules TEXT NOT NULL DEFAULT '{}',
    updated_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL
)
"""


@pytest.fixture
def model_pool_db(monkeypatch):
    """真实内存 SQLite 会话 + 模型池表，并在运行期间注入稳定的 Fernet 密钥。"""
    from internal.service import admin_model_pool_service as svc

    monkeypatch.setattr(svc, "_FERNET", _TEST_FERNET)

    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql(_MODEL_POOL_CONFIG_DDL)
        conn.exec_driver_sql(_MODEL_KEY_CONFIG_DDL)
        conn.exec_driver_sql(_MODEL_PROVIDER_CONFIG_DDL)
        conn.exec_driver_sql(_MODEL_TIER_POLICY_DDL)
        conn.commit()

    session_factory = sessionmaker(bind=engine, autoflush=False)
    session = session_factory()
    db_shim = SimpleNamespace(session=session, engine=engine)
    try:
        yield db_shim
    finally:
        session.close()
        engine.dispose()
