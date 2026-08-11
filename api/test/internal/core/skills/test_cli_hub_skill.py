from __future__ import annotations

from pathlib import Path

import yaml


def test_cli_hub_skill_manifest_is_prompt_skill():
    manifest_path = (
        Path(__file__).resolve().parents[4]
        / "internal/core/skills/catalog/cli-hub/manifest.yaml"
    )
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_key"] == "cli-hub"
    assert manifest["executor_type"] == "prompt"
    assert manifest["enabled"] is True


def test_cli_hub_skill_doc_has_install_and_search_commands():
    skill_path = (
        Path(__file__).resolve().parents[4]
        / "internal/core/skills/catalog/cli-hub/skill.md"
    )
    content = skill_path.read_text(encoding="utf-8")
    assert "cli-hub search" in content
    assert "cli-hub install" in content
    assert "cli-anything-hub" in content
