"""板块动作注册表测试（设计 §7.1 执行四步的第 1 步）。

核心不变式：**未声明的 action 必须被拒绝**（fail closed）。
工具内部按 action 分支，若校验漏了某个 action 就会越权，因此
"未声明即拒绝"是本设计的硬约束。
"""
import pytest

from internal.core.admin_agent_boards import (
    BOARD_ACTIONS,
    BOARD_IDS,
    board_ids_of,
    boards,
    resolve_action,
)


class TestBoardActionRegistry:
    def test_registry_is_not_empty(self):
        """守卫：注册表为空会让所有测试恒真。"""
        assert len(BOARD_ACTIONS) > 0
        assert len(BOARD_IDS) > 0

    def test_builtin_tool_board_is_registered(self):
        """P1b 的样板板块必须已登记。"""
        assert "builtin_tool" in BOARD_IDS

    def test_every_action_declares_a_real_permission_code(self):
        """每个 action 必须显式声明所需权限点，且必须是真实存在的 code。

        否则工具会在运行时因权限点不存在而永远拒绝（或更糟：被误实现为放行）。
        """
        from internal.core.rbac import PERMISSION_BY_CODE

        for action in BOARD_ACTIONS:
            assert action.permission_code, f"{action} 未声明 permission_code"
            assert action.permission_code in PERMISSION_BY_CODE, (
                f"{action} 声明的 {action.permission_code} 不在权限目录中"
            )

    def test_every_action_is_assignable_or_readonly_user_scope(self):
        """板块 action 的权限点必须**可下放**，否则 Agent 永远无权执行。

        这是"板块可被授权"的前提：若某个 action 声明了被封禁的权限点
        （如 role:*），该板块对 Agent 就是死代码。
        """
        from internal.core.admin_agent_authorization import is_assignable

        for action in BOARD_ACTIONS:
            assert is_assignable(action.permission_code), (
                f"{action.board}.{action.action} 声明的 {action.permission_code} 不可下放，"
                "该 action 对 Agent 永远不可达"
            )

    def test_resolve_action_returns_declared_action(self):
        action = resolve_action("builtin_tool", "update_enabled")
        assert action.permission_code == "builtin_tool:update"
        assert action.is_write is True

    def test_unknown_action_is_rejected(self):
        """未声明的 action 必须抛错（fail closed）。"""
        with pytest.raises(ValueError):
            resolve_action("builtin_tool", "drop_everything")

    def test_unknown_board_is_rejected(self):
        with pytest.raises(ValueError):
            resolve_action("not_a_board", "list")

    def test_blank_inputs_are_rejected(self):
        with pytest.raises(ValueError):
            resolve_action("", "list")
        with pytest.raises(ValueError):
            resolve_action("builtin_tool", "")

    def test_board_ids_are_derived_from_actions(self):
        """BOARD_IDS 必须由 BOARD_ACTIONS 派生，不允许手工维护两个清单。"""
        assert set(BOARD_IDS) == {a.board for a in BOARD_ACTIONS}
        assert set(boards()) == set(BOARD_IDS)

    def test_board_ids_of_lists_actions_of_one_board(self):
        ids = board_ids_of("builtin_tool")
        assert "update_enabled" in ids
        assert set(ids) == {
            a.action for a in BOARD_ACTIONS if a.board == "builtin_tool"
        }

    def test_every_board_has_at_least_one_read_action(self):
        """每个板块至少要有只读 action。

        否则 Agent 无法了解现状再动手（只能盲改），这与 board_agent.yaml 里
        "动手前先调用只读动作了解现状"的工作方式相矛盾。
        """
        for board in BOARD_IDS:
            kinds = {a.kind for a in BOARD_ACTIONS if a.board == board}
            assert "read" in kinds, f"板块 {board} 没有任何只读 action"

    def test_read_actions_are_not_write(self):
        action = resolve_action("builtin_tool", "list")
        assert action.kind == "read"
        assert action.is_write is False

    def test_action_keys_are_unique(self):
        """同一 (board, action) 不得重复登记，否则后者会静默覆盖前者。"""
        keys = [(a.board, a.action) for a in BOARD_ACTIONS]
        assert len(keys) == len(set(keys))
