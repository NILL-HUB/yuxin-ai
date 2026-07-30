#!/usr/bin/env python
"""pgvector 向量列就绪验证脚本。

验证 user_memory.embedding 列与 HNSW 索引是否就绪。
若索引缺失则自动创建。可独立运行，不依赖 Flask app 上下文。

用法: python api/internal/migration/pgvector_hnsw_index.py
"""

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TABLE_NAME = os.getenv("PGVECTOR_TABLE", "user_memory")
EMBEDDING_COLUMN = os.getenv("PGVECTOR_EMBEDDING_COLUMN", "embedding")
EMBEDDING_DIM = int(os.getenv("PGVECTOR_EMBEDDING_DIM", "1536"))
INDEX_NAME = os.getenv("PGVECTOR_INDEX_NAME", "user_memory_embedding_hnsw_idx")
DATABASE_URL = os.getenv(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql+asyncpg://openagent:openagent@localhost:5432/openagent",
)


async def verify_extension(engine) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extname, extversion FROM pg_extension WHERE extname='vector'")
        )
        row = result.fetchone()
        if row:
            print(f"[OK] pgvector extension installed (version={row[1]})")
            return True
        print("[FAIL] pgvector extension missing")
        return False


async def verify_embedding_column(engine) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name, udt_name FROM information_schema.columns "
                "WHERE table_name=:t AND column_name=:c"
            ),
            {"t": TABLE_NAME, "c": EMBEDDING_COLUMN},
        )
        row = result.fetchone()
        if row and row[1] == "vector":
            print(f"[OK] column {TABLE_NAME}.{EMBEDDING_COLUMN} is vector type")
            return True
        print(f"[FAIL] column {TABLE_NAME}.{EMBEDDING_COLUMN} missing or not vector type")
        return False


async def verify_hnsw_index(engine) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename=:t AND indexname=:i"
            ),
            {"t": TABLE_NAME, "i": INDEX_NAME},
        )
        row = result.fetchone()
        if row and "USING hnsw" in (row[1] or ""):
            print(f"[OK] HNSW index exists: {INDEX_NAME}")
            return True
        print(f"[WARN] HNSW index not found: {INDEX_NAME}")
        return False


async def create_hnsw_index(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
                f"ON {TABLE_NAME} USING hnsw ({EMBEDDING_COLUMN} vector_cosine_ops) "
                f"WITH (m = 16, ef_construction = 64)"
            )
        )
        print(f"[OK] HNSW index created: {INDEX_NAME}")


async def main() -> int:
    engine = create_async_engine(DATABASE_URL)
    try:
        if not await verify_extension(engine):
            print("\n[ERROR] 请在 init.sql 中添加: CREATE EXTENSION IF NOT EXISTS vector;")
            return 1

        if not await verify_embedding_column(engine):
            print(f"\n[ERROR] 请通过 Alembic 迁移添加: "
                  f"ALTER TABLE {TABLE_NAME} ADD COLUMN {EMBEDDING_COLUMN} vector({EMBEDDING_DIM});")
            return 1

        if not await verify_hnsw_index(engine):
            await create_hnsw_index(engine)

        print("\n[DONE] pgvector 向量列与 HNSW 索引就绪")
        return 0
    except Exception as e:
        print(f"\n[ERROR] {e}")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
