"""ASGI 全量 HTTP 入口（阶段 3 完成态）。

由 uvicorn 承载全部 HTTP 与 Socket.IO，用于承载高并发 Agent 流式对话
（方案 B：async 全链路，单事件循环内执行）。

架构要点：
- 复用 app.http.app 的 Http 容器作为依赖容器（config / extensions / injector）
- 核心消费链路：AppRuntimeService.stream_agent_events_async
  -> agent.astream（LangGraph async 图 + async LLM 节点），全程不占用子线程
- 同步 DB/模型解析调用通过 asyncio.to_thread 移入线程池，避免阻塞事件循环

端点：
- POST /api/async/chat/completion
    请求体 JSON:
      app_id: UUID                  应用 ID
      account_id: UUID              账户 ID（应用归属人）
      query: str                    用户提问
      image_urls: list[str]         图片 URL 列表（可选）
      history: list                 历史消息（可选）
      long_term_memory: str         长期记忆摘要（可选）
      conversation_id: str          会话 ID（可选）
      message_id: str               消息 ID（可选）
      enable_deep_thinking: bool    是否启用深度思考（可选）
    响应: text/event-stream（SSE 事件流）
"""

import logging
from dataclasses import asdict
from types import SimpleNamespace

from quart import Quart, Response, request

from app.http.app import app as flask_app
from internal.exception import CustomException
from internal.extension.socketio_extension import resolve_cors_settings

logger = logging.getLogger(__name__)

quart_app = Quart(__name__, static_folder=None)
quart_app.config.from_mapping(flask_app.config)

# 阶段 2.3：将 Quart 请求的同步字段注入请求作用域（internal.context.request / g /
# has_request_context）。Quart request 为 async 对象，同步 service / to_thread 线程中
# 无法直接访问，故在请求入口快照 headers/remote_addr/method/args 等字段。
# 注意：普通 threading.Thread 不继承 contextvars，后台任务天然不感知请求数据。
from internal.context import clear_request_scope, set_request_scope


@quart_app.before_request
async def _bind_request_scope():
    request_scope = SimpleNamespace(
        headers=dict(request.headers),
        remote_addr=request.remote_addr or "",
        method=request.method or "",
        args=dict(request.args),
        json=None,
        files={},
        form={},
        cookies=dict(request.cookies),
    )
    set_request_scope(request_scope)


@quart_app.teardown_request
async def _clear_request_scope(*_args):
    clear_request_scope()


@quart_app.errorhandler(CustomException)
async def _handle_custom_exception(error: CustomException) -> Response:
    response, _status = flask_app._register_error_handler(error)
    return response


@quart_app.after_request
async def _add_cors_headers(response: Response) -> Response:
    origins, supports_credentials = resolve_cors_settings(quart_app.config)
    origin = request.headers.get("Origin") or ""
    if origin in origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Credentials"] = (
        "true" if supports_credentials else "false"
    )
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Account-Id"
    )
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    )
    return response

# 阶段 3.3：初始化异步数据库会话基建（惰性创建引擎，供原生 async 端点使用）
# 说明：async_db（database_extension.db）已由 app.http.app 容器初始化（Http.__init__
# 调用 db.init_app(conf)）。此处不再重复 init，避免覆盖容器配置。

# 公共 helper 已迁移至 app.http.support。为避免 re-export 一次性绑定导致
# 测试 monkeypatch（monkeypatch.setattr(support, ...)）无法通过 asgi_app
# 模块属性（admin_routes_*/user_routes_9 的 ``a._ok(...)`` 等）生效，
# 此处以薄转发函数转发到 support：调用时实时解析 support 模块属性。
from app.http import support as _support


def _get_services():
    return _support._get_services()


def _load_runtime_context(app_id, account_id, image_urls):
    return _support._load_runtime_context(app_id, account_id, image_urls)


def _load_account(account_id):
    return _support._load_account(account_id)


def _get_conversation_service():
    return _support._get_conversation_service()


def _get_service(cls):
    return _support._get_service(cls)


def _json_resp(data=None, code="success", message="", status=200):
    return _support._json_resp(data, code=code, message=message, status=status)


def _ok(data=None):
    return _support._ok(data)


def _ok_msg(message):
    return _support._ok_msg(message)


def _err(code, message, status=400):
    return _support._err(code, message, status=status)


def _is_sync_iterator(obj):
    return _support._is_sync_iterator(obj)


def _sse_response(generator):
    return _support._sse_response(generator)


async def _resolve_account(account_id_override: str | None = None):
    return await _support._resolve_account(account_id_override)


async def _resolve_admin_permission(permission_code: str):
    return await _support._resolve_admin_permission(permission_code)


def _field(raw, default=None):
    return _support._field(raw, default)


def _int_arg(name, default):
    return _support._int_arg(name, default)


def _to_thread(fn, *args, **kwargs):
    return _support._to_thread(fn, *args, **kwargs)


def _resolve_webapp_actor():
    return _support._resolve_webapp_actor()


_service_cache = _support._service_cache


from app.http.admin_routes_1 import register_routes as _register_admin_routes_1
from app.http.admin_routes_2 import register_routes as _register_admin_routes_2
from app.http.admin_routes_3 import register_routes as _register_admin_routes_3
from app.http.admin_routes_4 import register_routes as _register_admin_routes_4
from app.http.admin_routes_5 import register_routes as _register_admin_routes_5
from app.http.admin_routes_6 import register_routes as _register_admin_routes_6
from app.http.admin_routes_7 import register_routes as _register_admin_routes_7
from app.http.admin_routes_8 import register_routes as _register_admin_routes_8
from app.http.user_routes_9 import register_routes as _register_user_routes_9

from app.http.account_auth_routes import register_routes as _register_account_auth_routes
from app.http.apps_routes import register_routes as _register_apps_routes
from app.http.chat_routes import register_routes as _register_chat_routes
from app.http.conversation_routes import register_routes as _register_conversation_routes
from app.http.home_misc_routes import register_routes as _register_home_misc_routes
from app.http.knowledge_mcp_routes import register_routes as _register_knowledge_mcp_routes
from app.http.schedule_assistant_routes import register_routes as _register_schedule_assistant_routes
from app.http.skills_tools_routes import register_routes as _register_skills_tools_routes
from app.http.workflow_routes import register_routes as _register_workflow_routes
from app.http.a2a_routes import register_routes as _register_a2a_routes
from app.http.im_voice_routes import register_routes as _register_im_voice_routes

_register_admin_routes_1(quart_app)
_register_admin_routes_2(quart_app)
_register_admin_routes_3(quart_app)
_register_admin_routes_4(quart_app)
_register_admin_routes_5(quart_app)
_register_admin_routes_6(quart_app)
_register_admin_routes_7(quart_app)
_register_admin_routes_8(quart_app)
_register_user_routes_9(quart_app)

_register_chat_routes(quart_app)
_register_conversation_routes(quart_app)
_register_account_auth_routes(quart_app)
_register_home_misc_routes(quart_app)
_register_apps_routes(quart_app)
_register_skills_tools_routes(quart_app)
_register_workflow_routes(quart_app)
_register_knowledge_mcp_routes(quart_app)
_register_schedule_assistant_routes(quart_app)
_register_a2a_routes(quart_app)
_register_im_voice_routes(quart_app)


# Socket.IO（ASGI 模式）：/socket.io/* 由 AsyncServer 处理，其余 HTTP 透传 quart_app。
# uvicorn 入口：app.http.asgi_app:app
from internal.extension.socketio_extension import init_socketio_asgi

app = init_socketio_asgi(quart_app, flask_app.config)
