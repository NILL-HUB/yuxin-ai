"""管理端 Agent 执行层（设计 §6.1 / §7.1 执行四步 / §9 审计）。

为什么新建独立链路而不复用用户端 ``chat()``：
``AssistantAgentService._build_assistant_runtime_tools()`` 是**用户域固有
工具的装配点**，按用户身份装配 create_app / 本机文件三件套 / 电脑控制 /
浏览器 / audio / code_execution / vision / todo / 知识库检索 / skill_detail /
agent_memory 等，且是**条件装配**（逐个 try、受功能开关与运行上下文约束），
实际数量随配置动态变化。复用它只能靠黑名单排除用户域工具，而黑名单对
"随配置动态增减"的集合是不完备的——漏一个就是越权。故本链路只装配
admin 板块工具（白名单式，未登记即不装配）。

本服务承担"执行四步"的第 2 步（自动化级别分流）与第 4 步（写审计），
第 1 步（权限/熔断校验）与第 3 步（调 service）委托给 ``BoardToolExecutor``。
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from internal.entity.admin_agent_entity import AdminAgentPrincipal

logger = logging.getLogger(__name__)


class ExecutionOutcome(str, Enum):
    """一次 Agent 执行的结果类别。"""

    EXECUTED = "executed"  # 已真实执行（只读动作，或 autonomous 档写动作）
    DRAFTED = "drafted"    # 未执行，已产出变更草稿等待人工批准（supervised 档）


class AdminAgentExecutionService:
    """板块动作的执行编排：分流域 + 审计域。

    依赖显式注入（构造参数），便于测试替换；生产侧由路由层组装。
    """

    def __init__(
        self,
        *,
        board_executor,
        draft_service,
        audit_log_service,
    ):
        self.board_executor = board_executor
        self.draft_service = draft_service
        self.audit_log_service = audit_log_service

    def run(
        self,
        principal: AdminAgentPrincipal,
        *,
        board: str,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行一个板块动作，按自动化级别分流并写审计。

        Returns:
            ``{"outcome": "executed"|"drafted", "result": ..., "draft_id": ...}``

        Raises:
            ValueError: (board, action) 未登记。
            PermissionError: 权限不足或板块熔断。
        """
        payload = payload or {}
        target_id = str(payload.get("tool_id") or payload.get("target_id") or "")

        # ---- 第 1 步：权限 / 熔断校验（不足 → 拒绝**并记审计**）----
        try:
            declared = self.board_executor.assert_allowed(
                principal, board=board, action=action
            )
        except (PermissionError, ValueError) as exc:
            self._audit(
                principal,
                action=f"admin_agent.{board}.{action}.denied",
                resource_type=board,
                resource_id=target_id,
                after_data={"reason": str(exc), "payload": payload},
            )
            raise

        # ---- 第 2 步：自动化级别分流 ----
        # 只读动作不进草稿：否则 supervised 档的 Agent 连"看现状"都做不到。
        needs_draft = declared.is_write and self.board_executor.requires_draft(
            principal, board
        )
        if needs_draft:
            draft = self.draft_service.create_draft(
                policy_type=board,
                target_id=target_id,
                before_config=payload.get("before_config") or {},
                after_config=payload,
                diff=payload.get("diff") or {},
                impact={"board": board, "action": action, "source": "admin_agent"},
                created_by=principal.admin_user_id,
                agent_id=principal.agent_id,
            )
            draft_id = str(getattr(draft, "id", "") or "")
            self._audit(
                principal,
                action=f"admin_agent.{board}.{action}.drafted",
                resource_type=board,
                resource_id=target_id,
                after_data={
                    "draft_id": draft_id,
                    "action": action,
                    "payload": payload,
                },
            )
            return {
                "outcome": ExecutionOutcome.DRAFTED.value,
                "result": None,
                "draft_id": draft_id,
            }

        # ---- 第 3 步：调板块实现体 ----
        result = self.board_executor.execute(
            principal, board=board, action=action, payload=payload
        )

        # ---- 第 4 步：写审计（actor_type=agent，admin_user_id 为人类责任人）----
        self._audit(
            principal,
            action=f"admin_agent.{board}.{action}",
            resource_type=board,
            resource_id=target_id,
            after_data={
                "action": action,
                "payload": payload,
                "result": result if isinstance(result, dict) else {"value": result},
            },
        )
        return {
            "outcome": ExecutionOutcome.EXECUTED.value,
            "result": result,
            "draft_id": None,
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _audit(
        self,
        principal: AdminAgentPrincipal,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        after_data: dict,
    ) -> None:
        """写一条 actor_type=agent 的审计。

        审计失败**不阻断**主流程（与既有 `_write_audit` / `_emit_audit` 的
        容错一致），但必须记日志便于排查。

        `commit=True`：本链路不共享调用方事务（路由层经 `_to_thread` 调度，
        线程退出时会归还 session），必须当场提交，否则审计会随 session
        归还被回滚——这正是 Task 1 修复的那类静默丢失。
        """
        try:
            self.audit_log_service.record(
                admin_user_id=principal.admin_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                actor_type="agent",
                agent_id=principal.agent_id,
                after_data=after_data,
                commit=True,
            )
        except Exception:
            logger.exception(
                "管理端 Agent 审计写入失败 action=%s agent_id=%s",
                action,
                principal.agent_id,
            )
