"""定时任务时区回归测试：cron 按业务时区（Asia/Shanghai）解释，存储统一为 UTC naive。

历史 bug：compute_next_run_at 用 UTC 字面时间直接喂给 croniter（按容器本地时区解释），
导致"每天早上7点"被算成 UTC 07:00（= 北京 15:00），任务比预期晚 8 小时执行。
"""
from datetime import UTC, datetime

import pytest

from internal.service.schedule_task_service import ScheduleTaskService


@pytest.fixture()
def service():
    return ScheduleTaskService(db=None)


class TestComputeNextRunAtTimezone:
    def test_daily_7am_is_next_business_7am(self, service):
        """当前北京时间 13:42（UTC 05:42），"每天7点"的下一次应为次日北京 07:00 = 当日 UTC 23:00。"""
        base = datetime(2026, 8, 8, 5, 42, 0)  # UTC naive = 北京 13:42
        result = service.compute_next_run_at("0 0 7 * * *", base)
        assert result == datetime(2026, 8, 8, 23, 0, 0)

    def test_base_before_7am_keeps_same_day_business_7am(self, service):
        """北京时间 06:00（UTC 前日 22:00），下一次应为当日北京 07:00 = UTC 前日 23:00。"""
        base = datetime(2026, 8, 7, 22, 0, 0)  # UTC naive = 北京 08-08 06:00
        result = service.compute_next_run_at("0 0 7 * * *", base)
        assert result == datetime(2026, 8, 7, 23, 0, 0)

    def test_base_exactly_at_business_7am_rolls_to_next_day(self, service):
        """北京时间恰好 07:00（UTC 前日 23:00），get_next 排除相等时刻，应推进到次日。"""
        base = datetime(2026, 8, 7, 23, 0, 0)  # UTC naive = 北京 08-08 07:00
        result = service.compute_next_run_at("0 0 7 * * *", base)
        assert result == datetime(2026, 8, 8, 23, 0, 0)

    def test_advance_after_run_keeps_24h_rhythm(self, service):
        """执行完成后基于 last_run_at（UTC naive）推进，保持每天北京 07:00 的节奏。"""
        last_run = datetime(2026, 8, 8, 23, 0, 0)  # = 北京 08-09 07:00 执行完成
        result = service.compute_next_run_at("0 0 7 * * *", last_run)
        assert result == datetime(2026, 8, 9, 23, 0, 0)

    def test_every_minute_alignment(self, service):
        """每分钟任务任意 base 都应给出下一个整分钟的 UTC naive 时间。"""
        base = datetime(2026, 8, 8, 12, 30, 15)
        result = service.compute_next_run_at("0 * * * * *", base)
        assert result == datetime(2026, 8, 8, 12, 31, 0)

    def test_aware_input_is_normalized(self, service):
        """若传入带时区的 datetime，也应统一转回 UTC naive。"""
        base = datetime(2026, 8, 8, 5, 42, 0, tzinfo=UTC)
        result = service.compute_next_run_at("0 0 7 * * *", base)
        assert result == datetime(2026, 8, 8, 23, 0, 0)


