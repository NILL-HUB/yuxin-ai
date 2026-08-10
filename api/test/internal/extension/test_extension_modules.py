import logging
import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from internal.extension import logging_extension, redis_extension, socketio_extension


def test_celery_app_should_be_independent_from_flask_app():
    from app.http.celery_app import celery_app

    assert celery_app.main == "llmops"
    assert "broker_url" in celery_app.conf
    assert "result_backend" in celery_app.conf
    # 记忆系统定时任务已注册（阶段 C：beat 配置移入独立 Celery 应用）
    beat = celery_app.conf.beat_schedule
    assert "skill-stats-flush" in beat
    assert "run-scheduled-tasks" in beat
    # 定时任务路由（consolidation 队列）
    routes = celery_app.conf.task_routes
    assert "internal.task.recycle_bin_tasks.*" in routes


def test_app_context_task_should_call_run_directly_without_app_context(monkeypatch):
    """阶段 3.4：任务不再包裹 Flask app context，直接执行 run。"""
    from app.http.celery_app import AppContextTask

    task = AppContextTask()
    task.run = lambda: "done"

    assert task() == "done"


class _FakeLogger:
    def __init__(self):
        self.level = logging.WARNING
        self.levels = []
        self.handlers = []

    def setLevel(self, level):
        self.level = level
        self.levels.append(level)

    def addHandler(self, handler):
        self.handlers.append(handler)

    def removeHandler(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)


class _FakeHandler:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.level = None
        self.formatter = None

    def setLevel(self, level):
        self.level = level

    def setFormatter(self, formatter):
        self.formatter = formatter


