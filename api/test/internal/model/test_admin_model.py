from datetime import UTC, datetime, timedelta
from uuid import uuid4

from internal.model import admin as admin_model


class TestAdminUserModel:
    def test_admin_user_should_expose_password_and_status_properties(self):
        active_user = admin_model.AdminUser(password="hashed", status="active")
        disabled_user = admin_model.AdminUser(password="", status="disabled")
        pending_user = admin_model.AdminUser(password=None, status="pending")

        assert active_user.is_password_set is True
        assert active_user.is_active is True
        assert disabled_user.is_password_set is False
        assert disabled_user.is_active is False
        assert pending_user.is_password_set is False
        assert pending_user.is_active is False


class TestAdminSessionModel:
    def test_admin_session_is_active_should_reflect_expired_and_revoked_state(self):
        active_session = admin_model.AdminSession(
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10),
            revoked_at=None,
        )
        revoked_session = admin_model.AdminSession(
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10),
            revoked_at=datetime.now(UTC).replace(tzinfo=None),
        )
        expired_session = admin_model.AdminSession(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
            revoked_at=None,
        )
        non_expiring_session = admin_model.AdminSession(expires_at=None, revoked_at=None)

        assert active_session.is_active is True
        assert revoked_session.is_active is False
        assert expired_session.is_active is False
        assert non_expiring_session.is_active is True


class TestAdminRbacModels:
    def test_rbac_models_should_use_expected_table_names_and_constraints(self):
        assert admin_model.AdminUser.__tablename__ == "admin_user"
        assert admin_model.AdminSession.__tablename__ == "admin_session"
        assert admin_model.Role.__tablename__ == "role"
        assert admin_model.Permission.__tablename__ == "permission"
        assert admin_model.AdminUserRole.__tablename__ == "admin_user_role"
        assert admin_model.RolePermission.__tablename__ == "role_permission"
        assert admin_model.AuditLog.__tablename__ == "audit_log"

        assert admin_model.AdminUserRole.__table__.primary_key.columns.keys() == ["admin_user_id", "role_id"]
        assert admin_model.RolePermission.__table__.primary_key.columns.keys() == ["role_id", "permission_id"]

    def test_role_and_permission_should_match_rad_fields(self):
        role = admin_model.Role(name="operator", code="operator", is_system=True)
        permission = admin_model.Permission(
            code="app:read",
            name="应用查看",
            resource="app",
            action="read",
        )

        assert role.name == "operator"
        assert role.code == "operator"
        assert role.is_system is True
        assert permission.code == "app:read"
        assert permission.resource == "app"
        assert permission.action == "read"

    def test_admin_models_should_define_unique_business_keys(self):
        assert "uq_admin_user_email" in {constraint.name for constraint in admin_model.AdminUser.__table__.constraints}
        assert "uq_role_code" in {constraint.name for constraint in admin_model.Role.__table__.constraints}
        assert "uq_permission_code" in {constraint.name for constraint in admin_model.Permission.__table__.constraints}

    def test_audit_log_should_capture_admin_action_context(self):
        admin_user_id = uuid4()
        before_data = {"status": "active"}
        after_data = {"status": "disabled"}
        audit_log = admin_model.AuditLog(
            admin_user_id=admin_user_id,
            action="admin_user:disable",
            resource_type="admin_user",
            resource_id=str(uuid4()),
            ip="127.0.0.1",
            user_agent="pytest",
            before_data=before_data,
            after_data=after_data,
        )

        assert audit_log.admin_user_id == admin_user_id
        assert audit_log.action == "admin_user:disable"
        assert audit_log.resource_type == "admin_user"
        assert audit_log.ip == "127.0.0.1"
        assert audit_log.before_data == before_data
        assert audit_log.after_data == after_data
