"""迁移链「空库从零跑通」冒烟守卫。

背景（为什么必须补这条测试）：
`test_migration_graph_integrity.py` 只校验迁移图的**静态结构**——无悬空
`down_revision`、只有一个 head。但这两条都成立时，**全新数据库上
`alembic upgrade head` 依然可能崩溃**：

    实测（2026-09）：空库升级到第 38 条迁移时失败
    `relation "user_memory" does not exist`
      [SQL: ALTER TABLE user_memory ADD COLUMN embedding_node_id VARCHAR(255)]

根因是**隐式跨支线依赖**：建表的 `d1e2f3a4b5c7` 挂在支线 `c0d1e2f3a4b5`
之后，改表的 `e1f2a3b4c5d7` 挂在另一条支线 `f7a8b9c0d1e2` 之后，两条支线
直到 `f2a3b4c5d6e8` 才合并。对 alembic 而言两者无先后约束，按拓扑序可能
先跑改表迁移；`e1f2a3b4c5d7` 实际依赖 `d1e2f3a4b5c7`，但这个依赖从未在链上
表达。本地库因为是**历史增量**应用（建表迁移当年早已跑过）而侥幸不报错，
只有**空库**才会暴露。

为什么危害大：`docker/entrypoint.sh` 在 `MIGRATION_ENABLED=true` 时会自动执行
`alembic upgrade head`。因此**生产首次部署、新建 staging、CI 全新 clone 建库**
都会踩中——这些场景的数据库都是空的。

本测试直接以「空库 + 全量迁移」复现真实部署路径：
  1. 建一个临时空库并装载与 `docker/postgres/init.sql` 一致的扩展；
  2. 在其上跑 `alembic upgrade head`；
  3. 断言退出码为 0。

环境要求：可连的 PostgreSQL（复用 `api/.env` 的 `POSTGRES_*`，或显式设置
`MIGRATION_SMOKE_DATABASE_URL`）。**连不上时 skip**，不阻塞无 PG 的本地环境；
CI 应确保该测试真实执行（否则本守卫形同虚设）。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = API_ROOT / "internal" / "migration" / "versions"
ALEMBIC_INI = API_ROOT / "internal" / "migration" / "alembic.ini"

_SMOKE_DB = "llmops_migration_smoke"
_REV = re.compile(r"^revision(?:\s*:\s*[^=]+)?\s*=\s*[\"']([^\"']+)[\"']", re.M)
_DOWN = re.compile(r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(.+)$", re.M)

_CREATE_TABLE = re.compile(r"create_table\(\s*[\"']([^\"']+)[\"']")
_REF_TABLE = re.compile(
    r"(?:add_column|alter_column|drop_column|drop_index|drop_constraint|"
    r"create_foreign_key|create_index|create_unique_constraint)\(\s*"
    r"(?:[\"'][^\"']+[\"']\s*,\s*)?[\"']([^\"']+)[\"']"
)
_SQL_TABLE = re.compile(
    r"(?:ALTER\s+TABLE|UPDATE|DELETE\s+FROM|INSERT\s+INTO)\s+[\"']?([a-z_][a-z0-9_]*)",
    re.I,
)


def _admin_url() -> str | None:
    """返回可连到 postgres 库（用于建/删临时库）的连接串。"""
    explicit = os.getenv("MIGRATION_SMOKE_DATABASE_URL")
    if explicit:
        return explicit

    host = os.getenv("POSTGRES_HOST")
    if not host:
        return None
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    port = os.getenv("POSTGRES_PORT", "5432")
    auth = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/postgres"


def _smoke_url(admin_url: str) -> str:
    base, _, _tail = admin_url.rpartition("/")
    return f"{base}/{_SMOKE_DB}"


def _run_sql(url: str, *statements: str) -> subprocess.CompletedProcess:
    """用 alembic 自身依赖的 psycopg2 执行 SQL（不引入额外依赖）。"""
    script = (
        "import sys, psycopg2\n"
        "url = sys.argv[1]\n"
        "stmts = sys.argv[2:]\n"
        "conn = psycopg2.connect(url)\n"
        "conn.autocommit = True\n"
        "cur = conn.cursor()\n"
        "for s in stmts:\n"
        "    cur.execute(s)\n"
        "cur.close(); conn.close()\n"
    )
    return subprocess.run(
        [sys.executable, "-c", script, url, *statements],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _parse_graph() -> tuple[dict[str, str], dict[str, list[str]]]:
    revs: dict[str, str] = {}
    downs: dict[str, list[str]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        content = path.read_text(encoding="utf-8")
        m = _REV.search(content)
        if not m:
            continue
        rev = m.group(1)
        revs[rev] = content
        dm = _DOWN.search(content)
        downs[rev] = re.findall(r"[\"']([^\"']+)[\"']", dm.group(1)) if dm else []
    return revs, downs


def _ancestors(rev: str, downs: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(downs.get(rev, []))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(downs.get(cur, []))
    return seen


def test_no_implicit_cross_branch_table_dependency():
    """改表迁移的「建表迁移」必须在其祖先链上，否则空库按拓扑序可能先改后建。

    这是对上面那次崩溃的**静态**复现——不依赖 PostgreSQL，任何环境都会跑，
    因此可作为快速回归防线（动态冒烟测试在无 PG 时会 skip）。
    """
    revs, downs = _parse_graph()
    assert revs, "未解析到任何迁移 revision"

    creators: dict[str, list[str]] = {}
    for rev, content in revs.items():
        for table in _CREATE_TABLE.findall(content):
            creators.setdefault(table.lower(), []).append(rev)

    problems: list[str] = []
    for rev, content in revs.items():
        refs = {t.lower() for t in _REF_TABLE.findall(content)}
        refs |= {t.lower() for t in _SQL_TABLE.findall(content)}
        anc = _ancestors(rev, downs)
        for table in sorted(refs):
            if len(table) < 3:
                continue
            owners = creators.get(table)
            if not owners:
                continue
            if any(owner in anc or owner == rev for owner in owners):
                continue
            problems.append(
                f"{rev} 引用表 {table}，但创建者 {owners} 不在其祖先链"
            )

    assert problems == [], (
        "存在隐式跨支线依赖：改表迁移与建表迁移不在同一祖先链上，"
        "全新数据库按 alembic 拓扑序可能先执行改表而崩溃。\n  - "
        + "\n  - ".join(problems)
    )


@pytest.mark.slow
def test_migration_chain_runs_on_empty_database():
    """空库 + 全量迁移必须成功（复现生产首次部署路径）。

    无可用 PostgreSQL 时 skip；CI 应保证该用例真实执行。
    """
    admin_url = _admin_url()
    if not admin_url:
        pytest.skip("未配置 POSTGRES_HOST / MIGRATION_SMOKE_DATABASE_URL，跳过空库冒烟")

    smoke_url = _smoke_url(admin_url)

    recreate = _run_sql(
        admin_url,
        f'DROP DATABASE IF EXISTS "{_SMOKE_DB}"',
        f'CREATE DATABASE "{_SMOKE_DB}"',
    )
    if recreate.returncode != 0:
        pytest.skip(
            "无法创建临时库（PostgreSQL 不可达或无权限），跳过空库冒烟："
            + recreate.stderr.strip()[:300]
        )

    try:
        ext = _run_sql(
            smoke_url,
            'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',
            "CREATE EXTENSION IF NOT EXISTS vector",
        )
        assert ext.returncode == 0, f"装载扩展失败：{ext.stderr.strip()[:500]}"

        env = dict(os.environ)
        env["PYTHONPATH"] = str(API_ROOT)
        base, _, tail = smoke_url.rpartition("/")
        env["POSTGRES_DB"] = tail
        env["POSTGRES_HOST"] = env.get("POSTGRES_HOST", "")
        # 显式给 alembic 一个不带 query 的 URI，避免 config 二次拼装
        env["SQLALCHEMY_DATABASE_URI"] = smoke_url

        result = subprocess.run(
            [
                sys.executable, "-m", "alembic",
                "-c", str(ALEMBIC_INI),
                "upgrade", "head",
            ],
            cwd=str(API_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )

        assert result.returncode == 0, (
            "空库上 `alembic upgrade head` 失败——生产首次部署会直接崩溃。\n"
            f"stdout tail:\n{result.stdout[-2000:]}\n"
            f"stderr tail:\n{result.stderr[-3000:]}"
        )
    finally:
        _run_sql(admin_url, f'DROP DATABASE IF EXISTS "{_SMOKE_DB}"')