@pytest.mark.parametrize(
    "debug, app_env, folder_exists, expected_level, expected_handlers, expect_makedirs",
    [
        (True, "production", False, logging.DEBUG, 2, True),
        (False, "development", True, logging.DEBUG, 2, False),
        (False, "production", True, logging.WARNING, 1, False),
    ],
)
def test_logging_extension_should_cover_debug_dev_and_prod_branches(
    monkeypatch,
    debug,
    app_env,
    folder_exists,
    expected_level,
    expected_handlers,
    expect_makedirs,
):
    import logging as _real_logging

    fake_logger = _FakeLogger()
    makedirs_calls = []

    # 仅替换 logging_extension 模块内的 logging 引用，避免污染标准库 logging
    # （防止与 pytest 的 logging 插件 / loggerDict 交互产生残留副作用）
    fake_logging_mod = SimpleNamespace(
        DEBUG=_real_logging.DEBUG,
        WARNING=_real_logging.WARNING,
        INFO=_real_logging.INFO,
        getLogger=lambda: fake_logger,
        StreamHandler=lambda: _FakeHandler(),
        Formatter=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(logging_extension, "logging", fake_logging_mod)
    monkeypatch.setattr(
        logging_extension,
        "ConcurrentTimedRotatingFileHandler",
        lambda *args, **kwargs: _FakeHandler(*args, **kwargs),
    )
    monkeypatch.setattr(logging_extension.os.path, "exists", lambda _path: folder_exists)
    monkeypatch.setattr(logging_extension.os, "makedirs", lambda path: makedirs_calls.append(path))
    monkeypatch.setattr(logging_extension.os, "getcwd", lambda: "/tmp/project")
    monkeypatch.setattr(
        logging_extension.os,
        "getenv",
        lambda key: app_env if key == "APP_ENV" else None,
    )

    app = SimpleNamespace(debug=debug)
    logging_extension.init_app(app)

    assert fake_logger.levels[-1] == expected_level
    assert len(fake_logger.handlers) == expected_handlers
    expected_log_dir = os.path.join("/tmp/project", "storage", "log")
    if expect_makedirs:
        assert makedirs_calls == [expected_log_dir]
    else:
        assert makedirs_calls == []


@pytest.mark.parametrize(
    "use_ssl, expected_class",
    [
        (False, redis_extension.Connection),
        (True, redis_extension.SSLConnection),
    ],
)
def test_redis_extension_should_select_connection_class_by_ssl_flag(
    monkeypatch, use_ssl, expected_class
):
    pool_calls = []
    fake_redis_client = SimpleNamespace(connection_pool=None)

    monkeypatch.setattr(
        redis_extension.redis,
        "ConnectionPool",
        lambda **kwargs: pool_calls.append(kwargs) or kwargs,
    )
    monkeypatch.setattr(redis_extension, "redis_client", fake_redis_client)

    app = SimpleNamespace(
        config={
            "REDIS_USE_SSL": use_ssl,
            "REDIS_HOST": "redis.local",
            "REDIS_PORT": 6380,
            "REDIS_USERNAME": "user",
            "REDIS_PASSWORD": "pwd",
            "REDIS_DB": 2,
        },
        extensions={},
    )

    redis_extension.init_app(app)

    assert pool_calls[0]["connection_class"] is expected_class
    assert fake_redis_client.connection_pool == pool_calls[0]
    assert app.extensions["redis"] is fake_redis_client


def test_socketio_extension_should_align_cors_settings_with_http_defaults(monkeypatch):
    import socketio as socketio_lib

    asgi_calls = []
    register_calls = []

    class _FakeAsyncServer:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            asgi_calls.append(kwargs)

        def on(self, event):
            def deco(handler):
                return handler

            return deco

    class _FakeASGIApp:
        def __init__(self, server, other_asgi_app=None, **kwargs):
            pass

    monkeypatch.setattr(socketio_lib, "AsyncServer", _FakeAsyncServer)
    monkeypatch.setattr(socketio_lib, "ASGIApp", _FakeASGIApp)
    monkeypatch.setattr(
        "internal.extension.websocket_handlers.register_socketio_handlers",
        lambda socketio: register_calls.append(socketio),
    )

    socketio_extension._socketio = None
    socketio_extension._socketio_app = None

    flask_config = {
        "CORS_ALLOW_ORIGINS": ["*"],
        "CORS_SUPPORTS_CREDENTIALS": True,
        "REDIS_URL": "redis://example",
    }

    app = socketio_extension.init_socketio_asgi(object(), flask_config)

    assert asgi_calls[0]["cors_allowed_origins"] == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert asgi_calls[0]["async_mode"] == "asgi"
    assert asgi_calls[0]["cors_credentials"] is True
    assert asgi_calls[0]["logger"] is False
    assert asgi_calls[0]["engineio_logger"] is False
    assert asgi_calls[0]["message_queue"] == "redis://example"
    assert len(register_calls) == 1
    assert app is not None


def test_socketio_extension_should_keep_default_socketio_path_for_edge_prefix_rewrite(monkeypatch):
    import socketio as socketio_lib

    asgi_calls = []

    class _FakeAsyncServer:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            asgi_calls.append(kwargs)

        def on(self, event):
            def deco(handler):
                return handler

            return deco

    class _FakeASGIApp:
        def __init__(self, server, other_asgi_app=None, **kwargs):
            pass

    monkeypatch.setattr(socketio_lib, "AsyncServer", _FakeAsyncServer)
    monkeypatch.setattr(socketio_lib, "ASGIApp", _FakeASGIApp)
    monkeypatch.setattr(
        "internal.extension.websocket_handlers.register_socketio_handlers",
        lambda _socketio: None,
    )

    socketio_extension._socketio = None
    socketio_extension._socketio_app = None

    flask_config = {
        "CORS_ALLOW_ORIGINS": ["http://localhost:5173"],
        "CORS_SUPPORTS_CREDENTIALS": True,
        "REDIS_URL": None,
    }

    socketio_extension.init_socketio_asgi(object(), flask_config)

    assert asgi_calls[0]["message_queue"] is None
    assert "path" not in asgi_calls[0]
