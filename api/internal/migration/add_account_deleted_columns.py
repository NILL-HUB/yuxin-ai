#!/usr/bin/env python
"""Account 表增加「账号删除」字段（幂等）。

status='deleted' 语义：管理员删除（注销）用户，不可逆；禁止登录。
与 disabled（停用，可逆，保留数据）区分。

字段与 disabled_* 对称：
    deleted_at    删除时间
    deleted_by    操作者（admin_user.id）
    deleted_reason 删除原因

幂等：IF NOT EXISTS，可重复执行。

用法：
    python internal/migration/add_account_deleted_columns.py
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _env_database_uri() -> str:
    return os.getenv(
        "SQLALCHEMY_DATABASE_URI",
        "postgresql://yuxin_ai:yuxin_ai@localhost:5432/yuxin_ai",
    )


def main() -> int:
    engine = create_engine(_env_database_uri())
    statements = [
        "ALTER TABLE account ADD COLUMN IF NOT EXISTS "
        "deleted_at timestamp without time zone",
        "ALTER TABLE account ADD COLUMN IF NOT EXISTS "
        "deleted_by uuid",
        "ALTER TABLE account ADD COLUMN IF NOT EXISTS "
        "deleted_reason character varying(1024) NOT NULL DEFAULT ''",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
            logger.info("执行成功: %s", statement)
    logger.info("account.deleted_* 字段已就绪（幂等）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
