import base64
import logging
import math
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

from internal.exception import FailException, NotFoundException, UnauthorizedException
from internal.core.rbac import SUPER_ADMIN_ROLE_CODE, all_permission_codes
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.admin import AdminSession, AdminUser, AdminUserRole, Permission, Role, RolePermission
from internal.service.audit_log_service import AuditLogService
from internal.service.jwt_service import JwtService
from pkg.password import (
    PASSWORD_HASH_VERSION_CURRENT,
    compare_password,
    hash_password,
    password_iterations_for_version,
    validate_password,
)

logger = logging.getLogger(__name__)

# 平台系统账号用户名（辅助 Agent 等内部服务使用的系统账号，不参与用户/应用分配管理）
SYSTEM_OWNER_ACCOUNT_USERNAME = "yuxin_ai"

# 禁止作为超级管理员初始密码的弱口令集合（H-2 部署默认凭据加固）。
# 命中任意一项时拒绝自动创建超级管理员，防止服务以弱密码上线。
_WEAK_ADMIN_PASSWORDS = frozenset(
    {
        "admin",
        "admin123",
        "administrator",
        "password",
        "password123",
        "root",
        "root123",
        "root123456",
        "123456",
        "12345678",
        "123456789",
        "1234567890",
        "123123",
        "666666",
        "888888",
        "abc123",
        "qwerty",
        "qwerty123",
        "a123456",
        "yuxin_ai123",
        "Root123456",
        "P@ssw0rd",
        "P@ssw0rd123",
    }
)


