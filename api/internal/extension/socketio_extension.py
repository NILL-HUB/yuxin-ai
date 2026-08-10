"""Socket.IO 扩展初始化（ASGI 模式，挂载到 Quart/uvicorn）。

架构（阶段 B：Flask-SocketIO → python-socketio AsyncServer）：

- uvicorn 进程（app.http.asgi_app:app）：
    ``socketio.AsyncServer(async_mode="asgi", message_queue=REDIS_URL)``
    订阅 Redis 广播频道，负责把事件转发给浏览器客户端（room 映射在服务端维护）。
- 任意进程（Celery worker / 同步 service）：
    ``RedisManager(REDIS_URL).emit(...)`` 直接 publish 到 Redis，
    AsyncServer 收到广播后按 room 转发给已连接的客户端。

这样 emit 调用方（同步任务/服务）无需改造，WebSocket 与 HTTP 同驻 uvicorn 事件循环。
"""
import logging
from typing import Any, Mapping, Optional

from socketio import RedisManager


_socketio: Any = None          # AsyncServer（uvicorn 进程内）
_socketio_app: Any = None      # ASGIApp 组合对象（uvicorn 入口）
_redis_manager: Optional[RedisManager] = None


def resolve_cors_settings(config: Mapping[str, Any]) -> tuple[list[str], bool]:
    """统一计算 HTTP / Socket.IO 使用的 CORS 配置。"""
    cors_allow_origins = list(config.get("CORS_ALLOW_ORIGINS") or [])
    cors_supports_credentials = bool(config.get("CORS_SUPPORTS_CREDENTIALS", True))

    if cors_supports_credentials and cors_allow_origins == ["*"]:
        logging.warning("CORS_ALLOW_ORIGINS='*' 与 supports_credentials=True 冲突，已拒绝使用通配符")
        cors_allow_origins = []

    if not cors_allow_origins:
        cors_allow_origins = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    return cors_allow_origins, cors_supports_credentials


def get_redis_manager() -> RedisManager:
    """获取跨进程 Redis 广播管理器（任意进程可用，emit 为同步调用）。"""
    global _redis_manager
    if _redis_manager is None:
        from config import Config

        config = Config()
        redis_url = getattr(config, "REDIS_URL", None)
        if not redis_url:
            raise RuntimeError("REDIS_URL 未配置，Socket.IO 跨进程广播不可用")
        _redis_manager = RedisManager(redis_url)
        logging.info("[SocketIO] RedisManager 已初始化（跨进程广播通道）")
    return _redis_manager


def get_socketio() -> Any:
    """获取 AsyncServer 实例（仅 uvicorn 进程内有效）。"""
    return _socketio


def init_socketio_asgi(quart_app: Any, flask_config: Mapping[str, Any]) -> Any:
    """在 uvicorn 进程中初始化 AsyncServer 并挂载到 Quart，返回组合 ASGIApp。

    - ``/socket.io/*`` 路径由 Socket.IO 处理
    - 其余 HTTP 路径透传给 ``quart_app``
    """
    global _socketio, _socketio_app
    if _socketio_app is not None:
        return _socketio_app

    from socketio import AsyncServer, ASGIApp
    from internal.extension.websocket_handlers import register_socketio_handlers

    cors_origins, cors_credentials = resolve_cors_settings(flask_config)
    redis_url = flask_config.get("REDIS_URL")

    _socketio = AsyncServer(
        async_mode="asgi",
        cors_allowed_origins=cors_origins,
        cors_credentials=cors_credentials,
        logger=False,
        engineio_logger=False,
        message_queue=redis_url or None,
    )

    register_socketio_handlers(_socketio)

    _socketio_app = ASGIApp(_socketio, other_asgi_app=quart_app)
    logging.info("[SocketIO] AsyncServer 已挂载到 Quart（ASGI 模式）")
    return _socketio_app
