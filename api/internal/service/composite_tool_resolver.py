from typing import Any
from uuid import UUID

from internal.entity.runtime_tool_entity import CompositeComponentRef
from internal.extension.database_extension import db
from internal.model import App, Workflow
from internal.service.tool_inventory_service import build_tool_id, parse_tool_id


class CompositeToolResolver:
    """组合工具展开解析器：递归解析组合工具的内部成员工具，返回扁平化的 CompositeComponentRef 列表。

    给定一个组合工具的 tool_id（如 workflow:{id} / agent_binding:{app_id}），
    递归解析出它直接和间接引用的所有成员工具。原子工具（builtin/api_tool/mcp/knowledge）
    和 skill 不递归展开。公开 App（is_public=True）走 A2A 黑盒，内部不可见，返回空列表。
    """

    def __init__(self, session=None):
        self.session = session or db.session

    def resolve(self, tool_id: str, *, max_depth: int = 8) -> list[CompositeComponentRef]:
        """递归解析组合工具的成员工具，返回扁平化列表。

        Args:
            tool_id: 组合工具 id，格式如 workflow:{id} / agent_binding:{app_id}
            max_depth: 最大递归深度，防止无限嵌套（默认 8）

        Returns:
            扁平化的 CompositeComponentRef 列表，含引用路径
        """
        visited: set[str] = set()
        return self._resolve_recursive(tool_id, visited=visited, depth=0, max_depth=max_depth)

    def _resolve_recursive(
        self,
        tool_id: str,
        *,
        visited: set[str],
        depth: int,
        max_depth: int,
    ) -> list[CompositeComponentRef]:
        # 1. 环检测：tool_id 已访问则返回空（防止循环引用）
        # 2. 深度限制：depth >= max_depth 则返回空
        if tool_id in visited or depth >= max_depth:
            return []
        visited.add(tool_id)

        # 3. 按 source_type 分发解析
        source_type, entity_id = parse_tool_id(tool_id)
        if source_type == "workflow":
            return self._resolve_workflow(
                entity_id, visited=visited, depth=depth, max_depth=max_depth
            )
        if source_type == "agent_binding":
            return self._resolve_agent_binding(
                entity_id, visited=visited, depth=depth, max_depth=max_depth
            )
        # 其他（原子工具 builtin/api_tool/mcp/knowledge、skill）不递归，返回空
        return []

    def _resolve_workflow(
        self,
        workflow_id: str,
        *,
        visited: set[str],
        depth: int,
        max_depth: int,
    ) -> list[CompositeComponentRef]:
        """从 Workflow.graph["nodes"] 提取 ToolNodeData + DatasetRetrievalNode。"""
        workflow = self._query_workflow(workflow_id)
        if workflow is None:
            return []

        graph = getattr(workflow, "graph", None)
        if not isinstance(graph, dict):
            return []

        components: list[CompositeComponentRef] = []
        for idx, node in enumerate(graph.get("nodes", []) or []):
            if not isinstance(node, dict):
                continue
            node_type = node.get("node_type") or node.get("type", "")
            if node_type == "tool":
                ref = self._build_workflow_tool_ref(node, idx)
                if ref is not None:
                    components.append(ref)
            elif node_type == "dataset_retrieval":
                components.extend(self._build_workflow_dataset_refs(node, idx))
            # 其他节点类型（LLM/CODE/HTTP/IF_ELSE 等）不引用工具，跳过
        return components

    def _resolve_agent_binding(
        self,
        app_id: str,
        *,
        visited: set[str],
        depth: int,
        max_depth: int,
    ) -> list[CompositeComponentRef]:
        """递归加载目标 App 的 AppConfig 绑定。

        公开 App（is_public=True）走 A2A 黑盒，内部不可见，返回空列表。
        私有 App 遍历 AppConfig 的 6 类工具绑定字段，is_recursive 的成员递归展开。
        """
        target_app = self._query_app(app_id)
        if target_app is None:
            return []
        # 公开 App 走 A2A，内部不可见，返回空（治理只能在 app_id 层级）
        if getattr(target_app, "is_public", False):
            return []

        config = getattr(target_app, "app_config", None)
        if config is None:
            return []

        components: list[CompositeComponentRef] = []

        # tools 字段：含 builtin_tool + api_tool（原子工具，is_recursive=False）
        for idx, item in enumerate(getattr(config, "tools", []) or []):
            ref = self._build_tools_field_ref(item, idx)
            if ref is not None:
                components.append(ref)

        # mcp_bindings 字段：MCP 绑定（原子工具，is_recursive=False）
        for idx, item in enumerate(getattr(config, "mcp_bindings", []) or []):
            if not isinstance(item, dict):
                continue
            binding_key = str(item.get("provider_key") or item.get("name") or "")
            if not binding_key:
                continue
            components.append(CompositeComponentRef(
                tool_id=build_tool_id("mcp", binding_key),
                source_type="mcp",
                ref_path=f"agent_binding.app_config.mcp_bindings[{idx}]",
                is_recursive=False,
            ))

        # skills 字段：技能包（不递归，按包治理）
        for idx, item in enumerate(getattr(config, "skills", []) or []):
            skill_id = self._extract_skill_id(item)
            if not skill_id:
                continue
            components.append(CompositeComponentRef(
                tool_id=build_tool_id("skill", skill_id),
                source_type="skill",
                ref_path=f"agent_binding.app_config.skills[{idx}]",
                is_recursive=False,
            ))

        # datasets 字段：AppConfig 通过 app_dataset_joins 属性获取，AppConfigVersion 有 datasets 列
        for idx, dataset_id in enumerate(self._extract_dataset_ids(config)):
            components.append(CompositeComponentRef(
                tool_id=build_tool_id("knowledge", dataset_id),
                source_type="knowledge",
                ref_path=f"agent_binding.app_config.datasets[{idx}]",
                is_recursive=False,
            ))

        # workflows 字段：list[UUID(str)]，is_recursive=True
        for idx, item in enumerate(getattr(config, "workflows", []) or []):
            workflow_id = self._extract_workflow_id(item)
            if not workflow_id:
                continue
            member_tool_id = build_tool_id("workflow", workflow_id)
            components.append(CompositeComponentRef(
                tool_id=member_tool_id,
                source_type="workflow",
                ref_path=f"agent_binding.app_config.workflows[{idx}]",
                is_recursive=True,
            ))
            components.extend(self._resolve_recursive(
                member_tool_id, visited=visited, depth=depth + 1, max_depth=max_depth,
            ))

        # agent_bindings 字段：list[dict] with app_id，is_recursive=True
        for idx, item in enumerate(getattr(config, "agent_bindings", []) or []):
            if not isinstance(item, dict):
                continue
            nested_app_id = str(item.get("app_id", "") or "").strip()
            if not nested_app_id:
                continue
            member_tool_id = build_tool_id("agent_binding", nested_app_id)
            components.append(CompositeComponentRef(
                tool_id=member_tool_id,
                source_type="agent_binding",
                ref_path=f"agent_binding.app_config.agent_bindings[{idx}]",
                is_recursive=True,
            ))
            components.extend(self._resolve_recursive(
                member_tool_id, visited=visited, depth=depth + 1, max_depth=max_depth,
            ))

        return components

    def _query_workflow(self, workflow_id: str) -> Workflow | None:
        try:
            workflow_uuid = UUID(str(workflow_id))
        except (ValueError, AttributeError, TypeError):
            return None
        return (
            self.session.query(Workflow)
            .filter(Workflow.id == workflow_uuid)
            .one_or_none()
        )

    def _query_app(self, app_id: str) -> App | None:
        try:
            app_uuid = UUID(str(app_id))
        except (ValueError, AttributeError, TypeError):
            return None
        return (
            self.session.query(App)
            .filter(App.id == app_uuid)
            .one_or_none()
        )

    @staticmethod
    def _build_workflow_tool_ref(node: dict, idx: int) -> CompositeComponentRef | None:
        """从 ToolNodeData 节点构建 CompositeComponentRef（builtin_tool/api_tool 原子工具）。"""
        tool_type = str(node.get("tool_type", "") or "")
        provider_id = str(node.get("provider_id", "") or "")
        tool_id_value = str(node.get("tool_id", "") or "")
        if tool_type == "builtin_tool":
            if not provider_id or not tool_id_value:
                return None
            member_tool_id = build_tool_id("builtin", provider_id, tool_id_value)
            source_type = "builtin"
        elif tool_type == "api_tool":
            if not tool_id_value:
                return None
            member_tool_id = build_tool_id("api_tool", tool_id_value)
            source_type = "api_tool"
        else:
            return None
        return CompositeComponentRef(
            tool_id=member_tool_id,
            source_type=source_type,
            ref_path=f"workflow.nodes[{idx}].tool",
            is_recursive=False,
        )

    @staticmethod
    def _build_workflow_dataset_refs(node: dict, idx: int) -> list[CompositeComponentRef]:
        """从 DatasetRetrievalNode 节点构建 CompositeComponentRef 列表（dataset_ids 是列表）。"""
        dataset_ids = node.get("dataset_ids", [])
        if not isinstance(dataset_ids, list):
            return []
        refs: list[CompositeComponentRef] = []
        for dataset_id in dataset_ids:
            dataset_id_str = str(dataset_id).strip()
            if not dataset_id_str:
                continue
            refs.append(CompositeComponentRef(
                tool_id=build_tool_id("knowledge", dataset_id_str),
                source_type="knowledge",
                ref_path=f"workflow.nodes[{idx}].dataset_retrieval",
                is_recursive=False,
            ))
        return refs

    @staticmethod
    def _build_tools_field_ref(item: Any, idx: int) -> CompositeComponentRef | None:
        """从 AppConfig.tools 的单项构建 CompositeComponentRef（builtin_tool/api_tool）。"""
        if not isinstance(item, dict):
            return None
        tool_type = str(item.get("type", "") or "")
        provider_id = str(item.get("provider_id", "") or "")
        tool_id_value = str(item.get("tool_id", "") or "")
        if tool_type == "builtin_tool":
            if not provider_id or not tool_id_value:
                return None
            return CompositeComponentRef(
                tool_id=build_tool_id("builtin", provider_id, tool_id_value),
                source_type="builtin",
                ref_path=f"agent_binding.app_config.tools[{idx}]",
                is_recursive=False,
            )
        if tool_type == "api_tool":
            if not tool_id_value:
                return None
            return CompositeComponentRef(
                tool_id=build_tool_id("api_tool", tool_id_value),
                source_type="api_tool",
                ref_path=f"agent_binding.app_config.tools[{idx}]",
                is_recursive=False,
            )
        return None

    @staticmethod
    def _extract_skill_id(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("skill_id") or item.get("id") or item.get("name") or "").strip()
        return str(item).strip() if item else ""

    @staticmethod
    def _extract_workflow_id(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("id") or item.get("workflow_id") or "").strip()
        return str(item).strip() if item else ""

    @staticmethod
    def _extract_dataset_ids(config: Any) -> list[str]:
        """提取知识库 id 列表。

        AppConfig 通过 app_dataset_joins 属性获取（返回 AppDatasetJoin 列表），
        AppConfigVersion 通过 datasets JSONB 列获取（list[str]）。
        """
        joins = getattr(config, "app_dataset_joins", None)
        if joins:
            result = []
            for join in joins:
                dataset_id = getattr(join, "dataset_id", None)
                if dataset_id is not None:
                    dataset_id_str = str(dataset_id).strip()
                    if dataset_id_str:
                        result.append(dataset_id_str)
            if result:
                return result
        datasets = getattr(config, "datasets", None)
        if isinstance(datasets, list):
            return [str(item).strip() for item in datasets if item]
        return []