class TestIntervalNextRun:
    """间隔触发计算：业务时区（北京）解释、存储 UTC naive，固定时刻对齐。"""

    def test_month_every_2_on_5th(self, service):
        """北京 8-08 13:42 创建「每 2 个月 5 号」→ 10-05（北京）= UTC 10-04 16:00。"""
        base = datetime(2026, 8, 8, 5, 42, 0)
        result = service.compute_interval_next_run_at({"unit": "month", "every": 2, "day_of_month": 5}, base)
        assert result == datetime(2026, 10, 4, 16, 0, 0)

    def test_month_same_month_before_day_passes(self, service):
        """北京 8-03 创建「每 1 个月 5 号」→ 当月 8-05（北京）= UTC 8-04 16:00。"""
        base = datetime(2026, 8, 2, 16, 0, 0)
        result = service.compute_interval_next_run_at({"unit": "month", "every": 1, "day_of_month": 5}, base)
        assert result == datetime(2026, 8, 4, 16, 0, 0)

    def test_month_day_31_clamps_to_month_end(self, service):
        """「每 1 个月 31 号」在 2 月钳制到月末；北京 2-01 创建 → 2-28（北京）= UTC 2-27 16:00。"""
        base = datetime(2026, 1, 31, 16, 0, 0)  # 北京 2-01 00:00
        result = service.compute_interval_next_run_at({"unit": "month", "every": 1, "day_of_month": 31}, base)
        assert result == datetime(2026, 2, 27, 16, 0, 0)

    def test_week_every_2_wednesday(self, service):
        """北京 8-08（周六）创建「每 2 周周三」→ 8-19 周三（北京）= UTC 8-18 16:00。"""
        base = datetime(2026, 8, 8, 5, 42, 0)
        result = service.compute_interval_next_run_at({"unit": "week", "every": 2, "day_of_week": 3}, base)
        assert result == datetime(2026, 8, 18, 16, 0, 0)

    def test_week_same_week_before_weekday_passes(self, service):
        """北京 8-04（周二）创建「每 1 周周三」→ 本周三 8-05（北京）。"""
        base = datetime(2026, 8, 3, 16, 0, 0)  # 北京 8-04 00:00
        result = service.compute_interval_next_run_at({"unit": "week", "every": 1, "day_of_week": 3}, base)
        assert result == datetime(2026, 8, 4, 16, 0, 0)

    def test_day_every_3_at_2am(self, service):
        """北京 8-08 13:42 创建「每 3 天 02:00」→ 8-11 02:00（北京）= UTC 8-10 18:00。"""
        base = datetime(2026, 8, 8, 5, 42, 0)
        result = service.compute_interval_next_run_at({"unit": "day", "every": 3, "hours": 2}, base)
        assert result == datetime(2026, 8, 10, 18, 0, 0)

    def test_day_same_day_before_hour_passes(self, service):
        """北京 8-08 01:00 创建「每 1 天 02:00」→ 当天 8-08 02:00（北京）。"""
        base = datetime(2026, 8, 7, 17, 0, 0)  # 北京 8-08 01:00
        result = service.compute_interval_next_run_at({"unit": "day", "every": 1, "hours": 2}, base)
        assert result == datetime(2026, 8, 7, 18, 0, 0)

    def test_hour_every_2h30m_from_midnight(self, service):
        """北京 13:42 创建「每 2 小时 30 分」→ 15:00（北京，0 点起 150 分钟周期）= UTC 07:00。"""
        base = datetime(2026, 8, 8, 5, 42, 0)
        result = service.compute_interval_next_run_at({"unit": "hour", "every": 2, "minutes": 30}, base)
        assert result == datetime(2026, 8, 8, 7, 0, 0)

    def test_hour_advance_keeps_fixed_slots(self, service):
        """推进：15:00（北京）完成后 → 17:30（北京）= UTC 09:30。"""
        base = datetime(2026, 8, 8, 7, 0, 0)
        result = service.compute_interval_next_run_at({"unit": "hour", "every": 2, "minutes": 30}, base)
        assert result == datetime(2026, 8, 8, 9, 30, 0)

    def test_hour_late_night_rolls_to_next_day(self, service):
        """北京 22:45「每 2 小时 30 分」当天周期结束 → 次日 00:00（北京）。"""
        base = datetime(2026, 8, 8, 14, 45, 0)
        result = service.compute_interval_next_run_at({"unit": "hour", "every": 2, "minutes": 30}, base)
        assert result == datetime(2026, 8, 8, 16, 0, 0)

    def test_minute_every_15_from_midnight(self, service):
        """北京 13:42「每 15 分钟」→ 13:45（北京）= UTC 05:45。"""
        base = datetime(2026, 8, 8, 5, 42, 0)
        result = service.compute_interval_next_run_at({"unit": "minute", "every": 15}, base)
        assert result == datetime(2026, 8, 8, 5, 45, 0)

    def test_validate_rejects_bad_config(self, service):
        import pytest

        from internal.exception import FailException

        with pytest.raises(FailException):
            service.validate_interval_config({"unit": "year", "every": 1})
        with pytest.raises(FailException):
            service.validate_interval_config({"unit": "month", "every": 0, "day_of_month": 5})
        with pytest.raises(FailException):
            service.validate_interval_config({"unit": "month", "every": 1, "day_of_month": 32})
        with pytest.raises(FailException):
            service.validate_interval_config({"unit": "hour", "every": 24, "minutes": 0})
        with pytest.raises(FailException):
            service.validate_interval_config(None)

    def test_describe_interval(self, service):
        assert service.describe_interval({"unit": "month", "every": 2, "day_of_month": 5}) == "每 2 个月 5 号 00:00"
        assert service.describe_interval({"unit": "week", "every": 1, "day_of_week": 1}) == "每 1 周 周一 00:00"
        assert service.describe_interval({"unit": "day", "every": 3, "hours": 2}) == "每 3 天 02:00"
        assert service.describe_interval({"unit": "hour", "every": 2, "minutes": 30}) == "每 2 小时 30 分"
        assert service.describe_interval({"unit": "minute", "every": 15}) == "每 15 分钟"
