"""全局运行时上下文（current_app / g / request / has_app_context）。

设计要点：
- service 层不再依赖任何 Web 框架的 app context / request context。
- ``current_app``：指向全局容器（Http 实例），提供 config / extensions / injector / logger。
- ``g``：contextvar 驱动的请求级存储（替代 flask.g），无请求上下文时写入 task 级兜底存储。
- ``request``：请求级快照代理（替代 flask.request），由 Quart 路由层注入同步字段。
- ``has_app_context()`` / ``has_request_context()``：由自身状态直接判定，
  测试通过 ``init_runtime`` / ``set_request_scope`` 注入。
- ``is_active_app(target)``：判断 target 是否为当前生效的应用对象，供工具闭包在调用时
  决定是否需要重新进入 app context。
"""
import contextvars
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 全局容器（Http 实例），应用启动时填充
_app_container: Any = None

# 请求级上下文（替代 flask.g / has_request_context）
_request_scope: contextvars.ContextVar = contextvars.ContextVar(
    "request_scope", default=None
)
_request_active: contextvars.ContextVar = contextvars.ContextVar(
    "request_active", default=False
)


class _GFallbackStorage(dict):
    """支持 getattr/setattr 语义的 g 兜底存储（替代 flask.g 在无 context 时的可写存储）。"""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


# 无请求上下文时 g 的兜底存储（contextvar，task 级隔离；惰性创建，避免并发共享同一实例）
_g_fallback: contextvars.ContextVar = contextvars.ContextVar(
    "g_fallback", default=None
)


def init_runtime(app_container: Any) -> None:
    """应用启动时注册全局容器。"""
    global _app_container
    _app_container = app_container


def set_request_scope(scope: Any) -> None:
    """进入 HTTP 请求时绑定请求级上下文（由 Quart 路由中间件调用）。"""
    _request_scope.set(scope)
    _request_active.set(True)


def clear_request_scope() -> None:
    """请求结束时清理请求级上下文。"""
    _request_scope.set(None)
    _request_active.set(False)


def is_active_app(target: Any) -> bool:
    """判断 target 是否为当前生效的应用对象。

    用于工具闭包在调用时决定是否需要重新进入 app context：
    - 容器场景（生产/Quart/测试助手）：``current_app`` 即全局容器，
      target 为容器时恒为 True，无需重入。
    """
    if target is None:
        return False
    return target is _app_container


class _GProxy:
    """替代 flask.g：有请求上下文时写入 scope，否则写入 task 级兜底存储。

    语义对齐 flask.g：
    - 请求内多次写入/读取共享同一对象
    - 无请求上下文（如测试、Celery 任务）时仍可写可读，不静默丢弃
    """

    def _resolve_storage(self):
        scope = _request_scope.get()
        if scope is not None:
            return scope
        storage = _g_fallback.get()
        if storage is None:
            storage = _GFallbackStorage()
            _g_fallback.set(storage)
        return storage

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve_storage(), name, None)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._resolve_storage(), name, value)

    def __contains__(self, name: str) -> bool:
        return hasattr(self._resolve_storage(), name)


class _CurrentAppProxy:
    """替代 flask.current_app：直接使用全局运行时容器。"""

    def _resolve(self) -> Any:
        return _app_container

    @property
    def config(self) -> dict:
        target = self._resolve()
        if target is None:
            return {}
        return getattr(target, "config", {})

    @property
    def extensions(self) -> dict:
        target = self._resolve()
        if target is None:
            return {}
        return getattr(target, "extensions", {})

    @property
    def injector(self) -> Any:
        target = self._resolve()
        if target is None:
            return None
        return getattr(target, "injector", None)

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger("app")

    @property
    def debug(self) -> bool:
        target = self._resolve()
        if target is None:
            return False
        return bool(getattr(target, "debug", False))

    @property
    def root_path(self) -> str:
        target = self._resolve()
        if target is None:
            return ""
        return getattr(target, "root_path", "")

    def app_context(self):
        """返回当前生效应用的 app context（容器为 no-op，Flask app 为真实上下文）。"""
        target = self._resolve()
        if target is not None and hasattr(target, "app_context"):
            return target.app_context()
        from contextlib import nullcontext

        return nullcontext()

    def _get_current_object(self) -> Any:
        return self._resolve()

    def __repr__(self) -> str:
        return "<RuntimeContainer>"


class _EmptyRequest:
    """无请求上下文时的安全空对象。"""

    headers: Any = {}
    remote_addr: str = ""
    method: str = ""
    args: Any = {}
    json: Any = None
    files: Any = {}
    form: Any = {}
    cookies: Any = {}

    def get_data(self, **kwargs) -> bytes:
        return b""

    def get_json(self, **kwargs) -> Any:
        return None


_EMPTY_REQUEST = _EmptyRequest()


class _RequestProxy:
    """替代 flask.request：优先请求级快照，回退 Flask request（测试桥接）。

    设计要点：
    - Quart 的 request 是 async 对象，无法在 to_thread 子线程 / 同步 service 中访问。
    - ASGI 入口（app.http.asgi_app）通过 ``set_request_scope`` 注入一个
      SimpleNamespace（含 headers / remote_addr / method / args 等同步字段）。
    - 均不可用时返回安全空值，不抛异常。
    """

    def _resolve(self):
        scope = _request_scope.get()
        if scope is not None:
            return scope
        return _EMPTY_REQUEST

    @property
    def headers(self) -> Any:
        return self._resolve().headers

    @property
    def remote_addr(self) -> Any:
        return self._resolve().remote_addr

    @property
    def method(self) -> str:
        return self._resolve().method

    @property
    def args(self) -> Any:
        return self._resolve().args

    @property
    def json(self) -> Any:
        return self._resolve().json

    @property
    def files(self) -> Any:
        return self._resolve().files

    @property
    def form(self) -> Any:
        return self._resolve().form

    @property
    def cookies(self) -> Any:
        return self._resolve().cookies

    def get_data(self, **kwargs) -> bytes:
        req = self._resolve()
        if req is _EMPTY_REQUEST:
            return b""
        return req.get_data(**kwargs)

    def get_json(self, **kwargs) -> Any:
        req = self._resolve()
        if req is _EMPTY_REQUEST:
            return None
        return req.get_json(**kwargs)


current_app = _CurrentAppProxy()
g = _GProxy()
request = _RequestProxy()


def has_app_context() -> bool:
    """替代 flask.has_app_context：全局容器存在即视为有上下文。"""
    return _app_container is not None


def has_request_context() -> bool:
    """替代 flask.has_request_context：由路由层设置请求活性。"""
    return bool(_request_active.get())


__all__ = [
    "current_app",
    "g",
    "request",
    "has_app_context",
    "has_request_context",
    "is_active_app",
    "init_runtime",
    "set_request_scope",
    "clear_request_scope",
]
