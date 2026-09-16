"""单次任务（trigger_type=once）回归测试。

覆盖：
1. validate_once_run_at / describe_once：执行时刻校验与描述
2. compute_task_next_run 按 once 分发
3. create_task 支持 once（next_run_at=run_at，cron 置空）
4. advance_next_run：单次任务清空 next_run_at 且保持 enabled
5. is_once_task 判定
6. ScheduleExecutionService._archive_once_task 归档到回收站
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from internal.exception import FailException
from internal.service.schedule_task_service import ScheduleTaskService


@pytest.fixture()
def service():
    return ScheduleTaskService(db=None)


class TestValidateOnceRunAt:
    def test_accepts_future_timestamp(self, service):
        future = datetime.now(UTC).timestamp() + 3600
        result = service.validate_once_run_at(future)
        assert isinstance(result, datetime)
        assert result.tzinfo is None
        assert result > datetime.now(UTC).replace(tzinfo=None)

    def test_accepts_iso_string_with_offset(self, service):
        result = service.validate_once_run_at("2099-01-01T15:00:00+08:00")
        assert result == datetime(2099, 1, 1, 7, 0, 0)

    def test_accepts_naive_iso_as_utc(self, service):
        result = service.validate_once_run_at("2099-01-01T15:00:00")
        assert result == datetime(2099, 1, 1, 15, 0, 0)

    def test_rejects_past_time(self, service):
        past = datetime.now(UTC).timestamp() - 3600
        with pytest.raises(FailException):
            service.validate_once_run_at(past)

    def test_rejects_invalid_value(self, service):
        with pytest.raises(FailException):
            service.validate_once_run_at(None)
        with pytest.raises(FailException):
            service.validate_once_run_at("not-a-time")


class TestDescribeOnce:
    def test_describes_in_business_timezone(self, service):
        result = service.describe_once(datetime(2026, 9, 13, 7, 0, 0))
        assert result == "仅执行一次：2026-09-13 15:00"

    def test_invalid_returns_plain_label(self, service):
        assert service.describe_once(None) == "仅执行一次"


class TestComputeTaskNextRunOnce:
    def test_once_returns_run_at(self, service):
        run_at = datetime(2099, 1, 1, 7, 0, 0)
        assert service.compute_task_next_run("once", "", None, run_at=run_at) == run_at

    def test_cron_still_uses_cron(self, service):
        result = service.compute_task_next_run("cron", "0 0 7 * * *")
        assert isinstance(result, datetime)


class TestCreateTaskOnce:
    def test_create_once_sets_next_run_at_and_blanks_cron(self, monkeypatch):
        service = ScheduleTaskService.__new__(ScheduleTaskService)
        created = {}

        def fake_create(model, **kwargs):
            created.update(kwargs)
            return SimpleNamespace(**kwargs, id=uuid4())

        monkeypatch.setattr(service, "create", fake_create)
        monkeypatch.setattr(service, "_get_platform_account", lambda: SimpleNamespace(id=uuid4()))

        run_at = datetime(2099, 1, 1, 7, 0, 0)
        service.create_task(None, "整理文档", "把文档整理一遍", "", trigger_type="once", run_at=run_at)

        assert created["trigger_type"] == "once"
        assert created["next_run_at"] == run_at
        assert created["run_at"] == run_at
        assert created["cron_expression"] == ""
        assert created["interval_config"] == {}
        assert "仅执行一次" in created["cron_humanized"]

    def test_create_once_without_run_at_raises(self, monkeypatch):
        service = ScheduleTaskService.__new__(ScheduleTaskService)
        with pytest.raises(FailException):
            service.create_task(None, "整理文档", "把文档整理一遍", "", trigger_type="once")


class TestAdvanceNextRunOnce:
    def test_once_clears_next_run_and_keeps_enabled(self, monkeypatch):
        service = ScheduleTaskService.__new__(ScheduleTaskService)
        task = SimpleNamespace(id=uuid4(), trigger_type="once", enabled=True, next_run_at=datetime.now(UTC).replace(tzinfo=None))
        updates = {}

        def fake_update(model, **kwargs):
            updates.update(kwargs)
            return model

        monkeypatch.setattr(service, "update", fake_update)
        service.advance_next_run(task)

        assert updates == {"next_run_at": None}
        assert "enabled" not in updates

    def test_cron_advances_next_run(self, monkeypatch):
        service = ScheduleTaskService.__new__(ScheduleTaskService)
        task = SimpleNamespace(
            id=uuid4(),
            trigger_type="cron",
            cron_expression="0 0 7 * * *",
            interval_config={},
            last_run_at=None,
        )
        updates = {}
        monkeypatch.setattr(service, "update", lambda model, **kw: updates.update(kw) or model)
        service.advance_next_run(task)
        assert isinstance(updates["next_run_at"], datetime)


class TestIsOnceTask:
    def test_detects_once(self, service):
        assert service.is_once_task(SimpleNamespace(trigger_type="once")) is True

    def test_other_types_are_not_once(self, service):
        assert service.is_once_task(SimpleNamespace(trigger_type="cron")) is False
        assert service.is_once_task(SimpleNamespace(trigger_type=None)) is False


class TestArchiveOnceTask:
    def test_non_once_task_is_skipped(self, monkeypatch):
        from internal.service.schedule_execution_service import ScheduleExecutionService

        service = ScheduleExecutionService.__new__(ScheduleExecutionService)
        called = []
        monkeypatch.setattr(
            "internal.service.recycle_bin_service.RecycleBinService",
            lambda: SimpleNamespace(delete_resource=lambda **kw: called.append(kw)),
        )
        service._archive_once_task(SimpleNamespace(id=uuid4(), trigger_type="cron", owner_type="user"))
        assert called == []

    def test_once_task_is_archived_as_user(self, monkeypatch):
        from internal.service.schedule_execution_service import ScheduleExecutionService

        service = ScheduleExecutionService.__new__(ScheduleExecutionService)
        task_id = uuid4()
        account_id = uuid4()
        called = []
        monkeypatch.setattr(
            "internal.service.recycle_bin_service.RecycleBinService",
            lambda: SimpleNamespace(delete_resource=lambda **kw: called.append(kw) or True),
        )
        service._archive_once_task(
            SimpleNamespace(id=task_id, trigger_type="once", owner_type="user", account_id=account_id, name="整理文档")
        )
        assert len(called) == 1
        assert called[0]["resource_type"] == "schedule_task"
        assert called[0]["resource_id"] == task_id
        assert called[0]["deleted_by_type"] == "user"
        assert called[0]["deleted_by"] == str(account_id)
        # 未显式传 retention_days → 跟随回收站系统默认（30 天）
        assert called[0].get("retention_days") is None

    def test_admin_once_task_is_archived_as_admin(self, monkeypatch):
        from internal.service.schedule_execution_service import ScheduleExecutionService

        service = ScheduleExecutionService.__new__(ScheduleExecutionService)
        called = []
        monkeypatch.setattr(
            "internal.service.recycle_bin_service.RecycleBinService",
            lambda: SimpleNamespace(delete_resource=lambda **kw: called.append(kw) or True),
        )
        service._archive_once_task(
            SimpleNamespace(id=uuid4(), trigger_type="once", owner_type="admin", account_id=uuid4(), name="平台任务")
        )
        assert called[0]["deleted_by_type"] == "admin"

    def test_archive_failure_does_not_raise(self, monkeypatch):
        from internal.service.schedule_execution_service import ScheduleExecutionService

        service = ScheduleExecutionService.__new__(ScheduleExecutionService)

        def boom(**_kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "internal.service.recycle_bin_service.RecycleBinService",
            lambda: SimpleNamespace(delete_resource=boom),
        )
        # 归档失败必须被吞掉，不能影响任务主流程
        service._archive_once_task(
            SimpleNamespace(id=uuid4(), trigger_type="once", owner_type="user", account_id=uuid4(), name="x")
        )
