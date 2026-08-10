"""WebSocket 事件处理（ASGI 模式，python-socketio AsyncServer）"""
import logging
from typing import Any
from uuid import UUID

from internal.exception import UnauthorizedException
from internal.lib.websocket_manager import ws_manager
from internal.service import AccountService, JwtService


def _resolve_socket_account_id(auth: dict[str, Any] | None = None) -> UUID:
    """根据握手认证信息解析并校验当前 Socket 对应的账号。"""
    payload = auth or {}
    token = str(payload.get("token", "")).strip()
    if not token:
        raise UnauthorizedException("Socket 连接缺少访问令牌")

    from app.http.module import injector

    jwt_service = injector.get(JwtService)
    account_service = injector.get(AccountService)

    token_payload = jwt_service.parse_token(token)
    account_service.validate_access_session(token_payload)

    account_id_raw = str(token_payload.get("sub", "")).strip()
    if not account_id_raw:
        raise UnauthorizedException("访问令牌缺少账号标识")

    try:
        account_id = UUID(account_id_raw)
    except ValueError as exc:
        raise UnauthorizedException("访问令牌中的账号标识非法") from exc

    account = account_service.get_account(account_id)
    if not account:
        raise UnauthorizedException("账号不存在或已失效")

    return account.id


def _require_authenticated_connection(sid: str):
    """确保当前 Socket 已通过握手鉴权并绑定账号。"""
    connection = ws_manager.get_connection(sid)
    if not connection:
        raise UnauthorizedException("Socket 连接未完成认证")

    return connection


async def handle_connect(sid: str, environ: dict[str, Any] | None = None, auth: dict[str, Any] | None = None) -> bool | None:
    """建立连接时校验握手 token，并绑定 Socket -> 账号映射。"""
    try:
        account_id = _resolve_socket_account_id(auth)
    except UnauthorizedException as exc:
        logging.warning("[WS] rejected sid=%s: %s", sid, exc)
        return False

    ws_manager.add_connection(sid, account_id)
    return None


async def handle_disconnect(sid: str) -> None:
    """断开连接时清理连接记录。"""
    ws_manager.remove_connection(sid)


async def handle_subscribe_message(sid: str, data: dict[str, Any] | None = None) -> None:
    """订阅消息流更新。"""
    try:
        _require_authenticated_connection(sid)
    except UnauthorizedException as exc:
        logging.warning("[WS] rejected subscribe_message sid=%s: %s", sid, exc)
        return

    payload = data or {}
    message_id = str(payload.get("message_id", "")).strip()
    conversation_id = str(payload.get("conversation_id", "")).strip()
    if not message_id:
        return

    ws_manager.subscribe_message(sid, message_id, conversation_id)


async def handle_unsubscribe_message(sid: str, data: dict[str, Any] | None = None) -> None:
    """取消订阅消息流更新。"""
    try:
        _require_authenticated_connection(sid)
    except UnauthorizedException as exc:
        logging.warning("[WS] rejected unsubscribe_message sid=%s: %s", sid, exc)
        return

    payload = data or {}
    message_id = str(payload.get("message_id", "")).strip()
    if not message_id:
        return

    ws_manager.unsubscribe_message(sid, message_id)


async def handle_subscribe_document_index_notification(sid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """订阅文档索引完成通知。"""
    from internal.extension.socketio_extension import get_socketio

    try:
        connection = _require_authenticated_connection(sid)
    except UnauthorizedException as exc:
        logging.warning("[WS] rejected document subscribe sid=%s: %s", sid, exc)
        return {"ok": False, "error": "unauthorized"}

    user_channel = str(connection.account_id)
    ws_manager.subscribe_notification(sid, user_channel)
    sio = get_socketio()
    if sio is not None:
        await sio.enter_room(sid, user_channel)
    return {"ok": True, "channel": user_channel}


async def handle_unsubscribe_document_index_notification(sid: str, data: dict[str, Any] | None = None) -> None:
    """取消订阅文档索引完成通知。"""
    from internal.extension.socketio_extension import get_socketio

    try:
        connection = _require_authenticated_connection(sid)
    except UnauthorizedException as exc:
        logging.warning("[WS] rejected document unsubscribe sid=%s: %s", sid, exc)
        return

    ws_manager.unsubscribe_notification(sid, str(connection.account_id))
    sio = get_socketio()
    if sio is not None:
        await sio.leave_room(sid, str(connection.account_id))


async def handle_subscribe_agent_notification(sid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """订阅Agent构建完成通知。"""
    from internal.extension.socketio_extension import get_socketio

    try:
        connection = _require_authenticated_connection(sid)
    except UnauthorizedException as exc:
        logging.warning("[WS] rejected agent subscribe sid=%s: %s", sid, exc)
        return {"ok": False, "error": "unauthorized"}

    # 使用前缀区分Agent通知
    agent_notification_key = f"agent:{connection.account_id}"
    ws_manager.subscribe_notification(sid, agent_notification_key)
    sio = get_socketio()
    if sio is not None:
        await sio.enter_room(sid, agent_notification_key)
    return {"ok": True, "channel": agent_notification_key}


async def handle_unsubscribe_agent_notification(sid: str, data: dict[str, Any] | None = None) -> None:
    """取消订阅Agent构建完成通知。"""
    from internal.extension.socketio_extension import get_socketio

    try:
        connection = _require_authenticated_connection(sid)
    except UnauthorizedException as exc:
        logging.warning("[WS] rejected agent unsubscribe sid=%s: %s", sid, exc)
        return

    # 使用前缀区分Agent通知
    agent_notification_key = f"agent:{connection.account_id}"
    ws_manager.unsubscribe_notification(sid, agent_notification_key)
    sio = get_socketio()
    if sio is not None:
        await sio.leave_room(sid, agent_notification_key)


def register_socketio_handlers(socketio: Any) -> None:
    """在 Socket.IO 初始化完成后显式注册事件处理器（on 装饰器形式）。"""
    socketio.on("connect")(handle_connect)
    socketio.on("disconnect")(handle_disconnect)
    socketio.on("subscribe_message")(handle_subscribe_message)
    socketio.on("unsubscribe_message")(handle_unsubscribe_message)
    socketio.on("subscribe_document_index_notification")(handle_subscribe_document_index_notification)
    socketio.on("unsubscribe_document_index_notification")(handle_unsubscribe_document_index_notification)
    socketio.on("subscribe_agent_notification")(handle_subscribe_agent_notification)
    socketio.on("unsubscribe_agent_notification")(handle_unsubscribe_agent_notification)
