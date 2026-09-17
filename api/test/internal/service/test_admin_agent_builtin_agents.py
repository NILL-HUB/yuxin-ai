"""预置 Agent 幂等补建测试（设计 §10.3）。

本文件断言的不变量：
1. 幂等 + **归属隔离**：只按 `owner_admin_user_id` 判定"已存在"，
   属于他人的同 builtin_key 记录不得被复用；重复调用零写入；
2. **不下放权限**：预置 Agent 的 granted_permissions 必须为空——
   权限只能由管理员显式下放（设计 §4.3），系统预置不得绕过；
3. 并发冲突只吞 `admin_agent_owner_builtin_uniq` 的唯一约束冲突并继续，
   其余 IntegrityError 与非 IntegrityError 硬错误一律上抛；
4. 入参归一化：字符串 admin_user_id 也要能工作，且落库字段为 UUID；
5. BUILTIN_ADMIN_AGENTS 的每个 prompt_key 都在 prompts/index.yaml 登记
   （登记缺失会让运行时取不到提示词）。
"""
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import yaml
from sqlalchemy.exc import IntegrityError

from internal.service.admin_agent_builtin_agents import (
    BUILTIN_ADMIN_AGENTS,
    BUILTIN_UNIQUE_CONSTRAINT,
    AdminAgentBuiltinService,
)

_INDEX_YAML_PATH = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "core"
    / "prompts"
    / "index.yaml"
)


def _integrity_error(constraint_name=BUILTIN_UNIQUE_CONSTRAINT):
    """构造真实 IntegrityError（orig.diag.constraint_name 可读）。"""
    orig = SimpleNamespace(diag=SimpleNamespace(constraint_name=constraint_name))
    return IntegrityError("INSERT INTO admin_agent ...", {}, orig)


class _Query:
    """查询替身：filter_by **真实应用**过滤条件，并记录 kwargs 供断言。"""

    def __init__(self, rows, filter_by_calls):
        self._rows = list(rows)
        self._filter_by_calls = filter_by_calls

    def filter_by(self, **kwargs):
        self._filter_by_calls.append(kwargs)
        matched = [
            row
            for row in self._rows
            if all(getattr(row, name, None) == value for name, value in kwargs.items())
        ]
        return _Query(matched, self._filter_by_calls)

    def all(self):
        return list(self._rows)


class _Session:
    """会话替身：支持 add / rollback / remove 与查询过滤记录。"""

    def __init__(self, rows, conflict_keys=(), add_error=None):
        self._rows = list(rows)
        self._conflict_keys = set(conflict_keys)
        self._add_error = add_error
        self.filter_by_calls = []
        self.added = []
        self.rollbacks = 0
        self.removes = 0

    def query(self, model):
        return _Query(self._rows, self.filter_by_calls)

    def add(self, obj):
        if self._add_error is not None:
            error, self._add_error = self._add_error, None
            raise error
        if obj.builtin_key in self._conflict_keys:
            raise _integrity_error()
        self.added.append(obj)

    def rollback(self):
        self.rollbacks += 1

    def remove(self):
        self.removes += 1


class _AutoCommit:
    """对齐 `pkg/sqlalchemy` 的 `_DualAutoCommit.__exit__` 语义：

    `with` 体内抛异常时 rollback，随后无论成败都 remove（丢弃该 session）。
    """

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                self._session.rollback()
        finally:
            self._session.remove()
        return False


def _service(existing=None, conflict_keys=(), add_error=None):
    service = AdminAgentBuiltinService.__new__(AdminAgentBuiltinService)
    session = _Session(
        rows=list(existing or []),
        conflict_keys=conflict_keys,
        add_error=add_error,
    )
    service.db = SimpleNamespace(session=session, auto_commit=lambda: _AutoCommit(session))
    service.session = session
    return service


def test_builtin_list_is_non_empty_and_keys_unique():
    keys = [item["builtin_key"] for item in BUILTIN_ADMIN_AGENTS]
    assert keys, "至少要有运维/运营两个预置 Agent"
    assert len(keys) == len(set(keys))


def test_builtin_prompt_keys_are_registered_in_index_yaml():
    """预置清单的 prompt_key 必须在 prompts/index.yaml 登记，否则运行时取不到提示词。"""
    registered = {
        entry.get("key")
        for entry in (yaml.safe_load(_INDEX_YAML_PATH.read_text(encoding="utf-8")) or [])
    }

    missing = [
        item["prompt_key"]
        for item in BUILTIN_ADMIN_AGENTS
        if item["prompt_key"] not in registered
    ]
    assert not missing, f"prompt_key 未在 prompts/index.yaml 登记：{missing}"


