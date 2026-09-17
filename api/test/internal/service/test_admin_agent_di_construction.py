"""DI 构造守卫测试：管理端 Agent 服务必须能被 injector 真实构造。

背景（实测断链）：``support._get_service`` 就是 ``injector.get(cls)``；若服务类
未声明 ``@inject``，injector 会尝试无参构造并抛 ``CallError``，导致
``/admin/agents/*`` 全部 500。

本文件直接对 ``injector.get`` 断言，并额外用一条**不替换
``support._get_service``** 的路由用例走真实构造路径——后者是这类断链的唯一有效
守卫：服务层单测惯用 ``__new__`` / 替身注入，恰好绕过接线环节（单测全绿仍可能
生产 500）。
"""
import asyncio

import pytest

import app.http.asgi_app as asgi_app
from app.http.admin_routes_7 import register_routes
from app.http.module import injector
from internal.service.admin_agent_builtin_agents import AdminAgentBuiltinService
from internal.service.admin_agent_chat_service import AdminAgentChatService
from internal.service.admin_agent_conversation_service import (
    AdminAgentConversationService,
)
from internal.service.admin_agent_service import AdminAgentService
from internal.service.admin_change_draft_service import AdminChangeDraftService

register_routes(asgi_app.quart_app)


@pytest.mark.parametrize(
    "service_cls",
    [
        AdminAgentService,
        AdminAgentBuiltinService,
        AdminAgentChatService,
        AdminChangeDraftService,
        AdminAgentConversationService,
    ],
)
def test_service_is_constructible_by_injector(service_cls):
    """injector.get 必须能构造服务（否则 `_get_service` 在生产上抛 CallError）。"""
    service = injector.get(service_cls)
    assert service.db is not None


def test_assignable_permissions_endpoint_uses_real_injector():
    """GET /admin/agents/assignable-permissions 走真实 injector 构造路径。

    刻意**不**替换 ``support._get_service``（conftest 只放行
    ``_resolve_admin_permission``）：修复前该路由因 injector 无法构造
    ``AdminAgentService`` 而 500，修复后应为 200。
    """

    async def _run():
        client = asgi_app.quart_app.test_client()
        return await client.get("/admin/agents/assignable-permissions")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
