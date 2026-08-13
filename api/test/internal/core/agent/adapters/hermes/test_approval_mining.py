from datetime import UTC, datetime

from internal.core.agent.adapters.hermes import (
    ConfirmationRecord,
    as_serializable,
    mine_approval_history,
)


def _record(tool_name, status, tool_input=None, summary="", reason=""):
    return ConfirmationRecord(
        tool_name=tool_name,
        status=status,
        tool_input=tool_input or {},
        execution_summary=summary,
        reason=reason,
        created_at=datetime.now(UTC),
    )


def test_proposes_frequently_confirmed_safe_tool():
    records = [
        _record("run_os_task", "confirmed", {"task": "清理临时文件"}, "扫描完成"),
        _record("run_os_task", "confirmed", {"task": "清理回收站"}, "扫描完成"),
        _record("run_os_task", "confirmed", {"task": "清理缓存"}, "扫描完成"),
    ]
    result = mine_approval_history(records)
    assert len(result.proposals) == 1
    assert result.proposals[0].tool_name == "run_os_task"
    assert result.proposals[0].approved_count == 3
    assert result.stats["total_confirmed"] == 3


def test_never_proposes_destructive_tool():
    records = [
        _record("delete_resource", "confirmed", {"id": "x"}),
        _record("delete_resource", "confirmed", {"id": "y"}),
        _record("delete_resource", "confirmed", {"id": "z"}),
    ]
    result = mine_approval_history(records)
    assert result.proposals == []


def test_requires_minimum_confirmation_count():
    records = [_record("send_email", "confirmed", {"to": "a@b.c"})]
    result = mine_approval_history(records)
    assert result.proposals == []


def test_circuit_breaker_on_consecutive_denials():
    records = [
        _record("run_os_task", "cancelled", {"task": "删除全部文件"}, "用户拒绝"),
        _record("run_os_task", "cancelled", {"task": "删除全部文件"}, "用户拒绝"),
        _record("run_os_task", "cancelled", {"task": "删除全部文件"}, "用户拒绝"),
    ]
    result = mine_approval_history(records)
    assert len(result.circuit_breakers) == 1
    breaker = result.circuit_breakers[0]
    assert breaker.tool_name == "run_os_task"
    assert breaker.denial_count == 3
    assert breaker.action == "block_loop"


def test_signature_ignores_approval_token():
    first = _record("run_os_task", "cancelled", {"task": "t", "approval_token": "a"})
    second = _record("run_os_task", "cancelled", {"task": "t", "approval_token": "b"})
    result = mine_approval_history([first, second, second])
    assert len(result.circuit_breakers) == 1


def test_different_signatures_do_not_share_breaker():
    records = [
        _record("run_os_task", "cancelled", {"task": "删除 A"}),
        _record("run_os_task", "cancelled", {"task": "删除 B"}),
        _record("run_os_task", "cancelled", {"task": "删除 C"}),
    ]
    result = mine_approval_history(records)
    assert result.circuit_breakers == []


def test_serializable_shape():
    result = mine_approval_history(
        [
            _record("run_os_task", "confirmed", {"task": "t"}, "完成"),
            _record("run_os_task", "confirmed", {"task": "t"}, "完成"),
            _record("run_os_task", "confirmed", {"task": "t"}, "完成"),
        ]
    )
    payload = as_serializable(result)
    assert payload["proposals"][0]["tool_name"] == "run_os_task"
    assert payload["stats"]["proposal_count"] == 1
