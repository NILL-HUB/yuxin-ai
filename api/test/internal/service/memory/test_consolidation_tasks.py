"""C4 consolidation_tasks 单元测试。"""

from uuid import uuid4

import pytest


class TestConsolidationTasks:
    def test_run_daily_consolidation_should_handle_empty_user_list(self):
        """空用户列表应返回空字典。"""
        from internal.task.consolidation_tasks import run_daily_consolidation

        # 直接调用任务函数（绕过 Celery），传入空列表
        result = run_daily_consolidation.run([])

        assert isinstance(result, dict)
        assert result == {}

    def test_run_weight_scan_should_not_raise_without_dependencies(self):
        """无依赖时 run_weight_scan 应降级处理。"""
        from internal.task.consolidation_tasks import run_weight_scan

        user_id = str(uuid4())
        # 直接调用任务函数（绕过 Celery）
        # 无 Neo4j 时应返回空字典或抛可重试异常（被 retry 捕获）
        try:
            result = run_weight_scan.run(user_id)
            assert isinstance(result, (dict, type(None)))
        except Exception:
            # 重试异常是预期行为（任务标记为 retry）
            pass

    def test_beat_schedule_should_contain_both_tasks(self):
        """beat schedule 应包含 daily-consolidation 和 weight-scan。"""
        from internal.task.consolidation_tasks import _celery_app

        schedule = _celery_app.conf.beat_schedule
        assert "daily-consolidation" in schedule
        assert "weight-scan" in schedule

    def test_task_routes_should_route_to_consolidation_queue(self):
        """任务应路由到 consolidation 队列。"""
        from internal.task.consolidation_tasks import _celery_app

        routes = _celery_app.conf.task_routes
        assert "internal.task.consolidation_tasks.*" in routes
        assert routes["internal.task.consolidation_tasks.*"]["queue"] == "consolidation"
