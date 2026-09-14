"""迁移图完整性守卫。

背景：曾出现 `p1a2b3c4d5e6` 的 `down_revision` 指向未被 git 跟踪的
`o9d0e1f2a3b4`，在开发机（该文件恰好存在）不报错，但全新 clone / CI 上
`alembic upgrade head` 会因 "Revision ... is not present" 直接崩溃。

因此本测试以 **git 跟踪的文件** 为准重建迁移图（而非磁盘上的全部文件），
断言：无悬空 down_revision、且只有一个 head。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = API_ROOT.parent
VERSIONS_RELATIVE = "api/internal/migration/versions"

_REVISION = re.compile(r"^revision(?:\s*:\s*[^=]+)?\s*=\s*[\"']([^\"']+)[\"']", re.M)
_DOWN_REVISION = re.compile(r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(.+)$", re.M)


def _tracked_version_files() -> list[str] | None:
    """返回 git 跟踪的迁移文件（仓库根相对路径）；非 git 仓库或缺少 git 时返回 None。"""
    try:
        result = subprocess.run(
            ["git", "ls-files", VERSIONS_RELATIVE],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip().endswith(".py")]


def _build_graph(paths: list[Path]) -> tuple[dict[str, str], list[str]]:
    revisions: dict[str, str] = {}
    down_revisions: list[str] = []
    for path in paths:
        content = path.read_text(encoding="utf-8")
        revision_match = _REVISION.search(content)
        if revision_match is not None:
            revisions[revision_match.group(1)] = path.name
        down_match = _DOWN_REVISION.search(content)
        if down_match is not None:
            down_revisions.extend(re.findall(r"[\"']([^\"']+)[\"']", down_match.group(1)))
    return revisions, down_revisions


def test_tracked_migration_graph_has_no_dangling_down_revision():
    """每个 down_revision 都必须能在 git 跟踪的迁移文件中找到定义方。"""
    tracked = _tracked_version_files()
    if tracked is None:
        pytest.skip("当前环境不可用 git，跳过基于跟踪文件的迁移图校验")

    revisions, down_revisions = _build_graph([REPO_ROOT / name for name in tracked])
    assert revisions, "未解析到任何迁移 revision"

    dangling = sorted({value for value in down_revisions if value not in revisions})
    assert dangling == [], (
        f"以下 down_revision 指向未被 git 跟踪的迁移，全新 clone 上 alembic 会崩溃：{dangling}"
    )


def test_tracked_migration_graph_has_single_head():
    """git 跟踪的迁移图必须只有一个 head，否则 `alembic upgrade head` 会报多 head。"""
    tracked = _tracked_version_files()
    if tracked is None:
        pytest.skip("当前环境不可用 git，跳过基于跟踪文件的迁移图校验")

    revisions, down_revisions = _build_graph([REPO_ROOT / name for name in tracked])
    heads = sorted(name for name in revisions if name not in down_revisions)
    assert len(heads) == 1, f"期望恰好一个迁移 head，实际为 {heads}"
