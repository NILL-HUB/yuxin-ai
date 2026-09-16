"""连接池泄漏根治：`internal.lib.runtime_context` 行为级测试。

背景（为什么需要这组测试）：
容器化后 `app_context()` 是 no-op（`internal/server/http.py`），进入 app 上下文
**不再提供任何资源生命周期保障**；而 SQLAlchemy `scoped_session` 按线程绑定，
线程内首次查库即开启事务，必须显式 `db.session.remove()` 才能归还连接。

历史缺陷：service 层自建线程（`Thread(...)` / `ThreadPoolExecutor` / 裸
`asyncio.to_thread`）绕过三道回收网（support._to_thread / asgi teardown /
celery after_return），线程退出后连接停在 `idle in transaction`，累积耗尽
`max_connections`，并会阻塞 DDL（实测一条 `ALTER TABLE admin_user` 被其表锁
阻塞数分钟）。

本测试锁定 `runtime_context` 的**契约**，防止后续重构把它改回泄漏形态：
1. 作用域退出时调用 `db.session.remove()`（归还连接）；
2. 作用域**可重入**，内层退出不得提前归还（否则回滚外层未提交事务）；
3. **不夺取调用方已有 session 的所有权**——若外层已持有 session（HTTP 请求
   线程 / Celery 任务），退出时不 remove，避免静默写丢失；
4. `run_in_app_context` 包装后仍能透传参数/返回值并复制 contextvars；
5. 清理失败（引擎未初始化 / remove 抛错）不得反噬业务主流程。
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from unittest.mock import MagicMock, patch

import pytest

import internal.lib.runtime_context as runtime_context


class _FakeRegistry:
    """模拟 scoped_session.registry（提供 has()）。"""

    def __init__(self, has_session: bool = False) -> None:
        self._has = has_session
        self.removed = 0

    def has(self) -> bool:
        return self._has


class _FakeScopedSession:
    def __init__(self, has_session: bool = False) -> None:
        self.registry = _FakeRegistry(has_session)
        self.remove_calls = 0

    def remove(self) -> None:
        self.remove_calls += 1


def _patch_db(scoped: _FakeScopedSession):
    """把 runtime_context 内使用的 db.session 替换为替身。"""
    fake_db = MagicMock()
    fake_db.session = scoped
    return patch.dict(
        "sys.modules",
        {"internal.extension.database_extension": MagicMock(db=fake_db)},
    )


@pytest.fixture(autouse=True)
def _reset_thread_state():
    """每个用例前后重置线程本地的作用域深度，避免用例间串扰。"""
    runtime_context._thread_state.__dict__.clear()
    yield
    runtime_context._thread_state.__dict__.clear()


class TestSessionReclaim:
    def test_scope_releases_session_on_exit(self):
        """最外层退出时必须调用 db.session.remove() 归还连接。"""
        scoped = _FakeScopedSession()
        with _patch_db(scoped):
            with runtime_context.session_scope():
                pass
        assert scoped.remove_calls == 1

    def test_scope_releases_session_on_exception(self):
        """作用域内抛异常时也必须归还 session（try/finally 语义）。"""
        scoped = _FakeScopedSession()
        with _patch_db(scoped):
            with pytest.raises(RuntimeError):
                with runtime_context.session_scope():
                    raise RuntimeError("boom")
        assert scoped.remove_calls == 1

    def test_nested_scope_releases_only_once_on_outermost_exit(self):
        """嵌套作用域只在最外层退出时归还一次，防止提前回滚外层事务。"""
        scoped = _FakeScopedSession()
        with _patch_db(scoped):
            with runtime_context.session_scope():
                with runtime_context.session_scope():
                    assert scoped.remove_calls == 0, "内层退出不得归还 session"
                assert scoped.remove_calls == 0, "仍在最外层作用域内，不得归还"
            assert scoped.remove_calls == 1

    def test_scope_does_not_steal_callers_existing_session(self):
        """调用方已持有 session 时，作用域退出不得 remove（避免写丢失）。

        HTTP 请求线程 / Celery 任务在外层已有 session，其生命周期由调用方
        负责；若此处 remove，会回滚调用方尚未提交的事务。
        """
        scoped = _FakeScopedSession(has_session=True)
        with _patch_db(scoped):
            with runtime_context.session_scope():
                pass
        assert scoped.remove_calls == 0, "不应夺取调用方已有 session 的所有权"

    def test_scope_releases_when_no_session_detected_before(self):
        """进入前无 session 时，退出需归还（由本作用域创建）。"""
        scoped = _FakeScopedSession(has_session=False)
        with _patch_db(scoped):
            with runtime_context.session_scope():
                pass
        assert scoped.remove_calls == 1

    def test_release_failure_is_swallowed(self):
        """remove 抛错不得向外传播（清理失败不能反噬业务）。"""
        scoped = _FakeScopedSession()
        scoped.remove = MagicMock(side_effect=RuntimeError("db gone"))
        with _patch_db(scoped):
            with runtime_context.session_scope():
                pass

    def test_release_tolerates_missing_remove(self):
        """db.session 无 remove 时静默跳过。"""
        fake_db = MagicMock()
        fake_db.session = MagicMock(spec=[])
        with patch.dict(
            "sys.modules",
            {"internal.extension.database_extension": MagicMock(db=fake_db)},
        ):
            with runtime_context.session_scope():
                pass

    def test_depth_reset_after_exception_inside_scope(self):
        """异常路径后深度必须归零，否则后续作用域永不归还 session。"""
        scoped = _FakeScopedSession()
        with _patch_db(scoped):
            with pytest.raises(RuntimeError):
                with runtime_context.session_scope():
                    raise RuntimeError("boom")
            assert runtime_context._scope_depth() == 0
            with runtime_context.session_scope():
                pass
        assert scoped.remove_calls == 2


class TestRunInAppContext:
    def test_wrapper_releases_session_and_passes_args(self):
        """包装函数需透传参数/返回值，并在退出时归还 session。"""
        scoped = _FakeScopedSession()
        seen = {}

        def job(a, b, *, c):
            seen["args"] = (a, b, c)
            return a + b + c

        with _patch_db(scoped):
            wrapped = runtime_context.run_in_app_context(job)
            assert wrapped(1, 2, c=3) == 6

        assert seen["args"] == (1, 2, 3)
        assert scoped.remove_calls == 1

    def test_wrapper_releases_session_on_exception(self):
        scoped = _FakeScopedSession()

        def job():
            raise ValueError("nope")

        with _patch_db(scoped):
            wrapped = runtime_context.run_in_app_context(job)
            with pytest.raises(ValueError):
                wrapped()

        assert scoped.remove_calls == 1

    def test_wrapper_copies_contextvars_into_thread(self):
        """包装后的线程应能看到调用方设置的 contextvar（可观测性/请求上下文）。"""
        token_var = contextvars.ContextVar("leak_guard_token", default="unset")
        token_var.set("from-caller")
        captured = {}

        def job():
            captured["value"] = token_var.get()

        scoped = _FakeScopedSession()
        with _patch_db(scoped):
            wrapped = runtime_context.run_in_app_context(job)
            t = threading.Thread(target=wrapped)
            t.start()
            t.join()

        assert captured["value"] == "from-caller"

    def test_thread_local_depth_isolated_from_parent_thread(self):
        """子线程不得继承父线程的作用域深度（否则子线程永不归还 session）。

        这正是选用 threading.local 而非 contextvar 的原因：contextvar 会被
        复制进子线程，子线程的深度就从父线程的 1 起算，退出时因 depth>0 而
        **跳过归还**，连接照样泄漏。

        判定方式：让父线程在作用域内启动子线程，分别记录各自线程的归还次数。
        正确实现下父、子**各归还一次**（各自线程的 session 各自负责）。
        """
        scoped = _FakeScopedSession()
        child_removes = {}

        def job():
            pass

        def child():
            with runtime_context.session_scope():
                pass
            child_removes["after_child"] = scoped.remove_calls

        with _patch_db(scoped):
            with runtime_context.session_scope():
                assert runtime_context._scope_depth() == 1, "父线程应处于作用域内"
                t = threading.Thread(target=child)
                t.start()
                t.join()
            parent_total = scoped.remove_calls

        # 子线程进入时深度从 0 起算，故它在自己线程内完成了一次归还
        assert child_removes["after_child"] == 1, "子线程未归还 session（深度被继承）"
        # 父线程随后退出，再归还一次
        assert parent_total == 2

    def test_to_thread_in_app_context_releases_session(self):
        """异步版同样归还 session。"""
        scoped = _FakeScopedSession()

        def job(x):
            return x * 2

        async def main():
            return await runtime_context.to_thread_in_app_context(job, 21)

        with _patch_db(scoped):
            assert asyncio.run(main()) == 42

        assert scoped.remove_calls == 1
