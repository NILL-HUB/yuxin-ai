"""定时任务结果 → 系统推送 扇出接线测试（唯一生产调用方）。"""

from types import SimpleNamespace
from uuid import uuid4

from internal.service import schedule_execution_service as ses
from internal.service.schedule_execution_service import ScheduleExecutionService


class _FakeGateway:
    def __init__(self):
        self.calls = []

    def notify_account(self, account_id, *, title, body, data=None):
        self.calls.append({"account_id": str(account_id), "title": title, "body": body, "data": data or {}})
        return {"ok": True}


def test_push_notification_fans_out_to_system_push(monkeypatch):
    gateway = _FakeGateway()

    class _Injector:
        def get(self, cls):
            return gateway

    monkeypatch.setattr("app.http.module.injector", _Injector())

    ws_calls = []
    monkeypatch.setattr(
        "internal.lib.websocket_manager.ws_manager.emit_notification_to_user",
        lambda user_id, payload, event="": ws_calls.append({"user_id": user_id, "event": event, "payload": payload}),
    )

    task = SimpleNamespace(id=uuid4(), account_id=uuid4(), name="每日报表")
    run = SimpleNamespace(
        id=uuid4(),
        status=ses.ScheduleRunStatus.SUCCESS.value,
        result_summary="已完成",
        error_message="",
    )

    service = ScheduleExecutionService.__new__(ScheduleExecutionService)
    service._push_notification(task, run)

    assert len(ws_calls) == 1
    assert ws_calls[0]["event"] == "schedule_task_result"

    assert len(gateway.calls) == 1
    call = gateway.calls[0]
    assert call["account_id"] == str(task.account_id)
    assert "每日报表" in call["title"]
    assert "执行成功" in call["title"]
    assert call["body"] == "已完成"
    assert call["data"]["task_id"] == str(task.id)


def test_push_notification_swallows_push_errors(monkeypatch):
    class _BoomInjector:
        def get(self, cls):
            raise RuntimeError("push down")

    monkeypatch.setattr("app.http.module.injector", _BoomInjector())
    monkeypatch.setattr(
        "internal.lib.websocket_manager.ws_manager.emit_notification_to_user",
        lambda user_id, payload, event="": None,
    )

    task = SimpleNamespace(id=uuid4(), account_id=uuid4(), name="任务")
    run = SimpleNamespace(
        id=uuid4(), status=ses.ScheduleRunStatus.FAILED.value, result_summary="", error_message="boom"
    )

    service = ScheduleExecutionService.__new__(ScheduleExecutionService)
    service._push_notification(task, run)  # 不应抛出
