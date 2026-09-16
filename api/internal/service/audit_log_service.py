import math
import uuid as uuid_lib
from importlib import import_module

from internal.extension.database_extension import db
from internal.model.admin import AuditLog


# 资源类型 -> （模型所在模块, 模型类名, 用于匹配 resource_id 的列, 名称列按优先级）
# 快照只在 create/update/delete 类操作里写入名称，像 disable/enable/set_status
# 这类状态变更只记录状态字段，因此需要回源表按 resource_id 补全可读名称。
_RESOURCE_NAME_LOOKUPS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "admin_user": ("internal.model.admin", "AdminUser", "id", ("name", "username", "email")),
    "role": ("internal.model.admin", "Role", "id", ("name", "code")),
    "customer_user": ("internal.model.account", "Account", "id", ("name", "username", "email")),
    "account": ("internal.model.account", "Account", "id", ("name", "username", "email")),
    "plan": ("internal.model.billing", "Plan", "id", ("name", "code")),
    "redeem_code_batch": ("internal.model.billing", "RedeemCodeBatch", "id", ("name", "description")),
    "redeem_code": ("internal.model.billing", "RedeemCode", "id", ("code_mask",)),
    "billing_config": ("internal.model.billing", "BillingConfig", "code", ("code", "description")),
    "skill": ("internal.model.skill", "SkillPackage", "id", ("label", "name")),
    "mcp": ("internal.model.mcp", "McpProvider", "id", ("label", "name")),
    "tool": ("internal.model.api_tool", "ApiTool", "id", ("name",)),
    "api_tool": ("internal.model.api_tool", "ApiToolProvider", "id", ("name",)),
    "storage_file": ("internal.model.upload_file", "UploadFile", "id", ("name", "key")),
    "upload_file": ("internal.model.upload_file", "UploadFile", "id", ("name", "key")),
    "system_knowledge": ("internal.model.knowledge", "KnowledgeBase", "id", ("name", "description")),
    "knowledge_base": ("internal.model.knowledge", "KnowledgeBase", "id", ("name", "description")),
    "knowledge_document": ("internal.model.knowledge", "KnowledgeDocument", "id", ("name",)),
    "external_data_source": ("internal.model.knowledge", "ExternalDataSource", "id", ("source_name",)),
    "app": ("internal.model.app", "App", "id", ("name",)),
    "workflow": ("internal.model.workflow", "Workflow", "id", ("name",)),
    "schedule_task": ("internal.model.schedule_task", "ScheduleTask", "id", ("name",)),
    "conversation": ("internal.model.conversation", "Conversation", "id", ("name",)),
    "purchase_order": ("internal.model.distribution", "PurchaseOrder", "id", ("order_no",)),
    "return_request": ("internal.model.distribution", "ReturnRequest", "id", ("reason",)),
    "payment_provider_config": (
        "internal.model.distribution",
        "PaymentProviderConfig",
        "provider",
        ("name", "provider"),
    ),
    "model": ("internal.model.model_pool_entity", "ModelPoolConfig", "id", ("display_name", "model_name")),
    "model_provider": ("internal.model.model_provider_entity", "ModelProviderConfig", "id", ("label", "name")),
    "orchestration_flag": (
        "internal.model.orchestration_feature_flag",
        "OrchestrationFeatureFlagModel",
        "id",
        ("name", "code"),
    ),
    "prompt_template": ("internal.model.prompt_template", "PromptTemplate", "prompt_key", ("name", "prompt_key")),
    # distribution_relation 的 resource_id 记录的是被绑定的邀请账户（invitee account）id
    "distribution_relation": (
        "internal.model.account",
        "Account",
        "id",
        ("name", "username", "email"),
    ),
}


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid_lib.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


