import base64
import calendar
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter
from injector import inject
from sqlalchemy import desc

from internal.entity.schedule_task_entity import ScheduleTaskStatus
from internal.exception import FailException, NotFoundException
from internal.model import Account, ScheduleTask, ScheduleTaskRun
from internal.service.base_service import BaseService
from pkg.password import hash_password
from pkg.sqlalchemy import SQLAlchemy


logger = logging.getLogger(__name__)

# 平台级定时任务归属的系统账号（username='platform'，不可登录）
PLATFORM_ACCOUNT_USERNAME = "platform"

# 业务时区：cron 表达式按该时区解释（用户看到的本地时间），存储与比较统一使用 UTC
APP_DEFAULT_TIMEZONE = "Asia/Shanghai"

# 触发类型
TRIGGER_TYPE_CRON = "cron"
TRIGGER_TYPE_INTERVAL = "interval"
TRIGGER_TYPES = (TRIGGER_TYPE_CRON, TRIGGER_TYPE_INTERVAL)

# 间隔单位
INTERVAL_UNIT_MONTH = "month"
INTERVAL_UNIT_WEEK = "week"
INTERVAL_UNIT_DAY = "day"
INTERVAL_UNIT_HOUR = "hour"
INTERVAL_UNIT_MINUTE = "minute"
INTERVAL_UNITS = (INTERVAL_UNIT_MONTH, INTERVAL_UNIT_WEEK, INTERVAL_UNIT_DAY, INTERVAL_UNIT_HOUR, INTERVAL_UNIT_MINUTE)

WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _app_timezone() -> ZoneInfo:
    return ZoneInfo(os.getenv("APP_TIMEZONE", APP_DEFAULT_TIMEZONE))


def _to_business_aware(dt: datetime) -> datetime:
    """UTC naive（系统存储语义）→ 业务时区 aware，供 croniter 解释 cron 表达式。"""
    if dt.tzinfo is not None:
        return dt.astimezone(_app_timezone())
    return dt.replace(tzinfo=UTC).astimezone(_app_timezone())


