"""cli-hub 清理守卫：文件已删除 + 迁移正确链接 + 清理语句就位。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[3] / "internal/migration/versions"
API_ROOT = Path(__file__).resolve().parents[3]


def _load(module_name: str):
    path = VERSIONS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_cleanup_migration_links_to_cli_provider_migration():
    mod = _load("d5f6a7b8c9e0_cleanup_cli_hub_skill")
    assert mod.revision == "d5f6a7b8c9e0"
    assert mod.down_revision == "c4e5f6a7b8d9"


def test_cli_hub_catalog_directory_removed():
    assert not (API_ROOT / "internal/core/skills/catalog/cli-hub").exists()


def test_cli_hub_test_module_removed():
    assert not (API_ROOT / "test/internal/core/skills/test_cli_hub_skill.py").exists()
