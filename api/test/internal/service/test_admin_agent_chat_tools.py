"""板块工具的 LLM 适配测试（设计 §7.1）。

不变量：
- 工具数 == 已登记板块数（板块级聚合，不做端点级）；
- 工具名与 `BOARD_IDS` 一一对应，未登记板块不会出现；
- 权限/未登记拒绝**不抛给 LLM**，而是返回可读 JSON（让模型据实回报管理员）；
- 业务失败（`CustomException` 家族：板块未实现、目标不存在）同样必须返回
  可读 JSON —— 否则异常会穿过工具边界中断整轮对话（S1 回归锁）。
"""
import json
from uuid import uuid4

import pytest

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.exception import FailException, NotFoundException
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
    def __init__(self, error=None, result=None):
        self.calls = []
        self._error = error
        self._result = result or {
            "outcome": "executed",
            "result": {"ok": True},
            "draft_id": None,
        }

    def run(self, principal, *, board, action, payload=None):
        self.calls.append({"board": board, "action": action, "payload": payload})
        if self._error is not None:
            raise self._error
        return self._result


def test_one_tool_per_registered_board():
    from internal.core.admin_agent_boards import BOARD_IDS

    tools = build_board_tools(_StubExecution(), _principal())

    assert [t.name for t in tools] == [f"admin_{b}" for b in BOARD_IDS]


def test_tool_forwards_board_action_and_payload():
    exec_svc = _StubExecution()
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}
    tool = tools["admin_builtin_tool"]

    payload = {"tool_id": "t1", "enabled": True}
    tool.invoke({"action": "update_enabled", "payload": payload})

    assert exec_svc.calls[0]["board"] == "builtin_tool"
    assert exec_svc.calls[0]["action"] == "update_enabled"
    assert exec_svc.calls[0]["payload"] == payload


def test_executed_outcome_is_returned_as_readable_json():
    exec_svc = _StubExecution(
        result={"outcome": "executed", "result": {"total": 2}, "draft_id": None}
    )
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}

    payload = json.loads(
        tools["admin_builtin_tool"].invoke({"action": "list", "payload": {}})
    )

    assert payload == {
        "ok": True,
        "board": "builtin_tool",
        "outcome": "executed",
        "result": {"total": 2},
        "draft_id": None,
    }


def test_supervised_write_is_reported_as_pending_draft():
    """supervised 档写动作：未真实执行，只回草稿 id。"""
    exec_svc = _StubExecution(
        result={"outcome": "drafted", "result": None, "draft_id": "draft-1"}
    )
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}

    payload = json.loads(
        tools["admin_builtin_tool"].invoke(
            {"action": "update_enabled", "payload": {"tool_id": "t1", "enabled": True}}
        )
    )

    assert payload["ok"] is True
    assert payload["outcome"] == "drafted"
    assert payload["draft_id"] == "draft-1"
    # 必须能看出"尚未生效"，否则模型会向管理员谎报已执行
    assert payload["result"] is None


def test_permission_denial_is_returned_as_readable_json():
    exec_svc = _StubExecution(error=PermissionError("Agent 无权限执行 builtin_tool.list（需要 builtin_tool:read）"))
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}

    payload = json.loads(tools["admin_builtin_tool"].invoke({"action": "list", "payload": {}}))

    assert payload["ok"] is False
    assert "无权限" in payload["error"]


def test_undeclared_action_is_returned_as_readable_json():
    exec_svc = _StubExecution(error=ValueError("板块 builtin_tool 未登记动作 nope（已登记: list, update_enabled, update_metadata）"))
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}

    payload = json.loads(tools["admin_builtin_tool"].invoke({"action": "nope", "payload": {}}))

    assert payload["ok"] is False
    assert "未登记" in payload["error"]


@pytest.mark.parametrize(
    "error",
    [
        FailException("板块 builtin_tool 尚未实现（已登记动作但无实现体）"),
        NotFoundException("内置工具 t1 不存在"),
    ],
    ids=["fail_exception", "not_found_exception"],
)
def test_business_failure_is_returned_as_readable_json(error):
    """`CustomException` 家族必须转成可读结果，不得穿过工具边界。

    执行层（BoardToolExecutor）以 FailException 表达"入参非法/板块无实现体"，
    下游 service 以 NotFoundException 表达"目标已不存在"——两者都是业务结论，
    抛给 LLM 会中断整轮对话。
    """
    exec_svc = _StubExecution(error=error)
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}

    payload = json.loads(
        tools["admin_builtin_tool"].invoke({"action": "list", "payload": {}})
    )

    assert payload["ok"] is False
    assert payload["board"] == "builtin_tool"
    assert payload["action"] == "list"
    assert payload["error"] == str(error)
