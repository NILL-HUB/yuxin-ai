"""审计 public_ai_feature_config 的档位解析换档影响（#5 档位语义修复前后对比）。

用法：
  python scripts/audit_feature_tier_shift.py
  python scripts/audit_feature_tier_shift.py --json

对比口径：
  before = 修复前逻辑（未配置/空档位回退字符串 "cheap"，档位解析落空后走默认模型路径）
  after  = 修复后逻辑（直接调用 PublicAIFeatureService.get_feature_fallback_tier）

脚本只读，不写任何库。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 容器内运行的脚本可通过 /proc/1/environ 继承环境变量（与 _inspect_prices.py 约定一致）
try:
    with open("/proc/1/environ", "rb") as f:
        for item in f.read().split(b"\0"):
            if b"=" in item:
                k, _, v = item.partition(b"=")
                os.environ.setdefault(k.decode(), v.decode())
except Exception:
    pass

from app.http import asgi_app  # noqa: F401  (导入即完成 db/扩展初始化)
from internal.extension.database_extension import db
from internal.model.model_pool_entity import ModelTierPolicy
from internal.service.public_ai_feature_service import (
    DEFAULT_FALLBACK_TIER,
    PublicAIFeatureService,
)
from internal.service.runtime_model_pool_service import RuntimeModelPoolService

LEGACY_BEFORE_DEFAULT = "cheap"


def _model_ref(model) -> str:
    if model is None:
        return "(none)"
    return f"{model.provider}/{model.model_name}"


def _tier_name(session, tier: str) -> str:
    try:
        policy = session.query(ModelTierPolicy).filter(ModelTierPolicy.tier_code == tier).one_or_none()
    except Exception:
        return ""
    return (policy.tier_name or "") if policy is not None else ""


def _before_tier(cfg) -> str:
    if cfg is None:
        return LEGACY_BEFORE_DEFAULT
    return str(cfg.fallback_tier or LEGACY_BEFORE_DEFAULT).lower()


def _pick_with_key(pool, tier: str, model_type: str):
    primary, candidates = pool.select_model_with_fallback(tier, model_type)
    chain = ([primary] + list(candidates)) if primary is not None else []
    for model in chain:
        if pool.select_key(model.id) is not None:
            return model
    return None


def _default_model(pool, model_type: str):
    model = _pick_with_key(pool, DEFAULT_FALLBACK_TIER, "chat")
    if model is not None:
        return model
    primary, candidates = pool.select_model_with_fallback(None, "chat")
    for candidate in ([primary] + list(candidates)) if primary is not None else []:
        if pool.select_key(candidate.id) is not None:
            return candidate
    return None


def _resolve(pool, tier: str, model_type: str):
    """按档位解析模型；档位无可用模型时走默认模型路径（load_default_language_model）。"""
    return _pick_with_key(pool, tier, model_type) or _default_model(pool, "chat")


def _cost_ref(pool, model):
    if model is None:
        return None
    value = pool._cost_reference(model)
    if value == float("inf"):
        return None
    return value


def run(as_json: bool) -> int:
    service = PublicAIFeatureService(db=db)
    pool = RuntimeModelPoolService(db=db)
    session = db.session

    default_model = _default_model(pool, "chat")
    features = service.list_all_features()

    rows = []
    for cfg in features:
        key = cfg.feature_key
        model_type = (cfg.model_type or "chat").lower()
        enabled = bool(cfg.enabled)
        before_tier = _before_tier(cfg)
        after_tier = service.get_feature_fallback_tier(key)

        if not enabled:
            # 功能被禁用时运行时直接抛异常，不产生模型调用，不纳入换档影响
            rows.append({
                "feature_key": key,
                "category": cfg.feature_category,
                "billable": bool(cfg.billable),
                "enabled": False,
                "bound_bypass": False,
                "before_tier": before_tier,
                "after_tier": after_tier,
                "before_model": "(disabled)",
                "after_model": "(disabled)",
                "before_cost_ref": None,
                "after_cost_ref": None,
                "cost_delta": None,
                "cost_delta_text": "n/a",
                "changed": False,
            })
            continue

        bound = service.get_feature_model_config(key)
        if bound is not None:
            # 已绑定可用模型：运行时优先用绑定模型，档位仅在绑定失效时才起作用
            before_model = after_model = bound
            bound_bypass = True
        else:
            before_model = _resolve(pool, before_tier, model_type)
            after_model = _resolve(pool, after_tier, model_type)
            bound_bypass = False

        # 兜底风险：假设绑定模型失效（status→inactive / 被删除）后的解析结果。
        # 这才是本修复真正会改变运行时的场景。
        fb_before_model = _resolve(pool, before_tier, model_type)
        fb_after_model = _resolve(pool, after_tier, model_type)
        fb_before_cost = _cost_ref(pool, fb_before_model)
        fb_after_cost = _cost_ref(pool, fb_after_model)
        if fb_before_cost is not None and fb_after_cost is not None and fb_before_cost != fb_after_cost:
            fb_delta = fb_after_cost - fb_before_cost
            fb_delta_text = f"{fb_delta:+.4f}"
        else:
            fb_delta = None
            fb_delta_text = "n/a"
        fb_changed = (before_tier != after_tier) or (_model_ref(fb_before_model) != _model_ref(fb_after_model))
        # 真正的成本影响信号：解析到的模型是否变了（档位标签变化但模型相同则无实际影响）
        fb_model_changed = _model_ref(fb_before_model) != _model_ref(fb_after_model)

        before_cost = _cost_ref(pool, before_model)
        after_cost = _cost_ref(pool, after_model)
        if before_cost is not None and after_cost is not None and before_cost != after_cost:
            delta = after_cost - before_cost
            delta_text = f"{delta:+.4f}"
        else:
            delta = None
            delta_text = "n/a"

        changed = (before_tier != after_tier) or (_model_ref(before_model) != _model_ref(after_model))
        rows.append({
            "feature_key": key,
            "category": cfg.feature_category,
            "billable": bool(cfg.billable),
            "enabled": enabled,
            "bound_bypass": bound_bypass,
            "before_tier": before_tier,
            "after_tier": after_tier,
            "before_model": _model_ref(before_model),
            "after_model": _model_ref(after_model),
            "before_cost_ref": before_cost,
            "after_cost_ref": after_cost,
            "cost_delta": delta,
            "cost_delta_text": delta_text,
            "changed": changed and not bound_bypass,
            "fb_before_model": _model_ref(fb_before_model),
            "fb_after_model": _model_ref(fb_after_model),
            "fb_before_cost_ref": fb_before_cost,
            "fb_after_cost_ref": fb_after_cost,
            "fb_cost_delta": fb_delta,
            "fb_cost_delta_text": fb_delta_text,
            "fb_changed": fb_changed,
            "fb_model_changed": fb_model_changed,
        })

    affected = [r for r in rows if r["changed"]]
    fallback_risk = [r for r in rows if r["enabled"] and r["fb_model_changed"]]
    fb_cheaper = [r for r in fallback_risk if r["fb_cost_delta"] is not None and r["fb_cost_delta"] < 0]
    fb_pricier = [r for r in fallback_risk if r["fb_cost_delta"] is not None and r["fb_cost_delta"] > 0]
    fb_unknown = [r for r in fallback_risk if r["fb_cost_delta"] is None]
    fb_label_only = [r for r in rows if r["enabled"] and r["fb_changed"] and not r["fb_model_changed"]]
    bound_rows = [r for r in rows if r["bound_bypass"]]
    disabled_rows = [r for r in rows if not r["enabled"]]

    gapped = []
    for model in pool.get_active_models(None, None):
        issues = []
        if bool(model.cache_pricing_enabled) and float(model.input_cached_price_per_1k_tokens or 0) <= 0:
            issues.append("cache_pricing_enabled=true 但缓存售价=0")
        if bool(model.peak_valley_enabled):
            peak_zero = float(model.peak_input_price_per_1k_tokens or 0) <= 0 and float(model.peak_output_price_per_1k_tokens or 0) <= 0
            valley_zero = float(model.valley_input_price_per_1k_tokens or 0) <= 0 and float(model.valley_output_price_per_1k_tokens or 0) <= 0
            if peak_zero:
                issues.append("peak_valley_enabled=true 但峰档售价=0")
            if valley_zero:
                issues.append("peak_valley_enabled=true 但谷档售价=0")
        if issues:
            gapped.append({"model": _model_ref(model), "issues": issues})

    result = {
        "total_features": len(rows),
        "affected_count": len(affected),
        "bound_bypass_count": len(bound_rows),
        "disabled_count": len(disabled_rows),
        "fallback_risk_count": len(fallback_risk),
        "fallback_cheaper_count": len(fb_cheaper),
        "fallback_pricier_count": len(fb_pricier),
        "fallback_unknown_cost_count": len(fb_unknown),
        "fallback_label_only_count": len(fb_label_only),
        "default_model": _model_ref(default_model),
        "affected": affected,
        "fallback_risk": fallback_risk,
        "bound_bypass": bound_rows,
        "model_pricing_gaps": gapped,
    }

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print("=" * 78)
    print("公共 AI 功能档位换档审计（#5 档位语义修复前后）")
    print("=" * 78)
    print(f"功能总数                : {result['total_features']}")
    print(f"当前运行时受影响        : {result['affected_count']}（已绑定模型的不受影响）")
    print(f"已绑定模型(绕过档位)    : {result['bound_bypass_count']}")
    print(f"已禁用                  : {result['disabled_count']}")
    print(f"默认兜底模型            : {result['default_model']}")
    print()
    print(f"绑定失效后受影响(兜底)  : {result['fallback_risk_count']}"
          f"（变便宜 {result['fallback_cheaper_count']} / 变贵 {result['fallback_pricier_count']}"
          f" / 成本未知 {result['fallback_unknown_cost_count']}）")
    print(f"其中仅档位标签变化      : {result['fallback_label_only_count']}"
          f"（解析模型不变，无实际成本影响）")
    print()

    print("-" * 78)
    print("[1] 当前运行时换档明细（未绑定模型、档位直接决定选型的功能）")
    print("-" * 78)
    if not affected:
        print("无：所有功能都已绑定模型，档位当前不参与选型。")
    for r in affected:
        name_after = _tier_name(session, r["after_tier"])
        tag = "变便宜" if (r["cost_delta"] is not None and r["cost_delta"] < 0) else (
            "变贵" if (r["cost_delta"] is not None and r["cost_delta"] > 0) else "成本未知")
        print(f"- {r['feature_key']}  [{r['category']}] billable={r['billable']}  => {tag}")
        print(f"    档位: {r['before_tier']} -> {r['after_tier']}"
              + (f"（{name_after}）" if name_after else ""))
        print(f"    模型: {r['before_model']}  ->  {r['after_model']}")
        print(f"    成本参考(3*in+out): {r['before_cost_ref']} -> {r['after_cost_ref']}  差 {r['cost_delta_text']}")
    print()

    print("-" * 78)
    print("[2] 兜底风险：绑定模型失效后，档位解析的换档结果")
    print("    （绑定失效 = 绑定模型 status 变 inactive 或被删除，此时才回退到档位池）")
    print("-" * 78)
    if not fallback_risk:
        print("无：绑定失效后解析模型与修复前一致。")
    for r in fallback_risk:
        name_after = _tier_name(session, r["after_tier"])
        tag = "变便宜" if (r["fb_cost_delta"] is not None and r["fb_cost_delta"] < 0) else (
            "变贵" if (r["fb_cost_delta"] is not None and r["fb_cost_delta"] > 0) else "成本未知")
        print(f"- {r['feature_key']}  [{r['category']}] billable={r['billable']}  => {tag}")
        print(f"    档位: {r['before_tier']} -> {r['after_tier']}"
              + (f"（{name_after}）" if name_after else ""))
        print(f"    兜底模型: {r['fb_before_model']}  ->  {r['fb_after_model']}")
        print(f"    成本参考(3*in+out): {r['fb_before_cost_ref']} -> {r['fb_after_cost_ref']}  差 {r['fb_cost_delta_text']}")
    print()

    print("-" * 78)
    print("[3] 模型定价配置缺口（#2 缓存价 / #3 峰谷价 为 0 但开关已开）")
    print("-" * 78)
    if not gapped:
        print("无。")
    for g in gapped:
        print(f"- {g['model']}: {'；'.join(g['issues'])}")
    print()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args()
    raise SystemExit(run(as_json=args.json))
