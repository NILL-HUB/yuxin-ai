import base64
import math
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

from internal.exception import FailException, NotFoundException, UnauthorizedException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.account import Account, AccountSession
from internal.model.admin import AdminSession, AdminUser, AdminUserRole, Permission, Role, RolePermission
from internal.service.audit_log_service import AuditLogService
from internal.service.jwt_service import JwtService
from pkg.password import compare_password, hash_password, validate_password


class AdminUserService:
    DEFAULT_TOKEN_EXPIRE_SECONDS = 60 * 60 * 24 * 7
    USER_TOKEN_EXPIRE_DAYS = 30

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

    def _ensure_bound_account_for_admin_username(
        self,
        *,
        username: str,
        email: str,
        name: str,
        password: str,
        status: str,
    ) -> Account:
        account = self.session.query(Account).filter(Account.username == username).one_or_none()
        if account is None and email:
            account = self.session.query(Account).filter(Account.email == email).one_or_none()
        salt = os.urandom(16)
        if account is None:
            account = Account(username=username, email=email, name=name, status=status)
            self.session.add(account)
            self.session.flush()
        account.username = username
        account.email = email
        account.name = name
        account.status = status
        account.password = base64.b64encode(hash_password(password, salt)).decode()
        account.password_salt = base64.b64encode(salt).decode()
        return account

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
        account = self._ensure_bound_account_for_admin_username(
            username=username,
            email=email,
            name=name,
            password=password,
            status="active",
        )
        salt = os.urandom(16)
        password_hashed = hash_password(password, salt)
        admin_user = AdminUser(
            account_id=account.id,
            username=username,
            email=email,
            name=name,
            password=base64.b64encode(password_hashed).decode(),
            password_salt=base64.b64encode(salt).decode(),
            status="active",
        )
        self.session.add(admin_user)
        self.session.flush()
        self.session.add(AdminUserRole(admin_user_id=admin_user.id, role_id=super_admin_role.id))
        self.session.commit()
        return {"created": True, "reason": "created"}

    def password_login(self, identifier: str, password: str) -> dict[str, object]:
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
        if not compare_password(password, admin_user.password, admin_user.password_salt):
            raise FailException(generic_error_message, reason_code="INVALID_ADMIN_CREDENTIALS")
        now = self._now()
        expires_at = now + timedelta(seconds=self.DEFAULT_TOKEN_EXPIRE_SECONDS)
        admin_session = AdminSession(
            admin_user_id=admin_user.id,
            last_active_at=now,
            expires_at=expires_at,
        )
        self.session.add(admin_session)
        self.session.flush()
        account = self._resolve_bound_account(admin_user)
        user_credential = self._issue_user_credential(account, now=now)
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
            "user_access_token": user_credential["access_token"],
            "user_expire_at": user_credential["expire_at"],
            "admin_user": self._serialize_current_admin_user(admin_user),
            "user": self._serialize_account(account),
        }

    def _resolve_bound_account(self, admin_user: AdminUser) -> Account:
        account = None
        if getattr(admin_user, "account_id", None):
            account = self.session.query(Account).filter(Account.id == admin_user.account_id).one_or_none()
        if account is None:
            account = self.session.query(Account).filter(Account.username == admin_user.username).one_or_none()
        if account is None or getattr(account, "is_disabled", False):
            raise FailException("管理员未绑定可用的用户端账号")
        if getattr(admin_user, "account_id", None) != account.id:
            admin_user.account_id = account.id
        return account

    def _issue_user_credential(self, account: Account, *, now: datetime | None = None) -> dict[str, object]:
        now = now or self._now()
        expires_at = now + timedelta(days=self.USER_TOKEN_EXPIRE_DAYS)
        account_session = AccountSession(
            account_id=account.id,
            last_active_at=now,
            expires_at=expires_at,
        )
        self.session.add(account_session)
        self.session.flush()
        access_token = self.jwt_service.generate_token({
            "sub": str(account.id),
            "iss": "llmops",
            "jti": str(account_session.id),
            "exp": int(expires_at.replace(tzinfo=UTC).timestamp()),
        })
        account.last_login_at = now
        return {
            "access_token": access_token,
            "expire_at": int(expires_at.replace(tzinfo=UTC).timestamp()),
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

    def change_own_password(self, admin_user_id, *, current_password: str, new_password: str) -> dict[str, object]:
        admin_user = self.session.query(AdminUser).filter(AdminUser.id == admin_user_id).one_or_none()
        if admin_user is None or not admin_user.is_active:
            raise UnauthorizedException("管理员账号不存在或已被禁用")
        if not admin_user.is_password_set or not compare_password(current_password, admin_user.password, admin_user.password_salt):
            raise FailException("当前密码错误")
        try:
            validate_password(new_password)
        except ValueError:
            raise FailException("密码需包含字母和数字，可使用下划线、点等常规字符，长度6~32位")
        salt = os.urandom(16)
        hashed_password = base64.b64encode(hash_password(new_password, salt)).decode()
        encoded_salt = base64.b64encode(salt).decode()
        admin_user.password = hashed_password
        admin_user.password_salt = encoded_salt
        if getattr(admin_user, "account_id", None):
            account = self.session.query(Account).filter(Account.id == admin_user.account_id).one_or_none()
            if account is not None:
                account.password = hashed_password
                account.password_salt = encoded_salt
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
        return admin_user, admin_session

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
        role_ids: list[str] | None = None,
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
        self._ensure_super_admin_assignment_allowed(role_ids or [])
        salt = os.urandom(16)
        account = self._ensure_bound_account_for_admin_username(
            username=username,
            email=email,
            name=name,
            password=password,
            status="active",
        )
        admin_user = AdminUser(
            account_id=account.id,
            username=username,
            email=email,
            name=name,
            password=base64.b64encode(hash_password(password, salt)).decode(),
            password_salt=base64.b64encode(salt).decode(),
            status="active",
        )
        self.session.add(admin_user)
        self.session.flush()
        self._replace_admin_user_roles(admin_user.id, role_ids or [])
        serialized = self._serialize_admin_user_with_roles(admin_user)
        self._emit_audit(
            operator_id=operator_id,
            action="create",
            resource_type="admin_user",
            resource_id=str(admin_user.id),
            ip=ip,
            user_agent=user_agent,
            after_data={"email": email, "name": name, "roles": [str(rid) for rid in role_ids or []]},
        )
        self.session.commit()
        return serialized

    def update_admin_user(
        self,
        admin_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        role_ids: list[str] | None = None,
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
            "status": admin_user.status,
            "roles": before_roles,
        }
        if role_ids is not None:
            self._ensure_super_admin_assignment_allowed(role_ids, current_admin_user_id=admin_user.id)
            target_roles = self._resolve_role_codes(role_ids)
        else:
            target_roles = before_roles
        target_status = status if status is not None else admin_user.status
        self._ensure_super_admin_still_available(admin_user.id, before_roles, target_roles, target_status)
        if name is not None:
            admin_user.name = name
        if status is not None:
            admin_user.status = status
        if role_ids is not None:
            self._replace_admin_user_roles(admin_user.id, role_ids)
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
                "status": serialized.get("status"),
                "roles": [str(rid) for rid in role_ids] if role_ids is not None else before_data["roles"],
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
        before_status = admin_user.status
        before_roles = self._get_role_codes(admin_user.id)
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

    def _resolve_role_codes(self, role_ids: list[str]) -> list[str]:
        if not role_ids:
            return []
        normalized_role_ids = [str(role_id) for role_id in role_ids]
        rows = self.session.query(Role.id, Role.code).filter(Role.id.in_(normalized_role_ids)).all()
        role_codes: list[str] = []
        for row in rows:
            if isinstance(row, tuple):
                role_code = row[1]
            else:
                role_code = getattr(row, "code", "")
            if role_code:
                role_codes.append(role_code)
        return role_codes

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

    def _ensure_super_admin_assignment_allowed(self, role_ids: list[str], current_admin_user_id=None) -> None:
        role_codes = self._resolve_role_codes(role_ids)
        if "super_admin" not in role_codes:
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

    def _replace_admin_user_roles(self, admin_user_id, role_ids: list[str]) -> None:
        self.session.query(AdminUserRole).filter(AdminUserRole.admin_user_id == admin_user_id).delete()
        for role_id in role_ids:
            self.session.add(AdminUserRole(admin_user_id=admin_user_id, role_id=role_id))

    def _serialize_current_admin_user(self, admin_user: AdminUser) -> dict[str, object]:
        result = self._serialize_admin_user(admin_user)
        result["roles"] = self._get_role_codes(admin_user.id)
        result["permissions"] = self._get_permission_codes(result["roles"])
        return result

    def _serialize_admin_user_with_roles(self, admin_user: AdminUser) -> dict[str, object]:
        result = self._serialize_admin_user(admin_user)
        result["roles"] = self._get_role_codes(admin_user.id)
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
        rows = (
            self.session.query(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .filter(Role.code.in_(role_codes))
            .all()
        )
        return sorted({row[0] for row in rows})

    @staticmethod
    def _serialize_account(account: Account) -> dict[str, object]:
        return {
            "id": str(account.id),
            "username": account.username,
            "email": account.email or "",
            "name": account.name,
            "avatar": account.avatar or "",
            "status": account.status,
        }

    @staticmethod
    def _serialize_admin_user(admin_user: AdminUser) -> dict[str, object]:
        return {
            "id": str(admin_user.id),
            "username": admin_user.username,
            "email": admin_user.email or "",
            "name": admin_user.name,
            "avatar": admin_user.avatar or "",
            "status": admin_user.status,
        }
