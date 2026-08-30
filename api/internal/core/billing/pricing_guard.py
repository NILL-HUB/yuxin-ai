"""双界校验 + 自动定价建议（谷峰/缓存定价的盈亏平衡保障）。

约定：
- 售价列口径 = 算力/1k token；成本列口径 = 人民币元/1k token。
- 成本折算算力/1k = cost_rmb_per_1k × credits_per_yuan；
- 售价折算人民币/1k = sell_credits_per_1k / credits_per_yuan。

校验维度：
- 下界（不亏损）：售价算力/1k ≥ 成本折算算力/1k × (1 + min_margin_ratio)；
- 上界（不高于官方）：售价人民币/1k ≤ official × official_price_cap_ratio。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def _d(value, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value if value is not None else default))
    except Exception:
        return default


_TIERS = (("peak", "峰档"), ("valley", "谷档"))
_DIMS = (("input", "输入(未命中)"), ("output", "输出"), ("input_cached", "输入(缓存命中)"))


def price_key_for(tier: str | None, dim: str) -> str:
    """返回档位×维度对应的售价列键。

    tier 为 None 时无前缀；dim 为 input_cached 时键为 input_cached_price_per_1k_tokens。
    """
    prefix = "" if tier is None else f"{tier}_"
    return f"{prefix}{'input_cached' if dim == 'input_cached' else dim}_price_per_1k_tokens"


def cost_key_for(tier: str | None, dim: str) -> str:
    """返回档位×维度对应的成本列键。"""
    prefix = "" if tier is None else f"{tier}_"
    return f"{prefix}{'input_cached' if dim == 'input_cached' else dim}_cost_per_1k_tokens"


def _tier_pairs(peak_valley_enabled: bool):
    if peak_valley_enabled:
        return _TIERS
    return [(None, "常规")]


def _dimensions(cache_pricing_enabled: bool):
    if cache_pricing_enabled:
        return _DIMS
    return _DIMS[:2]


def _official_value(official, tier, dim):
    """官方价取值：优先 dim 键，其次支持 tier_dim（如 valley_output）键。"""
    if not official:
        return None
    if dim in official:
        return official[dim]
    if tier:
        return official.get(f"{tier}_{dim}")
    return official.get(f"regular_{dim}")


def validate_pricing_bounds(
    fields: dict[str, Any], *,
    credits_per_yuan,
    min_margin_ratio,
    peak_valley_enabled: bool,
    cache_pricing_enabled: bool,
    official: dict | None = None,
    official_price_cap_ratio=None,
) -> list[str]:
    """逐档位×维度校验售价双界，返回中文错误列表；空列表=通过。

    fields 键示例：peak_input_price_per_1k_tokens / peak_output_cost_per_1k_tokens /
    valley_input_cached_price_per_1k_tokens / input_price_per_1k_tokens ...
    成本未填（<=0）的维度跳过校验。
    """
    errors: list[str] = []
    cpy = _d(credits_per_yuan, Decimal("100")) or Decimal("100")
    margin = _d(min_margin_ratio, Decimal("0.1")) or Decimal("0.1")
    cap = _d(official_price_cap_ratio, Decimal("1.1")) or Decimal("1.1")

    for tier, tier_label in _tier_pairs(peak_valley_enabled):
        for dim, dim_label in _dimensions(cache_pricing_enabled):
            sell = _d(fields.get(price_key_for(tier, dim)))
            cost_rmb = _d(fields.get(cost_key_for(tier, dim)))
            if cost_rmb <= 0:
                continue
            cost_credits_per_1k = cost_rmb * cpy
            if sell < cost_credits_per_1k * (Decimal("1") + margin):
                errors.append(
                    f"{tier_label} {dim_label}：售价 {sell} 低于成本折算 "
                    f"{cost_credits_per_1k}×{Decimal('1') + margin}，将亏损"
                )
            official_value = _official_value(official, tier, dim)
            if official_value is not None:
                rmb_per_1k_sel = sell / cpy
                if rmb_per_1k_sel > _d(official_value) * cap:
                    errors.append(
                        f"{tier_label} {dim_label}：售价折算 {rmb_per_1k_sel} 元/1k "
                        f"高于官方价×{cap}，用户会觉得贵"
                    )
    return errors


def suggest_sell_prices(
    fields: dict[str, Any], *,
    margin_ratio,
    credits_per_yuan,
    peak_valley_enabled: bool,
    cache_pricing_enabled: bool,
) -> dict[str, str]:
    """为每个 档位×维度 生成建议售价（算力/1k），6 位小数。

    售价算力/1k = cost_rmb_per_1k × (1 + margin_ratio) × credits_per_yuan。
    未填成本（<=0）的维度不产出建议。
    """
    cpy = _d(credits_per_yuan, Decimal("100")) or Decimal("100")
    margin = _d(margin_ratio, Decimal("0.3")) or Decimal("0.3")
    out: dict[str, str] = {}
    for tier, _label in _tier_pairs(peak_valley_enabled):
        for dim, _dl in _dimensions(cache_pricing_enabled):
            cost_rmb = _d(fields.get(cost_key_for(tier, dim)))
            if cost_rmb <= 0:
                continue
            sell = cost_rmb * (Decimal("1") + margin) * cpy
            out[price_key_for(tier, dim)] = f"{sell:.6f}"
    return out