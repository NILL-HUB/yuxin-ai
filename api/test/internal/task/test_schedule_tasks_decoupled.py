"""定时任务扫描/执行解耦 + 每用户并发上限测试。

覆盖本次「长任务治理」改动：
1. run_scheduled_tasks 只扫描+投递，不同步执行（不阻塞每分钟 tick）
2. schedule_task_execute 独立执行单个任务
3. ScheduleExecutionService 每用户并发上限（而非 celery 全局计数）
4. execute_task 不再有 90s 硬超时（直接同步迭代编排直至自然完成）
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


def _task(task_id=None, *, account_id=None, enabled=True):
    task_id = task_id or uuid4()
    return SimpleNamespace(
        id=task_id,
        account_id=account_id or uuid4(),
        enabled=enabled,
        name="测试任务",
        prompt="hi",
        task_type="assistant_chat",
    )


class _QueryStub:
    def __init__(self, one_or_none_result=None, count_result=0):
        self._one = one_or_none_result
        self._count = count_result

    def filter(self, *_a, **_k):
        return self

    def count(self):
        return self._count

    def one_or_none(self):
        return self._one


class TestRunScheduledTasksDecoupled:
    def test_run_scheduled_tasks_dispatches_each_due_task(self, monkeypatch):
        """扫描后对每个到期任务 advance_next_run + 投递，不同步执行。"""
        from internal.task import schedule_tasks

        t1, t2 = _task(), _task()
        advanced = []
        dispatched = []

        svc = SimpleNamespace(
            scan_due_tasks=lambda: [t1, t2],
            advance_next_run=lambda task: advanced.append(task.id),
        )
        monkeypatch.setattr(
            "internal.service.schedule_task_service.ScheduleTaskService",
            lambda _db: svc,
        )
        monkeypatch.setattr(
            schedule_tasks.schedule_task_execute,
            "delay",
            lambda task_id: dispatched.append(task_id),
        )

        result = schedule_tasks.run_scheduled_tasks.run()

        assert advanced == [t1.id, t2.id]
        assert dispatched == [str(t1.id), str(t2.id)]
        assert result == {"scanned": 2, "dispatched": 2}

    def test_run_scheduled_tasks_no_due_tasks(self, monkeypatch):
        from internal.task import schedule_tasks

        svc = SimpleNamespace(scan_due_tasks=lambda: [])
        monkeypatch.setattr(
            "internal.service.schedule_task_service.ScheduleTaskService",
            lambda _db: svc,
        )

        result = schedule_tasks.run_scheduled_tasks.run()

        assert result == {"scanned": 0}

    def test_run_scheduled_tasks_dispatches_and_advances_only_on_success(self, monkeypatch):
        """advance 失败的任务不投递（避免重复），且不影响其他任务。"""
        from internal.task import schedule_tasks

        t_ok, t_bad = _task(), _task()
        advanced, dispatched = [], []

        def _advance(task):
            if task.id == t_bad.id:
                raise RuntimeError("advance 失败")
            advanced.append(task.id)

        svc = SimpleNamespace(
            scan_due_tasks=lambda: [t_ok, t_bad],
            advance_next_run=_advance,
        )
        monkeypatch.setattr(
            "internal.service.schedule_task_service.ScheduleTaskService",
            lambda _db: svc,
        )
        monkeypatch.setattr(
            schedule_tasks.schedule_task_execute,
            "delay",
            lambda task_id: dispatched.append(task_id),
        )

        result = schedule_tasks.run_scheduled_tasks.run()

        assert advanced == [t_ok.id]
        assert dispatched == [str(t_ok.id)]
        assert result["scanned"] == 2


class TestScheduleTaskExecute:
    def test_execute_task_delegates(self, monkeypatch):
        """schedule_task_execute 应查任务并委托 execution.execute_task。"""
        from internal.task import schedule_tasks

        task = _task()
        executed = []
        execution = SimpleNamespace(
            execute_task=lambda t: executed.append(t.id),
        )
        db = SimpleNamespace(
            session=SimpleNamespace(
                query=lambda *_a: SimpleNamespace(
                    filter=lambda *_f, **_k: SimpleNamespace(one_or_none=lambda: task)
                )
            )
        )
        monkeypatch.setattr("app.http.module.injector", SimpleNamespace(get=lambda _cls: execution))
        monkeypatch.setattr("internal.extension.database_extension.db", db)

        result = schedule_tasks.schedule_task_execute.run(str(task.id))

        assert executed == [task.id]
        assert result == {"executed": True}

    def test_execute_task_skips_missing(self, monkeypatch):
        from internal.task import schedule_tasks

        db = SimpleNamespace(
            session=SimpleNamespace(
                query=lambda *_a: SimpleNamespace(
                    filter=lambda *_f, **_k: SimpleNamespace(one_or_none=lambda: None)
                )
            )
        )
        monkeypatch.setattr("app.http.module.injector", SimpleNamespace(get=lambda _cls: None))
        monkeypatch.setattr("internal.extension.database_extension.db", db)

        result = schedule_tasks.schedule_task_execute.run(str(uuid4()))

        assert result == {"executed": False, "reason": "not_found"}


class TestAccountConcurrencyLimit:
    def _service(self, db):
        from internal.service.schedule_execution_service import ScheduleExecutionService

        return ScheduleExecutionService.__new__(ScheduleExecutionService)

    def test_under_limit_passes(self, monkeypatch):
        from internal.service import schedule_execution_service as mod
        from internal.service.schedule_execution_service import ScheduleExecutionService

        db = SimpleNamespace(
            session=SimpleNamespace(
                query=lambda *_a: _QueryStub(count_result=2),
            )
        )
        service = ScheduleExecutionService.__new__(ScheduleExecutionService)
        service.db = db
        monkeypatch.setattr(mod, "_MAX_CONCURRENT_RUNS_PER_ACCOUNT", 5)

        assert service._account_under_concurrency_limit(uuid4()) is True

    def test_over_limit_blocks(self, monkeypatch):
        from internal.service import schedule_execution_service as mod
        from internal.service.schedule_execution_service import ScheduleExecutionService

        db = SimpleNamespace(
            session=SimpleNamespace(
                query=lambda *_a: _QueryStub(count_result=5),
            )
        )
        service = ScheduleExecutionService.__new__(ScheduleExecutionService)
        service.db = db
        monkeypatch.setattr(mod, "_MAX_CONCURRENT_RUNS_PER_ACCOUNT", 5)

        assert service._account_under_concurrency_limit(uuid4()) is False

    def test_zero_limit_disables_check(self, monkeypatch):
        from internal.service import schedule_execution_service as mod
        from internal.service.schedule_execution_service import ScheduleExecutionService

        service = ScheduleExecutionService.__new__(ScheduleExecutionService)
        monkeypatch.setattr(mod, "_MAX_CONCURRENT_RUNS_PER_ACCOUNT", 0)

        assert service._account_under_concurrency_limit(uuid4()) is True


class TestNoHardTimeout:
    def test_run_assistant_chat_has_no_deadline_or_abandon_thread(self):
        """90s 硬超时已移除：无 monotonic deadline 轮询，无「放弃 Agent 的弃置线程」。"""
        import inspect

        from internal.service import schedule_execution_service
        from internal.service.schedule_execution_service import ScheduleExecutionService

        source = inspect.getsource(schedule_execution_service)
        # 移除了 daemon 线程 + monotonic deadline 的轮询实现
        assert "time.monotonic" not in source
        assert "deadline" not in source
        # _run_assistant_chat 不实例化线程（锁续租线程在 execute_task 中，语义不同）
        chat_src = inspect.getsource(ScheduleExecutionService._run_assistant_chat)
        assert "threading.Thread(" not in chat_src

    def test_run_assistant_chat_sync_iterates_generator(self):
        """_run_assistant_chat 直接同步迭代 chat 生成器（无包裹线程）。"""
        import inspect

        from internal.service.schedule_execution_service import ScheduleExecutionService

        src = inspect.getsource(ScheduleExecutionService._run_assistant_chat)
        # 直接 for 迭代 assistant_service.chat(...) 直至自然完成
        assert "for _event in assistant_service.chat(" in src
        # 无 threading.Thread 实例化（daemon 线程弃置机制已移除）
        assert "threading.Thread(" not in src
        assert "threading.Thread(" not in inspect.getsource(
            ScheduleExecutionService._run_bound_app
        )


class TestStaleRunCleanup:
    def test_cleanup_stale_runs_marks_zombie_as_failed(self, monkeypatch):
        """僵尸 running 记录（超阈值）被标记 failed 并附原因。"""
        from datetime import UTC, datetime, timedelta

        from internal.task import schedule_tasks

        zombie = SimpleNamespace(
            id=uuid4(),
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=20),
        )
        updated_ids = []

        class _RecordingQuery:
            def filter(self, *_a, **_k):
                return self

            def limit(self, _n):
                return self

            def all(self):
                return [zombie]

            def update(self, values, **_kw):
                updated_ids.append(values["status"])
                return 1

        db = SimpleNamespace(
            session=SimpleNamespace(
                query=lambda _model: _RecordingQuery(),
                commit=lambda: None,
                rollback=lambda: None,
            )
        )
        monkeypatch.setattr("internal.extension.database_extension.db", db)

        result = schedule_tasks.cleanup_stale_runs.run()

        assert result["cleaned"] == 1
        assert updated_ids == ["failed"]

    def test_cleanup_stale_runs_no_zombie(self, monkeypatch):
        """无僵尸时不更新任何记录。"""
        from internal.task import schedule_tasks

        class _EmptyFilter:
            def filter(self, *_a, **_k):
                return self

            def limit(self, _n):
                return self

            def all(self):
                return []

        db = SimpleNamespace(
            session=SimpleNamespace(
                query=lambda *_a: _EmptyFilter(),
                commit=lambda: None,
                rollback=lambda: None,
            )
        )
        monkeypatch.setattr("internal.extension.database_extension.db", db)

        result = schedule_tasks.cleanup_stale_runs.run()

        assert result == {"cleaned": 0, "scanned": 0}


class TestLockTokenAndRenewal:
    def test_execute_task_release_lock_uses_token(self):
        """释放锁使用 Lua 脚本按 token 比对，不是无脑 delete。"""
        import inspect

        from internal.service.schedule_execution_service import ScheduleExecutionService

        src = inspect.getsource(ScheduleExecutionService._release_lock)
        assert "eval" in src
        assert "lock_token" in src
        assert 'redis.call("get", KEYS[1]) == ARGV[1]' in src

    def test_execute_task_lock_has_token_and_renewal(self):
        """执行锁带随机 token，且启动续租 watchdog 线程。"""
        import inspect

        from internal.service.schedule_execution_service import (
            _LOCK_RENEW_INTERVAL_SECONDS,
            ScheduleExecutionService,
        )

        src = inspect.getsource(ScheduleExecutionService.execute_task)
        assert "_uuid.uuid4()" in src
        assert "renew_stop = threading.Event()" in src
        assert "schedule-lock-renew" in src
        assert _LOCK_RENEW_INTERVAL_SECONDS > 0
