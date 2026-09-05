import random
import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from internal.extension.database_extension import db
from internal.exception import FailException, NotFoundException
from internal.model.account import Account
from internal.model.billing import Plan
from internal.model.distribution import (
    BalanceAccount,
    BalanceTransaction,
    DistributionRelation,
    PurchaseOrder,
    ReferralCode,
)

INVITE_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,31}$")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
COMMISSION_RATE_LOW = Decimal("0.20")
COMMISSION_RATE_HIGH = Decimal("0.30")
HIGH_RATE_MIN_SUBORDINATES = 5

_UTCNOW = datetime.now(UTC).replace(tzinfo=None)


class DistributionService:
    """分销领域服务：邀请码、一级分销关系、佣金结算与查询。

    单次计税：仅有"权益购买支付"（卡密兑换权益卡 / 订单支付成功）触发佣金；
    余额充值 top-up、提现、算力消耗、赠量不计税。
    """

    def __init__(self, session=None, balance_service=None, feature_flag_service=None):
        self.session = session or db.session
        self._balance_service = balance_service
        self._feature_flag_service = feature_flag_service

    # ------------------------------------------------------------------
    # 开关
    # ------------------------------------------------------------------
    def is_enabled(self) -> bool:
        flag_service = self._get_feature_flag_service()
        if flag_service is None:
            return False
        try:
            return bool(flag_service.is_enabled("ENABLE_DISTRIBUTION"))
        except Exception:
            return False

    def _get_feature_flag_service(self):
        if self._feature_flag_service is None:
            try:
                from internal.service.orchestration_feature_flag_service import OrchestrationFeatureFlagService

                self._feature_flag_service = OrchestrationFeatureFlagService(db)
            except Exception:
                return None
        return self._feature_flag_service

    def _get_balance_service(self):
        if self._balance_service is None:
            from internal.service.balance_service import BalanceService

            self._balance_service = BalanceService(session=self.session)
        return self._balance_service

    # ------------------------------------------------------------------
    # 邀请码
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_code(code: str) -> str:
        return (code or "").strip().upper()

    @staticmethod
    def validate_new_code(code: str) -> str:
        normalized = DistributionService.normalize_code(code)
        if not 4 <= len(normalized) <= 32:
            raise FailException("邀请码长度需为 4-32 个字符")
        if not INVITE_CODE_PATTERN.match(normalized):
            raise FailException("邀请码仅支持字母、数字与 - / _ 字符")
        return normalized

    def generate_plain_code(self) -> str:
        for _ in range(50):
            candidate = "".join(random.choice(CODE_ALPHABET) for _ in range(8))
            if self._code_exists(candidate):
                continue
            return candidate
        raise FailException("邀请码生成失败，请重试")

    def ensure_referral_code(self, account_id: UUID) -> ReferralCode:
        existing = (
            self.session.query(ReferralCode)
            .filter(ReferralCode.account_id == account_id)
            .one_or_none()
        )
        if existing is not None:
            return existing
        code = self.generate_plain_code()
        referral = ReferralCode(account_id=account_id, code=code)
        self.session.add(referral)
        return referral

    def update_referral_code(self, account_id: UUID, new_code: str) -> ReferralCode:
        normalized = self.validate_new_code(new_code)
        if self._code_exists(normalized):
            raise FailException("该邀请码已被使用，请更换（大小写不敏感）")
        referral = self.ensure_referral_code(account_id)
        referral.code = normalized
        referral.updated_at = _UTCNOW
        self.session.commit()
        return referral

    def get_referral_code(self, account_id: UUID) -> str | None:
        referral = (
            self.session.query(ReferralCode)
            .filter(ReferralCode.account_id == account_id)
            .one_or_none()
        )
        return referral.code if referral else None

    def resolve_inviter_by_code(self, code: str) -> Account | None:
        normalized = self.normalize_code(code)
        if not normalized:
            return None
        referral = (
            self.session.query(ReferralCode)
            .filter(ReferralCode.code == normalized)
            .one_or_none()
        )
        if referral is None:
            return None
        inviter = (
            self.session.query(Account)
            .filter(Account.id == referral.account_id)
            .one_or_none()
        )
        if inviter is None or (inviter.status or "active") != "active":
            return None
        return inviter

    def invite_info(self, code: str) -> dict:
        normalized = self.normalize_code(code)
        inviter = self.resolve_inviter_by_code(normalized) if normalized else None
        return {
            "valid": inviter is not None,
            "required": self.is_enabled(),
            "inviter_name": inviter.name if inviter else "",
        }

    def _code_exists(self, code: str) -> bool:
        return (
            self.session.query(ReferralCode.id)
            .filter(ReferralCode.code == code)
            .first()
            is not None
        )

    # ------------------------------------------------------------------
    # 分销关系（一级）
    # ------------------------------------------------------------------
    def relation_of(self, account_id: UUID) -> DistributionRelation | None:
        return (
            self.session.query(DistributionRelation)
            .filter(DistributionRelation.invitee_account_id == account_id)
            .one_or_none()
        )

    def bind_superior(
        self,
        invitee_id: UUID,
        inviter_id: UUID,
        source: str = "register",
        operator_id: UUID | None = None,
    ) -> DistributionRelation:
        if invitee_id == inviter_id:
            raise FailException("不能绑定自己为上级")
        inviter = (
            self.session.query(Account)
            .filter(Account.id == inviter_id)
            .one_or_none()
        )
        if inviter is None or (inviter.status or "active") != "active":
            raise FailException("邀请人账户不可用")
        # 一级分销防互为上下级
        reverse = (
            self.session.query(DistributionRelation)
            .filter(DistributionRelation.invitee_account_id == inviter_id)
            .one_or_none()
        )
        if reverse is not None and reverse.inviter_account_id == invitee_id:
            raise FailException("不能互为上下级")
        existing = (
            self.session.query(DistributionRelation)
            .filter(DistributionRelation.invitee_account_id == invitee_id)
            .one_or_none()
        )
        if existing is None:
            existing = DistributionRelation(
                invitee_account_id=invitee_id,
                inviter_account_id=inviter_id,
                source=source,
                updated_by=operator_id,
            )
            self.session.add(existing)
        else:
            existing.inviter_account_id = inviter_id
            existing.source = source
            existing.updated_by = operator_id
            existing.updated_at = _UTCNOW
        return existing

    def unbind_superior(self, invitee_id: UUID, operator_id: UUID | None = None) -> bool:
        relation = self.relation_of(invitee_id)
        if relation is None:
            return False
        self.session.delete(relation)
        return True

    def direct_subordinate_count(self, account_id: UUID) -> int:
        return (
            self.session.query(DistributionRelation.id)
            .filter(DistributionRelation.inviter_account_id == account_id)
            .count()
        )

    # ------------------------------------------------------------------
    # 佣金率（20% → 满5人永久30%）
    # ------------------------------------------------------------------
    def commission_rate(self, balance_account: BalanceAccount, subordinate_count: int) -> Decimal:
        if balance_account.high_rate_locked:
            return COMMISSION_RATE_HIGH
        if subordinate_count >= HIGH_RATE_MIN_SUBORDINATES:
            balance_account.high_rate_locked = True
            balance_account.updated_at = _UTCNOW
            return COMMISSION_RATE_HIGH
        return COMMISSION_RATE_LOW

    # ------------------------------------------------------------------
    # 佣金结算（单次计税）
    # ------------------------------------------------------------------
    def settle_commission_for_redeem(self, account_id: UUID, plan: Plan, source_id: UUID) -> None:
        """卡密兑换权益卡（membership/credits）触发；调用方确保 plan_type 非 balance。"""
        if not self.is_enabled():
            return
        amount = self._purchase_amount(plan.price)
        self._settle(account_id, amount, source="redeem_code", source_id=source_id)

    def settle_commission_for_order(self, account_id: UUID, order: PurchaseOrder) -> None:
        """统一订单支付成功（直购或在线）触发；balance 充值订单由调用方过滤。"""
        if not self.is_enabled():
            return
        if order.plan_type not in ("membership", "credits"):
            return
        amount = self._purchase_amount(order.amount)
        self._settle(account_id, amount, source="order", source_id=order.id)

    def _settle(self, account_id: UUID, amount: Decimal, *, source: str, source_id: UUID) -> None:
        relation = self.relation_of(account_id)
        if relation is None:
            return
        balance_service = self._get_balance_service()
        inviter_account = balance_service.ensure_account(relation.inviter_account_id)
        rate = self.commission_rate(inviter_account, self.direct_subordinate_count(relation.inviter_account_id))
        commission = (amount * rate).quantize(Decimal("0.01"))
        if commission <= 0:
            return
        balance_service.credit(
            relation.inviter_account_id,
            commission,
            source=source,
            source_id=source_id,
            amount_type="commission",
            rate=rate,
            description=f"下级购买返佣 {rate:.0%}",
        )

    @staticmethod
    def _purchase_amount(price) -> Decimal:
        try:
            return Decimal(str(price or 0)).quantize(Decimal("0.01"))
        except Exception:
            return Decimal("0.00")

    # ------------------------------------------------------------------
    # 分销中心查询（用户侧）
    # ------------------------------------------------------------------
    def my_distribution_summary(self, account_id: UUID, base_url: str = "") -> dict:
        referral = (
            self.session.query(ReferralCode)
            .filter(ReferralCode.account_id == account_id)
            .one_or_none()
        )
        if referral is None:
            referral = ReferralCode(account_id=account_id, code=self.generate_plain_code())
            self.session.add(referral)
            self.session.commit()
        relation = self.relation_of(account_id)
        superior = None
        if relation is not None:
            account = (
                self.session.query(Account)
                .filter(Account.id == relation.inviter_account_id)
                .one_or_none()
            )
            if account is not None:
                superior = {"id": str(account.id), "name": account.name or account.username or account.email or ""}
        subordinate_count = self.direct_subordinate_count(account_id)
        balance_account = self._get_balance_service().ensure_account(account_id)
        rate = self.commission_rate(balance_account, subordinate_count)
        self.session.commit()
        share_path = f"/register?invite={referral.code}"
        return {
            "referral_code": referral.code,
            "share_url": f"{base_url.rstrip('/')}{share_path}" if base_url else share_path,
            "superior": superior,
            "subordinate_count": subordinate_count,
            "high_rate_locked": bool(balance_account.high_rate_locked),
            "commission_rate": f"{rate * 100:.0f}",
        }

    def list_subordinates(self, account_id: UUID, current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = (
            self.session.query(DistributionRelation, Account)
            .join(Account, Account.id == DistributionRelation.invitee_account_id)
            .filter(DistributionRelation.inviter_account_id == account_id)
            .order_by(DistributionRelation.bound_at.desc())
        )
        total = query.count()
        rows = query.offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [
                {
                    "id": str(account.id),
                    "name": account.name or account.username or account.email or "",
                    "email": account.email or "",
                    "bound_at": self._timestamp(relation.bound_at),
                    "source": relation.source,
                }
                for relation, account in rows
            ],
            "paginator": self._paginator(total, current_page, page_size),
        }

    def list_commissions(self, account_id: UUID | None = None, current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = (
            self.session.query(BalanceTransaction)
            .filter(BalanceTransaction.amount_type == "commission")
            .order_by(BalanceTransaction.created_at.desc())
        )
        if account_id is not None:
            query = query.filter(BalanceTransaction.account_id == account_id)
        total = query.count()
        rows = query.offset((current_page - 1) * page_size).limit(page_size).all()
        account_names = self._account_name_map([row.account_id for row in rows])
        buyer_names = self._commission_buyer_names(rows)
        return {
            "list": [
                {
                    "id": str(row.id),
                    "account_id": str(row.account_id),
                    "account_name": account_names.get(row.account_id),
                    "buyer_name": buyer_names.get(str(row.id)),
                    "amount": float(row.amount),
                    "rate": float(row.rate) * 100 if row.rate is not None else None,
                    "source": row.source,
                    "source_id": str(row.source_id) if row.source_id else None,
                    "description": row.description,
                    "created_at": self._timestamp(row.created_at),
                }
                for row in rows
            ],
            "paginator": self._paginator(total, current_page, page_size),
        }

    def _commission_buyer_names(self, rows: list[BalanceTransaction]) -> dict:
        """佣金流水反查“消费的下级账号名”。

        佣金由下级购买/兑换触发，source_id 指向订单或卡密；
        通过订单/卡密定位到实际消费账号，再取账号名展示为来源。
        """
        order_rows = [row for row in rows if row.source == "order" and row.source_id is not None]
        redeem_rows = [row for row in rows if row.source == "redeem_code" and row.source_id is not None]
        buyer_account_ids: dict[str, UUID] = {}
        if order_rows:
            order_ids = [row.source_id for row in order_rows]
            orders = (
                self.session.query(PurchaseOrder.id, PurchaseOrder.account_id)
                .filter(PurchaseOrder.id.in_(order_ids))
                .all()
            )
            for order in orders:
                for row in order_rows:
                    if row.source_id == order.id:
                        buyer_account_ids[str(row.id)] = order.account_id
                        break
        if redeem_rows:
            from internal.model.billing import RedeemCode

            redeem_ids = [row.source_id for row in redeem_rows]
            codes = (
                self.session.query(RedeemCode.id, RedeemCode.redeemed_by)
                .filter(RedeemCode.id.in_(redeem_ids))
                .all()
            )
            for code in codes:
                if code.redeemed_by is None:
                    continue
                for row in redeem_rows:
                    if row.source_id == code.id:
                        buyer_account_ids[str(row.id)] = code.redeemed_by
                        break
        if not buyer_account_ids:
            return self._fallback_buyer_names(rows)
        accounts = (
            self.session.query(Account.id, Account.name, Account.username, Account.email)
            .filter(Account.id.in_(list(buyer_account_ids.values())))
            .all()
        )
        name_by_account = {
            account.id: account.name or account.username or account.email or ""
            for account in accounts
        }
        resolved = {
            transaction_id: name_by_account.get(account_id) or ""
            for transaction_id, account_id in buyer_account_ids.items()
        }
        # 未反查到名的记录（历史/测试数据 source 无对应单据）回退解析 description
        fallback = self._fallback_buyer_names(rows)
        for transaction_id, name in fallback.items():
            if transaction_id not in resolved or not resolved[transaction_id]:
                resolved[transaction_id] = name
        return resolved

    @staticmethod
    def _fallback_buyer_names(rows: list[BalanceTransaction]) -> dict:
        """从 description 中提取来源用户名。

        兼容两种真实文案形态：
        - “下级购买返佣 30% · tmp5”（测试/历史含用户）
        - “下级购买返佣 30%”（通用，无可提取则留空由前端兜底）
        """
        import re as _re

        result: dict[str, str] = {}
        pattern = _re.compile(r"(?:·|：|返佣\s*)[^\s·]{1,64}$")
        for row in rows:
            desc = (row.description or "").strip()
            name = ""
            match = pattern.search(desc)
            if match:
                candidate = match.group(0).lstrip("·：返佣 \t")
                # 去掉比例与多余描述，仅保留名字（不为纯数字）
                if candidate and not _re.fullmatch(r"[\d.%]+", candidate):
                    name = candidate
            result[str(row.id)] = name
        return result

    def _account_name_map(self, account_ids: list[UUID]) -> dict:
        ids = {account_id for account_id in account_ids if account_id}
        if not ids:
            return {}
        rows = self.session.query(Account.id, Account.name, Account.username, Account.email).filter(Account.id.in_(ids)).all()
        return {
            row.id: row.name or row.username or row.email or ""
            for row in rows
        }

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