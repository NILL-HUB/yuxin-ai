"""通用 admin 变更草稿服务测试（设计 §5.2）。

本服务是 supervised 档的载体：板块工具产出草稿 → 人工点「应用」才落库。

注意：query 替身**真实求值过滤条件**（而非"filter 直接 return self"的空壳）。
原因：草稿的「只能应用 pending」「只能回滚 applied」是**状态机安全边界**；
若替身忽略 filter，测试会在"能重复应用"的实现下依然通过——正是设计文档 §12
警告的假通过。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.sql import operators

from internal.exception import NotFoundException
from internal.service.admin_change_draft_service import (
    AdminChangeDraftService,
    DraftStatus,
)


class _QueryStub:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *criteria, **kw):
        for crit in criteria:
            self._rows = [r for r in self._rows if _matches(r, crit)]
        return self

    def filter_by(self, **kw):
        self._rows = [
            r for r in self._rows if all(getattr(r, k, None) == v for k, v in kw.items())
        ]
        return self

    def order_by(self, *a, **kw):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


def _matches(row, crit) -> bool:
    left = getattr(crit, "left", None)
    key = getattr(left, "key", None)
    if key is None:
        return True
    op = getattr(crit, "operator", None)
    right = crit.right
    if op is operators.eq:
        return getattr(row, key, None) == getattr(right, "value", right)
    if op is operators.in_op:
        values = getattr(right, "value", right)
        return getattr(row, key, None) in set(values)
    return True


class _AutoCommit:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._session.commit()
        return False


class _SessionStub:
    def __init__(self, rows=None):
        self.rows = list(rows) if rows is not None else []
        self.added = []
        self.commits = 0

    def query(self, *a, **kw):
        return _QueryStub(self.rows)

    def add(self, obj):
        self.added.append(obj)
        if obj not in self.rows:
            self.rows.append(obj)

    def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _service(rows=None):
    session = _SessionStub(rows)
    db = SimpleNamespace(session=session, auto_commit=lambda: _AutoCommit(session))
    return AdminChangeDraftService(db=db), session


def _draft(status="pending", policy_type="builtin_tool", **kw):
    return SimpleNamespace(
        id=uuid4(),
        suggestion_id=None,
        policy_type=policy_type,
        target_id=kw.get("target_id", "tool-1"),
        before_config=kw.get("before_config", {}),
        after_config=kw.get("after_config", {}),
        diff=kw.get("diff", {}),
        impact=kw.get("impact", {}),
        status=status,
        applied_by=None,
        applied_at=None,
        rolled_back_at=None,
        rollback_reason="",
    )


class TestCreateDraft:
    def test_create_draft_persists_board_and_payload(self):
        svc, session = _service()
        draft = svc.create_draft(
            policy_type="builtin_tool",
            target_id="tool-1",
            before_config={"enabled": True},
            after_config={"enabled": False},
            diff={"changes": [{"field": "enabled", "before": True, "after": False}]},
            impact={"scope": "builtin_tool"},
            created_by=uuid4(),
            agent_id=uuid4(),
        )
        assert draft.policy_type == "builtin_tool"
        assert draft.target_id == "tool-1"
        assert draft.status == DraftStatus.PENDING.value
        assert draft.suggestion_id is None
        assert session.commits == 1

    def test_create_draft_records_agent_id_in_impact(self):
        """agent_id 必须留在草稿里，否则「哪个 Agent 提的建议」无法追溯。

        policy_change_draft 无 agent_id 列，因此写入 impact（JSONB）而非改表
        ——避免为单一用途扩列，且 impact 本就是"变更影响面"的载体。
        """
        agent_id = uuid4()
        svc, _ = _service()
        draft = svc.create_draft(
            policy_type="builtin_tool",
            target_id="tool-1",
            before_config={},
            after_config={},
            diff={},
            impact={},
            created_by=uuid4(),
            agent_id=agent_id,
        )
        assert draft.impact.get("agent_id") == str(agent_id)

    def test_create_draft_does_not_mutate_caller_impact_dict(self):
        """不得原地修改调用方传入的 impact（否则调用方的对象被意外污染）。"""
        original = {"scope": "x"}
        svc, _ = _service()
        draft = svc.create_draft(
            policy_type="builtin_tool",
            target_id="t",
            before_config={},
            after_config={},
            diff={},
            impact=original,
            agent_id=uuid4(),
        )
        assert original == {"scope": "x"}
        assert "agent_id" in draft.impact


class TestApplyDraft:
    def test_apply_rejects_non_pending_draft(self):
        """已应用/已回滚的草稿不能重复应用（状态机边界）。"""
        draft = _draft(status="applied")
        svc, _ = _service([draft])
        with pytest.raises(ValueError, match="仅 pending 状态可应用"):
            svc.apply_draft(draft_id=draft.id, applied_by=uuid4())

    def test_apply_marks_applied_with_operator(self):
        draft = _draft(status="pending")
        svc, session = _service([draft])
        operator = uuid4()
        svc.apply_draft(draft_id=draft.id, applied_by=operator)
        assert draft.status == DraftStatus.APPLIED.value
        assert draft.applied_by == operator
        assert draft.applied_at is not None
        assert session.commits >= 1

    def test_apply_raises_not_found_for_unknown_draft(self):
        svc, _ = _service([])
        with pytest.raises(NotFoundException):
            svc.apply_draft(draft_id=uuid4(), applied_by=uuid4())


class TestRollbackDraft:
    def test_rollback_rejects_non_applied_draft(self):
        draft = _draft(status="pending")
        svc, _ = _service([draft])
        with pytest.raises(ValueError, match="仅 applied 状态可回滚"):
            svc.rollback_draft(draft_id=draft.id, rolled_back_by=uuid4(), reason="x")

    def test_rollback_marks_rolled_back_with_reason(self):
        draft = _draft(status="applied")
        svc, _ = _service([draft])
        svc.rollback_draft(draft_id=draft.id, rolled_back_by=uuid4(), reason="误操作")
        assert draft.status == DraftStatus.ROLLED_BACK.value
        assert draft.rollback_reason == "误操作"
        assert draft.rolled_back_at is not None


class TestListDrafts:
    def test_list_filters_by_status_and_board(self):
        d1 = _draft(status="pending", policy_type="builtin_tool")
        d2 = _draft(status="applied", policy_type="builtin_tool")
        d3 = _draft(status="pending", policy_type="prompt_template")
        svc, _ = _service([d1, d2, d3])
        rows = svc.list_drafts(status="pending", policy_type="builtin_tool")
        assert rows == [d1]

    def test_list_without_board_filter_returns_all_boards(self):
        """跨板块列出待应用草稿（「单一审核入口」的前提）。"""
        d1 = _draft(status="pending", policy_type="builtin_tool")
        d2 = _draft(status="pending", policy_type="prompt_template")
        svc, _ = _service([d1, d2])
        rows = svc.list_drafts(status="pending")
        assert {r.policy_type for r in rows} == {"builtin_tool", "prompt_template"}

    def test_list_without_status_returns_all(self):
        d1 = _draft(status="pending")
        d2 = _draft(status="applied")
        svc, _ = _service([d1, d2])
        assert len(svc.list_drafts()) == 2
