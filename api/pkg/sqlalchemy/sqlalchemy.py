"""纯 SQLAlchemy 数据库底座（替代 flask_sqlalchemy）。

- ``Base``：SQLAlchemy 2.0 DeclarativeBase，model 声明基类（替代 db.Model）
- ``SQLAlchemy``：双模式数据库访问层，API 兼容 flask_sqlalchemy 常用子集：
    - ``db.Model``（= Base）／``db.Column``／``db.Integer`` 等（re-export sqlalchemy 名字）
    - ``db.session``：智能代理 —— async 上下文返回 AsyncSession（async_scoped_session），
      同步上下文（线程/Celery 任务）返回同步 scoped_session
    - ``db.auto_commit()``：async contextmanager（async 上下文）/ contextmanager（同步上下文）
    - ``db.sync_engine`` / ``db.sync_session_factory``：同步引擎（psycopg2）
    - ``db.async_session``：async_scoped_session（强制 async 路径）
"""

import asyncio
import logging
from contextlib import contextmanager

import sqlalchemy as _sa
import sqlalchemy.orm as _sa_orm
from sqlalchemy import *  # noqa: F401,F403  (re-export 兼容 db.Column/db.String 等)
from sqlalchemy.orm import *  # noqa: F401,F403  (re-export 兼容 db.relationship/db.sessionmaker)
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类（替代 flask_sqlalchemy 的 db.Model）。"""


def _in_async_context() -> bool:
    """检测当前是否处于运行中的事件循环（async 上下文）。"""
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


class SQLAlchemy:
    """双模式 SQLAlchemy 数据库访问层（API 兼容 flask_sqlalchemy 常用子集）。"""

    Model = Base

    def __init__(self, app=None):
        self._uri = ""
        self._engine_options: dict = {}
        self._engine: AsyncEngine | None = None
        self._async_factory: async_sessionmaker[AsyncSession] | None = None
        self._async_scoped: async_scoped_session | None = None
        self._sync_engine: Engine | None = None
        self._sync_factory: sessionmaker | None = None
        self._sync_scoped: scoped_session | None = None
        if app is not None:
            self.init_app(app)

    def __getattr__(self, name):
        """转发 sqlalchemy 名字，兼容 db.Column / db.String / db.relationship 等用法。"""
        try:
            return getattr(_sa, name)
        except AttributeError:
            return getattr(_sa_orm, name)

    def init_app(self, config) -> None:
        """从配置源读取连接串与引擎选项（惰性创建引擎）。

        兼容三类配置源：
        - dict 式：``{"SQLALCHEMY_DATABASE_URI": ...}``
        - Flask/Quart app：``config.config``（dict）
        - 属性对象式（Config 实例 / 容器 Http）：``config.SQLALCHEMY_DATABASE_URI``
        """
        if isinstance(config, dict):
            cfg = config
        elif hasattr(config, "config") and isinstance(config.config, dict):
            cfg = config.config
        else:
            cfg = None
            self._uri = config.SQLALCHEMY_DATABASE_URI or ""
            self._engine_options = dict(config.SQLALCHEMY_ENGINE_OPTIONS or {})
            if not self._engine_options.get("connect_args") and getattr(
                config, "SQLALCHEMY_CONNECT_ARGS", None
            ):
                self._engine_options["connect_args"] = config.SQLALCHEMY_CONNECT_ARGS
        if cfg is not None:
            get = cfg.get
            self._uri = get("SQLALCHEMY_DATABASE_URI") or ""
            self._engine_options = dict(get("SQLALCHEMY_ENGINE_OPTIONS") or {})
            connect_args = get("SQLALCHEMY_CONNECT_ARGS")
            if not self._engine_options.get("connect_args") and connect_args:
                self._engine_options["connect_args"] = dict(connect_args)

    @property
    def enabled(self) -> bool:
        return bool(self._uri)

    @property
    def engine(self) -> AsyncEngine:
        self._ensure_async()
        return self._engine

    def _ensure_async(self) -> None:
        if self._engine is not None:
            return
        if not self._uri:
            raise RuntimeError("SQLALCHEMY_DATABASE_URI 未配置，数据库引擎不可用")

        from sqlalchemy.engine.url import make_url

        # 1) 解析 URI：asyncpg 不支持 psycopg2 特有参数（client_encoding 等），
        #    从 query 中剥离并迁移为 server_settings 风格的连接参数。
        url = make_url(self._uri)
        query = dict(url.query)
        server_settings = {}
        encoding = query.pop("client_encoding", None)
        if encoding:
            server_settings["client_encoding"] = encoding
        for key in list(query.keys()):
            if key.startswith("_") or key in {
                "options",
                "connect_timeout",
                "application_name",
            }:
                query.pop(key, None)

        async_url = url.set(drivername="postgresql+asyncpg", query=query)

        engine_options = dict(self._engine_options)
        connect_args = dict(engine_options.get("connect_args") or {})
        # 2) connect_args 内的 client_encoding / options / connect_timeout
        #    迁移为 asyncpg 支持的形式（server_settings / timeout）
        if "client_encoding" in connect_args:
            encoding = connect_args.pop("client_encoding")
            server_settings.setdefault("client_encoding", encoding)
        if "connect_timeout" in connect_args:
            connect_args.setdefault("timeout", connect_args.pop("connect_timeout"))
        options = connect_args.pop("options", None)
        if options:
            for part in str(options).split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    server_settings.setdefault(k.strip(), v.strip())
        if server_settings:
            merged = dict(connect_args.get("server_settings") or {})
            merged.update(server_settings)
            connect_args["server_settings"] = merged
        if connect_args:
            engine_options["connect_args"] = connect_args

        self._engine = create_async_engine(async_url, **engine_options)
        self._async_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._async_scoped = async_scoped_session(
            self._async_factory, scopefunc=asyncio.current_task
        )
        logger.info("async database engine 初始化完成")

    def _ensure_sync(self) -> None:
        if self._sync_engine is not None:
            return
        if not self._uri:
            raise RuntimeError("SQLALCHEMY_DATABASE_URI 未配置，同步引擎不可用")
        from sqlalchemy import create_engine

        self._sync_engine = create_engine(self._uri, **self._engine_options)
        self._sync_factory = sessionmaker(bind=self._sync_engine, expire_on_commit=False)
        self._sync_scoped = scoped_session(self._sync_factory)
        logger.info("sync database engine 初始化完成")

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        self._ensure_async()
        return self._async_factory

    @property
    def session(self):
        """兼容旧 Flask-SQLAlchemy 的同步 scoped session。

        业务 service 大量使用 ``db.session.query(...)``，而 async_scoped_session
        不提供 query()；统一返回同步会话，异步路径显式走 session_factory/async_session。
        """
        self._ensure_sync()
        return self._sync_scoped

    @property
    def async_session(self) -> async_scoped_session:
        """强制 async 路径的 scoped session（async 上下文内使用）。"""
        self._ensure_async()
        return self._async_scoped

    @property
    def sync_engine(self) -> Engine:
        """同步引擎（psycopg2，供 Celery 任务与迁移脚本使用，无需事件循环）。"""
        self._ensure_sync()
        return self._sync_engine

    @property
    def sync_session_factory(self) -> sessionmaker:
        self._ensure_sync()
        return self._sync_factory

    @property
    def sync_session(self) -> scoped_session:
        """强制同步路径的 scoped session（线程/Celery 任务内使用）。"""
        self._ensure_sync()
        return self._sync_scoped

    def auto_commit(self):
        """双协议自动提交上下文（兼容同步/异步两种用法）。

        - 未迁移的同步 service（在 to_thread 线程中）：``with db.auto_commit():``
        - 已迁移的 async service：``async with db.auto_commit():``

        内部复用 ``db.session``（同步→scoped_session / async→async_scoped_session），
        与 ``db.session.add(...)`` 使用同一 session 实例，语义与旧 flask_sqlalchemy 一致。
        """
        return _DualAutoCommit(self)

    @contextmanager
    def sync_auto_commit(self):
        """同步版自动提交上下文（线程/Celery 任务内使用）。"""
        session = self.sync_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._async_factory = None
            self._async_scoped = None
        if self._sync_engine is not None:
            self._sync_engine.dispose()
            self._sync_engine = None
            self._sync_factory = None
            self._sync_scoped = None


class _DualAutoCommit:
    """同步/异步双协议自动提交上下文。

    - ``__enter__/__exit__``：同步协议（scoped_session）
    - ``__aenter__/__aexit__``：异步协议（async_scoped_session）
    """

    def __init__(self, db: SQLAlchemy):
        self._db = db
        self._scoped = None

    # ---- 同步协议 ----
    def __enter__(self):
        self._scoped = self._db.sync_session
        return self._scoped

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                self._scoped.rollback()
            else:
                self._scoped.commit()
        finally:
            self._scoped.remove()

    # ---- 异步协议 ----
    async def __aenter__(self):
        self._scoped = self._db.async_session
        return self._scoped

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                await self._scoped.rollback()
            else:
                await self._scoped.commit()
        finally:
            await self._scoped.remove()
