"""一次性迁移：把 model_pool_config 售价列从旧 credits/1k 语义归一化为 人民币元/1k。

背景：
- 此前 backfill 按 credits 语义写入售价 = 成本 × (1+0.3) × credits_per_yuan(100)。
- 售价列口径改为 人民币元/1k 后，存量值需 ÷100 回到元，引擎扣费时再按 credits_per_yuan 折算。

规则（与 backfill_provider_pricing.py 写入逻辑一致）：
- DeepSeek-V4-Flash（commandcode/SiliconFlow/opencode）行：全部售价列 ÷100（只动 >0 的）；
- 其他行：售价列若近似等于对应成本×1.3×100（容差 1e-6）则 ÷100；
  否则不做推断，仅打印提示人工核对。

用法：python scripts/_migrate_sell_price_to_rmb.py [--apply] [--dry-run]
"""
import argparse
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

import asyncio

from sqlalchemy import text

SELL_COLS = [
    "input_price_per_1k_tokens",
    "output_price_per_1k_tokens",
    "input_cached_price_per_1k_tokens",
    "peak_input_price_per_1k_tokens",
    "peak_output_price_per_1k_tokens",
    "peak_input_cached_price_per_1k_tokens",
    "valley_input_price_per_1k_tokens",
    "valley_output_price_per_1k_tokens",
    "valley_input_cached_price_per_1k_tokens",
]
# 与售价同维度对应的成本列（键对应）
_COST_OF = {
    "input_price_per_1k_tokens": "input_cost_per_1k_tokens",
    "output_price_per_1k_tokens": "output_cost_per_1k_tokens",
    "input_cached_price_per_1k_tokens": "input_cached_cost_per_1k_tokens",
    "peak_input_price_per_1k_tokens": "peak_input_cost_per_1k_tokens",
    "peak_output_price_per_1k_tokens": "peak_output_cost_per_1k_tokens",
    "peak_input_cached_price_per_1k_tokens": "peak_input_cached_cost_per_1k_tokens",
    "valley_input_price_per_1k_tokens": "valley_input_cost_per_1k_tokens",
    "valley_output_price_per_1k_tokens": "valley_output_cost_per_1k_tokens",
    "valley_input_cached_price_per_1k_tokens": "valley_input_cached_cost_per_1k_tokens",
}
V4_FLASH_KEYS = {
    ("commandcode", "deepseek/deepseek-v4-flash"),
    ("SiliconFlow", "deepseek-ai/DeepSeek-V4-Flash"),
    ("opencode", "deepseek-v4-flash"),
}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


async def main(apply: bool) -> None:
    from app.http import asgi_app  # noqa: F401
    from internal.extension.database_extension import db

    async with db.engine.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, provider, model_name, "
                    + ", ".join(SELL_COLS + list({_COST_OF[c] for c in SELL_COLS}))
                    + " FROM model_pool_config ORDER BY provider, model_name"
                )
            )
        ).fetchall()
        updates = 0
        for r in rows:
            row_id = r[0]
            provider = r[1]
            model_name = r[2]
            base = {c: _f(r._mapping[c]) for c in SELL_COLS}
            cost = {c: _f(r._mapping[_COST_OF[c]]) for c in SELL_COLS}
            key = (provider, model_name)
            changed: list[str] = []
            for col in SELL_COLS:
                sell = base[col]
                if sell <= 0:
                    continue
                c = cost[col]
                is_flash = key in V4_FLASH_KEYS
                if is_flash:
                    new_val = sell / 100
                elif c > 0:
                    expected = c * 1.3 * 100
                    if abs(sell - expected) > 1e-6:
                        print(f"SKIP {provider}/{model_name} {col}: sell={sell} cost={c} 非 cost×1.3×100，人工核对")
                        continue
                    new_val = sell / 100
                else:
                    print(f"SKIP {provider}/{model_name} {col}: sell={sell} 但 cost=0，非回填产物，人工核对")
                    continue
                changed.append(f"{col}: {sell} -> {new_val:.6f}")
                if apply:
                    await conn.execute(
                        text(f"UPDATE model_pool_config SET {col} = :v WHERE id = :id"),
                        {"v": round(new_val, 6), "id": row_id},
                    )
            if changed:
                updates += 1
                tag = "APPLY" if apply else "DRY-RUN"
                print(f"[{tag}] {provider}/{model_name}")
                for line in changed:
                    print(f"    {line}")
        print(f"\nTOTAL rows changed: {updates} (mode={'apply' if apply else 'dry-run'})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写入数据库（默认仅 dry-run 打印）")
    args = ap.parse_args()
    asyncio.run(main(apply=args.apply))
