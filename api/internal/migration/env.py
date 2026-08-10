"""Alembic 迁移环境（纯 Alembic，无 flask_migrate / current_app 依赖）。

- 连接串来自 ``config.Config.SQLALCHEMY_DATABASE_URI``（env 驱动）
- target_metadata 使用 ``pkg.sqlalchemy.Base.metadata``（model 层统一声明基类）
- 迁移脚本目录：internal/migration/versions
"""
import logging
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from pkg.env_loader import load_project_env

# 确保 .env 已加载（与 app.http.app 保持一致）
load_project_env()

from pkg.sqlalchemy import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")

# 导入所有 model，确保 Base.metadata 完整（autogenerate 依赖）
from internal.model import *  # noqa: E402,F401,F403


def _build_uri() -> str:
    """从环境变量 / 默认配置构建连接串。"""
    from config import Config

    conf = Config()
    uri = conf.SQLALCHEMY_DATABASE_URI
    if not uri:
        raise RuntimeError(
            "SQLALCHEMY_DATABASE_URI 未配置，无法执行数据库迁移。"
            "请检查 api/.env 或环境变量。"
        )
    return uri


def get_metadata():
    return Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = _build_uri().replace("%", "%%")
    context.configure(
        url=url,
        target_metadata=get_metadata(),
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """

    # this callback is used to prevent an auto-migration from being generated
    # when there are no changes to the schema
    # reference: http://alembic.zzzcomputing.com/en/latest/cookbook.html
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("No changes in schema detected.")

    connectable = create_engine(_build_uri())

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