def test_ensure_creates_missing_agents_without_granting_permissions():
    admin_id = uuid4()
    service = _service(existing=[])

    service.ensure_builtin_agents(admin_id)

    assert len(service.session.added) == len(BUILTIN_ADMIN_AGENTS)
    for agent in service.session.added:
        assert agent.owner_admin_user_id == admin_id
        assert agent.granted_permissions == [], "预置 Agent 不得预置权限"
        assert agent.automation_policy == {}
        assert agent.enabled is True
        assert agent.builtin_key


def test_ensure_is_idempotent_when_all_exist():
    admin_id = uuid4()
    existing = [
        SimpleNamespace(builtin_key=item["builtin_key"], owner_admin_user_id=admin_id)
        for item in BUILTIN_ADMIN_AGENTS
    ]
    service = _service(existing=existing)

    service.ensure_builtin_agents(admin_id)

    assert service.session.added == [], "已存在时必须零写入"


def test_ensure_ignores_other_admins_builtin_agents():
    """归属隔离：他人的同 builtin_key 记录不算"已存在"，必须触发创建。"""
    admin_id = uuid4()
    other_id = uuid4()
    existing = [
        SimpleNamespace(builtin_key=item["builtin_key"], owner_admin_user_id=other_id)
        for item in BUILTIN_ADMIN_AGENTS
    ]
    service = _service(existing=existing)

    created = service.ensure_builtin_agents(admin_id)

    assert created == len(BUILTIN_ADMIN_AGENTS), "他人预置记录不得被复用"
    assert service.session.filter_by_calls == [
        {"owner_admin_user_id": admin_id}
    ], "存在性查询必须按 owner_admin_user_id 过滤"


def test_ensure_swallows_concurrent_duplicate_and_continues():
    """并发下已被另一请求建成：冲突被吞掉，后续条目继续创建。"""
    admin_id = uuid4()
    conflicting_key = BUILTIN_ADMIN_AGENTS[0]["builtin_key"]
    service = _service(existing=[], conflict_keys={conflicting_key})

    created = service.ensure_builtin_agents(admin_id)

    assert created == len(BUILTIN_ADMIN_AGENTS) - 1
    assert [agent.builtin_key for agent in service.session.added] == [
        item["builtin_key"]
        for item in BUILTIN_ADMIN_AGENTS
        if item["builtin_key"] != conflicting_key
    ]
    assert service.session.rollbacks == 1, "冲突的事务必须被回滚"
    assert service.session.removes == len(
        BUILTIN_ADMIN_AGENTS
    ), "每个 auto_commit 上下文退出时都必须 remove 丢弃 session（对齐 _DualAutoCommit）"


def test_ensure_rethrows_integrity_error_from_other_constraint():
    """非本索引的完整性错误不得被当成"并发已存在"吞掉。"""
    admin_id = uuid4()
    service = _service(existing=[], add_error=_integrity_error("some_other_uniq"))

    with pytest.raises(IntegrityError):
        service.ensure_builtin_agents(admin_id)


def test_ensure_swallows_integrity_error_without_diagnostics():
    """取不到 constraint_name 时按 IntegrityError 处理（fail-open）并继续。

    驱动/版本差异可能让 `orig.diag.constraint_name` 缺失；此时宁可放过一次
    真冲突，也不要把"并发已建"退化成用户可见的报错。
    """
    admin_id = uuid4()
    service = _service(
        existing=[],
        add_error=IntegrityError("INSERT INTO admin_agent ...", {}, Exception("duplicate key")),
    )

    created = service.ensure_builtin_agents(admin_id)

    assert created == len(BUILTIN_ADMIN_AGENTS) - 1


def test_ensure_rethrows_non_integrity_error():
    """表结构未迁移一类硬错误必须显式上抛，而不是记成"并发已存在"。"""
    admin_id = uuid4()
    service = _service(existing=[], add_error=RuntimeError("relation \"admin_agent\" does not exist"))

    with pytest.raises(RuntimeError):
        service.ensure_builtin_agents(admin_id)


def test_ensure_normalizes_string_admin_user_id():
    """路由层可能传字符串；入参须归一化为 UUID，且落库字段为 UUID。"""
    admin_id = uuid4()
    service = _service(existing=[])

    service.ensure_builtin_agents(str(admin_id))

    assert service.session.filter_by_calls == [{"owner_admin_user_id": admin_id}]
    assert len(service.session.added) == len(BUILTIN_ADMIN_AGENTS)
    for agent in service.session.added:
        assert isinstance(agent.owner_admin_user_id, UUID)
        assert agent.owner_admin_user_id == admin_id
