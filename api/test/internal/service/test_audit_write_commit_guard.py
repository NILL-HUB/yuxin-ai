"""审计写入提交守卫。

背景：`AuditLogService.record_for_write` 的契约是 `commit=False`，必须由调用方
事务提交。历史上有 3 处调用点在其后**再无 commit**，而请求/工作线程退出时
`runtime_context._exit_scope()` 会 `db.session.remove()`，`Session.close()`
回滚未提交事务 → 审计行永久丢失。另有 1 处路由层直接 `db.session.add(AuditLog)`
且永不提交。

为什么不用运行时测试：这类"写入后丢失"只在真实 session 生命周期结束时才显现，
单测里 session 是替身、不会 close，测不出；必须用静态扫描把契约固化。

**两级模型**（单级模型会误判委托点，也会漏掉调用方的顺序错误）：

1. **直接写入者**：函数体内直接调用 `record_for_write(` 或
   `db.session.add(AuditLog(`。它们要么自己 commit，要么被登记为
   ``DEFERRED_WRITERS``（**委托提交点**：刻意把 commit 责任交给调用方）。
2. **委托点的调用方**：调用 ``DEFERRED_WRITERS`` 的函数，必须在**该调用之后**
   有 commit。只检查"函数体内有没有 commit"是不够的——`revoke_admin_sessions`
   就是"commit 在审计写入之前"，函数体内确实有 commit，但审计仍然丢失。

已知局限（静态分析的边界）：无法覆盖"经 `a._to_thread(service.record, ...)`
把方法当参数传递"这类间接调用；这类调用点由 `record` 的 `commit=True` 默认值
兜底，风险低于 `commit=False` 的 `record_for_write`。
"""
from __future__ import annotations

import ast
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
SCAN_DIRS = (API_ROOT / "internal" / "service", API_ROOT / "app" / "http")

# 委托提交点：这些辅助**刻意**不 commit，把提交责任交给调用方（与
# `record_for_write(commit=False)` 的契约一致）。登记为 `相对路径::函数名`，
# 守卫据此改为检查它们的**调用方**是否在调用之后 commit——比"函数体内有无
# commit"更严格（`revoke_admin_sessions` 就曾把 commit 写在审计之前）。
#
# 为什么按 `文件::函数` 而非只按函数名：同名辅助在不同文件里语义不同。
# `scoped_knowledge_service._emit_audit` 是**自提交**的旁路审计（`record(commit=True)`），
# 因为它调用方的业务写早已 commit + remove，没有可搭车的事务；若按名字一刀切
# 会把它误判为委托点，从而对它的调用方提出无法满足的 commit 要求。
DEFERRED_WRITERS: frozenset[str] = frozenset(
    {
        "internal/service/admin_user_service.py::_emit_audit",
        "internal/service/admin_customer_user_service.py::_emit_audit",
        "internal/service/admin_rbac_service.py::_emit_audit",
        "internal/service/admin_billing_plan_service.py::_emit_audit",
        "internal/service/admin_billing_config_service.py::_emit_audit",
        "internal/service/admin_redeem_code_service.py::_emit_audit",
    }
)


def _deferred_key(rel: str, name: str) -> str:
    return f"{rel}::{name}"


def _iter_source_files():
    for base in SCAN_DIRS:
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _direct_audit_writes(node: ast.AST) -> list[tuple[int, str]]:
    """函数体内的**直接**审计写入：[(行号, 说明)]。

    刻意不把 `self._emit_audit(...)` 这类包装调用算作直接写入——它们是
    ``DEFERRED_WRITERS``，由第 2 条规则检查其调用方。
    """
    hits: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr == "record_for_write":
            hits.append((child.lineno, "record_for_write"))
            continue
        # db.session.add(AuditLog(...))
        if func.attr == "add" and child.args:
            arg = child.args[0]
            if isinstance(arg, ast.Call):
                name = getattr(arg.func, "id", None) or getattr(arg.func, "attr", None)
                if name == "AuditLog":
                    hits.append((child.lineno, "session.add(AuditLog)"))
    return hits


def _deferred_writer_names() -> set[str]:
    """从 DEFERRED_WRITERS 的 `文件::函数` 键中提取函数名（用于识别候选调用）。"""
    return {key.split("::", 1)[1] for key in DEFERRED_WRITERS}


def _deferred_writer_calls(node: ast.AST) -> list[tuple[int, str]]:
    """函数体内所有**可能的**委托点调用：[(行号, 名字)]。

    这里只按名字粗筛，精确判定（`当前文件::名字` 是否在清单里）交给调用处，
    因为同名辅助在不同文件里语义可能不同。
    """
    names = _deferred_writer_names()
    hits: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        name = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name in names:
            hits.append((child.lineno, name))
    return hits


