"""AdminAgentService 测试。

注意：本文件刻意实现**会真正求值过滤条件**的 query 替身（而非"filter 直接
return self"的空壳）。原因：`prune_revoked_permissions` / `list_agents` 的
owner 隔离是**安全边界**（A 管理员不得影响 B 的 Agent）；若替身忽略 filter，
测试会在"误删他人数据"的实现下依然通过——正是设计文档 §12 警告的假通过。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.sql import operators

from internal.service.admin_agent_service import AdminAgentService


class _QueryStub:
    """会按相等 / IN 条件真实过滤行的 query 替身。"""

    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *criteria, **kw):
        for crit in criteria:
            self._rows = [r for r in self._rows if _matches(r, crit)]
        return self

    def filter_by(self, **kw):
        self._rows = [
            r for r in self._rows if all(getattr(r, k, None) == v for k, v in kw.items())
        ]
        return self

    def order_by(self, *a, **kw):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows

    def count(self):
        return len(self._rows)


def _matches(row, crit) -> bool:
    """对 SQLAlchemy 二元表达式求值（仅支持本文件用到的 == 与 in_）。"""
    left = getattr(crit, "left", None)
    key = getattr(left, "key", None)
    if key is None:
        return True
    op = getattr(crit, "operator", None)
    right = crit.right
    if op is operators.in_op:
        values = getattr(right, "value", right)
        return getattr(row, key, None) in set(values)
    if op is operators.eq:
        return getattr(row, key, None) == getattr(right, "value", right)
    return True


class _SessionStub:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.added = []
        self.deleted = []

    def query(self, *a, **kw):
        return _QueryStub(self.rows)

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass


class _AutoCommit:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _service(rows=None):
    session = _SessionStub(rows)
    svc = AdminAgentService.__new__(AdminAgentService)
    svc.db = SimpleNamespace(session=session, auto_commit=lambda: _AutoCommit())
    return svc, session


def _agent(**over):
    data = {
        "id": uuid4(),
        "owner_admin_user_id": uuid4(),
        "name": "运维 Agent",
        "description": "",
        "prompt_key": None,
        "granted_permissions": [],
        "automation_policy": {},
        "budget_config": {},
        "enabled": True,
    }
    data.update(over)
    return SimpleNamespace(**data)


class TestAssignablePermissions:
    def test_returns_intersection_of_admin_and_whitelist(self):
        svc, _ = _service()
        result = svc.list_assignable_permissions(
            admin_permissions=["model_pool:read", "model_pool:update", "role:read"]
        )
        assert result == ["model_pool:read", "model_pool:update"]

    def test_excludes_banned_even_if_admin_has_it(self):
        svc, _ = _service()
        result = svc.list_assignable_permissions(
            admin_permissions=["permission:read", "admin_user:read"]
        )
        assert result == []

    def test_details_are_same_source_as_codes(self):
        """语义明细必须与 codes 同源、同序，且名称取自 PERMISSION_CATALOG。"""
        from internal.core.rbac import PERMISSION_BY_CODE

        svc, _ = _service()
        admin_perms = ["model_pool:read", "agent_pool:manage", "role:read"]
        codes = svc.list_assignable_permissions(admin_permissions=admin_perms)
        details = svc.list_assignable_permission_details(admin_permissions=admin_perms)

        # 与 codes 完全同源同序（单一事实源，不产生第二份列表）
        assert [item["code"] for item in details] == codes
        # 名称/资源/动作直接来自 RBAC 目录，而非另建的名称映射
        for item in details:
            spec = PERMISSION_BY_CODE[item["code"]]
            assert item["name"] == spec.name
            assert item["resource"] == spec.resource
            assert item["action"] == spec.action

    def test_details_exclude_banned(self):
        svc, _ = _service()
        details = svc.list_assignable_permission_details(
            admin_permissions=["role:read", "permission:read", "model_pool:read"]
        )
        assert [item["code"] for item in details] == ["model_pool:read"]


class TestCreateAgent:
    def test_rejects_granting_beyond_admin(self):
        svc, _ = _service()
        with pytest.raises(ValueError, match="无权下放"):
            svc.create_agent(
                admin_user_id=uuid4(),
                admin_permissions=["model_pool:read"],
                name="x",
                granted_permissions=["order:view"],
            )

    def test_persists_agent_with_empty_automation_policy(self):
        svc, session = _service()
        svc.create_agent(
            admin_user_id=uuid4(),
            admin_permissions=["model_pool:read"],
            name="x",
            granted_permissions=["model_pool:read"],
        )
        assert len(session.added) == 1
        created = session.added[0]
        assert created.name == "x"
        assert created.automation_policy == {}
        assert created.granted_permissions == ["model_pool:read"]

    def test_persists_budget_config_and_drops_empty_keys(self):
        svc, session = _service()
        svc.create_agent(
            admin_user_id=uuid4(),
            admin_permissions=["model_pool:read"],
            name="x",
            granted_permissions=["model_pool:read"],
            budget_config={
                "daily_executions": 5,
                "monthly_tokens": 1000,
                "daily_tokens": None,
            },
        )
        created = session.added[0]
        # 空值键不落库，闸门读路径按"未配置"处理
        assert created.budget_config == {
            "daily_executions": 5,
            "monthly_tokens": 1000,
        }

    def test_rejects_negative_budget_value(self):
        svc, _ = _service()
        with pytest.raises(ValueError, match="非法预算配置"):
            svc.create_agent(
                admin_user_id=uuid4(),
                admin_permissions=["model_pool:read"],
                name="x",
                granted_permissions=["model_pool:read"],
                budget_config={"daily_executions": -1},
            )

    def test_rejects_non_integer_budget_value(self):
        svc, _ = _service()
        with pytest.raises(ValueError, match="非法预算配置"):
            svc.create_agent(
                admin_user_id=uuid4(),
                admin_permissions=["model_pool:read"],
                name="x",
                granted_permissions=["model_pool:read"],
                budget_config={"monthly_tokens": "abc"},
            )


class TestUpdateAgent:
    def test_rejects_non_owner(self):
        owner = uuid4()
        agent = _agent(owner_admin_user_id=owner)
        svc, _ = _service([agent])
        with pytest.raises(PermissionError, match="仅创建者"):
            svc.update_agent(
                agent_id=agent.id,
                admin_user_id=uuid4(),          # 另一个管理员，不是创建者
                admin_permissions=["model_pool:read"],
                name="改名",
            )

    def test_rejects_invalid_automation_level(self):
        owner = uuid4()
        agent = _agent(owner_admin_user_id=owner)
        svc, _ = _service([agent])
        with pytest.raises(ValueError, match="非法自动化级别"):
            svc.update_agent(
                agent_id=agent.id,
                admin_user_id=owner,
                admin_permissions=["model_pool:read"],
                automation_policy={"model_pool": "yolo"},
            )

    def test_accepts_valid_automation_level(self):
        owner = uuid4()
        agent = _agent(owner_admin_user_id=owner)
        svc, _ = _service([agent])
        svc.update_agent(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["model_pool:read"],
            automation_policy={"model_pool": "autonomous"},
        )
        assert agent.automation_policy == {"model_pool": "autonomous"}

    def test_updates_budget_config(self):
        owner = uuid4()
        agent = _agent(owner_admin_user_id=owner)
        svc, _ = _service([agent])
        svc.update_agent(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["model_pool:read"],
            budget_config={"daily_executions": 3, "monthly_tokens": 500},
        )
        assert agent.budget_config == {"daily_executions": 3, "monthly_tokens": 500}

    def test_update_budget_config_absent_keeps_original(self):
        owner = uuid4()
        agent = _agent(owner_admin_user_id=owner, budget_config={"daily_executions": 3})
        svc, _ = _service([agent])
        svc.update_agent(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["model_pool:read"],
            name="改名",
        )
        assert agent.budget_config == {"daily_executions": 3}

    def test_rejects_invalid_budget_value_on_update(self):
        owner = uuid4()
        agent = _agent(owner_admin_user_id=owner)
        svc, _ = _service([agent])
        with pytest.raises(ValueError, match="非法预算配置"):
            svc.update_agent(
                agent_id=agent.id,
                admin_user_id=owner,
                admin_permissions=["model_pool:read"],
                budget_config={"daily_tokens": "x"},
            )


class TestPermissionRevocation:
    def test_prunes_revoked_permission_from_all_agents_of_admin(self):
        """管理员失权 → 立即从其名下所有 Agent 物理删除该项（§4.4）。"""
        owner = uuid4()
        a1 = _agent(owner_admin_user_id=owner,
                    granted_permissions=["model_pool:read", "order:view"])
        a2 = _agent(owner_admin_user_id=owner,
                    granted_permissions=["model_pool:read"])
        other = _agent(granted_permissions=["model_pool:read"])
        svc, _ = _service([a1, a2, other])

        removed = svc.prune_revoked_permissions(
            admin_user_id=owner,
            admin_permissions=["order:view"],   # model_pool:read 已失去
        )

        # 返回值语义是"(agent, permission) 组合数"：a1 失 1 项 + a2 失 1 项 = 2。
        # 注意：这与"受影响 agent 数"（2）恰好相同，但与"仅 a1 被改"（1）不同——
        # 实现若不按 owner 过滤，还会把 other 的 1 项也算进来（=3），被下方断言抓住。
        assert removed == 2
        assert a1.granted_permissions == ["order:view"]
        assert a2.granted_permissions == []
        # 他人 Agent 不受影响
        assert other.granted_permissions == ["model_pool:read"]

    def test_noop_when_admin_still_has_permission(self):
        owner = uuid4()
        a1 = _agent(owner_admin_user_id=owner,
                    granted_permissions=["model_pool:read"])
        svc, _ = _service([a1])

        removed = svc.prune_revoked_permissions(
            admin_user_id=owner,
            admin_permissions=["model_pool:read"],
        )

        assert removed == 0
        assert a1.granted_permissions == ["model_pool:read"]

    def test_prunes_permission_that_left_whitelist(self):
        """即使管理员仍持有，若该权限已不在白名单，也应清理。"""
        owner = uuid4()
        a1 = _agent(owner_admin_user_id=owner,
                    granted_permissions=["role:read"])
        svc, _ = _service([a1])

        removed = svc.prune_revoked_permissions(
            admin_user_id=owner,
            admin_permissions=["role:read"],
        )

        assert removed == 1
        assert a1.granted_permissions == []
