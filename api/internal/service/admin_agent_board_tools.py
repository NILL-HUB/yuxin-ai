"""管理端 Agent 的板块级聚合工具与执行闸门（设计 §7.1）。

设计要点：
- **一个板块一个工具**，内部按 ``action`` 分支。admin 有上百个端点，
  端点级工具会让工具数远超 selected_tools 上限、拉低 LLM 选择准确率；
  且"板块被授权"的语义天然对应板块级工具。
- **每 action 显式声明所需权限点**，未声明即拒绝（fail closed），
  声明表在 ``internal/core/admin_agent_boards.py``。
- 执行四步（设计 §7.1）：① 校验权限 ② 解析自动化级别 ③ 调 service
  ④ 写审计。本模块负责第 1、3 步与第 2 步的判定；第 2 步的分流落地与
  第 4 步的审计由 ``AdminAgentExecutionService`` 统一负责，避免这些逻辑
  散落在各板块。

service 层不感知 Agent（保持纯粹）：板块工具只是"带边界校验的薄转发"。
"""
from __future__ import annotations

import logging
from typing import Any

from internal.core.admin_agent_boards import boards as _boards
from internal.core.admin_agent_boards import resolve_action
from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.exception import FailException

logger = logging.getLogger(__name__)


class BoardToolExecutor:
    """板块动作的统一执行闸门与分发器。

    刻意**不用** ``@inject @dataclass``：它不持有状态，且需要能被测试直接
    构造（``BoardToolExecutor()``）。
    """

    def assert_allowed(
        self,
        principal: AdminAgentPrincipal,
        *,
        board: str,
        action: str,
    ):
        """执行四步中第 1、2 步的前置校验。

        Args:
            principal: 已算好三重交集的执行身份。

        Returns:
            已解析的 ``BoardAction``。

        Raises:
            ValueError: (board, action) 未登记（fail closed）。
            PermissionError: 权限不足，或板块处于 blocked 档。
        """
        declared = resolve_action(board, action)

        if not principal.has_permission(declared.permission_code):
            raise PermissionError(
                f"Agent 无权限执行 {board}.{action}"
                f"（需要 {declared.permission_code}）"
            )

        level = principal.automation_level_for(board)
        if level is AutomationLevel.BLOCKED:
            raise PermissionError(f"板块 {board} 已熔断（blocked），拒绝执行")

        return declared

    @staticmethod
    def requires_draft(principal: AdminAgentPrincipal, board: str) -> bool:
        """该板块的写操作是否需要走变更草稿（supervised 档）。

        fail closed：未配置的板块由 ``automation_level_for`` 返回 SUPERVISED，
        因此返回 True ——"忘记配置"不会变成"全自动"。
        """
        return principal.automation_level_for(board) is AutomationLevel.SUPERVISED

    # ------------------------------------------------------------------
    # 板块动作实现
    # ------------------------------------------------------------------

    def execute(
        self,
        principal: AdminAgentPrincipal,
        *,
        board: str,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行一个板块动作（**只读或已获批准的写**）。

        写操作的分流（supervised → 草稿 / autonomous → 直接执行）由调用方
        ``AdminAgentExecutionService`` 决定；本方法只负责"权限已通过后真正干活"。

        Raises:
            PermissionError: 权限不足或板块熔断。
            ValueError: (board, action) 未登记。
            FailException: 入参非法，或板块已登记但缺实现体。
        """
        self.assert_allowed(principal, board=board, action=action)
        handler = getattr(self, f"_do_{board}", None)
        if handler is None:
            raise FailException(f"板块 {board} 尚未实现（已登记动作但无实现体）")
        return handler(principal, action=action, payload=payload or {})

    # ------------------------------------------------------------------
    # builtin_tool（P1b 端到端样板板块）
    # ------------------------------------------------------------------

    def _do_builtin_tool(
        self, principal: AdminAgentPrincipal, *, action: str, payload: dict
    ) -> dict:
        """内置工具板块的 action 分发。

        复用既有 ``BuiltinToolService``，不重写查询/写入逻辑。
        """
        if action == "list":
            service = self._builtin_tool_service()
            items = service.get_builtin_tools()
            return {
                "board": "builtin_tool",
                "action": "list",
                "total": len(items),
                "items": [
                    {
                        "id": item.get("id"),
                        "provider": (item.get("provider") or {}).get("name")
                        or item.get("provider_id"),
                        "name": item.get("name"),
                        "label": item.get("label"),
                        "enabled": item.get("enabled"),
                        "source": item.get("source"),
                    }
                    for item in items
                ],
            }

        if action == "update_enabled":
            tool_id = payload.get("tool_id")
            enabled = payload.get("enabled")
            # 入参校验必须**先于**任何有副作用的调用
            if not tool_id or not isinstance(enabled, bool):
                raise FailException("update_enabled 需要 tool_id 与布尔 enabled")
            tool = self._builtin_tool_service().set_tool_enabled(
                tool_id, enabled, set_custom_source=True
            )
            return {
                "board": "builtin_tool",
                "action": "update_enabled",
                "tool_id": str(getattr(tool, "id", tool_id)),
                "enabled": bool(tool.enabled),
                "source": tool.source,
            }

        if action == "update_metadata":
            tool_id = payload.get("tool_id")
            if not tool_id:
                raise FailException("update_metadata 需要 tool_id")
            data = {
                k: v
                for k, v in payload.items()
                if k in {"label", "description", "task_keywords"}
            }
            if not data:
                raise FailException(
                    "update_metadata 至少需要 label/description/task_keywords 之一"
                )
            from app.http.admin_routes_8 import _builtin_tool_update

            result = _builtin_tool_update(tool_id, data)
            if isinstance(result, dict) and result.get("_errors"):
                raise FailException(f"参数校验失败: {result['_errors']}")
            return {
                "board": "builtin_tool",
                "action": "update_metadata",
                "tool_id": str(tool_id),
                "result": result,
            }

        raise FailException(f"builtin_tool 未实现 action: {action}")

    @staticmethod
    def _builtin_tool_service():
        """取 BuiltinToolService（复用 injector 单例，避免每次重建全量 map）。

        ``BuiltinToolService`` 依赖 ``BuiltinProviderManager``（首次构造会加载
        全部 builtin provider 并 dynamic_import），因此复用单例而非直接实例化。
        """
        from app.http import asgi_app as a
        from internal.service.builtin_tool_service import BuiltinToolService

        return a._get_service(BuiltinToolService)


def available_boards() -> tuple[str, ...]:
    """对 LLM 暴露的板块清单（工具 schema 用）。"""
    return _boards()
