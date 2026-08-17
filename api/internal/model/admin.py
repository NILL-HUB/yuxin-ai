from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UUID,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AdminUser(Base):
    __tablename__ = "admin_user"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_admin_user_id"),
        UniqueConstraint("username", name="uq_admin_user_username"),
        UniqueConstraint("email", name="uq_admin_user_email"),
        Index("admin_user_username_idx", "username"),
        Index("admin_user_email_idx", "email"),
        Index("admin_user_account_id_idx", "account_id"),
        Index("admin_user_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
    username = Column(String(64), nullable=False, server_default=text("''::character varying"))
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    email = Column(String(255), nullable=True, server_default=text("''::character varying"))
    avatar = Column(String(255), nullable=False, server_default=text("''::character varying"))
    password = Column(String(255), nullable=True, server_default=text("''::character varying"))
    password_salt = Column(String(255), nullable=True, server_default=text("''::character varying"))
    # 密码哈希格式版本：1=PBKDF2 10k 迭代（历史），2=PBKDF2 600k 迭代（当前）
    password_version = Column(Integer, nullable=False, server_default=text("'1'"))
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(255), nullable=False, server_default=text("''::character varying"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    roles = relationship("AdminUserRole", back_populates="admin_user", lazy="selectin")
    sessions = relationship("AdminSession", back_populates="admin_user", lazy="selectin")

    @property
    def is_password_set(self) -> bool:
        return self.password is not None and self.password != ""

    @property
    def is_active(self) -> bool:
        return self.status == "active"


class AdminSession(Base):
    __tablename__ = "admin_session"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_admin_session_id"),
        Index("admin_session_admin_user_id_idx", "admin_user_id"),
        Index("admin_session_revoked_at_idx", "revoked_at"),
        Index("admin_session_expires_at_idx", "expires_at"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    admin_user_id = Column(UUID, ForeignKey("admin_user.id"), nullable=False)
    user_agent = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    last_login_ip = Column(String(255), nullable=False, server_default=text("''::character varying"))
    last_active_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    admin_user = relationship("AdminUser", back_populates="sessions", lazy="joined")

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is None:
            return True
        return self.expires_at >= _utcnow_naive()


class Role(Base):
    __tablename__ = "role"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_role_id"),
        UniqueConstraint("code", name="uq_role_code"),
        Index("role_code_idx", "code"),
        Index("role_is_system_idx", "is_system"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    code = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    is_system = Column(Boolean, nullable=False, server_default=text("false"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    admin_users = relationship("AdminUserRole", back_populates="role", lazy="selectin")
    permissions = relationship("RolePermission", back_populates="role", lazy="selectin")


class Permission(Base):
    __tablename__ = "permission"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_permission_id"),
        UniqueConstraint("code", name="uq_permission_code"),
        Index("permission_code_idx", "code"),
        Index("permission_resource_action_idx", "resource", "action"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    code = Column(String(255), nullable=False, server_default=text("''::character varying"))
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    resource = Column(String(255), nullable=False, server_default=text("''::character varying"))
    action = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    roles = relationship("RolePermission", back_populates="permission", lazy="selectin")


class AdminUserRole(Base):
    __tablename__ = "admin_user_role"
    __table_args__ = (
        PrimaryKeyConstraint("admin_user_id", "role_id", name="pk_admin_user_role"),
        Index("admin_user_role_admin_user_id_idx", "admin_user_id"),
        Index("admin_user_role_role_id_idx", "role_id"),
    )

    admin_user_id = Column(UUID, ForeignKey("admin_user.id"), nullable=False)
    role_id = Column(UUID, ForeignKey("role.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    admin_user = relationship("AdminUser", back_populates="roles", lazy="joined")
    role = relationship("Role", back_populates="admin_users", lazy="joined")


class RolePermission(Base):
    __tablename__ = "role_permission"
    __table_args__ = (
        PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permission"),
        Index("role_permission_role_id_idx", "role_id"),
        Index("role_permission_permission_id_idx", "permission_id"),
    )

    role_id = Column(UUID, ForeignKey("role.id"), nullable=False)
    permission_id = Column(UUID, ForeignKey("permission.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    role = relationship("Role", back_populates="permissions", lazy="joined")
    permission = relationship("Permission", back_populates="roles", lazy="joined")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_audit_log_id"),
        Index("audit_log_admin_user_id_idx", "admin_user_id"),
        Index("audit_log_account_id_idx", "account_id"),
        Index("audit_log_action_idx", "action"),
        Index("audit_log_resource_type_idx", "resource_type"),
        Index("audit_log_created_at_idx", "created_at"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    admin_user_id = Column(UUID, ForeignKey("admin_user.id"), nullable=True)
    account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
    action = Column(String(255), nullable=False, server_default=text("''::character varying"))
    resource_type = Column(String(255), nullable=False, server_default=text("''::character varying"))
    resource_id = Column(String(255), nullable=False, server_default=text("''::character varying"))
    ip = Column(String(255), nullable=False, server_default=text("''::character varying"))
    user_agent = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    before_data = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    after_data = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    admin_user = relationship("AdminUser", foreign_keys=[admin_user_id], lazy="joined")
    account = relationship("Account", foreign_keys=[account_id], lazy="joined")
