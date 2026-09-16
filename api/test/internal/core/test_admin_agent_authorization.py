"""管理端 Agent 授权内核单测。

覆盖设计文档 §4.2（可下放白名单）与 §4.1（三重交集）。
"""
from internal.core.admin_agent_authorization import (
    ASSIGNABLE_PERMISSIONS,
    BANNED_PERMISSION_CODES,
    assert_grantable,
    compute_effective_permissions,
)
from internal.core.rbac import PERMISSION_CATALOG


class TestAssignableWhitelist:
    def test_banned_codes_are_excluded(self):
        """封禁项一律不在白名单：身份与权限体系不可下放。"""
        for code in BANNED_PERMISSION_CODES:
            assert code not in ASSIGNABLE_PERMISSIONS, f"{code} 不应可下放"

    def test_user_write_ops_excluded_but_read_allowed(self):
        """用户管理只读可下放，写操作不可（设计 §4.2）。"""
        assert "user:read" in ASSIGNABLE_PERMISSIONS
        for code in ("user:create", "user:update", "user:disable", "user:delete"):
            assert code not in ASSIGNABLE_PERMISSIONS, f"{code} 不应可下放"

    def test_whitelist_is_subset_of_catalog(self):
        """白名单不得出现目录外的幽灵权限点。"""
        catalog = {spec.code for spec in PERMISSION_CATALOG}
        assert ASSIGNABLE_PERMISSIONS <= catalog

    def test_model_pool_and_tool_governance_are_assignable(self):
        """设计 §4.3 举例：模型池/工具池/Agent池 应可下放。"""
        for code in (
            "model_pool:read", "model_pool:update",
            "tool_governance:read", "tool_governance:manage",
            "agent_pool:read", "agent_pool:manage",
        ):
            assert code in ASSIGNABLE_PERMISSIONS, f"{code} 应可下放"

    def test_fail_closed_for_unknown_resource(self, monkeypatch):
        """未显式登记的资源前缀默认不可下放（fail closed）。

        为什么必须注入合成 spec：现存目录中「resource 未登记」的权限点
        （admin / admin_user / permission / role）**恰好都在 BANNED 集合里**，
        因此用真实权限点会在 banned 分支提前返回，**根本走不到 resource 判断**，
        测试会假通过（把 resource 检查删掉也测不出来）。

        这里 monkeypatch 一个合成权限点（resource 为全新前缀），确保真正
        命中 resource 分支：这正是"新增权限点默认不可下放"的场景。
        """
        import internal.core.admin_agent_authorization as authz
        from internal.core.rbac import PermissionSpec

        synthetic = PermissionSpec(
            "brand_new_board:read", "查看新板块", "brand_new_board", "read"
        )
        patched = dict(authz.PERMISSION_BY_CODE)
        patched[synthetic.code] = synthetic
        monkeypatch.setattr(authz, "PERMISSION_BY_CODE", patched)

        # 走到 resource 分支：resource 未登记 → 拒绝（fail closed）
        assert authz.is_assignable("brand_new_board:read") is False
        # 对照：已登记 resource 的权限点仍可下放，证明不是"一律拒绝"
        assert authz.is_assignable("model_pool:read") is True

    def test_new_permission_point_defaults_to_not_assignable(self, monkeypatch):
        """新增权限点若未显式登记 resource，不得自动进入白名单。

        这是 fail-closed 的核心承诺：``initialize_defaults()`` 只增不删，
        未来新增权限点会直接进目录；若白名单是"黑名单式"的，它会静默
        暴露给 Agent。
        """
        import internal.core.admin_agent_authorization as authz
        from internal.core.rbac import PermissionSpec

        synthetic = PermissionSpec(
            "future_feature:manage", "管理未来功能", "future_feature", "manage"
        )
        patched = dict(authz.PERMISSION_BY_CODE)
        patched[synthetic.code] = synthetic
        monkeypatch.setattr(authz, "PERMISSION_BY_CODE", patched)

        assert authz.is_assignable("future_feature:manage") is False


class TestTripleIntersection:
    def test_effective_is_three_way_intersection(self):
        """effective = admin ∩ granted ∩ assignable，三者缺一不可。"""
        effective = compute_effective_permissions(
            admin_permissions=["model_pool:read", "model_pool:update", "role:read"],
            granted_permissions=["model_pool:read", "model_pool:update", "order:view"],
        )
        # role:read 被白名单剔除；order:view 管理员没有
        assert effective == frozenset({"model_pool:read", "model_pool:update"})

    def test_admin_losing_permission_shrinks_effective(self):
        """管理员失权后，即使 Agent 仍挂着该权限，effective 立即收紧。"""
        effective = compute_effective_permissions(
            admin_permissions=["model_pool:read"],
            granted_permissions=["model_pool:read", "model_pool:update"],
        )
        assert effective == frozenset({"model_pool:read"})

    def test_empty_when_no_overlap(self):
        effective = compute_effective_permissions(
            admin_permissions=["model_pool:read"],
            granted_permissions=["order:view"],
        )
        assert effective == frozenset()

    def test_banned_permission_never_effective(self):
        """即使管理员自身持有 role:read 且显式下放，也不得生效。"""
        effective = compute_effective_permissions(
            admin_permissions=["role:read"],
            granted_permissions=["role:read"],
        )
        assert effective == frozenset()


class TestAssertGrantable:
    def test_rejects_permission_admin_lacks(self):
        """保存时后端独立校验：UI 过滤不是安全边界，直连 API 必须被拒。"""
        import pytest
        with pytest.raises(ValueError, match="无权下放"):
            assert_grantable(
                requested=["order:view"],
                admin_permissions=["model_pool:read"],
            )

    def test_rejects_banned_permission(self):
        import pytest
        with pytest.raises(ValueError, match="不可下放"):
            assert_grantable(
                requested=["role:read"],
                admin_permissions=["role:read"],
            )

    def test_accepts_valid_subset(self):
        assert_grantable(
            requested=["model_pool:read", "model_pool:update"],
            admin_permissions=["model_pool:read", "model_pool:update", "order:view"],
        )
