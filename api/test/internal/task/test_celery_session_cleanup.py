"""AppContextTask 连接泄漏防护测试。

验证：
1. after_return 在任务结束后（无论成功/失败）调用 db.session.remove()，
   归还线程级 scoped_session 占用的连接（防 idle in transaction 累积）。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _build_task():
    """构造一个不依赖 celery 全链路的 AppContextTask 实例。"""
    from app.http.celery_app import AppContextTask

    # 直接实例化（celery Task 需要 app 绑定，这里绕过 __init__ 仅测 after_return 逻辑）
    task = AppContextTask.__new__(AppContextTask)
    return task


class TestAppContextTaskSessionCleanup:
    def test_after_return_removes_db_session(self):
        """after_return 应调用 db.session.remove()。"""
        task = _build_task()
        remove = MagicMock()
        fake_db = MagicMock()
        fake_db.session.remove = remove

        with patch.dict(
            "sys.modules",
            {
                "internal.extension.database_extension": MagicMock(db=fake_db),
            },
        ):
            # 模拟任务结束（成功场景）
            task.after_return("SUCCESS", None, "task-1", (), {}, None)

        remove.assert_called_once()

    def test_after_return_swallows_remove_error(self):
        """after_return 中 remove 抛异常不应向外传播（不影响任务结果）。"""
        task = _build_task()

        class _FakeDb:
            @property
            def session(self):
                raise RuntimeError("session broken")

        fake_db = _FakeDb()
        with patch.dict(
            "sys.modules",
            {
                "internal.extension.database_extension": MagicMock(db=fake_db),
            },
        ):
            # 不应抛异常
            task.after_return("FAILURE", None, "task-2", (), {}, MagicMock())

    def test_after_return_handles_missing_remove(self):
        """db.session 无 remove 方法时静默跳过。"""
        task = _build_task()
        fake_db = MagicMock()
        fake_db.session = MagicMock(spec=[])  # 无 remove 属性

        with patch.dict(
            "sys.modules",
            {
                "internal.extension.database_extension": MagicMock(db=fake_db),
            },
        ):
            task.after_return("SUCCESS", None, "task-3", (), {}, None)
