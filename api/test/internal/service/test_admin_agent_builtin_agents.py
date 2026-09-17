"""预置 Agent 幂等补建测试（设计 §10.3）。

关键不变量：
1. 幂等：重复调用不产生重复记录（靠 builtin_key 唯一索引兜底）；
2. **不下放权限**：预置 Agent 的 granted_permissions 必须为空——
   权限只能由管理员显式下放（设计 §4.3），系统预置不得绕过；
3. 未配置 automation_policy → 运行时按 supervised 处理（fail closed）。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.admin_agent_builtin_agents import (
    BUILTIN_ADMIN_AGENTS,
    AdminAgentBuiltinService,
)


class _Query:
    def __init__(self, rows):
        self._rows = list(rows)
        self._created = None

    def filter_by(self, **kwargs):
        self._kwargs = kwargs
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


def _service(existing=None):
    service = AdminAgentBuiltinService.__new__(AdminAgentBuiltinService)
    rows = list(existing or [])
    created = []

    class _Session:
        def query(self, model):
            return _Query(rows)

        def add(self, obj):
            created.append(obj)

    class _AutoCommit:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    service.db = SimpleNamespace(session=_Session(), auto_commit=lambda: _AutoCommit())
    service.created = created
    return service


def test_builtin_list_is_non_empty_and_keys_unique():
    keys = [item["builtin_key"] for item in BUILTIN_ADMIN_AGENTS]
    assert keys, "至少要有运维/运营两个预置 Agent"
    assert len(keys) == len(set(keys))


def test_ensure_creates_missing_agents_without_granting_permissions():
    admin_id = uuid4()
    service = _service(existing=[])

    service.ensure_builtin_agents(admin_id)

    assert len(service.created) == len(BUILTIN_ADMIN_AGENTS)
    for agent in service.created:
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

    assert service.created == [], "已存在时必须零写入"
