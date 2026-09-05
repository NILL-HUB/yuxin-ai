from uuid import UUID

from internal.extension.database_extension import db
from internal.exception import FailException, NotFoundException
from internal.model.distribution import PurchaseOrder


class AdminOrderService:
    """订单管理面板：列表（按状态/来源/用户筛选）、详情、关闭待支付订单。"""

    def __init__(self, session=None):
        self.session = session or db.session

    def list_all(self, status: str = "", order_source: str = "", account_id: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
        if status:
            query = query.filter(PurchaseOrder.status == status)
        if order_source:
            query = query.filter(PurchaseOrder.order_source == order_source)
        if account_id:
            query = query.filter(PurchaseOrder.account_id == UUID(account_id))
        total = query.count()
        rows = query.offset((current_page - 1) * page_size).limit(page_size).all()
        accounts = self._account_map([order.account_id for order in rows])
        return {
            "list": [self.serialize(order, accounts) for order in rows],
            "paginator": self._paginator(total, current_page, page_size),
        }

    def detail(self, order_id: UUID) -> dict:
        order = self.session.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).one_or_none()
        if order is None:
            raise NotFoundException("订单不存在")
        return self.serialize(order, self._account_map([order.account_id]))

    def close(self, order_id: UUID) -> dict:
        order = self.session.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).one_or_none()
        if order is None:
            raise NotFoundException("订单不存在")
        if order.status != "pending":
            raise FailException("仅待支付订单可关闭")
        order.status = "closed"
        self.session.commit()
        return self.serialize(order, self._account_map([order.account_id]))

    def serialize(self, order: PurchaseOrder, accounts: dict | None = None) -> dict:
        account = (accounts or {}).get(str(order.account_id))
        return {
            "id": str(order.id),
            "order_no": order.order_no,
            "account_id": str(order.account_id),
            "user_name": (account.name or account.username or "") if account else "",
            "user_email": (account.email or "") if account else "",
            "plan_id": str(order.plan_id),
            "plan_type": order.plan_type,
            "amount": float(order.amount),
            "pay_method": order.pay_method,
            "order_source": order.order_source,
            "status": order.status,
            "transaction_id": order.transaction_id,
            "paid_at": self._timestamp(order.paid_at),
            "created_at": self._timestamp(order.created_at),
        }

    def _account_map(self, account_ids) -> dict:
        from internal.model.account import Account

        ids = {UUID(str(aid)) for aid in account_ids if aid}
        if not ids:
            return {}
        rows = self.session.query(Account).filter(Account.id.in_(ids)).all()
        return {str(row.id): row for row in rows}

    @staticmethod
    def _timestamp(value):
        from datetime import UTC

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