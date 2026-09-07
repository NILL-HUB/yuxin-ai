import math
import secrets
import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID

from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.account import Account, AccountSession
from internal.model.admin import AdminUser
from internal.model.distribution import DistributionRelation
from internal.service.audit_log_service import AuditLogService
from pkg.password import hash_password, PASSWORD_HASH_VERSION_CURRENT


class AdminCustomerUserService:
    # 在线判定阈值：近 10 分钟内有活跃会话即视为在线
    ONLINE_THRESHOLD_MINUTES = 10

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
        # 排除绑定到管理员的账号，管理员不应出现在客户用户列表中
        admin_bound_ids = self._admin_bound_account_ids()
        if admin_bound_ids:
            query = query.filter(~Account.id.in_(admin_bound_ids))
        keyword = (keyword or "").strip()
        if keyword:
            like_value = f"%{escape_like_pattern(keyword)}%"
            query = query.filter((Account.email.ilike(like_value)) | (Account.name.ilike(like_value)))
        if status:
            query = query.filter(Account.status == status)
        else:
            # 默认不展示已删除账号（避免列表被注销用户占满；可显式按 status=deleted 查）
            query = query.filter(Account.status != "deleted")
        total = query.count()
        accounts = query.order_by(Account.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        superior_map = self._superior_map([account.id for account in accounts])
        return {
            "list": [self._serialize_account(account, superior_map.get(str(account.id))) for account in accounts],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_customer_user(self, account_id: UUID) -> dict[str, object]:
        account = self._get_account_or_raise(account_id)
        result = self._serialize_account(account, self._superior_map([account.id]).get(str(account.id)))
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
        if account.is_deleted:
            raise FailException("账号已删除，无法操作")
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
        if account.is_deleted:
            raise FailException("账号已删除，无法启用")
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

    def create_customer_user(
        self,
        *,
        email: str,
        name: str,
        password: str = "",
        username: str = "",
        phone: str = "",
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        """管理员代建用户账号。

        与用户自助注册的区别：管理员直接指定邮箱/密码创建，无需验证码。
        - email 唯一；username 可选（有值需唯一）
        - password 为空则创建无密码账号（用户后续自助设置/仅 OAuth 登录）
        """
        email = (email or "").strip().lower()
        name = (name or "").strip()
        username = (username or "").strip()
        phone = (phone or "").strip()
        if not email or "@" not in email:
            raise FailException("邮箱格式不正确")
        if not name:
            raise FailException("名称不能为空")
        # 唯一性校验
        if self._account_email_exists(email):
            raise FailException("该邮箱已被注册")
        if username and self._account_username_exists(username):
            raise FailException("该用户名已被使用")

        display_name = name or email.split("@", 1)[0]
        account = Account(
            email=email,
            username=username,
            name=display_name,
            phone=phone,
            status="active",
        )
        self.session.add(account)
        self.session.flush()
        # 设置密码（可选）
        if password:
            self._set_account_password(account, password)
        self._emit_audit(
            operator_id=operator_id,
            action="create",
            resource_id=str(account.id),
            ip=ip,
            user_agent=user_agent,
            before_data={},
            after_data={"email": email, "name": display_name, "username": username},
        )
        self.session.commit()
        return self._serialize_account(account)

    def update_customer_user(
        self,
        account_id: UUID,
        *,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        password: str | None = None,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        """更新用户资料；password 非空时重置密码（吊销旧会话）。"""
        account = self._get_account_or_raise(account_id)
        if account.is_deleted:
            raise FailException("账号已删除，无法编辑")
        before_data = {
            "name": account.name,
            "email": account.email,
            "phone": account.phone or "",
            "status": account.status,
        }
        if name is not None:
            name = (name or "").strip()
            if not name:
                raise FailException("名称不能为空")
            account.name = name
        if email is not None:
            email = (email or "").strip().lower()
            if not email or "@" not in email:
                raise FailException("邮箱格式不正确")
            if email != account.email and self._account_email_exists(email):
                raise FailException("该邮箱已被注册")
            account.email = email
        if phone is not None:
            account.phone = (phone or "").strip()
        if password:
            self._set_account_password(account, password)
        self._emit_audit(
            operator_id=operator_id,
            action="update",
            resource_id=str(account.id),
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data={
                "name": account.name,
                "email": account.email,
                "phone": account.phone or "",
                "password_reset": bool(password),
            },
        )
        self.session.commit()
        return self._serialize_account(account)

    def delete_customer_user(
        self,
        account_id: UUID,
        *,
        reason: str = "",
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        """删除（注销）用户账号：status='deleted'，不可逆。

        与 disable（停用、可逆、保留数据）区分：
        - disable：可随时 enable 恢复，名下数据保留
        - delete：注销账号，禁止登录、吊销全部会话、清理记忆数据，不可恢复

        数据处置：
        - PG user_memory 投影行删除（向量分表 CASCADE）
        - Neo4j 记忆图节点按 user_id 清理（同 ghost 清理）
        - 名下 app/knowledge_base 等业务数据保留行但不再可被该账号访问
          （账号已 deleted 无法登录，天然隔离）；如需物理清理需另行编排。
        """
        account = self._get_account_or_raise(account_id)
        if account.is_deleted:
            raise FailException("账号已删除，请勿重复操作")
        before_data = {
            "status": account.status,
            "name": account.name,
            "email": account.email,
        }
        now = self._now()
        revoked_sessions = self._revoke_active_sessions(account.id, now)
        # 置为 deleted（不可逆）
        account.status = "deleted"
        account.deleted_at = now
        account.deleted_by = operator_id
        account.deleted_reason = reason or ""
        # 清理该用户的运行态数据（记忆 + 定时任务，best-effort）
        cleanup_stats = self._cleanup_user_runtime_data(account.id)
        self._emit_audit(
            operator_id=operator_id,
            action="delete",
            resource_id=str(account.id),
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data={
                "status": "deleted",
                "deleted_reason": account.deleted_reason,
                "revoked_sessions": revoked_sessions,
                "cleanup": cleanup_stats,
            },
        )
        self.session.commit()
        return self._serialize_account(account)

    # =========================================================
    # 内部辅助（创建/删除）
    # =========================================================

    def _account_email_exists(self, email: str) -> bool:
        return (
            self.session.query(Account.id)
            .filter(Account.email == email)
            .first()
            is not None
        )

    def _account_username_exists(self, username: str) -> bool:
        return (
            self.session.query(Account.id)
            .filter(Account.username == username)
            .first()
            is not None
        )

    def _set_account_password(self, account: Account, password: str) -> None:
        """为账号设置密码（PBKDF2-600k，version=2，与用户自助注册一致）。"""
        from pkg.password import validate_password

        try:
            validate_password(password)
        except ValueError as exc:
            raise FailException(str(exc))
        salt = secrets.token_bytes(16)
        base64_salt = base64.b64encode(salt).decode()
        password_hashed = hash_password(password, salt)
        account.password = base64.b64encode(password_hashed).decode()
        account.password_salt = base64_salt
        account.password_version = PASSWORD_HASH_VERSION_CURRENT
        account.password_changed_at = self._now()
        # 密码变更 → 吊销旧会话
        self._revoke_active_sessions(account.id, self._now())

    def _cleanup_user_runtime_data(self, account_id: UUID) -> dict[str, int]:
        """清理指定账号的运行态数据（best-effort，失败不阻断删除主流程）。

        - PG：DELETE user_memory WHERE owner_account_id=...（向量分表 CASCADE）
        - Neo4j：按 user_id 清理 Episode/Entity/SemanticMemory/Community 节点；
          独占 Skill（仅归属该账号）物理删除；User/Trait/Preference 画像节点级联清理
        - PG：停用该账号名下定时任务（schedule_task.enabled=false）
        """
        stats = {
            "pg_rows": 0,
            "neo4j_nodes": 0,
            "neo4j_skills": 0,
            "neo4j_user_nodes": 0,
            "schedule_tasks_disabled": 0,
        }
        try:
            from internal.model.knowledge import UserMemory

            result = (
                self.session.query(UserMemory)
                .filter(UserMemory.owner_account_id == account_id)
                .delete()
            )
            stats["pg_rows"] = int(result or 0)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "delete_customer_user: PG 记忆清理失败 account=%s", account_id, exc_info=True
            )
        # Neo4j 清理（复用 ghost 清理的 Cypher 思路；覆盖 Community/Skill/User 等全量标签）
        try:
            from internal.extension.neo4j_extension import get_driver

            driver = get_driver()
            if driver is not None:
                with driver.session() as session:
                    # 1) 用户私有记忆节点（Episode/Entity/SemanticMemory/Community + MemoryNode 全覆盖）
                    #    Community 不带 MemoryNode 但 user_id 归属用户，可安全物理删除
                    result = session.run(
                        """
                        MATCH (n)
                        WHERE n.user_id = $uid
                          AND (n:MemoryNode OR n:Episode OR n:Entity OR n:SemanticMemory OR n:Community)
                        DETACH DELETE n
                        RETURN count(*) AS cnt
                        """,
                        uid=str(account_id),
                    ).single()
                    if result:
                        stats["neo4j_nodes"] = int(result["cnt"] or 0)

                    # 2) 独占 Skill 清理：仅当该 skill 只归属这一个已删账号时物理删除；
                    #    多账号共享的 skill 保留（避免误删他人技能）
                    shared = session.run(
                        """
                        MATCH (s:Skill {user_id: $uid})
                        WHERE NOT (s:MemoryNode)
                        RETURN s.id AS skill_id
                        """,
                        uid=str(account_id),
                    ).values()
                    deleted_skills = 0
                    for (skill_id,) in shared:
                        ownership = session.run(
                            """
                            MATCH (s:Skill {id: $skill_id})
                            RETURN count(s) AS cnt
                            """,
                            skill_id=skill_id,
                        ).single()
                        if ownership and int(ownership["cnt"] or 0) == 1:
                            session.run(
                                "MATCH (s:Skill {id: $skill_id}) DETACH DELETE s",
                                skill_id=skill_id,
                            )
                            deleted_skills += 1
                    stats["neo4j_skills"] = deleted_skills

                    # 3) 用户画像节点（User/Trait/Preference，新增于 Profile 落库）
                    result = session.run(
                        """
                        MATCH (u:User {id: $uid})
                        OPTIONAL MATCH (u)-[r]-(n)
                        WITH u, collect(DISTINCT n) AS nodes
                        DETACH DELETE u
                        WITH nodes
                        UNWIND nodes AS node
                        WITH node WHERE node:User OR node:Trait OR node:Preference OR node.user_id IS NULL
                        DETACH DELETE node
                        RETURN count(*) AS cnt
                        """,
                        uid=str(account_id),
                    ).single()
                    if result:
                        stats["neo4j_user_nodes"] = int(result["cnt"] or 0)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "delete_customer_user: Neo4j 记忆清理失败 account=%s", account_id, exc_info=True
            )
        # 停用定时任务（防止账号已删但任务仍定时执行）
        try:
            from internal.model.schedule_task import ScheduleTask

            result = (
                self.session.query(ScheduleTask)
                .filter(ScheduleTask.account_id == account_id)
                .filter(ScheduleTask.enabled.is_(True))
                .update({ScheduleTask.enabled: False})
            )
            stats["schedule_tasks_disabled"] = int(result or 0)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "delete_customer_user: 停用定时任务失败 account=%s", account_id, exc_info=True
            )
        return stats

    def revoke_customer_user_sessions(
        self,
        account_id: UUID,
        *,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, int]:
        account = self._get_account_or_raise(account_id)
        if account.is_deleted:
            raise FailException("账号已删除，无需撤销会话")
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
        self._ensure_not_admin_bound(account)
        return account

    def _ensure_not_admin_bound(self, account: Account) -> None:
        """管理员绑定的账号不允许在客户用户管理中操作，避免误禁用管理员导致系统瘫痪。"""
        bound = (
            self.session.query(AdminUser.id)
            .filter(AdminUser.account_id == account.id)
            .first()
        )
        if bound is not None:
            raise FailException("该账号为管理员账号，不能在用户管理中操作")

    def _admin_bound_account_ids(self) -> set:
        """返回所有绑定到 AdminUser 的 Account ID 集合，用于列表排除。"""
        rows = self.session.query(AdminUser.account_id).filter(AdminUser.account_id.isnot(None)).all()
        return {row[0] for row in rows}

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

    def _is_customer_user_online(self, account_id: UUID) -> bool:
        """判断用户是否在线：近 10 分钟内有未撤销的活跃会话即视为在线。"""
        now = self._now()
        threshold = now - timedelta(minutes=self.ONLINE_THRESHOLD_MINUTES)
        count = (
            self.session.query(AccountSession)
            .filter(AccountSession.account_id == account_id)
            .filter(AccountSession.revoked_at.is_(None))
            .filter(AccountSession.last_active_at.isnot(None))
            .filter(AccountSession.last_active_at >= threshold)
            .count()
        )
        return count > 0

    def _superior_map(self, account_ids) -> dict:
        ids = {str(account_id) for account_id in account_ids if account_id}
        if not ids:
            return {}
        relations = (
            self.session.query(DistributionRelation)
            .filter(DistributionRelation.invitee_account_id.in_([UUID(account_id) for account_id in ids]))
            .all()
        )
        inviter_ids = {relation.inviter_account_id for relation in relations}
        inviters = {}
        if inviter_ids:
            rows = self.session.query(Account).filter(Account.id.in_(inviter_ids)).all()
            inviters = {str(row.id): row for row in rows}
        result = {}
        for relation in relations:
            inviter = inviters.get(str(relation.inviter_account_id))
            if inviter is not None:
                result[str(relation.invitee_account_id)] = inviter
        return result

    def _serialize_account(self, account: Account, superior: Account | None = None) -> dict[str, object]:
        return {
            "id": str(account.id),
            "email": account.email,
            "name": account.name,
            "avatar": account.avatar or "",
            "status": account.status or "active",
            "disabled_at": self._timestamp(account.disabled_at),
            "disabled_by": str(account.disabled_by) if account.disabled_by else None,
            "disabled_reason": account.disabled_reason or "",
            "deleted_at": self._timestamp(account.deleted_at),
            "deleted_by": str(account.deleted_by) if account.deleted_by else None,
            "deleted_reason": account.deleted_reason or "",
            "last_login_at": self._timestamp(account.last_login_at),
            "last_login_ip": account.last_login_ip or "",
            "created_at": self._timestamp(account.created_at),
            # 新增：在线状态字段，供前端展示在线/离线标识
            "is_online": self._is_customer_user_online(account.id),
            "superior_id": str(superior.id) if superior else None,
            "superior_name": (superior.name or superior.username or "") if superior else "",
            "superior_email": (superior.email or "") if superior else "",
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
