import asyncio
import logging
import types
from contextlib import nullcontext
from pathlib import Path

import pytest

from internal.exception import NotFoundException
from internal.server.http import Http
from pkg.response import HttpCode


class _FakeConf:
    CELERY = {"broker_url": "redis://example"}
    CORS_ALLOW_ORIGINS = ["https://ui.example.com"]
    CORS_SUPPORTS_CREDENTIALS = True


class _FakeDB:
    def __init__(self):
        self.init_calls = []

    def init_app(self, app):
        self.init_calls.append(app)


class _FakeMigrate:
    def __init__(self):
        self.init_calls = []

    def init_app(self, app, db, directory):
        self.init_calls.append((app, db, directory))


class _FakeMail:
    def __init__(self):
        self.init_calls = []

    def init_app(self, app):
        self.init_calls.append(app)


def _new_http_app(monkeypatch):
    ext_calls = []

    monkeypatch.setattr(
        "internal.server.http.logging_extension.init_app",
        lambda app: ext_calls.append(("logging", app)),
    )
    monkeypatch.setattr(
        "internal.server.http.redis_extension.init_app",
        lambda app: ext_calls.append(("redis", app)),
    )

    db = _FakeDB()
    migrate = _FakeMigrate()
    mail = _FakeMail()
    conf = _FakeConf()

    app = Http(
        "test-http",
        conf=conf,
        db=db,
        migrate=migrate,
        mail=mail,
    )
    return app, db, migrate, mail, ext_calls, conf


def test_http_init_should_wire_extensions(monkeypatch):
    app, db, migrate, mail, ext_calls, conf = _new_http_app(monkeypatch)

    assert app.config["CELERY"] == {"broker_url": "redis://example"}
    assert db.init_calls == [conf]
    assert migrate.init_calls == []  # flask_migrate 已解耦，容器不再挂载
    assert mail.init_calls == [conf]
    assert [name for name, _ in ext_calls] == ["logging", "redis"]


def test_http_error_handler_should_return_custom_exception_payload(monkeypatch):
    app, *_ = _new_http_app(monkeypatch)

    with app.app_context():
        response, status = app._register_error_handler(NotFoundException("missing", {"detail": "x"}))

    assert status == 200
    payload = asyncio.run(response.get_json())
    assert payload["code"] == HttpCode.NOT_FOUND.value
    assert payload["message"] == "missing"
    assert payload["data"] == {"detail": "x"}


def test_http_error_handler_should_reraise_non_custom_error_when_debug(monkeypatch):
    app, *_ = _new_http_app(monkeypatch)
    app.debug = True
    monkeypatch.delenv("APP_ENV", raising=False)

    with app.app_context():
        with pytest.raises(RuntimeError, match="boom"):
            app._register_error_handler(RuntimeError("boom"))


def test_http_error_handler_should_not_rely_on_app_env(monkeypatch):
    """容器以 debug 开关为准，APP_ENV 不再影响异常处理。"""
    app, *_ = _new_http_app(monkeypatch)
    app.debug = False
    monkeypatch.setenv("APP_ENV", "development")

    with app.app_context():
        response, status = app._register_error_handler(RuntimeError("boom"))

    assert status == 200
    payload = asyncio.run(response.get_json())
    assert payload["code"] == HttpCode.FAIL.value


def test_http_error_handler_should_return_fail_payload_in_production(monkeypatch):
    app, *_ = _new_http_app(monkeypatch)
    app.debug = False
    monkeypatch.setenv("APP_ENV", "production")

    with app.app_context():
        response, status = app._register_error_handler(RuntimeError("boom"))

    assert status == 200
    payload = asyncio.run(response.get_json())
    assert payload["code"] == HttpCode.FAIL.value
    assert payload["message"] == "服务器内部错误"
    assert payload["data"] == {}


def test_app_module_main_should_bootstrap_container_and_celery(monkeypatch):
    run_calls = []

    class _FakeHttp:
        def __init__(self, *_args, **_kwargs):
            self.extensions = {"celery": "fake-celery-app"}
            self.config = {"ASSISTANT_MCP_BINDINGS": []}

        def app_context(self):
            return nullcontext()

        def run(self, **kwargs):
            run_calls.append(kwargs)

    class _FakeSQLAlchemy:
        pass

    class _FakeMigrate:
        pass

    class _FakeMail:
        pass

    class _FakeRouter:
        pass

    class _FakeInjector:
        def __init__(self, mapping):
            self.mapping = mapping

        def get(self, cls):
            return self.mapping[cls]

    fake_dotenv = types.ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda: None

    fake_flask_migrate = types.ModuleType("flask_migrate")
    fake_flask_migrate.Migrate = _FakeMigrate

    fake_config = types.ModuleType("config")
    fake_config.Config = type("Config", (), {})

    fake_internal_router = types.ModuleType("internal.router")
    fake_internal_router.Router = _FakeRouter

    fake_internal_server = types.ModuleType("internal.server")
    fake_internal_server.Http = _FakeHttp

    fake_pkg_sqlalchemy = types.ModuleType("pkg.sqlalchemy")
    fake_pkg_sqlalchemy.SQLAlchemy = _FakeSQLAlchemy

    fake_flask_mail = types.ModuleType("flask_mail")
    fake_flask_mail.Mail = _FakeMail

    fake_app_http_module = types.ModuleType("app.http.module")
    fake_app_http_module.injector = _FakeInjector(
        {
            _FakeSQLAlchemy: object(),
            _FakeMigrate: object(),
            _FakeMail: object(),
            _FakeRouter: object(),
        }
    )

    # 阶段 C：app.http.celery_app 是独立 Celery 实例（解耦于容器）
    fake_celery_app = types.ModuleType("app.http.celery_app")
    fake_celery_app.celery_app = types.SimpleNamespace(main="llmops")

    monkeypatch.setitem(__import__("sys").modules, "dotenv", fake_dotenv)
    monkeypatch.setitem(__import__("sys").modules, "flask_migrate", fake_flask_migrate)
    monkeypatch.setitem(__import__("sys").modules, "config", fake_config)
    monkeypatch.setitem(__import__("sys").modules, "internal.router", fake_internal_router)
    monkeypatch.setitem(__import__("sys").modules, "internal.server", fake_internal_server)
    monkeypatch.setitem(__import__("sys").modules, "pkg.sqlalchemy", fake_pkg_sqlalchemy)
    monkeypatch.setitem(__import__("sys").modules, "flask_mail", fake_flask_mail)
    monkeypatch.setitem(__import__("sys").modules, "app.http.module", fake_app_http_module)
    monkeypatch.setitem(__import__("sys").modules, "app.http.celery_app", fake_celery_app)
    # 避免模块级 init_runtime 污染全局容器
    monkeypatch.setattr("internal.context.init_runtime", lambda _app: None)

    app_file = Path(__file__).resolve().parents[3] / "app" / "http" / "app.py"
    globals_dict = {
        "__name__": "__main__",
        "__package__": "app.http",
        "__file__": str(app_file),
    }

    # 通过 `__main__` 方式执行模块，精确覆盖 app/http/app.py 的入口分支。
    exec(compile(app_file.read_text(encoding="utf-8"), str(app_file), "exec"), globals_dict)

    assert globals_dict["celery"].main == "llmops"
    assert isinstance(globals_dict["app"], _FakeHttp)
    # 新入口契约：HTTP 由 uvicorn 承载，__main__ 不再直接 run 开发服务器
    assert run_calls == []
