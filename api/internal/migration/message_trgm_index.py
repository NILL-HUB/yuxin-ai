#!/usr/bin/env python
"""会话消息 pg_trgm 全文索引就绪脚本。

为 message.query / message.answer 建立 pg_trgm GIN 索引，供会话原文搜索
（ConversationService.search_conversations 的 ILIKE 中缀检索）加速。
若索引缺失则自动创建。可独立运行，不依赖 Flask app 上下文。

用法: python api/internal/migration/message_trgm_index.py
说明: 本脚本不挂接 alembic 迁移链（仓库迁移链存在多 head，不便新增迁移），
     采用与 pgvector_hnsw_index.py 相同的独立幂等脚本模式。
"""

import os

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql://yuxin_ai:yuxin_ai@localhost:5432/yuxin_ai",
)


def main() -> int:
    engine = create_engine(DATABASE_URL)
    statements = [
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",
        "CREATE INDEX IF NOT EXISTS ix_message_query_trgm "
        "ON message USING gin (query gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS ix_message_answer_trgm "
        "ON message USING gin (substring(answer, 1, 20000) gin_trgm_ops)",
    ]
    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))
            print(f"[OK] {sql[:60]}...")
    print("[OK] message pg_trgm indexes ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
