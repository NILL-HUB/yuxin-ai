from datetime import UTC, datetime
from uuid import UUID

from internal.entity.app_entity import AppStatus
from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.model.account import Account
from internal.model.app import App, AppAssignment
from internal.service.audit_log_service import AuditLogService


class AdminAppAssignmentService:
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

    def assign_apps(
        self,
        account_id: UUID,
        app_ids: list[UUID],
        *,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        account = self._get_account_or_raise(account_id)
        assigned = 0
        reactivated = 0
        skipped = 0
        assignments = []
        for app_id in dict.fromkeys(app_ids or []):
            app = self._get_app_or_raise(app_id)
            if app.status != AppStatus.PUBLISHED.value:
                raise FailException("只能分配已发布的应用")
            assignment = self._get_assignment(app.id, account.id)
            if assignment is None:
                assignment = AppAssignment(app_id=app.id, account_id=account.id, assigned_by=operator_id, status="active")
                self.session.add(assignment)
                assigned += 1
            elif assignment.status == "revoked":
                assignment.status = "active"
                assignment.assigned_by = operator_id
                assignment.assigned_at = self._now()
                assignment.revoked_at = None
                assignment.updated_at = self._now()
                reactivated += 1
            else:
                skipped += 1
            assignments.append(self._serialize_assignment(assignment, app=app))
        if assigned or reactivated:
            self._emit_audit(
                operator_id=operator_id,
                action="assign",
                resource_id=str(account.id),
                ip=ip,
                user_agent=user_agent,
                after_data={"app_ids": [str(app_id) for app_id in app_ids or []], "assigned": assigned, "reactivated": reactivated},
            )
        self.session.commit()
        return {"assigned": assigned, "reactivated": reactivated, "skipped": skipped, "list": assignments}

    def revoke_assignment(
        self,
        account_id: UUID,
        assignment_id: UUID,
        *,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        assignment = (
            self.session.query(AppAssignment)
            .filter(AppAssignment.id == assignment_id, AppAssignment.account_id == account_id)
            .one_or_none()
        )
        if assignment is None:
            raise NotFoundException("应用分配不存在")
        before_data = {"status": assignment.status}
        assignment.status = "revoked"
        assignment.revoked_at = self._now()
        assignment.updated_at = self._now()
        self._emit_audit(
            operator_id=operator_id,
            action="revoke",
            resource_id=str(assignment.id),
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data={"status": "revoked"},
        )
        self.session.commit()
        return self._serialize_assignment(assignment)

    def list_assignments(self, account_id: UUID) -> dict[str, object]:
        self._get_account_or_raise(account_id)
        assignments = (
            self.session.query(AppAssignment)
            .filter(AppAssignment.account_id == account_id)
            .order_by(AppAssignment.created_at.desc())
            .all()
        )
        return {"list": [self._serialize_assignment(assignment) for assignment in assignments]}

    def _get_account_or_raise(self, account_id: UUID) -> Account:
        account = self.session.query(Account).filter(Account.id == account_id).one_or_none()
        if account is None:
            raise NotFoundException("用户不存在")
        return account

    def _get_app_or_raise(self, app_id: UUID) -> App:
        app = self.session.query(App).filter(App.id == app_id).one_or_none()
        if app is None:
            raise NotFoundException("应用不存在")
        return app

    def _get_assignment(self, app_id: UUID, account_id: UUID) -> AppAssignment | None:
        return (
            self.session.query(AppAssignment)
            .filter(AppAssignment.app_id == app_id, AppAssignment.account_id == account_id)
            .one_or_none()
        )

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
            resource_type="app_assignment",
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=after_data,
        )

    def _serialize_assignment(self, assignment: AppAssignment, *, app: App | None = None) -> dict[str, object]:
        app = app or getattr(assignment, "app", None)
        return {
            "id": str(assignment.id),
            "app_id": str(assignment.app_id),
            "account_id": str(assignment.account_id),
            "assigned_by": str(assignment.assigned_by) if assignment.assigned_by else None,
            "status": assignment.status,
            "assigned_at": self._timestamp(assignment.assigned_at),
            "revoked_at": self._timestamp(assignment.revoked_at),
            "app": self._serialize_app(app) if app else None,
        }

    @staticmethod
    def _serialize_app(app: App) -> dict[str, object]:
        return {
            "id": str(app.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "status": app.status,
            "is_public": bool(app.is_public),
        }
