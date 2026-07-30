import math

from internal.extension.database_extension import db
from internal.model.admin import AuditLog


class AuditLogService:
    def __init__(self, session=None):
        self.session = session or db.session

    def record(
        self,
        *,
        admin_user_id,
        action: str,
        resource_type: str,
        resource_id: str = "",
        ip: str = "",
        user_agent: str = "",
        before_data: dict | None = None,
        after_data: dict | None = None,
        commit: bool = True,
    ) -> AuditLog:
        audit_log = AuditLog(
            admin_user_id=admin_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data or {},
            after_data=after_data or {},
        )
        self.session.add(audit_log)
        if commit:
            self.session.commit()
        return audit_log

    def record_for_write(
        self,
        *,
        admin_user_id,
        action: str,
        resource_type: str,
        resource_id: str = "",
        ip: str = "",
        user_agent: str = "",
        before_data: dict | None = None,
        after_data: dict | None = None,
    ) -> AuditLog | None:
        if not admin_user_id:
            return None
        return self.record(
            admin_user_id=admin_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=after_data,
            commit=False,
        )

    def record_for_tool_invocation(
        self,
        *,
        account_id,
        action: str,
        resource_type: str,
        resource_id: str = "",
        before_data: dict | None = None,
        after_data: dict | None = None,
        commit: bool = True,
    ) -> AuditLog:
        audit_log = AuditLog(
            account_id=account_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_data=before_data or {},
            after_data=after_data or {},
        )
        self.session.add(audit_log)
        if commit:
            self.session.commit()
        return audit_log

    def list_audit_logs(
        self,
        *,
        action: str = "",
        resource_type: str = "",
        admin_user_id: str = "",
        account_id: str = "",
        start_time: int | None = None,
        end_time: int | None = None,
        current_page: int = 1,
        page_size: int = 20,
    ) -> dict[str, object]:
        from datetime import datetime, timezone

        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(AuditLog)
        if action:
            query = query.filter(AuditLog.action == action)
        if resource_type:
            query = query.filter(AuditLog.resource_type == resource_type)
        if admin_user_id:
            query = query.filter(AuditLog.admin_user_id == admin_user_id)
        if account_id:
            query = query.filter(AuditLog.account_id == account_id)
        if start_time:
            try:
                query = query.filter(AuditLog.created_at >= datetime.fromtimestamp(int(start_time), tz=timezone.utc).replace(tzinfo=None))
            except (ValueError, TypeError):
                pass
        if end_time:
            try:
                query = query.filter(AuditLog.created_at <= datetime.fromtimestamp(int(end_time), tz=timezone.utc).replace(tzinfo=None))
            except (ValueError, TypeError):
                pass
        total = query.count()
        audit_logs = query.order_by(AuditLog.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()

        # 批量查询关联的管理员和账号名称，避免依赖 relationship 加载，同时防止 N+1 查询
        admin_user_ids = {log.admin_user_id for log in audit_logs if log.admin_user_id}
        account_ids = {log.account_id for log in audit_logs if log.account_id}
        admin_user_map: dict = {}
        account_map: dict = {}
        if admin_user_ids:
            from internal.model.admin import AdminUser
            rows = self.session.query(AdminUser.id, AdminUser.username, AdminUser.name).filter(AdminUser.id.in_(admin_user_ids)).all()
            admin_user_map = {row[0]: (row[1] or row[2] or "") for row in rows}
        if account_ids:
            from internal.model.account import Account
            rows = self.session.query(Account.id, Account.name, Account.email).filter(Account.id.in_(account_ids)).all()
            account_map = {row[0]: (row[1] or row[2] or "") for row in rows}

        return {
            "list": [self._serialize_audit_log(audit_log, admin_user_map, account_map) for audit_log in audit_logs],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    @staticmethod
    def _serialize_audit_log(
        audit_log: AuditLog,
        admin_user_map: dict | None = None,
        account_map: dict | None = None,
    ) -> dict[str, object]:
        admin_user_map = admin_user_map or {}
        account_map = account_map or {}
        admin_user_name = admin_user_map.get(audit_log.admin_user_id, "") if audit_log.admin_user_id else ""
        account_name = account_map.get(audit_log.account_id, "") if audit_log.account_id else ""
        return {
            "id": str(audit_log.id),
            "admin_user_id": str(audit_log.admin_user_id) if audit_log.admin_user_id else None,
            "admin_user_name": admin_user_name,
            "account_id": str(audit_log.account_id) if audit_log.account_id else None,
            "account_name": account_name,
            "action": audit_log.action,
            "resource_type": audit_log.resource_type,
            "resource_id": audit_log.resource_id,
            "ip": audit_log.ip,
            "user_agent": audit_log.user_agent,
            "before_data": audit_log.before_data,
            "after_data": audit_log.after_data,
            "created_at": int(audit_log.created_at.timestamp()) if audit_log.created_at else 0,
        }
