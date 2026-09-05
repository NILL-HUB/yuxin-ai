from datetime import UTC, datetime
from uuid import UUID

from internal.extension.database_extension import db
from internal.exception import FailException, NotFoundException
from internal.model.account import Account
from internal.model.distribution import BalanceTransaction, DistributionRelation


class AdminDistributionService:
    """分销管理面板：总览统计、关系列表、佣金记录。"""

    def __init__(self, session=None, distribution_service=None):
        self.session = session or db.session
        self._distribution_service = distribution_service

    def _get_distribution_service(self):
        if self._distribution_service is None:
            from internal.service.distribution_service import DistributionService

            self._distribution_service = DistributionService(session=self.session)
        return self._distribution_service

    def overview(self) -> dict:
        bound_total = self.session.query(DistributionRelation.id).count()
        commission_total_rows = (
            self.session.query(BalanceTransaction)
            .filter(BalanceTransaction.amount_type == "commission")
            .all()
        )
        commission_total = sum(float(row.amount or 0) for row in commission_total_rows)
        now = self._now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_commission = sum(
            float(row.amount or 0)
            for row in commission_total_rows
            if row.created_at and row.created_at >= month_start
        )
        inviter_users = (
            self.session.query(DistributionRelation.inviter_account_id)
            .distinct()
            .count()
        )
        return {
            "bound_users": bound_total,
            "commission_total": round(commission_total, 2),
            "month_commission": round(month_commission, 2),
            "inviter_users": inviter_users,
            "distribution_enabled": self._get_distribution_service().is_enabled(),
        }

    def list_relations(self, current_page: int = 1, page_size: int = 20, inviter_id: str = "") -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = (
            self.session.query(DistributionRelation, Account)
            .join(Account, Account.id == DistributionRelation.invitee_account_id)
            .order_by(DistributionRelation.bound_at.desc())
        )
        if inviter_id:
            try:
                query = query.filter(DistributionRelation.inviter_account_id == UUID(inviter_id))
            except (ValueError, AttributeError):
                raise FailException("邀请人 ID 格式错误") from None
        total = query.count()
        rows = query.offset((current_page - 1) * page_size).limit(page_size).all()
        inviter_ids = {relation.inviter_account_id for relation, _ in rows}
        inviters = self._account_map(inviter_ids)
        return {
            "list": [
                {
                    "id": str(account.id),
                    "name": account.name or account.username or account.email or "",
                    "email": account.email or "",
                    "inviter_id": str(relation.inviter_account_id),
                    "inviter_name": self._inviter_name(inviters, relation.inviter_account_id),
                    "inviter_email": self._inviter_email(inviters, relation.inviter_account_id),
                    "bound_at": self._timestamp(relation.bound_at),
                    "source": relation.source,
                }
                for relation, account in rows
            ],
            "paginator": self._paginator(total, current_page, page_size),
        }

    def _account_map(self, account_ids) -> dict:
        from internal.model.account import Account

        ids = {UUID(str(aid)) for aid in account_ids if aid}
        if not ids:
            return {}
        rows = self.session.query(Account).filter(Account.id.in_(ids)).all()
        return {str(row.id): row for row in rows}

    @staticmethod
    def _inviter_name(inviters: dict, account_id) -> str:
        account = inviters.get(str(account_id))
        return (account.name or account.username or account.email or "") if account else ""

    @staticmethod
    def _inviter_email(inviters: dict, account_id) -> str:
        account = inviters.get(str(account_id))
        return (account.email or "") if account else ""

    def bind_or_unbind_superior(self, invitee_id: UUID, inviter_id: UUID | None, operator_id: UUID | None = None) -> dict:
        service = self._get_distribution_service()
        if inviter_id is None:
            removed = service.unbind_superior(invitee_id, operator_id)
            self.session.commit()
            return {"unbound": removed}
        relation = service.bind_superior(invitee_id, inviter_id, source="admin", operator_id=operator_id)
        self.session.commit()
        return {"inviter_id": str(relation.inviter_account_id)}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    @staticmethod
    def _paginator(total: int, current_page: int, page_size: int) -> dict:
        import math

        return {
            "total_record": total,
            "total_page": math.ceil(total / page_size) if total else 0,
            "current_page": current_page,
            "page_size": page_size,
        }