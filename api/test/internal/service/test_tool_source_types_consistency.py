"""工具来源类型（SOURCE_TYPES）一致性守卫。

CLI 作为与 builtin/api_tool/mcp/skill 并列的独立工具来源，必须同时出现在
schema 与 service 两处（两处重复定义，极易漂移）。
"""

from __future__ import annotations


def test_source_types_include_cli():
    from internal.schema.admin_tool_governance_schema import SOURCE_TYPES as SCHEMA_TYPES
    from internal.service.admin_tool_governance_service import SOURCE_TYPES as SERVICE_TYPES

    assert "cli" in SCHEMA_TYPES
    assert "cli" in SERVICE_TYPES


def test_source_types_stay_in_sync():
    from internal.schema.admin_tool_governance_schema import SOURCE_TYPES as SCHEMA_TYPES
    from internal.service.admin_tool_governance_service import SOURCE_TYPES as SERVICE_TYPES

    # 两处重复定义必须一致，防止只改一侧造成治理页与校验行为漂移
    assert SCHEMA_TYPES == SERVICE_TYPES


def test_tool_source_type_enum_has_cli():
    from internal.entity.tool_inventory_entity import ToolSourceType

    assert ToolSourceType.CLI.value == "cli"


def test_cli_sub_pool_registered():
    """cli 子池必须注册，否则 normalize_pool_name('cli') 会静默回退到 general。"""
    from internal.entity.tool_pool_entity import BUILTIN_TOOL_SUB_POOLS

    names = {pool["name"] for pool in BUILTIN_TOOL_SUB_POOLS}
    assert "cli" in names
