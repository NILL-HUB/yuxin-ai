import math
from datetime import UTC, datetime
from uuid import UUID

from internal.exception import NotFoundException
from internal.extension.database_extension import db
from internal.model.account import Account, AccountSession
from internal.service.audit_log_service import AuditLogService


class AdminCustomerUserService:
    def __init__(self, session=None, audit_log_service=None):
        self.session = session or db.session
        self.audit_log_service = audit_log_service or AuditLogService(session=self.session)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    def _emit_audit(
        self,
        *,
        operator_id,
        action: str,
        resource_id: str,
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
            resource_type="customer_user",
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=after_data,
        )

    def list_customer_users(
        self,
        *,
        keyword: str = "",
        status: str = "",
        current_page: int = 1,
        page_size: int = 20,
    ) -> dict[str, object]:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(Account)
        keyword = (keyword or "").strip()
        if keyword:
            like_value = f"%{keyword}%"
            query = query.filter((Account.email.ilike(like_value)) | (Account.name.ilike(like_value)))
        if status:
            query = query.filter(Account.status == status)
        total = query.count()
        accounts = query.order_by(Account.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_account(account) for account in accounts],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_customer_user(self, account_id: UUID) -> dict[str, object]:
        account = self._get_account_or_raise(account_id)
        result = self._serialize_account(account)
        result["sessions"] = [
            self._serialize_session(account_session)
            for account_session in self._list_sessions(account.id)
        ]
        return result

    def disable_customer_user(
        self,
        account_id: UUID,
        *,
        reason: str = "",
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        account = self._get_account_or_raise(account_id)
        before_data = {"status": account.status, "disabled_reason": account.disabled_reason or ""}
        now = self._now()
        revoked_sessions = self._revoke_active_sessions(account.id, now)
        account.status = "disabled"
        account.disabled_at = now
        account.disabled_by = operator_id
        account.disabled_reason = reason or ""
        self._emit_audit(
            operator_id=operator_id,
            action="disable",
            resource_id=str(account.id),
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data={"status": "disabled", "disabled_reason": account.disabled_reason, "revoked_sessions": revoked_sessions},
        )
        self.session.commit()
        return self._serialize_account(account)

    def enable_customer_user(
        self,
        account_id: UUID,
        *,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        account = self._get_account_or_raise(account_id)
        before_data = {"status": account.status, "disabled_reason": account.disabled_reason or ""}
        account.status = "active"
        account.disabled_at = None
        account.disabled_by = None
        account.disabled_reason = ""
        self._emit_audit(
            operator_id=operator_id,
            action="enable",
            resource_id=str(account.id),
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data={"status": "active", "disabled_reason": ""},
        )
        self.session.commit()
        return self._serialize_account(account)

    def revoke_customer_user_sessions(
        self,
        account_id: UUID,
        *,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, int]:
        account = self._get_account_or_raise(account_id)
        now = self._now()
        sessions = self._list_sessions(account.id)
        active_sessions = sum(1 for account_session in sessions if self._is_active_session(account_session, now))
        revoked_sessions = self._revoke_sessions(sessions, now)
        self._emit_audit(
            operator_id=operator_id,
            action="revoke_sessions",
            resource_id=str(account.id),
            ip=ip,
            user_agent=user_agent,
            before_data={"active_sessions": active_sessions},
            after_data={"revoked_sessions": revoked_sessions},
        )
        self.session.commit()
        return {"revoked_sessions": revoked_sessions}

    def _get_account_or_raise(self, account_id: UUID) -> Account:
        account = self.session.query(Account).filter(Account.id == account_id).one_or_none()
        if account is None:
            raise NotFoundException("用户不存在")
        return account

    def _list_sessions(self, account_id: UUID) -> list[AccountSession]:
        return (
            self.session.query(AccountSession)
            .filter(AccountSession.account_id == account_id)
            .order_by(AccountSession.last_active_at.desc(), AccountSession.created_at.desc())
            .all()
        )

    def _count_active_sessions(self, account_id: UUID) -> int:
        now = self._now()
        return sum(1 for account_session in self._list_sessions(account_id) if self._is_active_session(account_session, now))

    def _revoke_active_sessions(self, account_id: UUID, now: datetime) -> int:
        return self._revoke_sessions(self._list_sessions(account_id), now)

    def _revoke_sessions(self, sessions: list[AccountSession], now: datetime) -> int:
        revoked_count = 0
        for account_session in sessions:
            if not self._is_active_session(account_session, now):
                continue
            account_session.revoked_at = now
            revoked_count += 1
        return revoked_count

    @staticmethod
    def _is_active_session(account_session: AccountSession, now: datetime) -> bool:
        if account_session.revoked_at is not None:
            return False
        if account_session.expires_at and account_session.expires_at < now:
            return False
        return True

    def _serialize_account(self, account: Account) -> dict[str, object]:
        return {
            "id": str(account.id),
            "email": account.email,
            "name": account.name,
            "avatar": account.avatar or "",
            "status": account.status or "active",
            "disabled_at": self._timestamp(account.disabled_at),
            "disabled_by": str(account.disabled_by) if account.disabled_by else None,
            "disabled_reason": account.disabled_reason or "",
            "last_login_at": self._timestamp(account.last_login_at),
            "last_login_ip": account.last_login_ip or "",
            "created_at": self._timestamp(account.created_at),
        }

    def _serialize_session(self, account_session: AccountSession) -> dict[str, object]:
        return {
            "id": str(account_session.id),
            "status": "active" if self._is_active_session(account_session, self._now()) else "revoked",
            "user_agent": account_session.user_agent or "",
            "ip": account_session.last_login_ip or "",
            "created_at": self._timestamp(account_session.created_at),
            "last_active_at": self._timestamp(account_session.last_active_at),
            "expires_at": self._timestamp(account_session.expires_at),
            "revoked_at": self._timestamp(account_session.revoked_at),
        }
