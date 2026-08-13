from types import SimpleNamespace
from uuid import uuid4

from internal.service.approval_insights_service import ApprovalInsightsService


class _QueryStub:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows


class _SessionStub:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_args, **_kwargs):
        return _QueryStub(self._rows)


def _row(tool_name, status, tool_input=None, summary="", reason=""):
    return SimpleNamespace(
        tool_name=tool_name,
        status=status,
        tool_input=tool_input or {},
        execution_summary=summary,
        reason=reason,
        created_at=None,
        owner_account_id=uuid4(),
    )


def _service(rows):
    return ApprovalInsightsService(db=SimpleNamespace(session=_SessionStub(rows)))


def test_analyze_recent_builds_proposals():
    service = _service(
        [
            _row("run_os_task", "confirmed", {"task": "清理临时文件"}, "扫描完成"),
            _row("run_os_task", "confirmed", {"task": "清理回收站"}, "扫描完成"),
            _row("run_os_task", "confirmed", {"task": "清理缓存"}, "扫描完成"),
        ]
    )

    result = service.analyze_recent(days=90)

    assert result["stats"]["total_confirmed"] == 3
    assert result["proposals"][0]["tool_name"] == "run_os_task"
    assert result["proposals"][0]["approved_count"] == 3


def test_analyze_recent_detects_denial_loop():
    service = _service(
        [
            _row("run_os_task", "cancelled", {"task": "删除全部文件"}, "", "用户拒绝"),
            _row("run_os_task", "cancelled", {"task": "删除全部文件"}, "", "用户拒绝"),
            _row("run_os_task", "cancelled", {"task": "删除全部文件"}, "", "用户拒绝"),
        ]
    )

    result = service.analyze_recent(days=30)

    assert result["circuit_breakers"][0]["tool_name"] == "run_os_task"
    assert result["circuit_breakers"][0]["denial_count"] == 3


def test_analyze_recent_never_proposes_destructive_tool():
    service = _service(
        [
            _row("delete_resource", "confirmed", {"id": "1"}),
            _row("delete_resource", "confirmed", {"id": "2"}),
            _row("delete_resource", "confirmed", {"id": "3"}),
        ]
    )

    result = service.analyze_recent(days=90)

    assert result["proposals"] == []