class AuditLogService:
    def __init__(self, session=None):
        self.session = session or db.session

    def overview(
        self,
        *,
        action: str = "",
        resource_type: str = "",
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> dict:
        """审计日志观测概览：总量/操作分布/资源分布/按日趋势（SQL 级聚合）。"""
        from datetime import UTC, datetime

        from sqlalchemy import func

        def apply_window(query):
            if start_time:
                try:
                    query = query.filter(
                        AuditLog.created_at
                        >= datetime.fromtimestamp(int(start_time), tz=UTC).replace(tzinfo=None)
                    )
                except (ValueError, TypeError):
                    pass
            if end_time:
                try:
                    query = query.filter(
                        AuditLog.created_at
                        <= datetime.fromtimestamp(int(end_time), tz=UTC).replace(tzinfo=None)
                    )
                except (ValueError, TypeError):
                    pass
            return query

        def base_query(extra_filters=True):
            query = self.session.query(AuditLog)
            if extra_filters:
                if action:
                    query = query.filter(AuditLog.action == action)
                if resource_type:
                    query = query.filter(AuditLog.resource_type == resource_type)
            return apply_window(query)

        total = base_query().count()

        action_rows = (
            base_query()
            .with_entities(AuditLog.action, func.count().label("count"))
            .group_by(AuditLog.action)
            .order_by(func.count().desc())
            .limit(15)
            .all()
        )
        resource_rows = (
            base_query()
            .with_entities(AuditLog.resource_type, func.count().label("count"))
            .group_by(AuditLog.resource_type)
            .order_by(func.count().desc())
            .limit(15)
            .all()
        )
        ts_col = func.date_trunc("day", AuditLog.created_at)
        trend_rows = (
            base_query(extra_filters=False)
            .with_entities(ts_col.label("ts"), func.count().label("count"))
            .group_by(ts_col)
            .order_by(ts_col)
            .all()
        )
        admin_rows = (
            base_query(extra_filters=False)
            .with_entities(
                AuditLog.admin_user_id,
                func.count().label("count"),
            )
            .filter(AuditLog.admin_user_id.isnot(None))
            .group_by(AuditLog.admin_user_id)
            .order_by(func.count().desc())
            .limit(10)
            .all()
        )

        admin_ids = [row.admin_user_id for row in admin_rows]
        admin_name_map = {}
        if admin_ids:
            from internal.model.admin import AdminUser

            name_rows = (
                self.session.query(AdminUser.id, AdminUser.username, AdminUser.name)
                .filter(AdminUser.id.in_(admin_ids))
                .all()
            )
            admin_name_map = {str(row[0]): (row[1] or row[2] or "") for row in name_rows}

        return {
            "total": total,
            "by_action": [
                {"name": row.action or "unknown", "count": int(row.count or 0)}
                for row in action_rows
            ],
            "by_resource_type": [
                {"name": row.resource_type or "unknown", "count": int(row.count or 0)}
                for row in resource_rows
            ],
            "trend": [
                {
                    "timestamp": int(row.ts.replace(tzinfo=UTC).timestamp())
                    if row.ts and row.ts.tzinfo is None
                    else (int(row.ts.timestamp()) if row.ts else 0),
                    "count": int(row.count or 0),
                }
                for row in trend_rows
            ],
            "top_admins": [
                {
                    "name": admin_name_map.get(str(row.admin_user_id), str(row.admin_user_id)),
                    "count": int(row.count or 0),
                }
                for row in admin_rows
            ],
        }

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

        # 快照缺失名称时（如 disable/enable/set_status 类状态变更），批量回源表补全
        resource_name_map = self._build_resource_name_map(audit_logs)

        return {
            "list": [
                self._serialize_audit_log(audit_log, admin_user_map, account_map, resource_name_map)
                for audit_log in audit_logs
            ],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def _build_resource_name_map(self, audit_logs: list) -> dict[tuple[str, str], str]:
        """批量回源查询资源名称，补齐快照中缺失名称的审计记录。

        返回 {(resource_type, resource_id): name}，按 resource_type 分组后
        只对需要补全的记录各发一次 IN 查询，避免 N+1。
        """
        pending: dict[str, set[str]] = {}
        for log in audit_logs:
            if not log.resource_id or not log.resource_type:
                continue
            if AuditLogService._extract_resource_name(log.before_data, log.after_data):
                continue
            lookup = _RESOURCE_NAME_LOOKUPS.get(log.resource_type)
            if not lookup:
                continue
            pending.setdefault(log.resource_type, set()).add(str(log.resource_id))

        name_map: dict[tuple[str, str], str] = {}
        for resource_type, resource_ids in pending.items():
            module_path, class_name, match_column, name_columns = _RESOURCE_NAME_LOOKUPS[resource_type]
            try:
                model = getattr(import_module(module_path), class_name)
            except (ImportError, AttributeError):
                continue

            column = getattr(model, match_column, None)
            if column is None:
                continue

            if match_column == "id":
                keys = [uuid_lib.UUID(rid) for rid in resource_ids if _looks_like_uuid(rid)]
            else:
                keys = [rid for rid in resource_ids if rid]
            if not keys:
                continue

            value_columns = [getattr(model, name, None) for name in name_columns]
            value_columns = [col for col in value_columns if col is not None]
            if not value_columns:
                continue

            try:
                rows = self.session.query(column, *value_columns).filter(column.in_(keys)).all()
            except Exception:
                continue

            for row in rows:
                key = str(row[0])
                name = ""
                for value in row[1:]:
                    if isinstance(value, str) and value.strip():
                        name = value.strip()
                        break
                    if isinstance(value, int) and not isinstance(value, bool):
                        name = str(value)
                        break
                if name:
                    name_map[(resource_type, key)] = name
        return name_map

    @staticmethod
    def _extract_resource_name(
        before_data: dict | None,
        after_data: dict | None,
    ) -> str:
        """从变更前/后快照中提取可读的资源名称。

        审计写入时各资源会把自身名称字段放进 before_data/after_data
        （如 customer_user 的 name、plan 的 name、tool 的 tool_name），
        但字段名并不统一。这里按优先级扫描常见名称字段，
        让列表/详情能展示“删除了哪个用户/套餐”，而不是只显示 UUID。

        优先取 after_data（记录变更后的最终状态），为空时回退 before_data
        （删除类操作的名称只存在于变更前快照）。
        """
        name_keys = (
            "resource_name",
            "name",
            "username",
            "display_name",
            "title",
            "tool_name",
            "code",
            "order_no",
            "user_name",
            "email",
            "key",
        )
        sources = []
        if isinstance(after_data, dict):
            sources.append(after_data)
        if isinstance(before_data, dict):
            sources.append(before_data)

        for source in sources:
            for key in name_keys:
                value = source.get(key)
                if isinstance(value, str):
                    normalized = value.strip()
                    if normalized:
                        return normalized
                elif isinstance(value, int) and not isinstance(value, bool):
                    return str(value)
        return ""

    @staticmethod
    def _serialize_audit_log(
        audit_log: AuditLog,
        admin_user_map: dict | None = None,
        account_map: dict | None = None,
        resource_name_map: dict | None = None,
    ) -> dict[str, object]:
        admin_user_map = admin_user_map or {}
        account_map = account_map or {}
        resource_name_map = resource_name_map or {}
        admin_user_name = admin_user_map.get(audit_log.admin_user_id, "") if audit_log.admin_user_id else ""
        account_name = account_map.get(audit_log.account_id, "") if audit_log.account_id else ""
        # 优先用快照里的名称；快照没有时用回源补全的名称
        resource_name = AuditLogService._extract_resource_name(
            audit_log.before_data, audit_log.after_data
        )
        if not resource_name and audit_log.resource_id and audit_log.resource_type:
            resource_name = resource_name_map.get(
                (str(audit_log.resource_type), str(audit_log.resource_id)), ""
            )
        return {
            "id": str(audit_log.id),
            "admin_user_id": str(audit_log.admin_user_id) if audit_log.admin_user_id else None,
            "admin_user_name": admin_user_name,
            "account_id": str(audit_log.account_id) if audit_log.account_id else None,
            "account_name": account_name,
            "action": audit_log.action,
            "resource_type": audit_log.resource_type,
            "resource_id": audit_log.resource_id,
            "resource_name": resource_name,
            "ip": audit_log.ip,
            "user_agent": audit_log.user_agent,
            "before_data": audit_log.before_data,
            "after_data": audit_log.after_data,
            "created_at": int(audit_log.created_at.timestamp()) if audit_log.created_at else 0,
        }
