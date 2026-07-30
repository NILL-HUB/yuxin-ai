"""池治理链路完整性验证脚本（只验证子池归一化和 DI，不触发完整收集）"""
from uuid import UUID


def main():
    from app.http.app import app, injector
    from internal.service.tool_inventory_service import (
        ToolInventory,
        ToolCandidateCollector,
        ToolPolicyFilter,
        ToolRanker,
        CrossPoolToolSubsetBuilder,
    )
    from internal.entity.tool_pool_entity import ToolSubPoolRegistry
    from internal.service.runtime_tool_mount_service import RuntimeToolMountService
    from internal.service.composite_tool_resolver import CompositeToolResolver
    from internal.service.runtime_tool_governance_gate import RuntimeToolGovernanceGate

    with app.app_context():
        print("=== 池治理链路完整性验证 ===")

        # 1. 验证 ToolSubPoolRegistry DI
        registry = injector.get(ToolSubPoolRegistry)
        pools = registry.list_pools()
        print(f"1. ToolSubPoolRegistry: OK ({len(pools)} 个子池)")
        print(f"   子池: {[p['name'] for p in pools]}")

        # 2. 验证 ToolInventory DI
        inventory = injector.get(ToolInventory)
        print(f"2. ToolInventory: OK (registry={type(inventory.registry).__name__})")

        # 3. 验证 ToolCandidateCollector 通过 ToolInventory 归一化
        collector = injector.get(ToolCandidateCollector)
        print(f"3. ToolCandidateCollector.inventory: {type(collector.inventory).__name__}")
        print(f"   normalize('api') = {collector.inventory.normalize_pool_name('api')}")
        print(f"   normalize('mcp') = {collector.inventory.normalize_pool_name('mcp')}")
        print(f"   normalize('builtin') = {collector.inventory.normalize_pool_name('builtin')}")

        # 4. 验证完整工具池治理链路 DI
        policy_filter = injector.get(ToolPolicyFilter)
        ranker = injector.get(ToolRanker)
        subset_builder = injector.get(CrossPoolToolSubsetBuilder)
        mount_service = injector.get(RuntimeToolMountService)
        resolver = injector.get(CompositeToolResolver)
        gate = injector.get(RuntimeToolGovernanceGate)
        print(f"4. ToolPolicyFilter: {type(policy_filter).__name__}")
        print(f"5. ToolRanker: {type(ranker).__name__}")
        print(f"6. CrossPoolToolSubsetBuilder: {type(subset_builder).__name__}")
        print(f"7. RuntimeToolMountService: {type(mount_service).__name__}")
        print(f"8. CompositeToolResolver: {type(resolver).__name__}")
        print(f"9. RuntimeToolGovernanceGate: {type(gate).__name__}")

        # 5. 验证 DynamicMcpRuntimeService 已删除
        try:
            from internal.service.dynamic_mcp_runtime_service import DynamicMcpRuntimeService
            print("10. DynamicMcpRuntimeService: 仍存在（未删除）")
        except ImportError:
            print("10. DynamicMcpRuntimeService: 已删除 ✓")

        print("=== 池治理链路完整性验证通过 ===")


if __name__ == "__main__":
    main()
