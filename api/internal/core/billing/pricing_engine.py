"""定价引擎：系统内唯一计价入口。

售价/成本列口径均为 人民币元 / 1k token（后台按真实金额配置）：
扣费算力 = Σ tokens × 售价(元/1k) ÷ 1000 × credits_per_yuan（向上取整）
成本算力 = Σ tokens × 成本(元/1k) ÷ 1000 × credits_per_yuan
毛利算力 = 扣费算力 − 成本算力

模型未配置售价时回退全局汇率（credits_per_1k_tokens）作为兜底。
"""
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from internal.extension.database_extension import db
from internal.model.billing import BillingConfig
from internal.model.model_pool_entity import ModelPoolConfig

logger = logging.getLogger(__name__)


@dataclass
class BillingPlan:
    sell_credits: int
    cost_credits: int
    margin_credits: int
    billing_basis: str
    input_tokens: int = 0
    output_tokens: int = 0
    # 以下 *_per_1k 均为 人民币元/1k 口径（售价与成本同单位）
    sell_input_per_1k: float = 0.0
    sell_output_per_1k: float = 0.0
    cost_input_per_1k: float = 0.0
    cost_output_per_1k: float = 0.0
    cached_input_tokens: int = 0
    price_tier: str | None = None   # "peak" / "valley" / None
    sell_cached_input_per_1k: float = 0.0
    cost_cached_input_per_1k: float = 0.0


def _in_days(spec: str, weekday: str) -> bool:
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                if int(a) <= int(weekday) <= int(b):
                    return True
            except ValueError:
                continue
        elif part == weekday:
            return True
    return False


