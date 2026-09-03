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

import re
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


_HHMM_RE = re.compile(r"^(?P<h>\d{2}):(?P<m>\d{2})$")
_DAY_TOKEN_RE = re.compile(r"^\d{1,2}$|^\d{1,2}-\d{1,2}$")


def _parse_time_text(text: str) -> tuple[int, int] | None:
    """HH:MM 字符串解析为 (hour, minute)；end 允许 24:00（次日 00:00）。非法返回 None。"""
    m = _HHMM_RE.match(text)
    if not m:
        return None
    hour = int(m.group("h"))
    minute = int(m.group("m"))
    if hour == 24:
        return (24, 0) if minute == 0 else None
    if hour <= 23 and minute <= 59:
        return (hour, minute)
    return None


def _windows_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """两个窗口在同一星期几上的时间区间是否重叠（跨午夜窗口拆两段）。
    a_start > a_end 表示 a 跨午夜，等价 [a_start, 24:00) ∪ [00:00, a_end]。
    端点相接不算重叠：引擎含端点命中，若前一窗口 end 与后一窗口 start 相同，
    交叠仅为一个瞬时点，不构成重复计费区间，故按不相交处理。
    """
    a_segs = [(a_start, a_end)] if a_start <= a_end else [(a_start, 24 * 60), (0, a_end)]
    b_segs = [(b_start, b_end)] if b_start <= b_end else [(b_start, 24 * 60), (0, b_end)]
    for al, ar in a_segs:
        for bl, br in b_segs:
            if max(al, bl) < min(ar, br):
                return True
    return False


def validate_peak_windows(windows: list) -> list[str]:
    """校验峰谷时段窗口列表，返回中文错误列表；空列表=通过。

    校验项：
    - windows 必须是 list，元素必须是 dict 且含非空字符串 days/start/end；
    - start/end 必须是 HH:MM（00:00-23:59，end 允许 24:00），且不能两者同为 00:00（区间恒空）；
    - days 支持逗号分隔的单数字 0-6 或区间 a-b（0<=a<=b<=6）；
    - 同一星期数上的两个窗口若时间区间重叠则报"时段重叠"。
    第 N 行按 windows 下标从 1 起计（列表元素即为一行）。
    """
    errors: list[str] = []
    if not isinstance(windows, list):
        return ["峰谷时段窗口必须是一个数组"]

    def _parse_days(text: str) -> set[int] | None:
        text = str(text or "").strip()
        if not text:
            return None
        out: set[int] = set()
        for part in text.split(","):
            part = part.strip()
            if not _DAY_TOKEN_RE.match(part):
                return None
            if "-" in part:
                a, b = part.split("-")
                if a > b:
                    return None
                a, b = int(a), int(b)
                if a > 6 or b > 6:
                    return None
                out.update(range(a, b + 1))
            else:
                day = int(part)
                if day > 6:
                    return None
                out.add(day)
        return out

    parsed: list[tuple[int, set[int], int, int]] = []
    for idx, win in enumerate(windows, start=1):
        if not isinstance(win, dict):
            errors.append(f"峰谷时段第 {idx} 行：窗口必须是对象且包含 days/start/end 字段")
            continue
        days_text = win.get("days")
        start_text = win.get("start")
        end_text = win.get("end")
        if not days_text or not start_text or not end_text:
            errors.append(f"峰谷时段第 {idx} 行：days/start/end 字段不能为空")
            continue
        days_text = str(days_text).strip()
        start_text = str(start_text).strip()
        end_text = str(end_text).strip()
        if not (days_text and start_text and end_text):
            errors.append(f"峰谷时段第 {idx} 行：days/start/end 字段不能为空")
            continue
        parsed_start = _parse_time_text(start_text)
        parsed_end = _parse_time_text(end_text)
        if parsed_start is None:
            errors.append(f"峰谷时段第 {idx} 行：start 时间格式非法（应为 HH:MM）")
        if parsed_end is None:
            errors.append(f"峰谷时段第 {idx} 行：end 时间格式非法（应为 HH:MM，允许 24:00）")
        if parsed_start is not None and parsed_end is not None and parsed_start == (0, 0) and parsed_end == (0, 0):
            errors.append(f"峰谷时段第 {idx} 行：start 与 end 同为 00:00，时段恒空")
        days_set = _parse_days(days_text)
        if days_set is None:
            errors.append(f"峰谷时段第 {idx} 行：days 格式非法（应为 0-6 数字或 a-b 区间，逗号分隔）")
        if parsed_start is not None and parsed_end is not None and days_set is not None:
            parsed.append(
                (
                    idx,
                    days_set,
                    parsed_start[0] * 60 + parsed_start[1],
                    parsed_end[0] * 60 + parsed_end[1],
                )
            )

    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            i_idx, i_days, i_s, i_e = parsed[i]
            j_idx, j_days, j_s, j_e = parsed[j]
            if not (i_days & j_days):
                continue
            if _windows_overlap(i_s, i_e, j_s, j_e):
                errors.append(f"峰谷时段第 {i_idx} 行与第 {j_idx} 行时段重叠")
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


def build_pricing_preview(
    fields: dict[str, Any], *,
    margin_ratio,
    credits_per_yuan,
    peak_valley_enabled: bool,
    cache_pricing_enabled: bool,
    official: dict | None = None,
    official_price_cap_ratio=None,
    min_margin_ratio=None,
) -> dict[str, Any]:
    """基于表单字段的自动定价预览：返回建议售价 + 应用后的双界告警。

    - suggestions: dict（键→建议售价字符串），只含已有成本（>0）的维度；
    - applied: 恒为 False，纯计算预览、不落库；
    - warnings: 把建议值合并回 fields 后 validate_pricing_bounds 的错误列表，
      用于提示哪些维度建议价仍可能越界/亏损（仅提示不抛异常）。
    """
    suggestions = suggest_sell_prices(
        fields,
        margin_ratio=margin_ratio,
        credits_per_yuan=credits_per_yuan,
        peak_valley_enabled=peak_valley_enabled,
        cache_pricing_enabled=cache_pricing_enabled,
    )
    warnings: list[str] = []
    if suggestions:
        merged = dict(fields)
        merged.update(suggestions)
        warnings = validate_pricing_bounds(
            merged,
            credits_per_yuan=credits_per_yuan,
            min_margin_ratio=min_margin_ratio,
            peak_valley_enabled=peak_valley_enabled,
            cache_pricing_enabled=cache_pricing_enabled,
            official=official,
            official_price_cap_ratio=official_price_cap_ratio,
        )
    return {
        "suggestions": suggestions,
        "applied": False,
        "warnings": warnings,
    }