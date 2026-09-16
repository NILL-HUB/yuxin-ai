"""板块工具与 principal 装配测试（设计 §4.1 运行时实时重算 / §7.1）。"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.exception import FailException
from internal.service.admin_agent_service import AdminAgentService


class _QueryStub:
    def __init__(self, row):
        self._row = row

    def filter(self, *a, **kw):
        return self

    def first(self):
        return self._row


class _SessionStub:
    def __init__(self, row):
        self._row = row

    def query(self, *a, **kw):
        return _QueryStub(self._row)


def _agent(owner, granted, policy=None, enabled=True):
    return SimpleNamespace(
        id=uuid4(),
        owner_admin_user_id=owner,
        name="运维 Agent",
        granted_permissions=list(granted),
        automation_policy=policy or {},
        enabled=enabled,
    )


class TestGetPrincipal:
    def test_effective_is_intersection_of_three_sets(self):
        """运行时必须实时重算三重交集，不读静态快照。"""
        owner = uuid4()
        agent = _agent(owner, ["builtin_tool:read", "builtin_tool:update", "role:read"])
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))

        principal = svc.get_principal(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=[
                "builtin_tool:read",
                "builtin_tool:update",
                "model_pool:read",
            ],
        )

        # role:read 被封禁、model_pool:read 未下放，都应被剔除
        assert principal.effective_permissions == frozenset(
            {"builtin_tool:read", "builtin_tool:update"}
        )
        assert principal.admin_user_id == owner
        assert principal.agent_id == agent.id
        assert principal.agent_name == "运维 Agent"

    def test_admin_losing_permission_shrinks_agent_immediately(self):
        """管理员失权后，即使 granted 里还有，effective 也必须立即收紧。"""
        owner = uuid4()
        agent = _agent(owner, ["builtin_tool:read", "builtin_tool:update"])
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))

        principal = svc.get_principal(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["builtin_tool:read"],
        )
        assert principal.effective_permissions == frozenset({"builtin_tool:read"})

    def test_granted_beyond_assignable_is_dropped(self):
        """granted 里混入封禁权限点时必须被三重交集剔除（纵深防御）。"""
        owner = uuid4()
        agent = _agent(owner, ["role:delete", "permission:read", "builtin_tool:read"])
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))
        principal = svc.get_principal(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["role:delete", "permission:read", "builtin_tool:read"],
        )
        assert principal.effective_permissions == frozenset({"builtin_tool:read"})

    def test_automation_policy_is_parsed_to_enum(self):
        owner = uuid4()
        agent = _agent(
            owner, ["builtin_tool:update"], policy={"builtin_tool": "autonomous"}
        )
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))
        principal = svc.get_principal(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["builtin_tool:update"],
        )
        assert principal.automation_level_for("builtin_tool") is AutomationLevel.AUTONOMOUS
        # 未配置的板块 fail closed 到 supervised
        assert (
            principal.automation_level_for("prompt_template")
            is AutomationLevel.SUPERVISED
        )

    def test_invalid_automation_level_is_dropped_not_crashed(self):
        """非法级别被丢弃 → principal 兜底到 supervised（而不是抛错或放行）。"""
        owner = uuid4()
        agent = _agent(
            owner,
            ["builtin_tool:update"],
            policy={"builtin_tool": "god_mode", "prompt_template": "autonomous"},
        )
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))
        principal = svc.get_principal(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["builtin_tool:update"],
        )
        assert (
            principal.automation_level_for("builtin_tool")
            is AutomationLevel.SUPERVISED
        )
        assert (
            principal.automation_level_for("prompt_template")
            is AutomationLevel.AUTONOMOUS
        )

    def test_disabled_agent_is_rejected(self):
        owner = uuid4()
        agent = _agent(owner, ["builtin_tool:read"], enabled=False)
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))
        with pytest.raises(PermissionError, match="已停用"):
            svc.get_principal(
                agent_id=agent.id,
                admin_user_id=owner,
                admin_permissions=["builtin_tool:read"],
            )

    def test_non_owner_is_rejected(self):
        owner = uuid4()
        agent = _agent(owner, ["builtin_tool:read"])
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))
        with pytest.raises(PermissionError, match="仅创建者"):
            svc.get_principal(
                agent_id=agent.id,
                admin_user_id=uuid4(),
                admin_permissions=["builtin_tool:read"],
            )

    def test_missing_agent_returns_none(self):
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(None)))
        assert (
            svc.get_principal(
                agent_id=uuid4(), admin_user_id=uuid4(), admin_permissions=[]
            )
            is None
        )


def _principal(perms=None, policy=None):
    return AdminAgentPrincipal(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        agent_name="运维 Agent",
        effective_permissions=frozenset(
            perms if perms is not None else {"builtin_tool:read", "builtin_tool:update"}
        ),
        automation_policy=policy or {},
    )


class TestBoardToolPermissionGate:
    def test_action_without_permission_is_refused(self):
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        executor = BoardToolExecutor()
        with pytest.raises(PermissionError, match="无权限"):
            executor.assert_allowed(
                _principal(perms={"builtin_tool:read"}),
                board="builtin_tool",
                action="update_enabled",
            )

    def test_read_action_allowed_with_read_permission(self):
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        executor = BoardToolExecutor()
        executor.assert_allowed(
            _principal(perms={"builtin_tool:read"}),
            board="builtin_tool",
            action="list",
        )

    def test_blocked_board_is_refused_even_with_permission(self):
        """blocked 档是应急熔断：即使有权限也不执行。"""
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        executor = BoardToolExecutor()
        with pytest.raises(PermissionError, match="熔断"):
            executor.assert_allowed(
                _principal(policy={"builtin_tool": AutomationLevel.BLOCKED}),
                board="builtin_tool",
                action="update_enabled",
            )

    def test_undeclared_action_is_refused(self):
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        executor = BoardToolExecutor()
        with pytest.raises(ValueError):
            executor.assert_allowed(
                _principal(), board="builtin_tool", action="nope"
            )

    def test_requires_draft_only_for_supervised(self):
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        executor = BoardToolExecutor()
        assert executor.requires_draft(
            _principal(policy={"builtin_tool": AutomationLevel.SUPERVISED}),
            "builtin_tool",
        )
        assert not executor.requires_draft(
            _principal(policy={"builtin_tool": AutomationLevel.AUTONOMOUS}),
            "builtin_tool",
        )
        # 未配置 → supervised（fail closed）
        assert executor.requires_draft(_principal(), "builtin_tool")


class TestBuiltinToolActionValidation:
    """板块实现体的入参校验必须在触碰真实依赖之前完成。"""

    def test_update_enabled_requires_tool_id_and_bool(self):
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        executor = BoardToolExecutor()
        with pytest.raises(FailException, match="tool_id"):
            executor.execute(
                _principal(policy={"builtin_tool": AutomationLevel.AUTONOMOUS}),
                board="builtin_tool",
                action="update_enabled",
                payload={},
            )
        with pytest.raises(FailException, match="tool_id"):
            executor.execute(
                _principal(policy={"builtin_tool": AutomationLevel.AUTONOMOUS}),
                board="builtin_tool",
                action="update_enabled",
                payload={"tool_id": "t1", "enabled": "yes"},
            )

    def test_update_metadata_requires_tool_id(self):
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        executor = BoardToolExecutor()
        with pytest.raises(FailException, match="tool_id"):
            executor.execute(
                _principal(policy={"builtin_tool": AutomationLevel.AUTONOMOUS}),
                board="builtin_tool",
                action="update_metadata",
                payload={},
            )

    def test_update_metadata_rejects_empty_editable_fields(self):
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        executor = BoardToolExecutor()
        with pytest.raises(FailException, match="至少需要"):
            executor.execute(
                _principal(policy={"builtin_tool": AutomationLevel.AUTONOMOUS}),
                board="builtin_tool",
                action="update_metadata",
                payload={"tool_id": "t1", "enabled": False},
            )


class TestAvailableBoards:
    def test_available_boards_matches_registry(self):
        from internal.core.admin_agent_boards import BOARD_IDS
        from internal.service.admin_agent_board_tools import available_boards

        assert set(available_boards()) == set(BOARD_IDS)
