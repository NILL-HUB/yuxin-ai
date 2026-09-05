import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.model.billing import CreditAccount, CreditTransaction, Membership, Plan, RedeemCode, RedeemCodeBatch
from internal.model.conversation import Message
from internal.service.admin_redeem_code_service import AdminRedeemCodeService


class RedeemCodeService:
    CODE_PATTERN = re.compile(r"^OA-[A-Z0-9]{24}$")

    def __init__(self, session=None, balance_service=None, distribution_service=None):
        self.session = session or db.session
        self._balance_service = balance_service
        self._distribution_service = distribution_service

    def _get_balance_service(self):
        if self._balance_service is None:
            from internal.service.balance_service import BalanceService

            self._balance_service = BalanceService(session=self.session)
        return self._balance_service

    def _get_distribution_service(self):
        if self._distribution_service is None:
            try:
                from internal.service.distribution_service import DistributionService

                self._distribution_service = DistributionService(session=self.session)
            except ImportError:
                return None
        return self._distribution_service

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    def redeem(self, account_id: UUID, plain_code: str) -> dict:
        normalized_code = self._normalize_plain_code(plain_code)
        redeem_code = self._get_code_by_plain_code(normalized_code)
        if redeem_code is None:
            raise NotFoundException("卡密不存在，请检查后重新输入")
        self._ensure_code_redeemable(redeem_code)
        batch = self._get_batch_or_raise(redeem_code.batch_id)
        self._ensure_batch_redeemable(batch)
        plan = self._get_plan_or_raise(redeem_code.plan_id)
        if not plan.is_active:
            raise FailException("关联套餐已禁用，请联系客服")
        plan_type = (plan.plan_type or "membership").strip().lower()
        if plan_type not in ("balance", "membership", "credits"):
            raise FailException("套餐类型无效，请联系客服")
        self._ensure_code_not_redeemed(plan_type, redeem_code.id, account_id)

        membership = None
        credit_account = None
        if plan_type == "balance":
            self._get_balance_service().credit(
                account_id,
                plan.price,
                source="redeem_code",
                source_id=redeem_code.id,
                amount_type="recharge",
                description=f"卡密兑换余额充值 {plan.price} 元",
            )
        elif plan_type == "membership":
            membership = self._upsert_membership(account_id, plan, redeem_code.id)
            credit_account = self._grant_quota_credits(account_id, plan.grant_token_credits, redeem_code.id)
            self._settle_commission(account_id, plan, redeem_code.id)
        else:
            credit_account = self._grant_permanent_credits(account_id, plan.grant_token_credits, redeem_code.id)
            self._settle_commission(account_id, plan, redeem_code.id)

        now = self._now()
        redeem_code.status = "used"
        redeem_code.redeemed_by = account_id
        redeem_code.redeemed_at = now
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            if self._is_redeem_idempotent_conflict(error):
                raise FailException("该卡密已被兑换") from error
            raise
        return {
            "plan": self._serialize_plan(plan),
            "membership": self._serialize_membership(membership, plan) if membership else None,
            "credit_account": self._serialize_credit_account(credit_account) if credit_account else self._empty_credit_account(account_id),
            "redeem_code": {"id": str(redeem_code.id), "code_mask": redeem_code.code_mask, "redeemed_at": self._timestamp(redeem_code.redeemed_at)},
        }

    def _ensure_code_not_redeemed(self, plan_type: str, redeem_code_id: UUID, account_id: UUID) -> None:
        if plan_type == "balance":
            existing = self._get_balance_service().find_transaction(account_id, "redeem_code", redeem_code_id, "recharge")
            if existing is not None:
                raise FailException("该卡密已被兑换")
            return
        if self._get_redeem_grant_transaction(redeem_code_id) is not None:
            raise FailException("该卡密已被兑换")

    def _settle_commission(self, account_id: UUID, plan: Plan, source_id: UUID) -> None:
        distribution_service = self._get_distribution_service()
        if distribution_service is None:
            return
        settle = getattr(distribution_service, "settle_commission_for_redeem", None)
        if settle is None:
            return
        settle(account_id, plan, source_id)

    def get_membership_summary(self, account_id: UUID) -> dict:
        membership = self._get_current_membership(account_id)
        plan = self._get_plan_or_raise(membership.plan_id) if membership else None
        credit_account = self._get_credit_account(account_id)
        transactions = self._list_recent_transactions(account_id)
        task_rows = self._build_recent_tasks(account_id, transactions)
        query_by_transaction = {
            task["id"]: task["message"]
            for task in task_rows
            if task.get("message")
        }
        return {
            "membership": self._serialize_membership(membership, plan) if membership else None,
            "credit_account": self._serialize_credit_account(credit_account) if credit_account else self._empty_credit_account(account_id),
            "recent_transactions": [
                self._serialize_transaction(transaction, query_by_transaction.get(str(transaction.id)))
                for transaction in transactions
            ],
            "recent_tasks": task_rows,
        }

    def _build_recent_tasks(self, account_id: UUID, transactions: list[CreditTransaction]) -> list[dict]:
        """最近任务消耗：一次用户提问（message）对应一条算力消费。

        优先按 source_id 精确关联消息取用户问题原文；部分历史数据因
        消息重建导致 id 对不上，此时按“扣费时间相近的同账号最近提问”
        回退匹配，保证列表始终能呈现真实问题。仍找不到则退化为通用说明。
        """
        consume_transactions = [
            transaction
            for transaction in transactions
            if transaction.transaction_type == "consume"
            or int(transaction.amount or 0) < 0
        ]
        tasks: list[dict] = []
        for transaction in consume_transactions[:10]:
            query = None
            if transaction.source == "message" and transaction.source_id is not None:
                message = (
                    self.session.query(Message)
                    .filter(Message.id == transaction.source_id)
                    .one_or_none()
                )
                if message is None and transaction.created_at is not None:
                    # 回退匹配：扣费前后 3 分钟内该账号最近一次用户提问
                    window_start = transaction.created_at - timedelta(minutes=3)
                    window_end = transaction.created_at + timedelta(minutes=3)
                    message = (
                        self.session.query(Message)
                        .filter(
                            Message.created_by == account_id,
                            Message.created_at >= window_start,
                            Message.created_at <= window_end,
                            Message.is_deleted.is_(False),
                        )
                        .order_by(Message.created_at.desc())
                        .first()
                    )
                if message is not None:
                    query = (message.query or "").strip() or None
            tasks.append(
                {
                    "id": str(transaction.id),
                    "amount": int(transaction.amount or 0),
                    "transaction_type": transaction.transaction_type,
                    "source": transaction.source,
                    "source_id": str(transaction.source_id) if transaction.source_id else None,
                    "message": query,
                    "created_at": self._timestamp(transaction.created_at),
                }
            )
        return tasks

    def list_redeem_records(self, account_id: UUID) -> dict:
        redeem_codes = self._list_user_redeem_codes(account_id)
        return {"list": [self._serialize_redeem_record(account_id, redeem_code) for redeem_code in redeem_codes]}

    def _normalize_plain_code(self, plain_code: str) -> str:
        normalized_code = (plain_code or "").strip().upper()
        if not normalized_code:
            raise FailException("请输入卡密")
        if not self.CODE_PATTERN.match(normalized_code):
            raise FailException("卡密格式错误，请检查后重新输入")
        return normalized_code

    def _ensure_code_redeemable(self, redeem_code: RedeemCode) -> None:
        now = self._now()
        if redeem_code.status == "used":
            raise FailException("该卡密已被兑换")
        if redeem_code.status == "disabled" or redeem_code.disabled_at is not None:
            raise FailException("该卡密已被禁用，请联系客服")
        if redeem_code.expires_at is not None and redeem_code.expires_at < now:
            raise FailException("该卡密已过期")
        if redeem_code.status != "unused":
            raise FailException("该卡密状态异常，请联系客服")

    def _get_code_by_plain_code(self, plain_code: str) -> RedeemCode | None:
        return (
            self.session.query(RedeemCode)
            .filter(RedeemCode.code_hash == AdminRedeemCodeService.hash_code(plain_code))
            .with_for_update()
            .one_or_none()
        )

    def _get_batch_or_raise(self, batch_id: UUID) -> RedeemCodeBatch:
        batch = self.session.query(RedeemCodeBatch).filter(RedeemCodeBatch.id == batch_id).one_or_none()
        if batch is None:
            raise NotFoundException("卡密批次不存在，请联系客服")
        return batch

    def _ensure_batch_redeemable(self, batch: RedeemCodeBatch) -> None:
        if batch.status == "disabled" or batch.disabled_at is not None:
            raise FailException("该批次已被禁用，请联系客服")

    def _get_plan_or_raise(self, plan_id: UUID) -> Plan:
        plan = self.session.query(Plan).filter(Plan.id == plan_id).one_or_none()
        if plan is None:
            raise NotFoundException("关联套餐不存在，请联系客服")
        return plan

    def _get_redeem_grant_transaction(self, source_id: UUID) -> CreditTransaction | None:
        return (
            self.session.query(CreditTransaction)
            .filter(
                CreditTransaction.source == "redeem_code",
                CreditTransaction.source_id == source_id,
                CreditTransaction.transaction_type == "redeem_grant",
            )
            .one_or_none()
        )

    def _is_redeem_idempotent_conflict(self, error: IntegrityError) -> bool:
        message = str(error)
        return "credit_transaction_source_type_unique_idx" in message or "uq_balance_transaction_account_source_type" in message

    def _get_current_membership(self, account_id: UUID) -> Membership | None:
        return (
            self.session.query(Membership)
            .filter(Membership.account_id == account_id)
            .order_by(Membership.expires_at.desc())
            .first()
        )

    def _upsert_membership(self, account_id: UUID, plan: Plan, source_id: UUID) -> Membership:
        now = self._now()
        membership = self._get_current_membership(account_id)
        if membership and membership.plan_id == plan.id and membership.expires_at and membership.expires_at > now:
            base_time = membership.expires_at
            membership.expires_at = base_time + timedelta(days=int(plan.duration_days or 0))
            membership.status = "active"
            membership.source = "redeem_code"
            membership.source_id = source_id
            membership.updated_at = now
            return membership
        membership = Membership(
            account_id=account_id,
            plan_id=plan.id,
            status="active",
            started_at=now,
            expires_at=now + timedelta(days=int(plan.duration_days or 0)),
            source="redeem_code",
            source_id=source_id,
        )
        self.session.add(membership)
        return membership

    def _get_credit_account(self, account_id: UUID) -> CreditAccount | None:
        return self.session.query(CreditAccount).filter(CreditAccount.account_id == account_id).one_or_none()

    def _grant_quota_credits(self, account_id: UUID, amount: int, source_id: UUID) -> CreditAccount:
        """会员套餐：算力进入套餐额度池（随会员过期清零）。"""
        return self._grant_credits(account_id, amount, source_id, pool="quota")

    def _grant_permanent_credits(self, account_id: UUID, amount: int, source_id: UUID) -> CreditAccount:
        """算力包：算力进入永久算力池（永不过期）。"""
        return self._grant_credits(account_id, amount, source_id, pool="permanent")

    def _grant_credits(self, account_id: UUID, amount: int, source_id: UUID, *, pool: str) -> CreditAccount:
        credit_account = self._get_credit_account(account_id)
        if credit_account is None:
            credit_account = CreditAccount(account_id=account_id, permanent_credit=0, quota_credit=0, total_granted=0, total_consumed=0)
            self.session.add(credit_account)
        granted = int(amount or 0)
        if pool == "quota":
            credit_account.quota_credit = int(credit_account.quota_credit or 0) + granted
        else:
            credit_account.permanent_credit = int(credit_account.permanent_credit or 0) + granted
        credit_account.total_granted = int(credit_account.total_granted or 0) + granted
        credit_account.updated_at = self._now()
        self.session.add(CreditTransaction(
            account_id=account_id,
            amount=granted,
            balance_after=credit_account.available_tokens,
            transaction_type="redeem_grant",
            source="redeem_code",
            source_id=source_id,
            description="卡密兑换赠送算力值",
        ))
        return credit_account

    def _list_user_redeem_codes(self, account_id: UUID) -> list[RedeemCode]:
        return (
            self.session.query(RedeemCode)
            .filter(RedeemCode.redeemed_by == account_id, RedeemCode.status == "used")
            .order_by(RedeemCode.redeemed_at.desc())
            .all()
        )

    def _get_membership_by_source(self, account_id: UUID, source_id: UUID) -> Membership | None:
        return (
            self.session.query(Membership)
            .filter(Membership.account_id == account_id, Membership.source == "redeem_code", Membership.source_id == source_id)
            .one_or_none()
        )

    def _list_recent_transactions(self, account_id: UUID) -> list[CreditTransaction]:
        return (
            self.session.query(CreditTransaction)
            .filter(CreditTransaction.account_id == account_id)
            .order_by(CreditTransaction.created_at.desc())
            .all()
        )[:10]

    def _serialize_plan(self, plan: Plan) -> dict:
        return {
            "id": str(plan.id),
            "code": plan.code,
            "name": plan.name,
            "duration_days": int(plan.duration_days or 0),
            "grant_token_credits": int(plan.grant_token_credits or 0),
        }

    def _serialize_membership(self, membership: Membership, plan: Plan | None) -> dict:
        return {
            "id": str(membership.id),
            "status": membership.status,
            "started_at": self._timestamp(membership.started_at),
            "expires_at": self._timestamp(membership.expires_at),
            "source": membership.source,
            "source_id": str(membership.source_id) if membership.source_id else None,
            "plan": self._serialize_plan(plan) if plan else None,
        }

    def _serialize_credit_account(self, credit_account: CreditAccount) -> dict:
        return {
            "account_id": str(credit_account.account_id),
            "balance": credit_account.available_tokens,
            "total_granted": int(credit_account.total_granted or 0),
            "total_consumed": int(credit_account.total_consumed or 0),
            "quota_granted": int(credit_account.quota_granted or 0),
            "quota_cycle_days": int(credit_account.quota_cycle_days or 0),
            "quota_reset_at": self._timestamp(credit_account.quota_reset_at),
        }

    def _empty_credit_account(self, account_id: UUID) -> dict:
        return {
            "account_id": str(account_id),
            "balance": 0,
            "total_granted": 0,
            "total_consumed": 0,
            "quota_granted": 0,
            "quota_cycle_days": 0,
            "quota_reset_at": None,
        }

    def _serialize_redeem_record(self, account_id: UUID, redeem_code: RedeemCode) -> dict:
        plan = self._get_plan_or_raise(redeem_code.plan_id)
        membership = self._get_membership_by_source(account_id, redeem_code.id)
        return {
            "id": str(redeem_code.id),
            "code_mask": redeem_code.code_mask,
            "redeemed_at": self._timestamp(redeem_code.redeemed_at),
            "plan": self._serialize_plan(plan),
            "grant_token_credits": int(plan.grant_token_credits or 0),
            "membership_expires_at": self._timestamp(membership.expires_at) if membership else None,
        }

    def _serialize_transaction(self, transaction: CreditTransaction, message_query: str | None = None) -> dict:
        description = transaction.description
        # 消费流水：若已关联到用户问题，则前台用「问题」替代 token 算式说明
        is_consume = transaction.transaction_type == "consume" or int(transaction.amount or 0) < 0
        if is_consume and message_query:
            description = message_query
        return {
            "id": str(transaction.id),
            "amount": int(transaction.amount or 0),
            "balance_after": int(transaction.balance_after or 0),
            "transaction_type": transaction.transaction_type,
            "source": transaction.source,
            "source_id": str(transaction.source_id) if transaction.source_id else None,
            "description": description,
            "created_at": self._timestamp(transaction.created_at),
        }