@inject
@dataclass
class ScheduleTaskService(BaseService):
    """定时任务服务：CRUD + 秒级 cron 解析 + 到期扫描 + 执行投递"""

    db: SQLAlchemy

    PRESET_CRONS = {
        "every_second": "*/1 * * * * *",
        "every_minute": "0 * * * * *",
        "every_hour": "0 0 * * * *",
        "every_day": "0 0 0 * * *",
        "every_week": "0 0 0 * * 1",
        "every_month": "0 0 0 1 * *",
    }

    PRESET_LABELS = {
        "every_second": "每秒",
        "every_minute": "每分",
        "every_hour": "每小时",
        "every_day": "每天 00:00:00",
        "every_week": "每周一 00:00:00",
        "every_month": "每月1号 00:00:00",
    }

    def validate_cron(self, cron_expression: str) -> None:
        if not cron_expression:
            raise FailException("定时表达式不能为空")
        parts = cron_expression.strip().split()
        if len(parts) != 6:
            raise FailException("定时表达式需要 6 段：秒 分 时 日 月 周")
        try:
            croniter(cron_expression, _utcnow_naive(), second_at_beginning=True)
        except Exception as exc:
            raise FailException(f"定时表达式不合法：{exc}")

    def compute_next_run_at(self, cron_expression: str, base: datetime | None = None) -> datetime:
        # cron 按业务时区解释（如北京时间 07:00），存储统一转回 UTC naive 以便与 _utcnow_naive 一致比较
        base_business = _to_business_aware(base or _utcnow_naive())
        itr = croniter(cron_expression, base_business, second_at_beginning=True)
        next_business = itr.get_next(datetime)
        return next_business.astimezone(UTC).replace(tzinfo=None)

    # ---------------------------------------------------------------- interval 触发

    def validate_interval_config(self, interval_config: dict | None) -> dict:
        """校验间隔触发配置，返回规范化后的配置。"""
        if not interval_config:
            raise FailException("间隔触发需要配置间隔参数")
        config = dict(interval_config)
        unit = config.get("unit")
        if unit not in INTERVAL_UNITS:
            raise FailException("间隔单位不合法，可选：minute/hour/day/week/month")
        try:
            every = int(config.get("every", 0))
        except (TypeError, ValueError):
            raise FailException("间隔数量必须是正整数")
        if every < 1:
            raise FailException("间隔数量必须是正整数")
        config["every"] = every
        if unit == INTERVAL_UNIT_MONTH:
            day_of_month = int(config.get("day_of_month", 1))
            if not 1 <= day_of_month <= 31:
                raise FailException("每月触发日必须在 1~31 之间")
            config["day_of_month"] = day_of_month
        elif unit == INTERVAL_UNIT_WEEK:
            day_of_week = int(config.get("day_of_week", 1))
            if not 1 <= day_of_week <= 7:
                raise FailException("每周触发日必须是 1(周一)~7(周日)")
            config["day_of_week"] = day_of_week
        elif unit == INTERVAL_UNIT_DAY:
            hours = int(config.get("hours", 0))
            if not 0 <= hours <= 23:
                raise FailException("每日触发的时点必须在 0~23 之间")
            config["hours"] = hours
        elif unit == INTERVAL_UNIT_HOUR:
            if every > 23:
                raise FailException("按小时间隔时，间隔数量不能超过 23")
            minutes = int(config.get("minutes", 0))
            if not 0 <= minutes <= 59:
                raise FailException("每小时触发的分钟点必须在 0~59 之间")
            config["minutes"] = minutes
        elif unit == INTERVAL_UNIT_MINUTE:
            if every > 1440:
                raise FailException("按分钟间隔时，间隔数量不能超过 1440")
        return config

    def compute_interval_next_run_at(self, interval_config: dict, base: datetime | None = None) -> datetime:
        """计算 interval 触发的下一次执行时间（固定时刻对齐）。

        语义（业务时区）：
        - month: 从基准月（2000-01）起每隔 every 月，在每月 day_of_month 日 00:00 触发（月末钳制）
        - week:  从基准周起每隔 every 周，在周一 + day_of_week 触发 00:00
        - day:   从基准日起每隔 every 天，在 hours:00 触发
        - hour:  从基准时刻（2000-01-01 00:00）起每隔 every 小时 + minutes 分钟触发
        - minute: 从基准时刻起每隔 every 分钟触发
        """
        config = self.validate_interval_config(interval_config)
        unit = config["unit"]
        every = config["every"]
        base_business = _to_business_aware(base or _utcnow_naive())
        tz = _app_timezone()

        if unit == INTERVAL_UNIT_MONTH:
            day_of_month = config["day_of_month"]
            base_month_index = (base_business.year - 2000) * 12 + (base_business.month - 1)
            idx = base_month_index
            while True:
                year = 2000 + idx // 12
                month = idx % 12 + 1
                day = min(day_of_month, calendar.monthrange(year, month)[1])
                candidate = datetime(year, month, day, 0, 0, 0, tzinfo=tz)
                if candidate > base_business:
                    return candidate.astimezone(UTC).replace(tzinfo=None)
                idx += every
        elif unit == INTERVAL_UNIT_WEEK:
            day_of_week = config["day_of_week"]
            monday = base_business.date() - timedelta(days=base_business.weekday())
            candidate = datetime.combine(monday + timedelta(days=day_of_week - 1), time.min, tzinfo=tz)
            if candidate <= base_business:
                candidate += timedelta(weeks=every)
            return candidate.astimezone(UTC).replace(tzinfo=None)
        elif unit == INTERVAL_UNIT_DAY:
            hours = config["hours"]
            candidate = datetime.combine(base_business.date(), time(hours, 0, 0), tzinfo=tz)
            if candidate <= base_business:
                candidate += timedelta(days=every)
            return candidate.astimezone(UTC).replace(tzinfo=None)
        elif unit == INTERVAL_UNIT_HOUR:
            period_minutes = every * 60 + config["minutes"]
        else:
            period_minutes = every
        # 小时/分钟：以每天 00:00 为周期起点（cron 风格固定时刻），周期 = period_minutes 分钟
        day_start = datetime.combine(base_business.date(), time.min, tzinfo=tz)
        day_minutes = int((base_business - day_start).total_seconds()) // 60
        remainder = day_minutes % period_minutes
        if remainder == 0 and base_business.second == 0:
            next_day_minutes = day_minutes + period_minutes
        else:
            next_day_minutes = day_minutes + (period_minutes - remainder)
        if next_day_minutes >= 1440:
            # 当天周期已结束，次日 00:00 开启新周期
            return (day_start + timedelta(days=1)).astimezone(UTC).replace(tzinfo=None)
        return (day_start + timedelta(minutes=next_day_minutes)).astimezone(UTC).replace(tzinfo=None)

    def compute_task_next_run(self, trigger_type: str, cron_expression: str = "", interval_config: dict | None = None, base: datetime | None = None) -> datetime:
        """按任务触发类型分发计算下一次执行时间。"""
        if trigger_type == TRIGGER_TYPE_INTERVAL:
            return self.compute_interval_next_run_at(interval_config or {}, base)
        return self.compute_next_run_at(cron_expression, base)

    def describe_interval(self, interval_config: dict) -> str:
        """生成间隔触发的人类可读描述，如「每 2 个月 5 号 00:00」。"""
        config = self.validate_interval_config(interval_config)
        unit = config["unit"]
        every = config["every"]
        if unit == INTERVAL_UNIT_MONTH:
            return f"每 {every} 个月 {config['day_of_month']} 号 00:00"
        if unit == INTERVAL_UNIT_WEEK:
            return f"每 {every} 周 {WEEKDAY_LABELS[config['day_of_week'] - 1]} 00:00"
        if unit == INTERVAL_UNIT_DAY:
            return f"每 {every} 天 {config['hours']:02d}:00"
        if unit == INTERVAL_UNIT_HOUR:
            return f"每 {every} 小时 {config['minutes']:02d} 分"
        return f"每 {every} 分钟"

    def _describe_trigger(self, trigger_type: str, cron_expression: str, cron_humanized: str, interval_config: dict | None) -> str:
        """按触发类型生成展示用描述。"""
        if trigger_type == TRIGGER_TYPE_INTERVAL:
            return self.describe_interval(interval_config or {})
        return cron_humanized or cron_expression

    def _get_platform_account(self) -> Account:
        """获取平台系统账号（username='platform'）；不存在则创建一个随机密码不可登录的账号，返回其 id 归属方。"""
        account = (
            self.db.session.query(Account)
            .filter(Account.username == PLATFORM_ACCOUNT_USERNAME)
            .one_or_none()
        )
        if account is not None:
            return account
        random_password = secrets.token_urlsafe(24)
        salt = secrets.token_bytes(16)
        hashed = base64.b64encode(hash_password(random_password, salt)).decode()
        encoded_salt = base64.b64encode(salt).decode()
        return self.create(
            Account,
            username=PLATFORM_ACCOUNT_USERNAME,
            email="platform@local",
            name="平台系统",
            password=hashed,
            password_salt=encoded_salt,
        )

    def create_task(
        self,
        account: Account | None,
        name: str,
        prompt: str,
        cron_expression: str,
        description: str = "",
        cron_humanized: str = "",
        owner_type: str = "user",
        trigger_type: str = TRIGGER_TYPE_CRON,
        interval_config: dict | None = None,
    ) -> ScheduleTask:
        trigger_type = trigger_type or TRIGGER_TYPE_CRON
        if trigger_type not in TRIGGER_TYPES:
            raise FailException("触发类型不合法")
        normalized_interval = None
        if trigger_type == TRIGGER_TYPE_INTERVAL:
            normalized_interval = self.validate_interval_config(interval_config)
            cron_expression = cron_expression or ""
            humanized = self.describe_interval(normalized_interval)
        else:
            self.validate_cron(cron_expression)
            humanized = cron_humanized or self._guess_humanized(cron_expression)
        next_run_at = self.compute_task_next_run(trigger_type, cron_expression, normalized_interval)
        if owner_type == "admin":
            account_id = self._get_platform_account().id
        else:
            account_id = account.id if account is not None else None
        return self.create(
            ScheduleTask,
            account_id=account_id,
            owner_type=owner_type,
            name=name,
            prompt=prompt,
            trigger_type=trigger_type,
            cron_expression=cron_expression,
            cron_humanized=humanized,
            interval_config=normalized_interval or {},
            description=description or "",
            status=ScheduleTaskStatus.ACTIVE.value,
            next_run_at=next_run_at,
        )

    def _guess_humanized(self, cron_expression: str) -> str:
        for key, cron in self.PRESET_CRONS.items():
            if cron == cron_expression:
                return self.PRESET_LABELS[key]
        return cron_expression

    def update_task(
        self,
        task_id,
        account: Account | None,
        *,
        name=None,
        prompt=None,
        cron_expression=None,
        description=None,
        enabled=None,
        cron_humanized=None,
        owner_type: str = "user",
        trigger_type=None,
        interval_config=None,
    ) -> ScheduleTask:
        task = self.get_task(task_id, account, owner_type=owner_type)
        updates = {}
        if name is not None:
            updates["name"] = name
        if prompt is not None:
            updates["prompt"] = prompt
        if description is not None:
            updates["description"] = description
        if enabled is not None:
            updates["enabled"] = enabled
            updates["status"] = ScheduleTaskStatus.ACTIVE.value if enabled else ScheduleTaskStatus.PAUSED.value
        trigger_type_changed = trigger_type is not None and trigger_type != task.trigger_type
        final_trigger_type = trigger_type or task.trigger_type
        if final_trigger_type not in TRIGGER_TYPES:
            raise FailException("触发类型不合法")
        if trigger_type_changed:
            updates["trigger_type"] = final_trigger_type
        if cron_expression is not None or interval_config is not None or trigger_type_changed:
            if final_trigger_type == TRIGGER_TYPE_INTERVAL:
                normalized_interval = self.validate_interval_config(
                    interval_config if interval_config is not None else (task.interval_config or {})
                )
                new_cron = cron_expression or ("" if trigger_type_changed else task.cron_expression)
                humanized = self.describe_interval(normalized_interval)
                updates["cron_expression"] = new_cron
                updates["cron_humanized"] = humanized
                updates["interval_config"] = normalized_interval
                updates["next_run_at"] = self.compute_interval_next_run_at(normalized_interval)
            else:
                self.validate_cron(cron_expression if cron_expression is not None else task.cron_expression)
                updates["cron_expression"] = cron_expression if cron_expression is not None else task.cron_expression
                updates["cron_humanized"] = cron_humanized or self._guess_humanized(updates["cron_expression"])
                updates["interval_config"] = {}
                updates["next_run_at"] = self.compute_next_run_at(updates["cron_expression"])
        if not updates:
            return task
        return self.update(task, **updates)

    def get_task(self, task_id, account: Account | None, owner_type: str = "user") -> ScheduleTask:
        task = self.get(ScheduleTask, task_id)
        if task is None:
            raise NotFoundException("定时任务不存在")
        if owner_type == "admin":
            if task.owner_type != "admin":
                raise NotFoundException("定时任务不存在")
        elif account is None or str(task.account_id) != str(account.id):
            raise NotFoundException("定时任务不存在")
        return task

    def list_tasks(
        self, account: Account | None, page: int, page_size: int, owner_type: str = "user"
    ) -> tuple[list[ScheduleTask], int]:
        query = self.db.session.query(ScheduleTask)
        if owner_type == "admin":
            query = query.filter(ScheduleTask.owner_type == "admin")
        else:
            query = query.filter(ScheduleTask.owner_type == "user")
            if account is not None:
                query = query.filter(ScheduleTask.account_id == account.id)
        total = query.count()
        tasks = query.order_by(desc(ScheduleTask.created_at)).offset((page - 1) * page_size).limit(page_size).all()
        return tasks, total

    def delete_task(
        self,
        task_id,
        account: Account | None,
        owner_type: str = "user",
        *,
        retention_days: int | None = None,
        agent_id=None,
    ) -> None:
        task = self.get_task(task_id, account, owner_type=owner_type)
        # 进入平台回收站：快照任务 + 运行记录，物理删除原表，留存期内可在回收站恢复
        from internal.service.recycle_bin_service import RecycleBinService

        deleted = RecycleBinService().delete_resource(
            resource_type="schedule_task",
            resource_id=task.id,
            resource_key=str(task.id),
            resource_name=task.name,
            deleted_by=str(account.id) if account is not None else None,
            deleted_by_type="admin" if owner_type == "admin" else "user",
            retention_days=retention_days,
            agent_id=agent_id,
        )
        if not deleted:
            raise NotFoundException("定时任务不存在")

    def list_runs(
        self, task_id, account: Account | None, page: int, page_size: int, owner_type: str = "user"
    ) -> tuple[list[ScheduleTaskRun], int]:
        self.get_task(task_id, account, owner_type=owner_type)
        query = self.db.session.query(ScheduleTaskRun).filter(ScheduleTaskRun.schedule_task_id == task_id)
        total = query.count()
        runs = query.order_by(desc(ScheduleTaskRun.started_at)).offset((page - 1) * page_size).limit(page_size).all()
        return runs, total

    def scan_due_tasks(self) -> list[ScheduleTask]:
        """扫描到期任务（next_run_at <= now 且 enabled），按到期时间升序保证执行顺序稳定"""
        now = _utcnow_naive()
        return self.db.session.query(ScheduleTask).filter(
            ScheduleTask.enabled.is_(True),
            ScheduleTask.next_run_at.isnot(None),
            ScheduleTask.next_run_at <= now,
        ).order_by(ScheduleTask.next_run_at.asc()).limit(50).all()

    def advance_next_run(self, task: ScheduleTask) -> ScheduleTask:
        """系统扫描后推进 next_run_at（跳过 account 校验）"""
        next_run_at = self.compute_task_next_run(
            task.trigger_type, task.cron_expression, task.interval_config or {}, task.last_run_at or _utcnow_naive()
        )
        return self.update(task, next_run_at=next_run_at)