class AdminUserService:
    DEFAULT_TOKEN_EXPIRE_SECONDS = 60 * 60 * 24 * 7
    # 管理员会话活跃时间刷新节流间隔（参考 account_service.SESSION_TOUCH_INTERVAL_SECONDS）
    ADMIN_SESSION_TOUCH_INTERVAL_SECONDS = 5 * 60
    # 在线判定阈值：近 10 分钟内有活跃会话即视为在线
    ONLINE_THRESHOLD_MINUTES = 10

    def __init__(self, session=None, jwt_service=None, audit_log_service=None):
        self.session = session or db.session
        self.jwt_service = jwt_service or JwtService
        self.audit_log_service = audit_log_service or AuditLogService(session=self.session)

    def _emit_audit(
        self,
        *,
        operator_id,
        action: str,
        resource_type: str,
        resource_id: str = "",
        ip: str = "",
        user_agent: str = "",
        before_data: dict | None = None,
        after_data: dict | None = None,
    ) -> None:
        if not operator_id:
            return
        self.audit_log_service.record_for_write(
            admin_user_id=operator_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=after_data,
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _normalize_email(email: str) -> str:
        return (email or "").strip().lower()

    @staticmethod
    def _normalize_username(username: str) -> str:
        return (username or "").strip()

    @staticmethod
    def _normalize_identifier(identifier: str) -> str:
        return (identifier or "").strip()

    def initialize_super_admin_from_env(self) -> dict[str, object]:
        username = self._normalize_username(os.getenv("ADMIN_INITIAL_USERNAME", "admin"))
        email = os.getenv("ADMIN_INITIAL_EMAIL", "").strip().lower()
        password = os.getenv("ADMIN_INITIAL_PASSWORD", "")
        name = os.getenv("ADMIN_INITIAL_NAME", "").strip() or "超级管理员"
        if not username or not password:
            return {"created": False, "reason": "missing_env"}
        try:
            validate_password(password)
        except ValueError:
            return {"created": False, "reason": "invalid_password"}
        # H-2：拒绝弱口令作为初始密码，避免服务以默认凭据上线被扫描器直接接管
        if password.lower() in _WEAK_ADMIN_PASSWORDS or password == "Root123456":
            logger.warning(
                "ADMIN_INITIAL_PASSWORD 命中弱口令黑名单，已跳过超级管理员自动创建。"
                "请配置强密码后重新启动。"
            )
            return {"created": False, "reason": "weak_password"}
        existing_user = self.session.query(AdminUser).filter(AdminUser.username == username).one_or_none()
        if existing_user is not None:
            return {"created": False, "reason": "exists"}
        super_admin_role = self.session.query(Role).filter(Role.code == "super_admin").one_or_none()
        if super_admin_role is None:
            return {"created": False, "reason": "missing_super_admin_role"}
        if self._get_active_super_admin_user(exclude_admin_user_id=None) is not None:
            return {"created": False, "reason": "super_admin_exists"}
        if email:
            existing_email_user = self.session.query(AdminUser).filter(AdminUser.email == email).one_or_none()
            if existing_email_user is not None:
                return {"created": False, "reason": "exists"}
        salt = os.urandom(16)
        password_hashed = hash_password(password, salt)
        admin_user = AdminUser(
            account_id=None,
            username=username,
            email=email,
            name=name,
            password=base64.b64encode(password_hashed).decode(),
            password_salt=base64.b64encode(salt).decode(),
            password_version=PASSWORD_HASH_VERSION_CURRENT,
            status="active",
        )
        self.session.add(admin_user)
        self.session.flush()
        self.session.add(AdminUserRole(admin_user_id=admin_user.id, role_id=super_admin_role.id))
        self.session.commit()
        return {"created": True, "reason": "created"}

    def password_login(
        self,
        identifier: str,
        password: str,
        client_ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        """管理员密码登录。

        登录 IP/UA 由调用方（Quart 端点）从请求中提取后传入，
        不直接依赖 Flask request（Quart 单栈下无 Flask request context）。
        """
        generic_error_message = "账号不存在或者密码错误"
        identifier = self._normalize_identifier(identifier)
        normalized_email = self._normalize_email(identifier)
        admin_user = (
            self.session.query(AdminUser)
            .filter((AdminUser.username == identifier) | (AdminUser.email == normalized_email))
            .one_or_none()
        )
        if admin_user is None or not admin_user.is_password_set:
            raise FailException(generic_error_message, reason_code="INVALID_ADMIN_CREDENTIALS")
        if not admin_user.is_active:
            raise FailException("管理员账号已被禁用")
        if not compare_password(
            password,
            admin_user.password,
            admin_user.password_salt,
            iterations=password_iterations_for_version(
                getattr(admin_user, "password_version", 1)
            ),
        ):
            raise FailException(generic_error_message, reason_code="INVALID_ADMIN_CREDENTIALS")
        # 登录成功后透明升级旧参数密码哈希
        self._rehash_admin_password_if_outdated(admin_user, password)
        now = self._now()
        expires_at = now + timedelta(seconds=self.DEFAULT_TOKEN_EXPIRE_SECONDS)
        # 更新最后登录信息（IP/UA 由调用方传入，避免依赖 Flask request）
        admin_user.last_login_at = now
        admin_user.last_login_ip = client_ip
        admin_session = AdminSession(
            admin_user_id=admin_user.id,
            last_active_at=now,
            expires_at=expires_at,
            last_login_ip=client_ip,
            user_agent=user_agent,
        )
        self.session.add(admin_session)
        self.session.flush()
        access_token = self.jwt_service.generate_token({
            "sub": str(admin_user.id),
            "realm": "admin",
            "session_id": str(admin_session.id),
            "exp": datetime.now(UTC) + timedelta(seconds=self.DEFAULT_TOKEN_EXPIRE_SECONDS),
        })
        self.session.commit()
        return {
            "access_token": access_token,
            "admin_access_token": access_token,
            "expire_at": int(expires_at.replace(tzinfo=UTC).timestamp()),
            "admin_user": self._serialize_current_admin_user(admin_user),
        }

    def parse_admin_token(self, token: str) -> dict[str, object]:
        payload = self.jwt_service.parse_token(token)
        if payload.get("realm") != "admin" or not payload.get("sub") or not payload.get("session_id"):
            raise UnauthorizedException("管理员认证失败，请重新登录")
        return payload

    def get_current_admin_from_token(self, token: str) -> dict[str, object]:
        admin_user, admin_session = self._resolve_admin_user_and_session(token)
        return self._serialize_current_admin_user(admin_user)

    def logout(self, token: str) -> None:
        _, admin_session = self._resolve_admin_user_and_session(token)
        admin_session.revoked_at = self._now()
        self.session.commit()

    def _rehash_admin_password_if_outdated(self, admin_user: AdminUser, password: str) -> None:
        """登录成功后透明升级旧参数哈希：若密码版本低于当前版本则重新哈希并原地升级。"""
        if int(getattr(admin_user, "password_version", 1) or 1) >= PASSWORD_HASH_VERSION_CURRENT:
            return
        salt = os.urandom(16)
        admin_user.password = base64.b64encode(hash_password(password, salt)).decode()
        admin_user.password_salt = base64.b64encode(salt).decode()
        admin_user.password_version = PASSWORD_HASH_VERSION_CURRENT
        self.session.commit()

    def change_own_password(self, admin_user_id, *, current_password: str, new_password: str) -> dict[str, object]:
        admin_user = self.session.query(AdminUser).filter(AdminUser.id == admin_user_id).one_or_none()
        if admin_user is None or not admin_user.is_active:
            raise UnauthorizedException("管理员账号不存在或已被禁用")
        if not admin_user.is_password_set or not compare_password(
            current_password,
            admin_user.password,
            admin_user.password_salt,
            iterations=password_iterations_for_version(
                getattr(admin_user, "password_version", 1)
            ),
        ):
            raise FailException("当前密码错误")
        try:
            validate_password(new_password)
        except ValueError:
            raise FailException("密码需包含字母和数字，可使用下划线、点等常规字符，长度6~32位")
        # H-2：禁止管理员将密码修改为弱口令
        if new_password.lower() in _WEAK_ADMIN_PASSWORDS:
            raise FailException("新密码为常见弱口令，请更换更复杂的密码")
        salt = os.urandom(16)
        hashed_password = base64.b64encode(hash_password(new_password, salt)).decode()
        encoded_salt = base64.b64encode(salt).decode()
        admin_user.password = hashed_password
        admin_user.password_salt = encoded_salt
        admin_user.password_version = PASSWORD_HASH_VERSION_CURRENT
        self.session.commit()
        return self._serialize_admin_user(admin_user)

    def _resolve_admin_user_and_session(self, token: str) -> tuple[AdminUser, AdminSession]:
        payload = self.parse_admin_token(token)
        admin_user = self.session.query(AdminUser).filter(AdminUser.id == payload["sub"]).one_or_none()
        if admin_user is None or not admin_user.is_active:
            raise UnauthorizedException("管理员账号不存在或已被禁用")
        admin_session = self.session.query(AdminSession).filter(AdminSession.id == payload["session_id"]).one_or_none()
        if admin_session is None or admin_session.admin_user_id != admin_user.id or not admin_session.is_active:
            raise UnauthorizedException("管理员登录会话已失效，请重新登录")
        # 刷新管理员会话活跃时间（5分钟节流）
        self.touch_admin_session(admin_session)
        return admin_user, admin_session

    def touch_admin_session(self, admin_session: AdminSession) -> None:
        """刷新管理员会话活跃时间（5分钟节流）。

        参考 account_service.touch_account_session 的实现模式：仅在距上次活跃时间
        超过节流间隔时才落库更新，避免每个请求都写数据库。
        """
        now = self._now()
        last_active_at = getattr(admin_session, "last_active_at", None)
        if (
            last_active_at is not None
            and (now - last_active_at).total_seconds() < self.ADMIN_SESSION_TOUCH_INTERVAL_SECONDS
        ):
            return  # 节流：5分钟内不重复刷新
        admin_session.last_active_at = now
        self.session.commit()

    def list_admin_users(self, *, search: str = "", status: str = "all", current_page: int = 1, page_size: int = 20) -> dict[str, object]:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(AdminUser)
        if search:
            keyword = f"%{escape_like_pattern(search)}%"
            query = query.filter((AdminUser.username.ilike(keyword)) | (AdminUser.email.ilike(keyword)) | (AdminUser.name.ilike(keyword)))
        if status and status != "all":
            query = query.filter(AdminUser.status == status)
        total = query.count()
        admin_users = query.order_by(AdminUser.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_admin_user_with_roles(admin_user) for admin_user in admin_users],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_admin_user(self, admin_id: UUID) -> dict[str, object]:
        admin_user = self.session.query(AdminUser).filter(AdminUser.id == admin_id).one_or_none()
        if admin_user is None:
            raise NotFoundException("管理员不存在")
        return self._serialize_admin_user_with_roles(admin_user)

    def create_admin_user(
        self,
        *,
        email: str,
        name: str,
        password: str,
        username: str = "",
        role_codes: list[str] | None = None,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        email = self._normalize_email(email)
        explicit_username = self._normalize_username(username)
        username = explicit_username or email
        if not username:
            raise FailException("管理员账号不能为空")
        existing_user = self.session.query(AdminUser).filter(AdminUser.username == username).one_or_none()
        if existing_user is not None:
            raise FailException("管理员账号已存在")
        if explicit_username and email:
            existing_email_user = self.session.query(AdminUser).filter(AdminUser.email == email).one_or_none()
            if existing_email_user is not None:
                raise FailException("管理员邮箱已存在")
        try:
            validate_password(password)
        except ValueError:
            raise FailException("密码需包含字母和数字，可使用下划线、点等常规字符，长度6~32位")
        # H-2：禁止将管理员密码设置为弱口令
        if password.lower() in _WEAK_ADMIN_PASSWORDS:
            raise FailException("密码为常见弱口令，请更换更复杂的密码")
        self._ensure_super_admin_assignment_allowed(role_codes or [])
        salt = os.urandom(16)
        admin_user = AdminUser(
            account_id=None,
            username=username,
            email=email,
            name=name,
            password=base64.b64encode(hash_password(password, salt)).decode(),
            password_salt=base64.b64encode(salt).decode(),
            password_version=PASSWORD_HASH_VERSION_CURRENT,
            status="active",
        )
        self.session.add(admin_user)
        self.session.flush()
        self._replace_admin_user_roles(admin_user.id, role_codes or [])
        serialized = self._serialize_admin_user_with_roles(admin_user)
        self._emit_audit(
            operator_id=operator_id,
            action="create",
            resource_type="admin_user",
            resource_id=str(admin_user.id),
            ip=ip,
            user_agent=user_agent,
            after_data={"email": email, "name": name, "roles": list(role_codes or [])},
        )
        self.session.commit()
        return serialized

    def update_admin_user(
        self,
        admin_id: UUID,
        *,
        name: str | None = None,
        email: str | None = None,
        status: str | None = None,
        role_codes: list[str] | None = None,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        admin_user = self.session.query(AdminUser).filter(AdminUser.id == admin_id).one_or_none()
        if admin_user is None:
            raise NotFoundException("管理员不存在")
        before_roles = self._get_role_codes(admin_user.id)
        before_data = {
            "name": admin_user.name,
            "email": admin_user.email,
            "status": admin_user.status,
            "roles": before_roles,
        }
        if operator_id and str(operator_id) == str(admin_user.id) and role_codes is not None and not role_codes:
            raise FailException("不能移除自己的全部角色")
        if role_codes is not None:
            self._ensure_super_admin_assignment_allowed(role_codes, current_admin_user_id=admin_user.id)
            target_roles = list(role_codes)
        else:
            target_roles = before_roles
        target_status = status if status is not None else admin_user.status
        self._ensure_super_admin_still_available(admin_user.id, before_roles, target_roles, target_status)
        if name is not None:
            admin_user.name = name
        if email is not None:
            normalized_email = self._normalize_email(email) if email else ""
            # 校验邮箱唯一性（排除自身）
            if normalized_email:
                existing = (
                    self.session.query(AdminUser)
                    .filter(AdminUser.email == normalized_email)
                    .filter(AdminUser.id != admin_user.id)
                    .first()
                )
                if existing is not None:
                    raise FailException("管理员邮箱已存在")
            admin_user.email = normalized_email
        if status is not None:
            admin_user.status = status
        if role_codes is not None:
            self._replace_admin_user_roles(admin_user.id, role_codes)
        serialized = self._serialize_admin_user_with_roles(admin_user)
        self._emit_audit(
            operator_id=operator_id,
            action="update",
            resource_type="admin_user",
            resource_id=str(admin_user.id),
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data={
                "name": serialized.get("name"),
                "email": serialized.get("email"),
                "status": serialized.get("status"),
                "roles": list(role_codes) if role_codes is not None else before_data["roles"],
            },
        )
        self.session.commit()
        return serialized

    def disable_admin_user(
        self,
        admin_id: UUID,
        *,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> None:
        admin_user = self.session.query(AdminUser).filter(AdminUser.id == admin_id).one_or_none()
        if admin_user is None:
            raise NotFoundException("管理员不存在")
        before_roles = self._get_role_codes(admin_user.id)
        # 超级管理员账号不允许被禁用，避免系统最高权限账号失效导致系统瘫痪
        if "super_admin" in before_roles:
            raise FailException("超级管理员账号不允许禁用")
        before_status = admin_user.status
        self._ensure_super_admin_still_available(admin_user.id, before_roles, before_roles, "disabled")
        admin_user.status = "disabled"
        self._emit_audit(
            operator_id=operator_id,
            action="disable",
            resource_type="admin_user",
            resource_id=str(admin_user.id),
            ip=ip,
            user_agent=user_agent,
            before_data={"status": before_status},
            after_data={"status": "disabled"},
        )
        self.session.commit()

    def enable_admin_user(
        self,
        admin_id: UUID,
        *,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        admin_user = self.session.query(AdminUser).filter(AdminUser.id == admin_id).one_or_none()
        if admin_user is None:
            raise NotFoundException("管理员不存在")
        before_status = admin_user.status
        admin_user.status = "active"
        self._emit_audit(
            operator_id=operator_id,
            action="enable",
            resource_type="admin_user",
            resource_id=str(admin_user.id),
            ip=ip,
            user_agent=user_agent,
            before_data={"status": before_status},
            after_data={"status": "active"},
        )
        self.session.commit()
        return self._serialize_admin_user_with_roles(admin_user)

    def reset_admin_user_password(
        self,
        admin_id: UUID,
        *,
        password: str,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        admin_user = self.session.query(AdminUser).filter(AdminUser.id == admin_id).one_or_none()
        if admin_user is None:
            raise NotFoundException("管理员不存在")
        # 超级管理员账号不允许被重置密码，避免系统最高权限账号被篡改
        if "super_admin" in self._get_role_codes(admin_user.id):
            raise FailException("超级管理员账号不允许重置密码")
        try:
            validate_password(password)
        except ValueError:
            raise FailException("密码需包含字母和数字，可使用下划线、点等常规字符，长度6~32位")
        # H-2：禁止将管理员密码重置为弱口令
        if password.lower() in _WEAK_ADMIN_PASSWORDS:
            raise FailException("密码为常见弱口令，请更换更复杂的密码")
        salt = os.urandom(16)
        hashed_password = base64.b64encode(hash_password(password, salt)).decode()
        encoded_salt = base64.b64encode(salt).decode()
        admin_user.password = hashed_password
        admin_user.password_salt = encoded_salt
        admin_user.password_version = PASSWORD_HASH_VERSION_CURRENT
        self._emit_audit(
            operator_id=operator_id,
            action="reset_password",
            resource_type="admin_user",
            resource_id=str(admin_user.id),
            ip=ip,
            user_agent=user_agent,
            before_data={},
            after_data={},
        )
        self.session.commit()
        return self._serialize_admin_user_with_roles(admin_user)

    def revoke_admin_sessions(
        self,
        admin_user_id: UUID,
        *,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, int]:
        """撤销管理员所有活跃会话（踢下线）。

        - 超级管理员不允许被踢下线，避免系统最高权限账号被强制下线。
        """
        admin_user = self.session.query(AdminUser).filter(AdminUser.id == admin_user_id).one_or_none()
        if admin_user is None:
            raise NotFoundException("管理员不存在")
        # 超级管理员账号不允许被踢下线，与 disable_admin_user 保持一致的判定模式
        if "super_admin" in self._get_role_codes(admin_user.id):
            raise FailException("超级管理员不允许被踢下线")
        now = self._now()
        # 撤销该管理员的所有活跃 AdminSession
        sessions = self.session.query(AdminSession).filter(AdminSession.admin_user_id == admin_user_id).all()
        revoked_count = 0
        for session in sessions:
            if session.revoked_at is None and (session.expires_at is None or session.expires_at >= now):
                session.revoked_at = now
                revoked_count += 1
        self.session.commit()
        # 审计日志：记录踢下线操作及撤销会话数量
        self._emit_audit(
            operator_id=operator_id,
            action="revoke_admin_sessions",
            resource_type="admin_user",
            resource_id=str(admin_user.id),
            ip=ip,
            user_agent=user_agent,
            after_data={"revoked_count": revoked_count},
        )
        return {"revoked_sessions": revoked_count}

    def _resolve_role_ids(self, role_codes: list[str]) -> list[str]:
        if not role_codes:
            return []
        normalized_codes = [str(code).strip() for code in role_codes]
        if len(normalized_codes) != len(set(normalized_codes)):
            raise FailException("角色编码不能重复")
        rows = self.session.query(Role.id, Role.code).filter(Role.code.in_(normalized_codes)).all()
        role_id_by_code = {}
        for row in rows:
            if isinstance(row, tuple):
                role_id_by_code[row[1]] = str(row[0])
            else:
                role_id_by_code[getattr(row, "code", "")] = str(getattr(row, "id", ""))
        missing = [code for code in normalized_codes if code not in role_id_by_code]
        if missing:
            raise FailException(f"角色编码不存在: {', '.join(missing)}")
        return [role_id_by_code[code] for code in normalized_codes]

    def _get_active_super_admin_user(self, exclude_admin_user_id=None) -> AdminUser | None:
        query = (
            self.session.query(AdminUser)
            .join(AdminUserRole, AdminUserRole.admin_user_id == AdminUser.id)
            .join(Role, Role.id == AdminUserRole.role_id)
            .filter(Role.code == "super_admin", AdminUser.status == "active")
        )
        if exclude_admin_user_id is not None:
            query = query.filter(AdminUser.id != exclude_admin_user_id)
        return query.one_or_none()

    def _ensure_super_admin_assignment_allowed(self, role_codes: list[str], current_admin_user_id=None) -> None:
        if SUPER_ADMIN_ROLE_CODE not in role_codes:
            return
        if self._get_active_super_admin_user(exclude_admin_user_id=current_admin_user_id) is not None:
            raise FailException("超级管理员账号已存在，不允许分配第二个超级管理员角色")

    def _ensure_super_admin_still_available(
        self,
        admin_user_id,
        before_roles: list[str],
        target_roles: list[str],
        target_status: str,
    ) -> None:
        if "super_admin" not in before_roles:
            return
        if "super_admin" in target_roles and target_status == "active":
            return
        if self._get_active_super_admin_user(exclude_admin_user_id=admin_user_id) is None:
            raise FailException("至少保留一个超级管理员账号")

    def _replace_admin_user_roles(self, admin_user_id, role_codes: list[str]) -> None:
        self.session.query(AdminUserRole).filter(AdminUserRole.admin_user_id == admin_user_id).delete()
        role_ids = self._resolve_role_ids(role_codes)
        for role_id in role_ids:
            self.session.add(AdminUserRole(admin_user_id=admin_user_id, role_id=role_id))

    def _serialize_current_admin_user(self, admin_user: AdminUser) -> dict[str, object]:
        result = self._serialize_admin_user(admin_user)
        account_id = getattr(admin_user, "account_id", None)
        result["account_id"] = str(account_id) if account_id else None
        result["roles"] = self._get_role_codes(admin_user.id)
        result["permissions"] = self._get_permission_codes(result["roles"])
        return result

    def _is_admin_online(self, admin_user_id: UUID) -> bool:
        """判断管理员是否在线：近 10 分钟内有未撤销的活跃会话即视为在线。"""
        now = self._now()
        threshold = now - timedelta(minutes=self.ONLINE_THRESHOLD_MINUTES)
        count = (
            self.session.query(AdminSession)
            .filter(AdminSession.admin_user_id == admin_user_id)
            .filter(AdminSession.revoked_at.is_(None))
            .filter(AdminSession.last_active_at.isnot(None))
            .filter(AdminSession.last_active_at >= threshold)
            .count()
        )
        return count > 0

    def _serialize_admin_user_with_roles(self, admin_user: AdminUser) -> dict[str, object]:
        result = self._serialize_admin_user(admin_user)
        result["roles"] = self._get_role_codes(admin_user.id)
        # 新增：在线状态字段，供前端展示在线/离线标识
        result["is_online"] = self._is_admin_online(admin_user.id)
        return result

    def _get_role_codes(self, admin_user_id) -> list[str]:
        rows = (
            self.session.query(Role.code)
            .join(AdminUserRole, AdminUserRole.role_id == Role.id)
            .filter(AdminUserRole.admin_user_id == admin_user_id)
            .all()
        )
        return [row[0] for row in rows]

    def _get_permission_codes(self, role_codes: list[str]) -> list[str]:
        if not role_codes:
            return []
        if SUPER_ADMIN_ROLE_CODE in role_codes:
            return list(all_permission_codes())
        rows = (
            self.session.query(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .filter(Role.code.in_(role_codes))
            .all()
        )
        return sorted({row[0] for row in rows})

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    @staticmethod
    def _serialize_admin_user(admin_user: AdminUser) -> dict[str, object]:
        return {
            "id": str(admin_user.id),
            "username": admin_user.username,
            "email": admin_user.email or "",
            "name": admin_user.name,
            "avatar": admin_user.avatar or "",
            "status": admin_user.status,
            "account_id": str(admin_user.account_id) if admin_user.account_id else None,
            "created_at": AdminUserService._timestamp(admin_user.created_at),
            "last_login_at": AdminUserService._timestamp(admin_user.last_login_at),
            "last_login_ip": admin_user.last_login_ip or "",
        }