class PricingEngine:
    DEFAULT_CREDITS_PER_1K = 1
    DEFAULT_CREDITS_PER_YUAN = 100

    def __init__(self, session=None, configs: dict[str, float] | None = None):
        # 生产环境无 session 传入时惰性绑定真实会话（同 CreditService 约定），
        # 否则模型明细查询取不到，会退化为全局汇率兜底，导致"按模型单价扣费"失效。
        self.session = session
        self._configs = configs or {}

    def _resolve_session(self):
        if self.session is None:
            self.session = db.session
        return self.session

    @staticmethod
    def _resolve_price_tier(moment, windows, tz_name: str, enabled: bool) -> str | None:
        """moment(UTC) 按 tz_name 折算后判断是否落在任一高峰窗口；未启用或空窗口返回 None。"""
        if not enabled or not windows:
            return None
        try:
            if moment is None:
                moment = datetime.now(UTC)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            local = moment.astimezone(ZoneInfo(tz_name or "Asia/Shanghai"))
            hhmm = f"{local.hour:02d}:{local.minute:02d}"
            weekday = str(local.weekday())  # 0=周一
        except Exception:
            return None
        for win in windows:
            if not isinstance(win, dict):
                continue
            days = str(win.get("days", "") or "")
            start = str(win.get("start", "") or "")
            end = str(win.get("end", "") or "")
            if not (days and start and end):
                continue
            if not _in_days(days, weekday):
                continue
            if start <= end:
                if start <= hhmm <= end:
                    return "peak"
            else:  # 跨午夜窗口（原子化为两段更稳妥，此处兜底支持）
                if hhmm >= start or hhmm <= end:
                    return "peak"
        return "valley"

    def plan_usage(self, model_id: str, *, input_tokens: int, output_tokens: int,
                   cached_input_tokens: int = 0, moment=None) -> BillingPlan:
        input_tokens = max(int(input_tokens or 0), 0)
        output_tokens = max(int(output_tokens or 0), 0)
        cached_input_tokens = max(int(cached_input_tokens or 0), 0)
        model = self._load_model(model_id)
        credits_per_1k = self._config("credits_per_1k_tokens", self.DEFAULT_CREDITS_PER_1K)
        credits_per_yuan = self._config("credits_per_yuan", self.DEFAULT_CREDITS_PER_YUAN)

        enabled_pv = bool(getattr(model, "peak_valley_enabled", False))
        enabled_cache = bool(getattr(model, "cache_pricing_enabled", False))
        if not enabled_cache:
            cached_input_tokens = 0
        input_tokens = max(input_tokens - cached_input_tokens, 0)  # 剩余为未命中
        windows = getattr(model, "peak_windows", None) or []
        if enabled_pv and windows:
            tz_name = self._config_text("peak_valley_timezone", "Asia/Shanghai")
        else:
            tz_name = "Asia/Shanghai"
        tier = self._resolve_price_tier(moment, windows, tz_name, enabled_pv)

        fallback = BillingPlan(
            sell_credits=0, cost_credits=0, margin_credits=0, billing_basis="global_rate",
            input_tokens=input_tokens, output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens, price_tier=tier,
        )

        if model is None:
            fallback.sell_credits = self._ceil_credits(input_tokens + output_tokens, credits_per_1k)
            logger.warning(
                "pricing_engine fallback_to_global_rate model_id=%s reason=%s billing_basis=%s "
                "price_tier=%s input_tokens=%d output_tokens=%d cached_input_tokens=%d",
                model_id or "", "model_not_found", fallback.billing_basis,
                tier, input_tokens, output_tokens, cached_input_tokens,
            )
            return fallback

        def _col_sell(name_peak, name_valley, name_flat):
            if enabled_pv and tier == "peak":
                return self._decimal_float(getattr(model, name_peak, 0) or 0)
            if enabled_pv and tier == "valley":
                return self._decimal_float(getattr(model, name_valley, 0) or 0)
            return self._decimal_float(getattr(model, name_flat, 0) or 0)

        # 售价列口径 = 人民币元/1k（与成本列一致）；扣费算力 = 元 × credits_per_yuan
        sell_in = _col_sell("peak_input_price_per_1k_tokens", "valley_input_price_per_1k_tokens", "input_price_per_1k_tokens")
        sell_out = _col_sell("peak_output_price_per_1k_tokens", "valley_output_price_per_1k_tokens", "output_price_per_1k_tokens")
        sell_cached = _col_sell("peak_input_cached_price_per_1k_tokens", "valley_input_cached_price_per_1k_tokens", "input_cached_price_per_1k_tokens")
        base_price = self._decimal_float(getattr(model, "price_per_1k_tokens", 0) or 0)
        if not sell_in:
            sell_in = base_price
        if not sell_out:
            sell_out = base_price

        if sell_in <= 0 and sell_out <= 0:
            # 无任何售价配置 → 全局汇率兜底
            fallback.sell_credits = self._ceil_credits(input_tokens + cached_input_tokens + output_tokens, credits_per_1k)
            logger.warning(
                "pricing_engine fallback_to_global_rate model_id=%s reason=%s billing_basis=%s "
                "price_tier=%s input_tokens=%d output_tokens=%d cached_input_tokens=%d",
                model_id or "", "no_model_price", fallback.billing_basis,
                tier, input_tokens, output_tokens, cached_input_tokens,
            )
            return fallback

        # 售价金额(元) = Σ tokens × 元/1k ÷ 1000；扣费算力 = ceil(金额 × credits_per_yuan)
        # ceil 放在汇率折算之后一次性执行（与成本侧 cost=ceil(cost_rmb×cpy) 对称），
        # 避免逐维向上取整导致毛利系统性虚增。
        sell_rmb = (input_tokens * sell_in + cached_input_tokens * sell_cached + output_tokens * sell_out) / 1000
        sell = math.ceil(sell_rmb * credits_per_yuan)

        cost_in = _col_sell("peak_input_cost_per_1k_tokens", "valley_input_cost_per_1k_tokens", "input_cost_per_1k_tokens")
        cost_out = _col_sell("peak_output_cost_per_1k_tokens", "valley_output_cost_per_1k_tokens", "output_cost_per_1k_tokens")
        cost_cached = _col_sell("peak_input_cached_cost_per_1k_tokens", "valley_input_cached_cost_per_1k_tokens", "input_cached_cost_per_1k_tokens")
        cost_rmb = (input_tokens * cost_in + cached_input_tokens * cost_cached + output_tokens * cost_out) / 1000
        cost = math.ceil(cost_rmb * credits_per_yuan)

        return BillingPlan(
            sell_credits=max(sell, 0),
            cost_credits=max(cost, 0),
            margin_credits=sell - cost,
            billing_basis="model_price" if not (enabled_pv or enabled_cache) else "model_price_tier",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            price_tier=tier,
            sell_input_per_1k=sell_in,
            sell_output_per_1k=sell_out,
            sell_cached_input_per_1k=sell_cached,
            cost_input_per_1k=cost_in,
            cost_output_per_1k=cost_out,
            cost_cached_input_per_1k=cost_cached,
        )

    @staticmethod
    def _ceil_credits(total_tokens: int, credits_per_1k: float) -> int:
        if total_tokens <= 0:
            return 0
        return math.ceil(total_tokens * credits_per_1k / 1000)

    def _config(self, code: str, default: float) -> float:
        if code in self._configs:
            return float(self._configs[code] or default)
        try:
            session = self._resolve_session()
        except Exception:
            logger.warning("pricing_engine config_session_unavailable code=%s", code, exc_info=True)
            return default
        row = self._query_within_savepoint(
            session,
            lambda: session.query(BillingConfig).filter(BillingConfig.code == code).one_or_none(),
            kind="billing_config",
            key=code,
        )
        if row is not None and row.value_numeric:
            return float(row.value_numeric)
        return default

    def _config_text(self, code: str, default: str) -> str:
        if code in self._configs:
            value = self._configs[code]
            return str(value) if value else default
        try:
            session = self._resolve_session()
        except Exception:
            logger.warning("pricing_engine config_session_unavailable code=%s", code, exc_info=True)
            return default
        row = self._query_within_savepoint(
            session,
            lambda: session.query(BillingConfig).filter(BillingConfig.code == code).one_or_none(),
            kind="billing_config",
            key=code,
        )
        if row is not None:
            try:
                text = row.value_text
            except Exception:
                logger.warning("pricing_engine config_row_read_failed code=%s field=value_text", code, exc_info=True)
                text = None
            if text:
                return str(text)
            try:
                numeric = row.value_numeric
            except Exception:
                logger.warning("pricing_engine config_row_read_failed code=%s field=value_numeric", code, exc_info=True)
                numeric = None
            if numeric:
                return str(numeric)
        return default

    def _load_model(self, model_id: str):
        if not model_id:
            return None
        try:
            session = self._resolve_session()
        except Exception:
            logger.warning("pricing_engine model_session_unavailable model_id=%s", model_id, exc_info=True)
            return None
        # ModelPoolConfig.id 为 UUID 主键；非 UUID 的 model_id（如模型名 deepseek-v4-flash）
        # 直接按 model_name 匹配，避免 Postgres 对 UUID 列做类型转换报错中止当前事务。
        # 注意：按 id 匹配时必须绑定 UUID 对象（SQLite 的 UUID 绑定器要求 .hex 方法），
        # 不能预转成字符串，否则在测试/小存储后端会绑定失败。
        try:
            pool_id = uuid.UUID(str(model_id))
        except (TypeError, ValueError, AttributeError):
            return self._query_model(session, ModelPoolConfig.model_name == str(model_id), model_id=model_id)
        return self._query_model(session, ModelPoolConfig.id == pool_id, model_id=model_id)

    @staticmethod
    def _query_within_savepoint(session, query_fn, *, kind: str, key: str):
        """在 SAVEPOINT 内执行一次计价查询。

        任何语句错误只回滚 savepoint，绝不毒化外层事务——否则后续扣费/对账
        会因 InFailedSqlTransaction 全部静默失败。每次失败都记 WARN（含 kind/
        key/异常摘要），让兜底可观测。savepoint 建立本身失败（如外层事务已
        failed 时 begin_nested 抛 PendingRollbackError）同样兜底返回 None，
        不让 plan_usage 直接抛异常崩掉。测试用假 session 无 begin_nested 时
        退回直接查询（异常同样被记录并吞为 None）。
        """
        try:
            nested_cm = session.begin_nested()
        except AttributeError:
            try:
                return query_fn()
            except Exception as exc:
                logger.warning(
                    "pricing_engine query_failed kind=%s key=%s error_type=%s",
                    kind, key, type(exc).__name__,
                    exc_info=True,
                )
                return None
        except Exception as exc:
            logger.warning(
                "pricing_engine savepoint_begin_failed kind=%s key=%s error_type=%s",
                kind, key, type(exc).__name__,
                exc_info=True,
            )
            try:
                return query_fn()
            except Exception as inner_exc:
                logger.warning(
                    "pricing_engine query_failed kind=%s key=%s error_type=%s",
                    kind, key, type(inner_exc).__name__,
                    exc_info=True,
                )
                return None
        try:
            with nested_cm:
                return query_fn()
        except Exception as exc:
            logger.warning(
                "pricing_engine query_failed kind=%s key=%s error_type=%s",
                kind, key, type(exc).__name__,
                exc_info=True,
            )
            return None

    @staticmethod
    def _query_model(session, condition, *, model_id: str | None = None):
        """在 SAVEPOINT 内执行模型查询；失败记 WARN 并返回 None（调用方走全局汇率兜底）。"""
        return PricingEngine._query_within_savepoint(
            session,
            lambda: session.query(ModelPoolConfig).filter(condition).one_or_none(),
            kind="model",
            key=model_id or str(condition),
        )

    @staticmethod
    def _decimal_float(value: Any) -> float:
        try:
            return float(Decimal(str(value)))
        except (TypeError, ValueError, ArithmeticError):
            return 0.0