"""板块工具的 LLM 适配测试（设计 §7.1）。

不变量：
- 工具数 == 已登记板块数（板块级聚合，不做端点级）；
- 工具名与 `BOARD_IDS` 一一对应，未登记板块不会出现；
- 权限/未登记拒绝**不抛给 LLM**，而是返回可读 JSON（让模型据实回报管理员）。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.service.admin_agent_chat_tools import build_board_tools


def _principal():
    return AdminAgentPrincipal(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        agent_name="运维 Agent",
        effective_permissions=frozenset({"builtin_tool:read", "builtin_tool:update"}),
        automation_policy={"builtin_tool": AutomationLevel.SUPERVISED},
    )


class _StubExecution:
    def __init__(self, error=None):
        self.calls = []
        self._error = error

    def run(self, principal, *, board, action, payload=None):
        self.calls.append({"board": board, "action": action, "payload": payload})
        if self._error is not None:
            raise self._error
        return {"outcome": "executed", "result": {"ok": True}, "draft_id": None}


def test_one_tool_per_registered_board():
    from internal.core.admin_agent_boards import BOARD_IDS

    tools = build_board_tools(_StubExecution(), _principal())

    assert [t.name for t in tools] == [f"admin_{b}" for b in BOARD_IDS]


def test_tool_forwards_board_action_and_payload():
    exec_svc = _StubExecution()
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}
    tool = tools["admin_builtin_tool"]

    tool.invoke({"action": "list", "payload": {}})

    assert exec_svc.calls[0]["board"] == "builtin_tool"
    assert exec_svc.calls[0]["action"] == "list"


def test_permission_denial_is_returned_as_readable_json():
    import json

    exec_svc = _StubExecution(error=PermissionError("Agent 无权限执行 builtin_tool.list（需要 builtin_tool:read）"))
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}

    payload = json.loads(tools["admin_builtin_tool"].invoke({"action": "list", "payload": {}}))

    assert payload["ok"] is False
    assert "无权限" in payload["error"]


def test_undeclared_action_is_returned_as_readable_json():
    import json

    exec_svc = _StubExecution(error=ValueError("板块 builtin_tool 未登记动作 nope（已登记: list, update_enabled, update_metadata）"))
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}

    payload = json.loads(tools["admin_builtin_tool"].invoke({"action": "nope", "payload": {}}))

    assert payload["ok"] is False
    assert "未登记" in payload["error"]
