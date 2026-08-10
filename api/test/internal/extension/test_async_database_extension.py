"""异步数据库会话基建单元测试（pkg.sqlalchemy.SQLAlchemy 双模式底座）。

覆盖原 async_database_extension.AsyncDatabase 的验证目标：
- enabled / 引擎懒加载
- postgresql:// → postgresql+asyncpg:// 驱动切换
- engine 复用（session_factory 复用同一引擎）
- dispose 后惰性重建
"""

import asyncio

from pkg.sqlalchemy import SQLAlchemy


class _FakeFlaskApp:
    def __init__(self, uri, engine_options=None):
        self.config = {
            "SQLALCHEMY_DATABASE_URI": uri,
            "SQLALCHEMY_ENGINE_OPTIONS": engine_options or {},
        }


def test_enabled_false_without_uri():
    db = SQLAlchemy(_FakeFlaskApp(""))

    assert db.enabled is False
    assert db._engine is None
    assert db._sync_engine is None


def test_engine_switches_to_asyncpg_driver(monkeypatch):
    created = {}

    def _fake_create_async_engine(url, **kwargs):
        created["url"] = str(url)
        created["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(
        "pkg.sqlalchemy.sqlalchemy.create_async_engine",
        _fake_create_async_engine,
    )

    db = SQLAlchemy(_FakeFlaskApp(
        "postgresql://user:pass@localhost:5432/db?client_encoding=utf8",
        {"pool_size": 30, "pool_recycle": 3600},
    ))

    engine = db.engine

    assert engine is not None
    assert created["url"].startswith("postgresql+asyncpg://")
    assert created["kwargs"]["pool_size"] == 30
    assert db.enabled is True


def test_session_factory_reuses_engine(monkeypatch):
    calls = {"count": 0}

    def _fake_create_async_engine(url, **kwargs):
        calls["count"] += 1
        return object()

    monkeypatch.setattr(
        "pkg.sqlalchemy.sqlalchemy.create_async_engine",
        _fake_create_async_engine,
    )

    db = SQLAlchemy(_FakeFlaskApp("postgresql://u:p@h/db"))

    factory1 = db.session_factory
    factory2 = db.session_factory
    db.engine

    assert factory1 is not None
    assert factory1 is factory2
    assert calls["count"] == 1


def test_dispose_resets_state(monkeypatch):
    disposed = {"engine": None}

    class _Engine:
        async def dispose(self):
            disposed["engine"] = self

    engine = _Engine()
    calls = {"count": 0}

    def _fake_create_async_engine(url, **kwargs):
        calls["count"] = calls.get("count", 0) + 1
        return engine

    monkeypatch.setattr(
        "pkg.sqlalchemy.sqlalchemy.create_async_engine",
        _fake_create_async_engine,
    )

    db = SQLAlchemy(_FakeFlaskApp("postgresql://u:p@h/db"))
    db.engine

    asyncio.run(db.dispose())

    assert disposed["engine"] is engine
    assert calls["count"] == 1
    assert db.engine is not None  # dispose 后惰性重建
    assert calls["count"] == 2
