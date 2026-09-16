"""把板块动作注册表暴露为「每板块一个」LangChain 工具（设计 §7.1）。

为什么不复用 `AssistantAgentService._build_assistant_runtime_tools`：
那是用户域工具的条件装配点（逐个 try + 功能开关），复用它只能靠黑名单
排除用户域工具，而黑名单对动态集合不完备——漏一个就是越权（设计 §6.1）。
本模块**只**为已登记板块生成工具，白名单式，边界可自证。

为什么拒绝不抛异常：工具的调用方是 LLM。抛异常会中断整轮对话，而
`PermissionError` / `ValueError` 都是"该动作不能做"的正常业务结论——
应作为**可读结果**回给模型，让它如实向管理员汇报（审计已由执行层写好）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, create_model

from internal.core.admin_agent_boards import boards as _boards
from internal.entity.admin_agent_entity import AdminAgentPrincipal

logger = logging.getLogger(__name__)

__all__ = ["build_board_tools", "tool_name_for_board"]


def tool_name_for_board(board: str) -> str:
    """板块 → LLM 工具名（LLM 工具名只允许字母/数字/下划线/连字符）。"""
    return f"admin_{board}"


def _make_args_schema(board: str, actions: list[str]):
    description = (
        f"要执行的动作，必须取自：{', '.join(actions)}。"
        "未登记的动作会被拒绝（fail closed）。"
    )
    return create_model(
        f"Admin{board.title().replace('_', '')}Args",
        action=(str, Field(..., description=description)),
        payload=(dict, Field(default_factory=dict, description="动作入参（按动作语义传）")),
    )


def _make_tool_class(board: str, actions: list[str]):
    schema = _make_args_schema(board, actions)
    tool_name = tool_name_for_board(board)

    class _BoardTool(BaseTool):
        name: str = tool_name
        description: str = (
            f"执行管理端「{board}」板块的治理动作。可选动作：{', '.join(actions)}。"
            "只读动作可直接执行；写动作按该板块的自动化级别可能转为待批准草稿。"
        )
        args_schema: type[BaseModel] = schema
        execution_service: Any = None
        principal: Any = None

        def _run(self, action: str = "", payload: dict | None = None, **kwargs: Any) -> str:
            try:
                result = self.execution_service.run(
                    self.principal, board=board, action=action, payload=payload or {}
                )
            except (PermissionError, ValueError) as exc:
                # 拒绝是正常业务结论：回可读结果，不中断对话（审计已由执行层记录）
                return json.dumps(
                    {"ok": False, "board": board, "action": action, "error": str(exc)},
                    ensure_ascii=False,
                )
            return json.dumps(
                {"ok": True, "board": board, **result}, ensure_ascii=False
            )

        async def _arun(self, action: str = "", payload: dict | None = None, **kwargs: Any) -> str:
            return self._run(action=action, payload=payload, **kwargs)

    return _BoardTool


def build_board_tools(execution_service, principal: AdminAgentPrincipal) -> list[BaseTool]:
    """为每个已登记板块构造一个绑定到该 principal 的工具。

    工具实例持有 principal，因此**不能**跨 Agent 复用或缓存。
    """
    from internal.core.admin_agent_boards import board_ids_of

    tools: list[BaseTool] = []
    for board in _boards():
        cls = _make_tool_class(board, board_ids_of(board))
        tools.append(cls(execution_service=execution_service, principal=principal))
    return tools
