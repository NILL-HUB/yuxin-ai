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
from sqlalchemy import text

import asyncio

cols = [
    "model_name", "provider", "tier", "status",
    "input_price_per_1k_tokens", "output_price_per_1k_tokens",
    "input_cached_price_per_1k_tokens",
    "input_cost_per_1k_tokens", "output_cost_per_1k_tokens",
    "input_cached_cost_per_1k_tokens",
    "peak_input_price_per_1k_tokens", "peak_output_price_per_1k_tokens", "peak_input_cached_price_per_1k_tokens",
    "valley_input_price_per_1k_tokens", "valley_output_price_per_1k_tokens", "valley_input_cached_price_per_1k_tokens",
    "peak_input_cost_per_1k_tokens", "peak_output_cost_per_1k_tokens", "peak_input_cached_cost_per_1k_tokens",
    "valley_input_cost_per_1k_tokens", "valley_output_cost_per_1k_tokens", "valley_input_cached_cost_per_1k_tokens",
    "price_per_1k_tokens", "peak_valley_enabled", "cache_pricing_enabled",
]

BILLING_COLS = ["code", "value_numeric", "value_string"]


async def main():
    async with db.engine.connect() as c:
        rows = (await c.execute(text("SELECT " + ", ".join(cols) + " FROM model_pool_config ORDER BY id"))).fetchall()
        bills = (
            await c.execute(
                text(
                    "SELECT code, value_numeric, value_text FROM billing_config "
                    "WHERE code IN ('credits_per_yuan','credits_per_1k_tokens','usd_to_cny','sell_margin_ratio')"
                )
            )
        ).fetchall()
    print("== billing_config ==")
    for b in bills:
        print("\t".join(str(x) for x in b))
    print()
    print("== model_pool_config ==")
    print("\t".join(cols))
    for r in rows:
        print("\t".join(str(x) for x in r))


asyncio.run(main())
