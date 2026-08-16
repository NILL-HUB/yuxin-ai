"""会话路由模块（从 asgi_app.py 拆分）：/conversations/* 全家族。"""
from dataclasses import asdict
from types import SimpleNamespace

from quart import Response, request

from app.http import support as _support
from app.http.app import app as flask_app
from app.http.support import (
    _err,
    _field,
    _json_resp,
    _ok,
    _ok_msg,
    _resolve_account,
    _to_thread,
)

_registered = False


def _get_conversation_service():
    return _support._get_conversation_service()


def _get_service(cls):
    return _support._get_service(cls)


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/conversations/recent")
    async def async_recent_conversations() -> Response:
        """async 最近会话列表：async session 直查，不占用工作线程。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        raw_limit = request.args.get("limit") or 20
        try:
            limit = max(1, min(int(raw_limit), 1000))
        except ValueError:
            limit = 20

        assistant_agent_id = flask_app.config.get("ASSISTANT_AGENT_ID") or None
        results = await _get_conversation_service().get_recent_conversations_async(
            account,
            limit=limit,
            assistant_agent_id=assistant_agent_id,
        )
        return _ok(results)

    @quart_app.get("/conversations/<uuid:conversation_id>/messages")
    async def async_conversation_messages(conversation_id) -> Response:
        """async 会话消息分页：async session 直查，不占用工作线程。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        try:
            req = SimpleNamespace(
                current_page=_field(int(request.args.get("current_page") or 1), 1),
                page_size=_field(int(request.args.get("page_size") or 20), 20),
                created_at=_field(request.args.get("created_at"), None),
            )
        except ValueError:
            return _err("invalid_param", "current_page/page_size 必须为整数", 400)

        from internal.exception import NotFoundException
        from internal.schema.conversation_schema import GetConversationMessagesWithPageResp
        from pkg.paginator import PageModel

        try:
            messages, paginator = await _get_conversation_service().get_conversation_messages_with_page_async(
                conversation_id,
                req,
                account,
            )
        except NotFoundException:
            return _err("conversation_not_found", "该会话不存在或被删除", 404)

        resp = GetConversationMessagesWithPageResp(many=True)
        data = {"list": resp.dump(messages), "paginator": asdict(paginator)}
        return _ok(data)

    @quart_app.post("/conversations/<uuid:conversation_id>/delete")
    async def async_delete_conversation(conversation_id) -> Response:
        """async 删除会话（软删除 + 进入回收站，可指定留存天数；agent 代删默认 7 天）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.exception import NotFoundException

        payload = await request.get_json(force=True, silent=True) or {}
        try:
            await _to_thread(
                _get_conversation_service().delete_conversation,
                conversation_id,
                account,
                retention_days=payload.get("retention_days"),
                agent_id=payload.get("agent_id"),
            )
        except NotFoundException:
            return _err("conversation_not_found", "该会话不存在或被删除", 404)
        return _ok_msg("删除会话成功")

    @quart_app.post("/conversations/<uuid:conversation_id>/messages/<uuid:message_id>/delete")
    @quart_app.post("/conversations/<uuid:conversation_id>/messages/<uuid:message_id>")
    async def async_delete_message(conversation_id, message_id) -> Response:
        """async 删除会话消息（含历史客户端无 /delete 后缀的兼容路由）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.exception import NotFoundException

        try:
            await _to_thread(
                _get_conversation_service().delete_message,
                conversation_id,
                message_id,
                account,
            )
        except NotFoundException:
            return _err("message_not_found", "该消息不存在", 404)
        return _ok_msg("删除会话消息成功")

    @quart_app.get("/conversations/<uuid:conversation_id>/name")
    async def async_get_conversation_name(conversation_id) -> Response:
        """async 获取会话名称。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.exception import NotFoundException

        try:
            conversation = await _to_thread(
                _get_conversation_service().get_conversation, conversation_id, account
            )
        except NotFoundException:
            return _err("conversation_not_found", "该会话不存在或被删除", 404)
        return _ok({"name": conversation.name})

    @quart_app.post("/conversations/<uuid:conversation_id>/name")
    async def async_update_conversation_name(conversation_id) -> Response:
        """async 更新会话名称。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _err("invalid_param", "会话名称不能为空", 400)

        await _to_thread(
            _get_conversation_service().update_conversation,
            conversation_id,
            account,
            name=name,
        )
        return _ok_msg("修改会话名称成功")

    @quart_app.post("/conversations/<uuid:conversation_id>/is-pinned")
    async def async_update_conversation_is_pinned(conversation_id) -> Response:
        """async 更新会话置顶状态。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        is_pinned = bool(payload.get("is_pinned"))

        await _to_thread(
            _get_conversation_service().update_conversation,
            conversation_id,
            account,
            is_pinned=is_pinned,
        )
        return _ok_msg("修改会话置顶状态成功")

    @quart_app.get("/conversations/search")
    async def async_search_conversations() -> Response:
        """async 搜索会话及其消息内容。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        query = str(request.args.get("query") or "")
        raw_limit = request.args.get("limit") or 50
        try:
            limit = max(1, min(int(raw_limit), 200))
        except ValueError:
            limit = 50

        conversations = await _to_thread(
            _get_conversation_service().search_conversations,
            account,
            query,
            limit,
        )
        from internal.schema.conversation_schema import SearchConversationsResp

        resp = SearchConversationsResp(many=True)
        return _ok(resp.dump(conversations))

    @quart_app.get("/conversations/<uuid:conversation_id>/variables")
    async def async_get_variables(conversation_id) -> Response:
        """async 获取会话变量列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.exception import NotFoundException
        from internal.service.conversation_variable_service import ConversationVariableService

        try:
            await _to_thread(_get_conversation_service().get_conversation, conversation_id, account)
        except NotFoundException:
            return _err("conversation_not_found", "该会话不存在或被删除", 404)

        variables = await _to_thread(
            _get_service(ConversationVariableService).get_variables, conversation_id
        )
        return _ok({"list": variables})

    @quart_app.post("/conversations/<uuid:conversation_id>/variables")
    async def async_set_variable(conversation_id) -> Response:
        """async 设置会话变量。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from pydantic import ValidationError
        from internal.exception import NotFoundException
        from internal.schema.conversation_variable_schema import SetVariableReq
        from internal.service.conversation_variable_service import ConversationVariableService

        try:
            await _to_thread(_get_conversation_service().get_conversation, conversation_id, account)
        except NotFoundException:
            return _err("conversation_not_found", "该会话不存在或被删除", 404)

        payload = await request.get_json(force=True) or {}
        try:
            req = SetVariableReq(**payload)
        except ValidationError as ex:
            errors = {
                ".".join(str(loc) for loc in error["loc"]): [error["msg"]]
                for error in ex.errors()
            }
            first_msg = next(iter(errors.values()))[0]
            return _json_resp(code="validate_error", message=first_msg, data=errors, status=400)

        variable = await _to_thread(
            _get_service(ConversationVariableService).set_variable,
            conversation_id,
            req.name,
            req.value,
            req.value_type,
        )
        return _ok(variable)

    @quart_app.post("/conversations/<uuid:conversation_id>/variables/batch")
    async def async_batch_set_variables(conversation_id) -> Response:
        """async 批量设置会话变量。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from pydantic import ValidationError
        from internal.exception import NotFoundException
        from internal.schema.conversation_variable_schema import BatchSetVariablesReq
        from internal.service.conversation_variable_service import ConversationVariableService

        try:
            await _to_thread(_get_conversation_service().get_conversation, conversation_id, account)
        except NotFoundException:
            return _err("conversation_not_found", "该会话不存在或被删除", 404)

        payload = await request.get_json(force=True) or {}
        try:
            req = BatchSetVariablesReq(**payload)
        except ValidationError as ex:
            errors = {
                ".".join(str(loc) for loc in error["loc"]): [error["msg"]]
                for error in ex.errors()
            }
            first_msg = next(iter(errors.values()))[0]
            return _json_resp(code="validate_error", message=first_msg, data=errors, status=400)

        variables = await _to_thread(
            _get_service(ConversationVariableService).batch_set_variables,
            conversation_id,
            req.variables,
        )
        return _ok({"list": variables})

    @quart_app.post("/conversations/<uuid:conversation_id>/variables/<string:name>/delete")
    async def async_delete_variable(conversation_id, name) -> Response:
        """async 删除会话变量。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.exception import NotFoundException
        from internal.service.conversation_variable_service import ConversationVariableService

        try:
            await _to_thread(_get_conversation_service().get_conversation, conversation_id, account)
        except NotFoundException:
            return _err("conversation_not_found", "该会话不存在或被删除", 404)

        await _to_thread(
            _get_service(ConversationVariableService).delete_variable,
            conversation_id,
            name,
        )
        return _ok_msg("删除变量成功")

    @quart_app.post("/conversations/<uuid:conversation_id>/variables/delete-all")
    async def async_delete_all_variables(conversation_id) -> Response:
        """async 清空会话变量。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.exception import NotFoundException
        from internal.service.conversation_variable_service import ConversationVariableService

        try:
            await _to_thread(_get_conversation_service().get_conversation, conversation_id, account)
        except NotFoundException:
            return _err("conversation_not_found", "该会话不存在或被删除", 404)

        count = await _to_thread(
            _get_service(ConversationVariableService).delete_variables_by_conversation,
            conversation_id,
        )
        return _ok({"count": count})
