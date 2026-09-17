"""渲染 Celery 任务注册与队列隔离测试。

渲染任务必须同时具备：任务函数、TASK_MODULES 登记、显式 import、队列路由。
只有函数没有登记/路由 = 断链（AGENTS.md 强制审查项）。
"""
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
CELERY_APP = API_ROOT / "app/http/celery_app.py"
CONFIG = API_ROOT / "config/config.py"
TASK_FILE = API_ROOT / "internal/task/render_tasks.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_task_module_exists():
    assert TASK_FILE.is_file(), "缺少渲染任务模块"


def test_task_module_registered_in_celery():
    source = _read(CELERY_APP)
    assert "render_tasks" in source, "任务模块必须登记进 TASK_MODULES"


def test_task_module_explicitly_imported():
    source = _read(CELERY_APP)
    assert "internal.task.render_tasks as" in source


def test_render_queue_declared_and_routed():
    source = _read(CONFIG)
    assert 'Queue("render")' in source, "必须声明 render 队列"
    assert "internal.task.render_tasks.*" in source, "必须把渲染任务路由到 render 队列"


def test_task_uses_shared_task_with_explicit_name():
    source = _read(TASK_FILE)
    assert "@shared_task" in source
    assert "internal.task.render_tasks." in source


def test_task_is_retryable_and_uses_injector():
    source = _read(TASK_FILE)
    assert "max_retries" in source
    assert "self.retry" in source
    assert "injector" in source


def test_task_declares_late_ack_and_worker_lost_rejection():
    """闸门 5：worker 中途被杀时任务必须重新入队，不能静默丢失。"""
    source = _read(TASK_FILE)
    assert "acks_late=True" in source
    assert "reject_on_worker_lost=True" in source


def test_task_has_soft_time_limit():
    """闸门 6：必须有超时上限，避免长任务无限占用渲染槽位。"""
    source = _read(TASK_FILE)
    assert "soft_time_limit" in source


def test_task_returns_gate_slot_on_finish():
    """任务结束必须归还闸门计数，否则渲染额度会泄漏、用户永久被拒。"""
    source = _read(TASK_FILE)
    assert "mark_dequeued" in source, "任务开始必须递减队列积压计数"
    assert "guard.release" in source, "任务结束必须归还账号槽位与防重锁"
