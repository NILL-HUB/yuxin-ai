"""外部数据源自动同步定时任务测试。"""

from internal.task import external_data_source_tasks as tasks


def test_task_is_registered_with_expected_name():
    assert (
        tasks.run_external_data_source_auto_sync.name
        == "internal.task.external_data_source_tasks.run_external_data_source_auto_sync"
    )


def test_task_delegates_to_service(monkeypatch):
    captured = {}

    class _Service:
        def auto_sync_all(self):
            captured["called"] = True
            return {"scanned": 2, "synced": 1, "failed": 1}

    monkeypatch.setattr(tasks, "_get_service", lambda: _Service())

    result = tasks.run_external_data_source_auto_sync()

    assert captured["called"] is True
    assert result == {"scanned": 2, "synced": 1, "failed": 1}
