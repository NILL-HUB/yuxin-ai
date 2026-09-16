"""通用 admin 变更草稿服务（设计 §5.2）。

定位：``supervised`` 档自动化级别的载体——板块工具产出草稿（before/after/
diff/impact），管理员在后台点「应用」才真正落库，并提供回滚。

与 ``RoutingPolicyChangeService`` 的关系：后者是**路由板块**的专用编排
（含 suggestion 状态联动与特性开关写入），本服务是**通用台账**（只管草稿
本身的状态机）。路由板继续用自己的服务，其它板块用本服务，二者共用同一张
``policy_change_draft`` 表——避免 admin 侧并存两套草稿表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID

from internal.exception import NotFoundException
from internal.model.routing_quality import PolicyChangeDraftModel
from pkg.sqlalchemy import SQLAlchemy


class DraftStatus(str, Enum):
    """草稿状态机（与路由既有取值保持一致）。"""

    PENDING = "pending"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AdminChangeDraftService:
    """通用 admin 变更草稿的创建 / 列出 / 应用 / 回滚。"""

    def __init__(self, db: SQLAlchemy):
        self.db = db

    def create_draft(
        self,
        *,
        policy_type: str,
        target_id: str,
        before_config: dict,
        after_config: dict,
        diff: dict,
        impact: dict,
        created_by: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> PolicyChangeDraftModel:
        """创建一个待应用的变更草稿。

        Args:
            policy_type: **板块标识**（如 ``builtin_tool``）；路由板沿用
                ``model_routing`` / ``tool_policy`` / ``agent_policy``。
            agent_id: 提议该变更的 Agent；写入 ``impact``（本表无 agent_id 列，
                不为单一用途扩列，且 impact 本就是"变更影响面"的载体）。

        Returns:
            已落库的草稿（status=pending）。
        """
        # 复制而非原地修改：避免污染调用方传入的 dict。
        merged_impact = dict(impact or {})
        if agent_id is not None:
            merged_impact["agent_id"] = str(agent_id)
        if created_by is not None:
            merged_impact.setdefault("created_by", str(created_by))

        draft = PolicyChangeDraftModel(
            suggestion_id=None,
            policy_type=str(policy_type),
            target_id=str(target_id or ""),
            before_config=before_config or {},
            after_config=after_config or {},
            diff=diff or {},
            impact=merged_impact,
            status=DraftStatus.PENDING.value,
            rollback_reason="",
        )
        with self.db.auto_commit():
            self.db.session.add(draft)
        return draft

    def list_drafts(
        self,
        *,
        status: str = "",
        policy_type: str = "",
    ) -> list[PolicyChangeDraftModel]:
        """按状态与板块列出草稿（两者都为空则返回全部）。"""
        query = self.db.session.query(PolicyChangeDraftModel)
        if status:
            query = query.filter(PolicyChangeDraftModel.status == status)
        if policy_type:
            query = query.filter(PolicyChangeDraftModel.policy_type == policy_type)
        return query.order_by(PolicyChangeDraftModel.created_at.desc()).all()

    def get_draft(self, draft_id: UUID) -> PolicyChangeDraftModel:
        draft = (
            self.db.session.query(PolicyChangeDraftModel)
            .filter(PolicyChangeDraftModel.id == draft_id)
            .first()
        )
        if draft is None:
            raise NotFoundException("变更草稿不存在")
        return draft

    def apply_draft(self, *, draft_id: UUID, applied_by: UUID) -> PolicyChangeDraftModel:
        """把 pending 草稿标记为 applied。

        注意：本方法**只改变台账状态**，不执行板块动作——动作由调用方
        （板块工具/路由）在此之后执行，保证"先记账再执行"的审计顺序。

        Raises:
            NotFoundException: 草稿不存在。
            ValueError: 草稿不是 pending。
        """
        draft = self.get_draft(draft_id)
        if draft.status != DraftStatus.PENDING.value:
            raise ValueError(f"仅 pending 状态可应用，当前为 {draft.status}")
        draft.status = DraftStatus.APPLIED.value
        draft.applied_by = applied_by
        draft.applied_at = _utcnow_naive()
        with self.db.auto_commit():
            self.db.session.add(draft)
        return draft

    def rollback_draft(
        self,
        *,
        draft_id: UUID,
        rolled_back_by: UUID,
        reason: str = "",
    ) -> PolicyChangeDraftModel:
        """把 applied 草稿标记为 rolled_back。

        Raises:
            NotFoundException: 草稿不存在。
            ValueError: 草稿不是 applied。
        """
        draft = self.get_draft(draft_id)
        if draft.status != DraftStatus.APPLIED.value:
            raise ValueError(f"仅 applied 状态可回滚，当前为 {draft.status}")
        draft.status = DraftStatus.ROLLED_BACK.value
        draft.rolled_back_at = _utcnow_naive()
        draft.rollback_reason = reason or ""
        with self.db.auto_commit():
            self.db.session.add(draft)
        return draft