def _commit_lines(node: ast.AST) -> list[int]:
    """函数体内所有**提交动作**的行号。

    三种形式都算提交：
    - `xxx.commit()` / `xxx.auto_commit()`（显式提交 / 提交上下文）
    - `AuditLogService.record(..., commit=True)`（以参数形式请求立即提交；
      `record` 的 commit 默认即为 True，写死 True 属于"当场提交"的意图声明）
    """
    lines: list[int] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr in {"commit", "auto_commit"}:
            lines.append(child.lineno)
            continue
        if isinstance(func, ast.Name) and func.id == "commit":
            lines.append(child.lineno)
            continue
        # record(..., commit=True)
        name = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name == "record":
            for kw in child.keywords:
                if (
                    kw.arg == "commit"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    lines.append(child.lineno)
                    break
    return lines


def _func_name(node) -> str:
    return node.name


def _collect_violations() -> list[str]:
    violations: list[str] = []
    for path in _iter_source_files():
        rel = path.relative_to(API_ROOT).as_posix()
        # utf-8-sig：Python 源文件允许 UTF-8 BOM（PEP 263，解释器会自行剥离），
        # 但 ast.parse 收到裸字符串时不会——用 utf-8-sig 读取以对齐解释器行为，
        # 否则带 BOM 的合法文件会被误判为语法错误。
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            commits = _commit_lines(node)

            # 规则 1：直接写入者必须自己 commit，或是登记的委托点
            direct = _direct_audit_writes(node)
            if (
                direct
                and not commits
                and _deferred_key(rel, _func_name(node)) not in DEFERRED_WRITERS
            ):
                hows = ", ".join(sorted({how for _, how in direct}))
                violations.append(
                    f"{rel}::{_func_name(node)} 通过 {hows} 直接写审计但函数体内无 commit，"
                    "且未登记为委托提交点"
                )

            # 规则 2：委托点的调用方必须在**调用之后**提交。
            # 判定用 `当前文件::被调名`——委托点登记本身就是按文件+函数名的，
            # 因此"同名的自提交变体"（如 scoped_knowledge_service 的
            # `_emit_audit`，它自己 commit）不会被误判，其调用方也无需再提交。
            for lineno, wrapper in _deferred_writer_calls(node):
                if _deferred_key(rel, wrapper) not in DEFERRED_WRITERS:
                    continue
                if not any(line > lineno for line in commits):
                    violations.append(
                        f"{rel}::{_func_name(node)} 在第 {lineno} 行调用委托点 {wrapper}() "
                        "之后没有 commit，审计会随 session 归还被回滚"
                    )
    return violations


def test_audit_writes_must_be_committed():
    """审计写入必须最终被提交（直接写入者自提交，委托点的调用方后置提交）。"""
    violations = _collect_violations()
    assert violations == [], (
        "以下位置的审计写入不会被提交，事务回滚会导致审计静默丢失：\n  "
        + "\n  ".join(violations)
    )


class TestDetectorSelfCheck:
    """守卫自检：AST 逻辑失效会让守卫恒真，必须证明它真的能命中违规。"""

    def test_rules_not_vacuous(self):
        """守卫自身不是空转：必须真的扫到文件，且委托点清单非空。"""
        files = list(_iter_source_files())
        assert len(files) > 50
        assert DEFERRED_WRITERS, "委托提交点清单不得为空，否则规则 2 形同虚设"
        assert _deferred_writer_names(), "无法从清单提取函数名，规则 2 会静默失效"

    def test_detects_direct_writer_without_commit(self):
        tree = ast.parse(
            "def f(self):\n"
            "    self.audit_log_service.record_for_write(admin_user_id=1)\n"
        )
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        assert _direct_audit_writes(fn)
        assert _commit_lines(fn) == []

    def test_detects_direct_auditlog_add(self):
        tree = ast.parse("def f():\n    db.session.add(AuditLog(admin_user_id=1))\n")
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        hits = _direct_audit_writes(fn)
        assert hits and hits[0][1] == "session.add(AuditLog)"

    def test_detects_deferred_writer_call(self):
        tree = ast.parse(
            "def f(self):\n"
            "    self._emit_audit(operator_id=1)\n"
        )
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        assert _deferred_writer_calls(fn)

    def test_commit_after_call_is_accepted_but_commit_before_is_not(self):
        """顺序敏感：commit 在委托调用之后才算合规。"""
        after = ast.parse(
            "def f(self):\n"
            "    self._emit_audit(operator_id=1)\n"
            "    self.session.commit()\n"
        )
        fn = next(n for n in ast.walk(after) if isinstance(n, ast.FunctionDef))
        call_line = _deferred_writer_calls(fn)[0][0]
        assert any(line > call_line for line in _commit_lines(fn))

        before = ast.parse(
            "def f(self):\n"
            "    self.session.commit()\n"
            "    self._emit_audit(operator_id=1)\n"
        )
        fn2 = next(n for n in ast.walk(before) if isinstance(n, ast.FunctionDef))
        call_line2 = _deferred_writer_calls(fn2)[0][0]
        assert not any(line > call_line2 for line in _commit_lines(fn2))

    def test_auto_commit_counts_as_commit(self):
        tree = ast.parse(
            "def f(self):\n"
            "    self._emit_audit(operator_id=1)\n"
            "    with self.db.auto_commit():\n"
            "        self.db.session.add(x)\n"
        )
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        call_line = _deferred_writer_calls(fn)[0][0]
        assert any(line > call_line for line in _commit_lines(fn))
