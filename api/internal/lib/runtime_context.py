"""运行上下文执行辅助：统一「进入 app 上下文 + 执行同步 DB 逻辑 + 归还 session」。

## 为什么需要这个模块（历史缺陷）

容器化改造后 `app_context()` 已经是 **no-op**（见 `internal/server/http.py` 的
`Http.app_context`，注释即"service 层不再依赖 Flask app context"）。
换句话说，进入 app_context **不再提供任何资源生命周期保障**。

而 SQLAlchemy 的 `scoped_session` 是按**线程**绑定 session 的：线程内第一次
`db.session.query(...)` 会开启事务，**必须显式 `db.session.remove()`** 才会
结束事务并归还连接到连接池。

历史上仓库有三道 session 归还网，但**互不相交**，恰好漏掉了「service 层自建线程」：

=========  ==================================================  ==================
归还机制    位置                                                  覆盖边界
=========  ==================================================  ==================
线程池清理   `support._to_thread` 的 `finally`                   仅 HTTP 路由经它调用的路径
请求兜底     `asgi_app._clear_request_scope`                   仅主线程（teardown 不跑在后台线程）
任务兜底     `celery_app.AppContextTask.after_return`           仅 Celery 任务生命周期
=========  ==================================================  ==================

于是任何 `threading.Thread(target=...).start()` 或裸 `asyncio.to_thread(...)`
进入 app_context 跑 DB 后，线程退出时 session 悬空，连接停在
`idle in transaction`，累积到 `max_connections` 耗尽；并会阻塞 DDL
（实测：一条 `ALTER TABLE admin_user` 被其表锁阻塞数分钟）。

## 使用约定（新增后台 DB 逻辑必须遵守）

    # 推荐：统一入口，session 必然归还
    from internal.lib.runtime_context import run_in_app_context, to_thread_in_app_context

    def _bg_job():
        ...
    thread = Thread(target=run_in_app_context(_bg_job), daemon=True)
    thread.start()

    # 异步：直接 await
    result = await to_thread_in_app_context(sync_fn, arg1, arg2)

    # 已在 app_context 中但需要显式包一层（如工具闭包）
    with app_session_scope():
        ...

**禁止**再手写 `with flask_app.app_context(): ...` 包裹 DB 操作的裸线程或裸
`asyncio.to_thread`——那正是本模块要消灭的模式。防回退测试见
`test/internal/lib/test_runtime_context.py` 与 `test/internal/service/test_session_cleanup_guard.py`。
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

# 每个线程的作用域嵌套深度（threading.local 而非 contextvar：
# contextvar 会被复制进子线程，导致子线程"继承"父线程的深度而永不归还 session）。
_thread_state = threading.local()


def _scope_depth() -> int:
    return getattr(_thread_state, "depth", 0)


def _release_session() -> None:
    """结束当前线程绑定的 scoped_session，归还连接到连接池。

    幂等且静默：无 session / 已归还 / 引擎未初始化时都不应报错——
    清理失败绝不能反噬业务主流程。
    """
    try:
        from internal.extension.database_extension import db

        remove_session = getattr(db.session, "remove", None)
        if callable(remove_session):
            remove_session()
    except Exception:
        logger.debug("释放数据库 session 失败（已忽略）", exc_info=True)


def _session_exists() -> bool | None:
    """当前线程是否已绑定 scoped_session。

    返回 ``None`` 表示无法判定（scoped_session 未实现 registry，如测试替身）。
    """
    try:
        from internal.extension.database_extension import db

        registry = getattr(db.session, "registry", None)
        has = getattr(registry, "has", None)
        if callable(has):
            return bool(has())
    except Exception:
        logger.debug("探测数据库 session 是否存在失败", exc_info=True)
    return None


def _enter_scope() -> None:
    """进入一层作用域；最外层需记录进入前是否已有 session。"""
    depth = _scope_depth()
    if depth == 0:
        # 记下"进入前是否已存在 session"：决定退出时该不该由我们归还。
        _thread_state.pre_existing = _session_exists()
    _thread_state.depth = depth + 1


def _exit_scope() -> None:
    """退出一层作用域；仅最外层且 session 由本作用域创建时才归还。

    「由本作用域创建」的判定很关键：若调用方（如 HTTP 请求线程、Celery 任务）
    在外层已经持有 session，说明生命周期由调用方负责，我们贸然 ``remove()``
    会回滚其尚未提交的事务，制造静默写丢失。
    """
    depth = _scope_depth() - 1
    _thread_state.depth = max(depth, 0)
    if depth > 0:
        return
    pre_existing = getattr(_thread_state, "pre_existing", None)
    _thread_state.pre_existing = None
    # pre_existing 为 True → 调用方原有 session，归还责任不归我们。
    # pre_existing 为 None → 无法判定（替身/未初始化），沿用保守的归还行为。
    if pre_existing is True:
        return
    _release_session()


@contextmanager
def session_scope() -> Iterator[None]:
    """**只**负责归还 session 的轻量上下文（不进入 app 上下文）。

    适用于「已经/另行进入 app 上下文，但仍需保证归还」的场景，可与其它
    上下文组合：

        with runtime_flask_app.app_context(), session_scope():
            ...

    **可重入**：只有最外层退出时才 `db.session.remove()`（见
    :func:`app_session_scope` 的说明）。
    """
    _enter_scope()
    try:
        yield
    finally:
        _exit_scope()


@contextmanager
def app_session_scope() -> Iterator[Any]:
    """进入 app 上下文并在**最外层退出时**保证归还 session。

    用法（工具闭包 / 短逻辑）：

        with app_session_scope():
            data = some_service.query()

    **可重入**：只有最外层的 `with` 退出时才 `db.session.remove()`。
    原因：service 代码路径常出现嵌套（如 Agent 工具在已进入作用域的
    执行流里再包一层），若每层都 `remove()`，内层退出会提前结束并回滚
    外层尚未提交的事务，制造比泄漏更难排查的"写丢失"。因此用线程级
    深度计数，内层只做计数进出，归还责任归最外层。

    注意：本上下文**不会**替你提交事务；写操作请用 `db.auto_commit()`
    （其内部已在退出时 `remove()`），或自行 commit。
    """
    from app.http.app import app as _flask_app

    with _flask_app.app_context():
        with session_scope():
            yield _flask_app


def run_in_app_context(fn: Callable[..., Any]) -> Callable[..., Any]:
    """把一个同步可调用对象包装为「在 app 上下文中执行 + 退出必归还 session」。

    用于 `threading.Thread(target=...)` / `ThreadPoolExecutor.submit(...)`
    等场景。同时复制调用方（包装发生处）的 contextvars，使线程内仍可读取
    请求级上下文（`internal.context.request` / `has_request_context`）。

    用法：

        thread = Thread(target=run_in_app_context(job), daemon=True)
        thread.start()

    ⚠️ **每次派发都必须新建 wrapper**（`run_in_app_context(job)` 要在调用方
    线程内求值，如上例）。原因有二：
    1. contextvars 快照在**包装时**捕获——若在 worker 线程内才 copy，拿到的
       是 worker 的空上下文，请求级上下文会静默丢失；
    2. 同一个 `contextvars.Context` 不能被并发进入，复用同一 wrapper 会抛
       `RuntimeError: cannot enter context ... already entered`。
    现网所有调用点（Thread / asyncio.to_thread / ThreadPoolExecutor.submit）
    都是「即建即用」，符合该约束。
    """

    request_context = contextvars.copy_context()

    @functools.wraps(fn)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        with app_session_scope():
            return request_context.run(fn, *args, **kwargs)

    return _wrapper


async def to_thread_in_app_context(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """异步版：把同步 DB 调用移入线程池，并保证该线程的 session 被归还。

    用于替代裸 `asyncio.to_thread(sync_fn, ...)`——后者在线程退出后不归还
    session，是同类泄漏源。
    """
    return await asyncio.to_thread(run_in_app_context(fn), *args, **kwargs)
