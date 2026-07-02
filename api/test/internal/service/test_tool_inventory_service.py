from types import SimpleNamespace
from uuid import UUID

from internal.entity.tool_inventory_entity import ToolSourceType
from internal.entity.workflow_entity import WorkflowStatus
from internal.model import SkillPackage, Workflow
from internal.service.tool_inventory_service import ToolCandidateCollector

ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000001")


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
    """模型感知的伪会话：按 model 类返回预设列表，未配置的模型返回空。

    可选 filter_fns 为每个 model 提供一个 post_filter 函数，模拟 SQL 过滤。
    """

    def __init__(self, by_model=None, filter_fns=None):
        self._by_model = by_model or {}
        self._filter_fns = filter_fns or {}

    def query(self, model):
        return _QueryStub(
            self._by_model.get(model, []),
            post_filter=self._filter_fns.get(model),
        )


def _make_package(
    *,
    package_id=UUID("11111111-1111-1111-1111-111111111111"),
    name="pdf",
    label="PDF 工具",
    description="PDF 处理技能包",
    capabilities=None,
    enabled=True,
    metadata=None,
):
    return SimpleNamespace(
        id=package_id,
        name=name,
        label=label,
        description=description,
        capabilities=capabilities if capabilities is not None else ["pdf_parse"],
        enabled=enabled,
        metadata=metadata or {},
    )


def test_collect_skill_tools_returns_correct_format():
    package = _make_package()
    collector = ToolCandidateCollector(session=_SessionStub({SkillPackage: [package]}))

    result = collector._collect_skill_tools(ACCOUNT_ID)

    assert len(result) == 1
    candidate = result[0]
    assert candidate["name"] == "pdf"
    assert candidate["description"] == "PDF 处理技能包"
    assert candidate["provider_id"] == str(package.id)
    assert candidate["provider_name"] == "PDF 工具"
    assert candidate["inputs"] == []
    assert candidate["visibility"] == "system"
    assert candidate["enabled"] is True
    metadata = candidate["metadata"]
    assert metadata["tool_pool"] == "skill"
    assert metadata["risk_level"] == "low"
    assert metadata["permission_scope"] == "system"
    assert metadata["cost_level"] == "low"
    assert metadata["owner"] == "system"
    assert metadata["enabled"] is True
    assert metadata["health_status"] == "healthy"


def test_collect_skill_tools_filters_disabled_package():
    enabled_pkg = _make_package(
        package_id=UUID("11111111-1111-1111-1111-111111111111"),
        name="enabled_skill",
    )
    disabled_pkg = _make_package(
        package_id=UUID("22222222-2222-2222-2222-222222222222"),
        name="disabled_skill",
        enabled=False,
    )
    collector = ToolCandidateCollector(
        session=_SessionStub({SkillPackage: [enabled_pkg, disabled_pkg]})
    )

    result = collector._collect_skill_tools(ACCOUNT_ID)

    assert len(result) == 1
    assert result[0]["name"] == "enabled_skill"


def test_collect_skill_tools_tool_id_format():
    package = _make_package(package_id=UUID("abcdefab-1234-5678-9abc-def012345678"))
    collector = ToolCandidateCollector(session=_SessionStub({SkillPackage: [package]}))

    result = collector._collect_skill_tools(ACCOUNT_ID)

    assert len(result) == 1
    assert result[0]["id"] == f"skill:{package.id}"


def test_collect_skill_tools_source_type_is_skill():
    package = _make_package()
    collector = ToolCandidateCollector(session=_SessionStub({SkillPackage: [package]}))

    result = collector._collect_skill_tools(ACCOUNT_ID)

    assert len(result) == 1
    assert result[0]["source_type"] == ToolSourceType.SKILL.value
    assert result[0]["source_type"] == "skill"


def test_collect_includes_skill_candidates():
    """collect() 应纳入 skill 候选；其他模型在伪会话中为空。"""
    package = _make_package()
    collector = ToolCandidateCollector(session=_SessionStub({SkillPackage: [package]}))

    result = collector.collect(ACCOUNT_ID)

    skill_candidates = [c for c in result if c["source_type"] == ToolSourceType.SKILL.value]
    assert len(skill_candidates) == 1
    assert skill_candidates[0]["id"] == f"skill:{package.id}"


