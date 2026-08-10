"""独立 Celery 应用（不再依赖 Flask app_context，运行时容器惰性初始化）。

入口（entrypoint.sh）：``celery -A app.http.celery_app:celery_app``

设计要点：
- broker/backend/队列/路由/定时 全部来自 ``config.Config.CELERY``（env 驱动）。
- ``AppContextTask`` 不再包裹 Flask app_context，但首次执行时惰性初始化运行时容器，
  使 ``current_app.config / extensions / injector`` 在 Celery 任务中可用；
  任务内通过 ``db.sync_session`` / ``db.sync_session_factory`` 访问数据库
  （同步引擎 psycopg2，无 Web 框架依赖）。
- ``set_default()`` 使 ``shared_task`` 装饰器绑定到本实例。
"""
import logging

from celery import Celery, Task

logger = logging.getLogger(__name__)


def _ensure_runtime() -> None:
    """惰性初始化共享运行时容器，避免 Celery 任务访问 current_app 时断流。"""
    from internal.context import current_app, init_runtime

    if current_app.injector is not None:
        return

    from app.http.module import injector
    from config import Config
    from internal.server import Http

    container = Http("app.http.celery_app", conf=Config())
    container.injector = injector
    init_runtime(container)


class AppContextTask(Task):
    """任务基类：执行前确保运行时容器可用（保留类名兼容注册引用）。"""

    def __call__(self, *args, **kwargs):
        _ensure_runtime()
        return self.run(*args, **kwargs)


def _build_config() -> dict:
    from config import Config

    return Config().CELERY


TASK_MODULES = [
    "internal.task.app_task",
    "internal.task.email_task",
    "internal.task.schedule_tasks",
    "internal.task.consolidation_tasks",
    "internal.task.knowledge_indexing_tasks",
    "internal.task.recycle_bin_tasks",
]


celery_app = Celery("llmops", task_cls=AppContextTask, include=TASK_MODULES)
celery_app.conf.update(_build_config())

# 显式导入任务模块，保证 worker/beat 启动即完成任务注册
# （仅靠 include 参数在部分 celery 版本下惰性加载不可靠）
import internal.task.app_task as _task_app  # noqa: F401,E402
import internal.task.email_task as _task_email  # noqa: F401,E402
import internal.task.schedule_tasks as _task_schedule  # noqa: F401,E402
import internal.task.consolidation_tasks as _task_consolidation  # noqa: F401,E402
import internal.task.knowledge_indexing_tasks as _task_knowledge  # noqa: F401,E402
import internal.task.recycle_bin_tasks as _task_recycle  # noqa: F401,E402

# 补充记忆系统定时任务（每日巩固/权重扫描/技能治理/统计合并），与 Config 内置 4 项合并
from celery.schedules import crontab  # noqa: E402

beat_schedule = dict(getattr(celery_app.conf, "beat_schedule", {}) or {})
beat_schedule.update(
    {
        "skill-curation": {
            "task": "internal.task.consolidation_tasks.run_skill_curation",
            "schedule": crontab(hour=4, minute=0, day_of_week=0),  # 每周日凌晨 4:00
            "args": [],
        },
        "skill-stats-flush": {
            "task": "internal.task.consolidation_tasks.run_skill_stats_flush",
            "schedule": crontab(minute=0),  # 每小时整点执行（基因3）
            "args": [],
        },
    }
)
celery_app.conf.beat_schedule = beat_schedule

# 定时任务路由（记忆系统巩固任务走 consolidation 队列）
task_routes = dict(getattr(celery_app.conf, "task_routes", {}) or {})
task_routes.update(
    {
        "internal.task.recycle_bin_tasks.*": {"queue": "consolidation"},
    }
)
celery_app.conf.task_routes = task_routes

celery_app.set_default()
