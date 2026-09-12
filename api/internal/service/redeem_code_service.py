import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func
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
        consume_window = self._list_recent_consume_window(account_id)
        task_rows = self._build_recent_tasks(account_id, consume_window)
        return {
            "membership": self._serialize_membership(membership, plan) if membership else None,
            "credit_account": self._serialize_credit_account(credit_account) if credit_account else self._empty_credit_account(account_id),
            "recent_transactions": [
                self._serialize_transaction(transaction) for transaction in transactions
            ],
            "recent_tasks": task_rows,
        }

    def _build_recent_tasks(self, account_id: UUID, transactions: list[CreditTransaction]) -> list[dict]:
        """最近任务消耗：按「用户消息」边界把扣费聚合成任务行。

        一次用户提问（message）执行期间产生的多笔模型调用扣费归并为一条任务：
        amount=该任务合计、message=用户问题原文。归属规则与流水接口一致——
        消费归属到“不晚于其发生时间的最近一条用户提问”，保证与「算力流水」卡片口径统一。
        """
        consume_transactions = [
            transaction
            for transaction in transactions
            if transaction.transaction_type == "consume"
            or int(transaction.amount or 0) < 0
        ]
        if not consume_transactions:
            return []
        messages = (
            self.session.query(Message)
            .filter(
                Message.created_by == account_id,
                Message.is_deleted.is_(False),
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        anchors = [(message.created_at, message) for message in messages]
        rows = self._build_task_flow_rows(consume_transactions, anchors)
        # 仅保留消费任务行（负净额/含消费类型的聚合行），按最近时间降序
        consume_rows = [
            row for row in rows if row["transaction_type"] == "consume" and row["amount"] < 0
        ]
        consume_rows.sort(key=lambda row: row["_sort_at"], reverse=True)
        tasks: list[dict] = []
        for row in consume_rows[:6]:
            tasks.append({
                "id": row.get("id") or "",
                "amount": int(row["amount"] or 0),
                "transaction_type": "consume",
                "source": row.get("source", ""),
                "source_id": row.get("source_id"),
                "message": row.get("task_message") or row.get("description") or None,
                "created_at": self._timestamp(row["_sort_at"]),
            })
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

    def _list_recent_consume_window(self, account_id: UUID) -> list[CreditTransaction]:
        """拉取足够覆盖“最近几次任务”的消费流水（上限 500 条）。

        一次用户任务可能产生大量模型调用级扣费，仅取最近 10 条会被单次
        长任务占满，导致「最近任务消耗」看不到真实的多任务分布。
        """
        return (
            self.session.query(CreditTransaction)
            .filter(
                CreditTransaction.account_id == account_id,
                CreditTransaction.transaction_type == "consume",
            )
            .order_by(CreditTransaction.created_at.desc())
            .all()
        )[:500]

    def list_credit_transactions(
        self,
        account_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """分页返回算力流水（任务级聚合）与累计消耗。

        消费按「用户消息」切分为任务：同一条用户消息执行期间产生的
        多笔模型调用扣费聚合成一行（避免“一次任务被拆成几十笔 -1/-2”），
        行文案用用户消息原文；充值/到账（redeem_grant/order_grant）各自成行。
        """
        page = max(int(page or 1), 1)
        page_size = min(max(int(page_size or 20), 1), 100)
        transactions = (
            self.session.query(CreditTransaction)
            .filter(CreditTransaction.account_id == account_id)
            .order_by(CreditTransaction.created_at.asc())
            .all()
        )
        messages = (
            self.session.query(Message)
            .filter(
                Message.created_by == account_id,
                Message.is_deleted.is_(False),
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        # 消息时间锚点（升序），用于把消费归属到“不晚于扣费时间的最近一次用户提问”。
        anchors = [(message.created_at, message) for message in messages]
        rows = self._build_task_flow_rows(transactions, anchors)
        rows.sort(key=lambda row: row["_sort_at"], reverse=True)
        total = len(rows)
        total_consumed_row = (
            self.session.query(func.coalesce(func.sum(-CreditTransaction.amount), 0))
            .filter(
                CreditTransaction.account_id == account_id,
                CreditTransaction.amount < 0,
            )
            .scalar()
        )
        items = rows[(page - 1) * page_size : page * page_size]
        return {
            "list": [
                {
                    "id": row.get("id"),
                    "amount": row["amount"],
                    "balance_after": 0,
                    "transaction_type": row["transaction_type"],
                    "source": row.get("source", ""),
                    "source_id": row.get("source_id"),
                    "description": row["description"],
                    "created_at": self._timestamp(row["_sort_at"]),
                    "ref_id": row.get("ref_id"),
                    "tx_count": row.get("tx_count"),
                    "task_message": row.get("task_message"),
                }
                for row in items
            ],
            "total": int(total),
            "total_consumed": int(total_consumed_row or 0),
            "page": page,
            "page_size": page_size,
        }

    def _build_task_flow_rows(
        self,
        transactions: list[CreditTransaction],
        anchors: list[tuple],
    ) -> list[dict]:
        """把消费按用户消息边界聚合成任务行，充值/到账各自成行。"""
        rows: list[dict] = []
        pending: dict = {}  # message_id -> task dict（聚合中）
        for transaction in transactions:
            amount = int(transaction.amount or 0)
            if amount >= 0 or transaction.transaction_type != "consume":
                # 充值/到账/调整等正向或非消费行：各自成行，保留原始时间
                rows.append({
                    "id": str(transaction.id),
                    "amount": amount,
                    "transaction_type": transaction.transaction_type,
                    "source": transaction.source,
                    "source_id": str(transaction.source_id) if transaction.source_id else None,
                    "description": transaction.description or "",
                    "_sort_at": transaction.created_at,
                    "tx_count": None,
                })
                continue
            # 消费行：归属到不晚于扣费时间的最近一条用户消息
            owner = None
            for msg_at, message in anchors:
                if msg_at <= transaction.created_at:
                    owner = message
                else:
                    break
            task = pending.get(str(owner.id)) if owner is not None else None
            if task is None:
                task = {
                    "id": str(transaction.id),
                    "amount": 0,
                    "transaction_type": "consume",
                    "source": transaction.source,
                    "source_id": str(transaction.source_id) if transaction.source_id else None,
                    "description": (owner.query or "").strip() or "算力任务消耗"
                    if owner is not None
                    else (transaction.description or "算力任务消耗"),
                    "_sort_at": transaction.created_at,
                    "_last_at": transaction.created_at,
                    "tx_count": 0,
                    "task_message": (owner.query or "").strip() if owner is not None else None,
                    "_key": str(owner.id) if owner is not None else None,
                }
                if owner is not None:
                    pending[str(owner.id)] = task
                else:
                    rows.append(task)
                    continue
            task["amount"] += amount
            task["tx_count"] = int(task.get("tx_count") or 0) + 1
            task["_last_at"] = max(task["_last_at"], transaction.created_at)
            task["_sort_at"] = task["_last_at"]
        consumed_keys = set(pending.keys())
        return [row for row in rows if row.get("_key") not in consumed_keys] + list(pending.values())

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