# ------------------------------------------------------------------ #
#  Workflow 候选收集测试                                              #
# ------------------------------------------------------------------ #

def _make_workflow(
    *,
    workflow_id=UUID("33333333-3333-3333-3333-333333333333"),
    name="数据检索流",
    tool_call_name="data_retrieval_flow",
    description="组合数据检索工作流",
    status=WorkflowStatus.PUBLISHED.value,
    account_id=ACCOUNT_ID,
):
    return SimpleNamespace(
        id=workflow_id,
        name=name,
        tool_call_name=tool_call_name,
        description=description,
        status=status,
        account_id=account_id,
    )


def test_collect_workflow_tools_returns_correct_format():
    wf = _make_workflow()
    collector = ToolCandidateCollector(session=_SessionStub({Workflow: [wf]}))

    result = collector._collect_workflow_tools(ACCOUNT_ID)

    assert len(result) == 1
    candidate = result[0]
    assert candidate["name"] == "数据检索流"
    assert candidate["description"] == "组合数据检索工作流"
    assert candidate["provider_id"] == str(wf.id)
    assert candidate["provider_name"] == "数据检索流"
    assert candidate["inputs"] == []
    assert candidate["visibility"] == "private"
    assert candidate["enabled"] is True
    metadata = candidate["metadata"]
    assert metadata["tool_pool"] == "workflow"
    assert metadata["risk_level"] == "medium"
    assert metadata["permission_scope"] == "user"
    assert metadata["cost_level"] == "medium"
    assert metadata["owner"] == str(ACCOUNT_ID)
    assert metadata["enabled"] is True
    assert metadata["health_status"] == "healthy"


def test_collect_workflow_tools_filters_non_published():
    published_wf = _make_workflow(
        workflow_id=UUID("33333333-3333-3333-3333-333333333333"),
        name="published_wf",
    )
    draft_wf = _make_workflow(
        workflow_id=UUID("44444444-4444-4444-4444-444444444444"),
        name="draft_wf",
        status=WorkflowStatus.DRAFT.value,
    )
    collector = ToolCandidateCollector(
        session=_SessionStub(
            {Workflow: [published_wf, draft_wf]},
            filter_fns={
                Workflow: lambda wf: wf.status == WorkflowStatus.PUBLISHED.value
            },
        )
    )

    result = collector._collect_workflow_tools(ACCOUNT_ID)

    assert len(result) == 1
    assert result[0]["name"] == "published_wf"


def test_collect_workflow_tools_tool_id_format():
    wf = _make_workflow(workflow_id=UUID("abcdefab-1234-5678-9abc-def012345678"))
    collector = ToolCandidateCollector(session=_SessionStub({Workflow: [wf]}))

    result = collector._collect_workflow_tools(ACCOUNT_ID)

    assert len(result) == 1
    assert result[0]["id"] == f"workflow:{wf.id}"


def test_collect_workflow_tools_source_type_is_workflow():
    wf = _make_workflow()
    collector = ToolCandidateCollector(session=_SessionStub({Workflow: [wf]}))

    result = collector._collect_workflow_tools(ACCOUNT_ID)

    assert len(result) == 1
    assert result[0]["source_type"] == ToolSourceType.WORKFLOW.value
    assert result[0]["source_type"] == "workflow"


def test_collect_workflow_tools_default_risk_level_is_medium():
    wf = _make_workflow()
    collector = ToolCandidateCollector(session=_SessionStub({Workflow: [wf]}))

    result = collector._collect_workflow_tools(ACCOUNT_ID)

    assert len(result) == 1
    assert result[0]["metadata"]["risk_level"] == "medium"


def test_collect_includes_workflow_candidates():
    """collect() 应纳入 workflow 候选；其他模型在伪会话中为空。"""
    wf = _make_workflow()
    collector = ToolCandidateCollector(session=_SessionStub({Workflow: [wf]}))

    result = collector.collect(ACCOUNT_ID)

    workflow_candidates = [
        c for c in result if c["source_type"] == ToolSourceType.WORKFLOW.value
    ]
    assert len(workflow_candidates) == 1
    assert workflow_candidates[0]["id"] == f"workflow:{wf.id}"
