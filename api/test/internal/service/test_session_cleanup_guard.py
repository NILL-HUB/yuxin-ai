"""连接池泄漏防回退：静态扫描禁用「裸后台线程 + app context」模式。

背景（为什么需要静态扫描，而不只是行为测试）：
`test_runtime_context.py` 锁定的是辅助函数**自身**的契约；它无法阻止后续开发
**绕开辅助**、重新手写泄漏形态。历史缺陷正是这样发生的——三道回收网各自实现
（support._to_thread / asgi teardown / celery after_return），互不相交，service
层新写的 `Thread(target=...)` 天然落在网外，评审与单测都难以察觉（单测习惯直接
构造服务对象、注入替身，恰好绕过接线环节）。

因此本测试用 AST 静态扫描 `internal/` 与 `app/`，把「必须归还 session」的三种
高危写法显式冻结：

1. **裸线程 / 线程池入口**：`threading.Thread(target=<未包装函数>)` 与
   `ThreadPoolExecutor.submit(<未包装函数>, ...)`。若 target 未经
   `run_in_app_context` 包装，线程内开启的事务不会归还。
2. **裸 `asyncio.to_thread`**：应改用 `to_thread_in_app_context`（或至少有
   `run_in_app_context` 包装），否则线程池中的 session 悬空。
3. **无 session 归还的 `app_context()`**：`with x.app_context():` 必须与
   `session_scope()` / `app_session_scope()` 同现（`internal/lib/runtime_context.py`
   自身为白名单——它就是提供该组合的地方）。

白名单机制：确属「已知安全」或「非 DB 场景」的例外，必须在 `_ALLOWLIST` 中
逐条登记并写明理由，强制后续新增例外时留下可审查的记录。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[3]
SCAN_ROOTS = [API_ROOT / "internal", API_ROOT / "app"]

# ---------------------------------------------------------------- 白名单
# key: 相对 api/ 的 POSIX 路径；value: 行号 → 豁免理由（必须具体）。
# 设计上应保持为空：优先改代码，而不是加豁免。仅当确属「扫描器无法证明安全」
# 且人工复核确认无泄漏时才登记。
_ALLOWLIST: dict[str, dict[int, str]] = {}


def _iter_python_files():
    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _rel(path: Path) -> str:
    return path.relative_to(API_ROOT).as_posix()


def _is_wrapped(node: ast.AST | None) -> bool:
    """判断节点是否为 `run_in_app_context(...)` 调用（即已包装）。"""
    if isinstance(node, ast.Call):
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        return name == "run_in_app_context"
    return False


_SCOPE_CONTEXT_MANAGERS = {"session_scope", "app_session_scope"}


def _opens_scope_self(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """函数体内是否自行进入了 session 归还作用域。

    等价于 `with app_session_scope():` / `with session_scope():` / 调用
    `run_in_app_context(...)` / 在 `finally` 中直接 `remove()`——这些写法都能
    保证线程退出时归还 session。
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.With):
            for item in sub.items:
                expr = item.context_expr
                if isinstance(expr, ast.Call):
                    name = getattr(expr.func, "id", None) or getattr(
                        expr.func, "attr", None
                    )
                    if name in _SCOPE_CONTEXT_MANAGERS:
                        return True
        if isinstance(sub, ast.Call) and _is_wrapped(sub):
            return True
        # 手工 `db.session.remove()`（含 `self._db.sync_session.remove()`）
        if _is_session_remove_call(sub):
            return True
    return False


_SESSION_ATTRS = {"session", "sync_session", "async_session"}
_DB_ROOTS = {"db", "_db", "async_db"}


