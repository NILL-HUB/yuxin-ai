"""回填供应商真实成本与峰谷/缓存档位（deepseek-v4-flash 两渠道；2026-08-31 快照）。

用法：
  python scripts/backfill_provider_pricing.py --dry-run
  python scripts/backfill_provider_pricing.py --apply
成本单位：元 / 1k token（opencode 按 usd_to_cny 折算，默认 7.2）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    with open("/proc/1/environ", "rb") as f:
        for item in f.read().split(b"\0"):
            if b"=" in item:
                k, _, v = item.partition(b"=")
                os.environ.setdefault(k.decode(), v.decode())
except Exception:
    pass

from app.http import asgi_app  # noqa: F401
from internal.extension.database_extension import db
from internal.model.model_pool_entity import ModelPoolConfig
from sqlalchemy import text


def _usd_to_cny() -> float:
    try:
        with db.auto_commit() as s:
            from internal.model.billing import BillingConfig
            row = s.query(BillingConfig).filter(BillingConfig.code == "usd_to_cny").one_or_none()
            return float(row.value_numeric) if row and row.value_numeric else 7.2
    except Exception:
        return 7.2


# (provider, model_name) -> dict: cost 元/1k（peak/valley 的 input/output/cached）
PLAN = {}

_flash_sf = {
    "valley": {"input": "0.0015", "output": "0.0045", "cached": "0.00015"},
    "peak": {"input": "0.0030", "output": "0.0090", "cached": "0.00030"},
}
# opencode: USD→CNY 汇率折算
_fx = _usd_to_cny()
_flash_oc = {
    "valley": {"input": f"{0.22 * _fx / 1000:.6f}", "output": f"{0.66 * _fx / 1000:.6f}", "cached": f"{0.007 * _fx / 1000:.6f}"},
    "peak": {"input": f"{0.44 * _fx / 1000:.6f}", "output": f"{1.32 * _fx / 1000:.6f}", "cached": f"{0.014 * _fx / 1000:.6f}"},
}
PLAN[("SiliconFlow", "deepseek-ai/DeepSeek-V4-Flash")] = {
    "costs": _flash_sf,
    "windows": [{"days": "0-6", "start": "00:00", "end": "02:00"}, {"days": "0-6", "start": "08:00", "end": "24:00"}],
    "official": {"input": "3.0", "output": "9.0", "cached": "0.30"},  # 元/M（峰档官方参考）
}
PLAN[("opencode", "deepseek-v4-flash")] = {
    "costs": _flash_oc,
    "windows": [{"days": "0-4", "start": "09:00", "end": "12:00"}, {"days": "0-4", "start": "14:00", "end": "18:00"}],
    "official": {"input": f"{0.44 * _fx:.4f}", "output": f"{1.32 * _fx:.4f}", "cached": f"{0.014 * _fx:.4f}"},  # 元/M（峰档）
}


def run(apply: bool) -> None:
    with db.auto_commit() as s:
        for (provider, model_name), cfg in PLAN.items():
            row = (
                s.query(ModelPoolConfig)
                .filter(ModelPoolConfig.provider == provider, ModelPoolConfig.model_name == model_name)
                .one_or_none()
            )
            if row is None:
                print(f"SKIP (no row): {provider}/{model_name}")
                continue
            costs = cfg["costs"]
            print(f"== {provider}/{model_name} ==")
            if not apply:
                print(f"  DRY-RUN plans: peak_valley=True cache=True windows={cfg['windows']}")
                print(f"  costs(元/1k)={costs}")
                print(f"  official(元/M)={cfg['official']}")
                continue
            row.peak_valley_enabled = True
            row.cache_pricing_enabled = True
            row.peak_windows = cfg["windows"]
            for tier in ("peak", "valley"):
                c = costs[tier]
                setattr(row, f"{tier}_input_cost_per_1k_tokens", c["input"])
                setattr(row, f"{tier}_output_cost_per_1k_tokens", c["output"])
                setattr(row, f"{tier}_input_cached_cost_per_1k_tokens", c["cached"])
                # 建议售价（元/1k）= 成本(元/1k) × (1+毛利率)（与成本同单位，直出元/1k）
                sell = float(c["input"]) * (1 + 0.3)
                setattr(row, f"{tier}_input_price_per_1k_tokens", f"{sell:.6f}")
                sell = float(c["output"]) * (1 + 0.3)
                setattr(row, f"{tier}_output_price_per_1k_tokens", f"{sell:.6f}")
                sell = float(c["cached"]) * (1 + 0.3)
                setattr(row, f"{tier}_input_cached_price_per_1k_tokens", f"{sell:.6f}")
            s.flush()
            print(f"  APPLIED cost+windows+sell for {provider}/{model_name}")
        _report_uncovered(s, apply=apply)


def _report_uncovered(s, apply: bool) -> None:
    """PLAN 之外但已存在于模型池的模型：不强行回填，仅提示人工处理。"""
    rows = s.query(ModelPoolConfig).filter(
        (ModelPoolConfig.provider.in_(["SiliconFlow", "opencode"]))
        | (ModelPoolConfig.model_name.ilike("%deepseek%"))
    ).all()
    for row in rows:
        key = (row.provider, row.model_name)
        if key in PLAN:
            continue
        if key == ("SiliconFlow", "tencent/Hunyuan-MT-7B"):
            print(
                "NOTE: SiliconFlow/tencent/Hunyuan-MT-7B 官方价格已确认=免费(0 元/M，未提供缓存价)，"
                "成本保持默认 0，无需回填"
            )
            continue
        print(f"NOTE: {row.provider}/{row.model_name} 成本未回填，可后台手工配置")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="仅打印计划，不写库（默认行为）")
    ap.add_argument("--apply", action="store_true", help="写入数据库")
    args = ap.parse_args()
    run(apply=args.apply)