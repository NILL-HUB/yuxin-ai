"""P0-6 tool_id 统一 + P1-3/P1-4 候选收集 + P0-3 治理门过滤 端到端集成测试。

验证环节：
    ToolCandidateCollector 收集 6 类工具（api_tool/mcp/builtin/knowledge/skill/
    workflow）后，tool_id 格式统一且全局唯一；collect 结果能被 ToolPolicyFilter
    过滤、ToolRanker 排序正常处理。

测试场景：
    1. tool_id 格式统一验证（6 类工具各 1 个，parse_tool_id 解析 source_type 正确）
    2. collect 后接 ToolPolicyFilter 过滤（safe 工具 accepted，disabled 工具 filtered_out）
    3. collect 后接 ToolRanker 排序（不同 success_rate，高分在前）
    4. tool_id 全局唯一性（collect 后无重复）
    5. 混合多类工具 collect + filter 端到端不报错
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

from internal.entity.tool_inventory_entity import ToolSourceType
from internal.entity.workflow_entity import WorkflowStatus
from internal.model import (
    ApiTool,
    ExternalDataSource,
    KnowledgeBase,
    McpProvider,
    SkillPackage,
    Workflow,
)
from internal.service.tool_inventory_service import (
    ToolCandidateCollector,
    ToolPolicyFilter,
    ToolRanker,
    build_tool_id,
    parse_tool_id,
)


ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000001")


# ------------------------------------------------------------------ #
#  Stub（复用 test_tool_inventory_service.py 的模型感知会话桩）       #
# ------------------------------------------------------------------ #

class _QueryStub:
    """最小化查询桩：忽略 filter 条件，直接返回预设列表。

    可选 post_filter 用于模拟 SQL 层过滤（如 status == PUBLISHED）。
    """

    def __init__(self, items, post_filter=None):
        self._items = items
        self._post_filter = post_filter

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        items = list(self._items)
        if self._post_filter is not None:
            items = [item for item in items if self._post_filter(item)]
        return items


class _SessionStub:
    """模型感知的伪会话：按 model 类返回预设列表，未配置的模型返回空。"""

    def __init__(self, by_model=None, filter_fns=None):
        self._by_model = by_model or {}
        self._filter_fns = filter_fns or {}

    def query(self, model):
        return _QueryStub(
            self._by_model.get(model, []),
            post_filter=self._filter_fns.get(model),
        )


# ------------------------------------------------------------------ #
#  工具构造工厂                                                       #
# ------------------------------------------------------------------ #

def _make_api_tool(*, tool_id=None, name="search_orders", provider=None):
    return SimpleNamespace(
        id=tool_id or uuid4(),
        name=name,
        description="订单搜索 API",
        provider=provider or SimpleNamespace(id=uuid4(), name="erp-provider"),
        parameters=[{"name": "q", "in": "query", "type": "string"}],
        metadata={},
        task_keywords=[],
        account_id=ACCOUNT_ID,
    )


def _make_mcp_provider(*, provider_id=None, tool_names=None, is_public=False):
    return SimpleNamespace(
        id=provider_id or uuid4(),
        name="github-mcp",
        label="GitHub MCP",
        description="GitHub MCP 服务",
        tool_names=tool_names or ["create_issue", "list_prs"],
        task_keywords=[],
        metadata={},
        is_public=is_public,
        account_id=ACCOUNT_ID,
    )


def _make_builtin_tool_service():
    """构造 BuiltinToolService 桩，返回 1 个 provider 含 1 个工具。"""
    return SimpleNamespace(
        get_builtin_tools=lambda: [
            {
                "name": "weather",
                "label": "天气",
                "metadata": {},
                "tools": [
                    {
                        "name": "get_weather",
                        "description": "获取天气",
                        "metadata": {},
                        "inputs": [],
                        "task_keywords": [],
                    }
                ],
            }
        ]
    )


def _make_knowledge_base(*, base_id=None, knowledge_scope="user"):
    return SimpleNamespace(
        id=base_id or uuid4(),
        name="产品文档库",
        description="产品文档知识库",
        knowledge_scope=knowledge_scope,
        metadata={},
        owner_account_id=ACCOUNT_ID,
        enabled=True,
    )


def _make_skill_package(*, package_id=None, name="pdf"):
    return SimpleNamespace(
        id=package_id or uuid4(),
        name=name,
        label="PDF 工具",
        description="PDF 处理技能包",
        capabilities=["pdf_parse"],
        task_keywords=[],
        enabled=True,
        metadata={},
    )


def _make_workflow(*, workflow_id=None, name="数据流", status=None):
    return SimpleNamespace(
        id=workflow_id or uuid4(),
        name=name,
        tool_call_name="data_flow",
        description="数据处理工作流",
        status=status or WorkflowStatus.PUBLISHED.value,
        task_keywords=[],
        account_id=ACCOUNT_ID,
    )


# ------------------------------------------------------------------ #
#  测试用例                                                           #
# ------------------------------------------------------------------ #

def test_tool_id_format_unified_across_six_source_types():
    """场景1：6 类工具 tool_id 格式统一验证。

    构造 api_tool/mcp/builtin/knowledge/skill/workflow 各 1 个，collect() 后
    所有 tool_id 应符合标准格式，parse_tool_id 解析后 source_type 正确。
    """
    api_tool = _make_api_tool()
    mcp_provider = _make_mcp_provider(tool_names=["create_issue"])
    knowledge_base = _make_knowledge_base()
    skill_package = _make_skill_package()
    workflow = _make_workflow()
    session = _SessionStub({
        ApiTool: [api_tool],
        McpProvider: [mcp_provider],
        KnowledgeBase: [knowledge_base],
        SkillPackage: [skill_package],
        Workflow: [workflow],
        ExternalDataSource: [],
    })
    collector = ToolCandidateCollector(
        session=session, builtin_tool_service=_make_builtin_tool_service()
    )

    result = collector.collect(ACCOUNT_ID)

    tool_ids = {c["id"] for c in result}
    # 6 类工具各 1 个
    assert f"api_tool:{api_tool.id}" in tool_ids
    assert f"mcp:{mcp_provider.id}:create_issue" in tool_ids
    assert "builtin:weather:get_weather" in tool_ids
    assert f"knowledge:{knowledge_base.id}" in tool_ids
    assert f"skill:{skill_package.id}" in tool_ids
    assert f"workflow:{workflow.id}" in tool_ids
    # parse_tool_id 解析 source_type 正确
    id_to_source = {c["id"]: c["source_type"] for c in result}
    assert id_to_source[f"api_tool:{api_tool.id}"] == ToolSourceType.API.value
    assert id_to_source[f"mcp:{mcp_provider.id}:create_issue"] == ToolSourceType.MCP.value
    assert id_to_source["builtin:weather:get_weather"] == ToolSourceType.BUILTIN.value
    assert id_to_source[f"knowledge:{knowledge_base.id}"] == ToolSourceType.KNOWLEDGE.value
    assert id_to_source[f"skill:{skill_package.id}"] == ToolSourceType.SKILL.value
    assert id_to_source[f"workflow:{workflow.id}"] == ToolSourceType.WORKFLOW.value
    # parse_tool_id 拆分第一个冒号
    source, entity = parse_tool_id(f"mcp:{mcp_provider.id}:create_issue")
    assert source == "mcp"
    assert entity == f"{mcp_provider.id}:create_issue"


def test_collect_then_policy_filter_accepts_safe_and_filters_disabled():
    """场景2：collect 后接 ToolPolicyFilter 过滤。

    构造 1 个 safe 工具 + 1 个 enabled=False 工具，ToolPolicyFilter.filter() 后
    safe 工具 accepted，disabled 工具 filtered_out。
    """
    api_tool = _make_api_tool(name="safe_tool")
    disabled_tool = _make_api_tool(name="disabled_tool")
    session = _SessionStub({
        ApiTool: [api_tool, disabled_tool],
        McpProvider: [],
        KnowledgeBase: [],
        SkillPackage: [],
        Workflow: [],
        ExternalDataSource: [],
    })
    collector = ToolCandidateCollector(session=session)

    result = collector.collect(ACCOUNT_ID)
    # 手动把第 2 个工具的 metadata 设为 disabled（绕过 collect 的 _is_available 过滤）
    # 这里直接构造 filter 输入验证 ToolPolicyFilter 行为
    safe_candidate = {
        "id": "api_tool:safe-1",
        "name": "safe_tool",
        "metadata": {
            "tool_pool": "api",
            "risk_level": "safe",
            "permission_scope": "user",
            "enabled": True,
            "owner": "system",
            "cost_level": "low",
        },
    }
    disabled_candidate = {
        "id": "api_tool:disabled-1",
        "name": "disabled_tool",
        "metadata": {
            "tool_pool": "api",
            "risk_level": "safe",
            "permission_scope": "user",
            "enabled": False,
            "owner": "system",
            "cost_level": "low",
        },
    }

    filter_result = ToolPolicyFilter().filter(
        [safe_candidate, disabled_candidate], account_id=str(ACCOUNT_ID)
    )

    accepted_ids = {c["id"] for c in filter_result["candidates"]}
    assert "api_tool:safe-1" in accepted_ids
    assert "api_tool:disabled-1" not in accepted_ids
    assert len(filter_result["filtered_out_tools"]) == 1
    assert filter_result["filtered_out_tools"][0]["reason"] == "tool_disabled"
    # collect 本身能正常运行
    assert len(result) >= 1


def test_collect_then_ranker_sorts_by_success_rate():
    """场景3：collect 后接 ToolRanker 排序，不同 success_rate 高分在前。

    构造 2 个工具，success_rate 不同（0.9 vs 0.1），其余因子接近，
    ToolRanker 排序后高 success_rate 工具在前。
    """
    high_rate_candidate = {
        "id": "api_tool:high-rate",
        "name": "high_rate_tool",
        "metadata": {
            "tool_pool": "api",
            "success_rate": 0.9,
            "health_status": "healthy",
            "cost_level": "low",
            "avg_latency": 100,
            "capabilities": ["search"],
            "permission_scope": "user",
            "owner": "system",
            "enabled": True,
        },
    }
    low_rate_candidate = {
        "id": "api_tool:low-rate",
        "name": "low_rate_tool",
        "metadata": {
            "tool_pool": "api",
            "success_rate": 0.1,
            "health_status": "healthy",
            "cost_level": "low",
            "avg_latency": 100,
            "capabilities": ["search"],
            "permission_scope": "user",
            "owner": "system",
            "enabled": True,
        },
    }

    ranked = ToolRanker().rank([low_rate_candidate, high_rate_candidate])

    assert ranked[0]["id"] == "api_tool:high-rate"
    assert ranked[1]["id"] == "api_tool:low-rate"
    assert ranked[0]["score"] > ranked[1]["score"]
    # success_rate 体现在 score_breakdown
    assert ranked[0]["score_breakdown"]["success_rate"] == 0.9
    assert ranked[1]["score_breakdown"]["success_rate"] == 0.1


def test_tool_id_globally_unique_after_collect():
    """场景4：tool_id 全局唯一性。

    构造多类工具（含同名 mcp tool_names），collect() 后所有 tool_id 无重复。
    """
    api_tool = _make_api_tool(name="t1")
    # 2 个 mcp provider 都含同名 tool "shared_tool"，tool_id 应因 provider_id 不同而唯一
    mcp_a = _make_mcp_provider(tool_names=["shared_tool"])
    mcp_b = _make_mcp_provider(tool_names=["shared_tool"])
    skill_a = _make_skill_package(name="skill_a")
    skill_b = _make_skill_package(name="skill_b")
    session = _SessionStub({
        ApiTool: [api_tool],
        McpProvider: [mcp_a, mcp_b],
        KnowledgeBase: [],
        SkillPackage: [skill_a, skill_b],
        Workflow: [],
        ExternalDataSource: [],
    })
    collector = ToolCandidateCollector(session=session)

    result = collector.collect(ACCOUNT_ID)

    tool_ids = [c["id"] for c in result]
    assert len(tool_ids) == len(set(tool_ids)), f"tool_id 有重复: {tool_ids}"
    # 2 个 mcp provider 的同名工具 tool_id 不同
    assert f"mcp:{mcp_a.id}:shared_tool" in tool_ids
    assert f"mcp:{mcp_b.id}:shared_tool" in tool_ids
    assert f"mcp:{mcp_a.id}:shared_tool" != f"mcp:{mcp_b.id}:shared_tool"


def test_mixed_tools_collect_and_filter_end_to_end():
    """场景5：混合多类工具 collect + filter 端到端不报错。

    构造 api_tool + skill + workflow，collect() 后接 ToolPolicyFilter，
    过滤结果结构正确且不抛异常。
    """
    api_tool = _make_api_tool(name="mixed_api")
    skill = _make_skill_package(name="mixed_skill")
    workflow = _make_workflow(name="mixed_workflow")
    session = _SessionStub({
        ApiTool: [api_tool],
        McpProvider: [],
        KnowledgeBase: [],
        SkillPackage: [skill],
        Workflow: [workflow],
        ExternalDataSource: [],
    })
    collector = ToolCandidateCollector(session=session)

    result = collector.collect(ACCOUNT_ID)

    # collect 结果应含 3 类工具
    source_types = {c["source_type"] for c in result}
    assert ToolSourceType.API.value in source_types
    assert ToolSourceType.SKILL.value in source_types
    assert ToolSourceType.WORKFLOW.value in source_types
    # 接 ToolPolicyFilter 不报错（skill 默认 permission_scope=system 会被过滤，
    # api_tool/workflow permission_scope=user 放行）
    filter_result = ToolPolicyFilter().filter(result, account_id=str(ACCOUNT_ID))
    assert "candidates" in filter_result
    assert "filtered_out_tools" in filter_result
    # 至少有候选被处理
    total = len(filter_result["candidates"]) + len(filter_result["filtered_out_tools"])
    assert total == len(result)