def _is_session_remove_call(node: ast.AST) -> bool:
    """是否为 `<...>.session.remove()` / `<...>.sync_session.remove()` 调用。"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "remove":
        return False
    inner = func.value
    return isinstance(inner, ast.Attribute) and inner.attr in _SESSION_ATTRS


def _refs_db_session(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """函数体是否可能触达关系型数据库 session。

    用于把「纯计算/纯 Redis/纯 HTTP」的后台线程（如探针、锁续租、webhook 投递）
    与真正访问 DB 的线程区分开——前者不可能造成 session 泄漏，不应报违规。
    判定：出现 `db`/`_db`/`async_db` 标识符，或 `.session` / `.sync_session` /
    `.async_session` 属性访问。
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in _DB_ROOTS:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in _SESSION_ATTRS:
            return True
    return False


def _target_name(node: ast.AST | None) -> str | None:
    """取 target 的简单名（Name.id 或 Attribute.attr，如 self._stop_active_task）。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _collect_defs() -> dict[str, list[ast.AST]]:
    """跨全部被扫描文件收集 `函数名 → 定义节点`。

    必须跨模块：`chat_routes.py` 中 `asyncio.to_thread(_load_runtime_context, ...)`
    的目标定义在 `support.py`，只在单文件内解析会漏判/误判。
    """
    defs: dict[str, list[ast.AST]] = {}
    for path in _iter_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.setdefault(node.name, []).append(node)
    return defs


def _target_is_safe(node: ast.AST | None, defs: dict[str, list[ast.AST]]) -> tuple[bool, str]:
    """判断一个派发目标是否安全，返回 (是否安全, 说明)。

    安全判定（按优先级）：
    1. 已显式 `run_in_app_context(...)` 包装；
    2. 目标函数定义中自行归还 session（scope / remove）；
    3. 目标函数不触达 DB session（纯 Redis/HTTP/Neo4j/计算，无泄漏可能）；
    4. 目标无法解析（lambda / 外部库函数）——无法静态证明，保守放过并
       由人工评审兜底（这类通常是 LLM/HTTP 调用，不直接持有 DB session）。
    """
    if _is_wrapped(node):
        return True, "已 run_in_app_context 包装"
    name = _target_name(node)
    if not name:
        return True, "目标不可解析（lambda/表达式）"
    targets = defs.get(name)
    if not targets:
        return True, "目标为外部/导入函数，无法静态解析"
    if any(_opens_scope_self(t) for t in targets):
        return True, "目标函数自行归还 session"
    if not any(_refs_db_session(t) for t in targets):
        return True, "目标函数不触达 DB session"
    return False, f"目标 {name} 触达 DB session 但未归还"


def _iter_dispatch_targets(call: ast.Call) -> list[ast.AST]:
    """取出该调用中「被派发到另一个线程执行」的函数表达式。"""
    func = call.func
    # Thread(target=...)
    for kw in call.keywords:
        if kw.arg == "target":
            return [kw.value]
    # executor.submit(fn, ...)
    if getattr(func, "attr", None) == "submit" and call.args:
        return [call.args[0]]
    # asyncio.to_thread(fn, ...)
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "to_thread"
        and isinstance(func.value, ast.Name)
        and func.value.id == "asyncio"
        and call.args
    ):
        return [call.args[0]]
    return []


def _collect_violations() -> list[tuple[str, int, str]]:
    """返回 (相对路径, 行号, 违规描述) 列表。"""
    violations: list[tuple[str, int, str]] = []
    defs = _collect_defs()

    for path in _iter_python_files():
        rel = _rel(path)
        try:
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover - 语法错误应由 lint 拦截
            pytest.fail(f"{rel} 存在语法错误，静态扫描无法进行: {exc}")
        lines = source.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for target in _iter_dispatch_targets(node):
                safe, reason = _target_is_safe(target, defs)
                if safe:
                    continue
                kind = _dispatch_kind(node)
                violations.append((rel, node.lineno, f"{kind}：{reason}"))

        # app_context 与 session 归还必须同现（app_context 已是 no-op，
        # 因此它不再提供任何保障——单独使用必属遗漏）。
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            for item in node.items:
                expr = item.context_expr
                if not isinstance(expr, ast.Call):
                    continue
                if getattr(expr.func, "attr", None) != "app_context":
                    continue
                names = {
                    getattr(i.context_expr.func, "id", None)
                    or getattr(i.context_expr.func, "attr", None)
                    for i in node.items
                    if isinstance(i.context_expr, ast.Call)
                }
                if names & _SCOPE_CONTEXT_MANAGERS:
                    continue
                # 该 with 块内若手工 remove()，同样安全
                block_has_remove = any(
                    _is_session_remove_call(sub)
                    for stmt in node.body
                    for sub in ast.walk(stmt)
                )
                if block_has_remove:
                    continue
                if not _block_refs_db_session(node):
                    continue
                violations.append(
                    (
                        rel,
                        node.lineno,
                        "with x.app_context() 未组合 session_scope：DB 事务不会归还",
                    )
                )

    # 过滤白名单
    return [
        (rel, lineno, desc)
        for rel, lineno, desc in violations
        if lineno not in _ALLOWLIST.get(rel, {})
    ]


def _dispatch_kind(call: ast.Call) -> str:
    func = call.func
    if any(kw.arg == "target" for kw in call.keywords):
        return "Thread(target=...)"
    if getattr(func, "attr", None) == "submit":
        return "executor.submit(...)"
    return "asyncio.to_thread(...)"


def _block_refs_db_session(with_node: ast.With) -> bool:
    """with 块内是否触达 DB session（用于决定是否需要归还）。"""
    for stmt in with_node.body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Name) and sub.id in _DB_ROOTS:
                return True
            if isinstance(sub, ast.Attribute) and sub.attr in _SESSION_ATTRS:
                return True
    return False


def test_no_raw_background_thread_patterns():
    """冻结「裸后台线程 + app context」模式，防止连接泄漏回潮。

    失败时的修复方式（二选一）：
    - 首选：改用 `internal.lib.runtime_context` 的
      `run_in_app_context` / `app_session_scope` / `to_thread_in_app_context`；
    - 若确属非 DB 场景（如纯 HTTP 调用），在 `_ALLOWLIST` 中登记文件+行号+理由。
    """
    violations = _collect_violations()
    if not violations:
        return
    detail = "\n".join(f"  {rel}:{lineno}  {desc}" for rel, lineno, desc in violations)
    pytest.fail(
        "检测到可能造成连接泄漏的裸后台线程写法，请改用 "
        "internal/lib/runtime_context 提供的辅助（或登记白名单并说明理由）：\n"
        f"{detail}"
    )


def test_allowlist_entries_still_exist():
    """白名单锚点必须有效：文件删除或行号漂移后应清理，避免白名单腐烂。

    若本测试失败，说明某条豁免指向的文件/行已不存在——请删除该条豁免，
    或更新其行号（豁免随重构失效会导致真实违规被静默放过）。
    """
    stale: list[str] = []
    for rel, entries in _ALLOWLIST.items():
        path = API_ROOT / rel
        if not entries:
            continue
        if not path.exists():
            stale.append(f"{rel}（文件不存在）")
            continue
        source_lines = path.read_text(encoding="utf-8-sig").splitlines()
        for lineno in entries:
            if lineno < 1 or lineno > len(source_lines):
                stale.append(f"{rel}:{lineno}（行号越界）")
    if stale:
        pytest.fail("白名单条目已失效，请更新或删除：\n" + "\n".join(f"  {s}" for s in stale))


def test_allowlist_is_minimal_and_justified():
    """白名单必须逐条写明理由，并保持最小化。

    防止「一遇扫描失败就往白名单里塞文件」的惰性做法把守卫架空：每条豁免
    必须是非空字符串理由，且豁免总数设上限，新增时需有意识取舍。
    """
    for rel, entries in _ALLOWLIST.items():
        for lineno, reason in entries.items():
            assert isinstance(reason, str) and reason.strip(), (
                f"白名单 {rel}:{lineno} 缺少豁免理由"
            )
    total = sum(len(v) for v in _ALLOWLIST.values())
    assert total <= 10, f"白名单条目过多（{total}），守卫可能已被架空"


def _defs_from(snippet: str) -> dict[str, list[ast.AST]]:
    """从源码片段解析出 `函数名 → 定义节点`（供检测器自测使用）。"""
    tree = ast.parse(snippet)
    defs: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.setdefault(node.name, []).append(node)
    return defs


class TestDetectorSelfCheck:
    """检测器自测：证明守卫**能真的抓到违规**，而非恒真（防空洞守卫）。

    这些用例直接喂合成 AST 给检测函数，不依赖仓库存量代码的状态。
    """

    def test_detects_raw_thread_touching_db(self):
        """裸线程 + 线程内访问 DB，必须判为违规（历史缺陷原形）。"""
        snippet = (
            "def _bg_write():\n"
            "    account = db.session.get(Account, account_id)\n"
            "\n"
            "def spawn():\n"
            "    Thread(target=_bg_write, daemon=True).start()\n"
        )
        defs = _defs_from(snippet)
        call = next(
            n
            for n in ast.walk(ast.parse(snippet))
            if isinstance(n, ast.Call) and any(k.arg == "target" for k in n.keywords)
        )
        target = _iter_dispatch_targets(call)[0]
        safe, reason = _target_is_safe(target, defs)
        assert safe is False, "检测器漏判了裸线程 + DB 访问（守卫形同虚设）"
        assert "_bg_write" in reason

    def test_accepts_wrapped_thread(self):
        """经 run_in_app_context 包装的线程应判为安全。"""
        snippet = (
            "def _bg_write():\n"
            "    account = db.session.get(Account, account_id)\n"
            "\n"
            "def spawn():\n"
            "    Thread(target=run_in_app_context(_bg_write)).start()\n"
        )
        call = next(
            n
            for n in ast.walk(ast.parse(snippet))
            if isinstance(n, ast.Call) and any(k.arg == "target" for k in n.keywords)
        )
        target = _iter_dispatch_targets(call)[0]
        safe, _ = _target_is_safe(target, _defs_from(snippet))
        assert safe is True

    def test_accepts_target_that_scopes_itself(self):
        """target 内部自行 app_session_scope 时判为安全（正确写法）。"""
        snippet = (
            "def _worker():\n"
            "    with app_session_scope():\n"
            "        db.session.get(Account, account_id)\n"
            "\n"
            "def spawn():\n"
            "    Thread(target=_worker).start()\n"
        )
        defs = _defs_from(snippet)
        call = next(
            n
            for n in ast.walk(ast.parse(snippet))
            if isinstance(n, ast.Call) and any(k.arg == "target" for k in n.keywords)
        )
        safe, _ = _target_is_safe(_iter_dispatch_targets(call)[0], defs)
        assert safe is True

    def test_accepts_target_unrelated_to_db(self):
        """target 不触达 DB（纯 Redis/HTTP）时不应误报。"""
        snippet = (
            "def _renew_lock():\n"
            "    redis_client.expire(lock_key, 30)\n"
            "\n"
            "def spawn():\n"
            "    Thread(target=_renew_lock).start()\n"
        )
        defs = _defs_from(snippet)
        call = next(
            n
            for n in ast.walk(ast.parse(snippet))
            if isinstance(n, ast.Call) and any(k.arg == "target" for k in n.keywords)
        )
        safe, _ = _target_is_safe(_iter_dispatch_targets(call)[0], defs)
        assert safe is True

    def test_detects_bare_asyncio_to_thread_touching_db(self):
        """裸 asyncio.to_thread + DB 访问必须判为违规。"""
        snippet = (
            "def _load():\n"
            "    return db.session.query(Account).all()\n"
            "\n"
            "async def go():\n"
            "    return await asyncio.to_thread(_load)\n"
        )
        defs = _defs_from(snippet)
        call = next(
            n
            for n in ast.walk(ast.parse(snippet))
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "to_thread"
        )
        safe, _ = _target_is_safe(_iter_dispatch_targets(call)[0], defs)
        assert safe is False
