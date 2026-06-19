import logging

from injector import inject

from internal.entity.orchestrator_entity import RequestContext
from internal.model.billing import CreditAccount
from pkg.sqlalchemy import SQLAlchemy


logger = logging.getLogger(__name__)

MINIMUM_BALANCE_FOR_DEEP_THINKING = 1


@inject
class RequestContextBuilder:
    DEFAULT_BALANCE_CREDITS = 1.0
    DEFAULT_BUDGET_LEVEL = "normal"

    def __init__(self, db: SQLAlchemy = None):
        self.db = db

    def build(self, query: str, **context) -> RequestContext:
        enable_deep_thinking = bool(context.get("enable_deep_thinking"))
        account_id = self._text(context.get("account_id"))
        balance_credits = self._resolve_balance(account_id, context.get("balance_credits"))
        return RequestContext(
            query=self._normalize_query(query),
            account_id=account_id,
            conversation_id=self._text(context.get("conversation_id")),
            message_id=self._text(context.get("message_id")),
            image_urls=self._image_urls(context.get("image_urls")),
            enable_deep_thinking=enable_deep_thinking,
            deep_thinking_requested=enable_deep_thinking,
            budget_level=self._budget_level(context.get("budget_level")),
            balance_credits=balance_credits,
            budget_allowed=balance_credits >= MINIMUM_BALANCE_FOR_DEEP_THINKING,
            routing_log_id=context.get("routing_log_id"),
        )

    def _resolve_balance(self, account_id: str, override=None) -> float:
        if override is not None:
            try:
                return max(float(override), 0.0)
            except (TypeError, ValueError):
                pass
        if not account_id or self.db is None:
            return 0.0
        try:
            credit_account = (
                self.db.session.query(CreditAccount)
                .filter_by(account_id=account_id)
                .first()
            )
            return float(credit_account.get_balance()) if credit_account else 0.0
        except Exception:
            logger.warning("查询账户余额失败", exc_info=True)
            return 0.0

    @staticmethod
    def _normalize_query(query: str) -> str:
        return (query or "").strip()

    @staticmethod
    def _text(value) -> str:
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _image_urls(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]

    def _budget_level(self, value) -> str:
        text = self._text(value) or self.DEFAULT_BUDGET_LEVEL
        return text if text in {"low", "normal", "high"} else self.DEFAULT_BUDGET_LEVEL
