"""管理端 Agent 服务：定义 CRUD + 授权校验（设计 §4、§5）。

边界说明：
- 本服务**只负责 Agent 的定义与授权**，不执行任何板块动作。
  执行链路的装配在 P1b 的 AdminAgentService（执行侧）。
- 权限校验在此处做"保存时"校验（§4.3 第二层）；
  "运行时"校验由每次请求实时重算 effective（第一/三层）。
"""
from __future__ import annotations

from uuid import UUID

from internal.core.admin_agent_authorization import (
    ASSIGNABLE_PERMISSIONS,
    assert_grantable,
)
from internal.entity.admin_agent_entity import AutomationLevel
from internal.model.admin_agent import AdminAgent
from pkg.sqlalchemy import SQLAlchemy


class AdminAgentService:
    def __init__(self, db: SQLAlchemy):
        self.db = db

    # ---------- 授权（§4.3 展示即受限） ----------

    def list_assignable_permissions(self, *, admin_permissions) -> list[str]:
        """返回该管理员**实际可下放**的权限点（交集，不是全量目录）。

        设计 §4.3：API 只返回交集，UI 只渲染该列表——
        管理员看不到自己没有的权限点，无从选择。
        """
        return sorted(frozenset(admin_permissions) & ASSIGNABLE_PERMISSIONS)

    # ---------- Agent 定义 CRUD ----------

    def list_agents(self, *, admin_user_id: UUID) -> list[AdminAgent]:
        """仅返回**该管理员自己创建**的 Agent（设计 §2：仅创建者可用）。"""
        return (
            self.db.session.query(AdminAgent)
            .filter(AdminAgent.owner_admin_user_id == admin_user_id)
            .order_by(AdminAgent.created_at)
            .all()
        )

    def get_agent(self, *, agent_id: UUID, admin_user_id: UUID) -> AdminAgent | None:
        agent = (
            self.db.session.query(AdminAgent)
            .filter(AdminAgent.id == agent_id)
            .first()
        )
        if agent is None:
            return None
        if agent.owner_admin_user_id != admin_user_id:
            raise PermissionError("仅创建者可使用该 Agent")
        return agent

    def create_agent(
        self,
        *,
        admin_user_id: UUID,
        admin_permissions,
        name: str,
        description: str = "",
        prompt_key: str | None = None,
        granted_permissions=None,
        automation_policy=None,
    ) -> AdminAgent:
        granted = list(granted_permissions or [])
        assert_grantable(requested=granted, admin_permissions=admin_permissions)
        policy = self._validate_policy(automation_policy)

        agent = AdminAgent(
            owner_admin_user_id=admin_user_id,
            name=name,
            description=description,
            prompt_key=prompt_key,
            granted_permissions=granted,
            automation_policy=policy,
            budget_config={},
            enabled=True,
        )
        with self.db.auto_commit():
            self.db.session.add(agent)
        return agent

    def update_agent(
        self,
        *,
        agent_id: UUID,
        admin_user_id: UUID,
        admin_permissions,
        name: str | None = None,
        description: str | None = None,
        prompt_key: str | None = None,
        granted_permissions=None,
        automation_policy=None,
        enabled: bool | None = None,
    ) -> AdminAgent:
        agent = self.get_agent(agent_id=agent_id, admin_user_id=admin_user_id)
        if agent is None:
            raise LookupError("Agent 不存在")

        if granted_permissions is not None:
            granted = list(granted_permissions)
            assert_grantable(requested=granted, admin_permissions=admin_permissions)
            agent.granted_permissions = granted
        if automation_policy is not None:
            agent.automation_policy = self._validate_policy(automation_policy)
        if name is not None:
            agent.name = name
        if description is not None:
            agent.description = description
        if prompt_key is not None:
            agent.prompt_key = prompt_key
        if enabled is not None:
            agent.enabled = enabled

        with self.db.auto_commit():
            self.db.session.add(agent)
        return agent

    def delete_agent(self, *, agent_id: UUID, admin_user_id: UUID) -> None:
        agent = self.get_agent(agent_id=agent_id, admin_user_id=admin_user_id)
        if agent is None:
            raise LookupError("Agent 不存在")
        with self.db.auto_commit():
            self.db.session.delete(agent)

    # ---------- 权限回收（§4.4） ----------

    def prune_revoked_permissions(
        self,
        *,
        admin_user_id: UUID,
        admin_permissions,
    ) -> int:
        """管理员失权后，从其名下所有 Agent 中物理删除失效权限（设计 §4.4）。

        「失效」= 不在 ``admin_permissions`` 中，**或**已不在可下放白名单中。
        理由：不留"显示有、实际无效"的混乱状态，避免管理员困惑
        "为什么 Agent 不干活了"。

        代价（可接受）：管理员重新获得权限后需**手动重新下放**——更安全的取舍。

        Returns:
            被移除的 (agent, permission) 组合数。
        """
        allowed = frozenset(admin_permissions) & ASSIGNABLE_PERMISSIONS
        agents = (
            self.db.session.query(AdminAgent)
            .filter(AdminAgent.owner_admin_user_id == admin_user_id)
            .all()
        )
        removed = 0
        touched: list[AdminAgent] = []
        for agent in agents:
            current = list(agent.granted_permissions or [])
            kept = [code for code in current if code in allowed]
            if len(kept) != len(current):
                removed += len(current) - len(kept)
                agent.granted_permissions = kept
                touched.append(agent)
        if touched:
            with self.db.auto_commit():
                for agent in touched:
                    self.db.session.add(agent)
        return removed

    # ---------- 内部 ----------

    @staticmethod
    def _validate_policy(policy) -> dict:
        """校验 automation_policy 取值合法（§5.1 三档）。

        非法取值必须**显式报错**而非静默降级——静默降级会让管理员
        以为自己配了 autonomous 而实际是 supervised（或反之）。
        """
        result: dict[str, str] = {}
        for board, level in (policy or {}).items():
            try:
                result[str(board)] = AutomationLevel(level).value
            except ValueError:
                raise ValueError(
                    f"非法自动化级别: {board}={level!r}，"
                    f"可选值 {[x.value for x in AutomationLevel]}"
                )
        return result
