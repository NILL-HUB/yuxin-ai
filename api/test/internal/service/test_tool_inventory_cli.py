"""CLI 工具来源进入候选池（补断链）。

背景：CLI 子命令此前永远进不了工具池——`_collect_mcp_tools` 读的是
`mcp_provider.tool_names` + provider 级 description，而 CLI 的按工具定义在
`cli_provider.tool_schema` 展开出的 `cli_tool`。这里验证 CLI 以
`source_type="cli"`、**工具级 description** 进入候选池。
"""

from __future__ import annotations

from types import SimpleNamespace

from internal.model.cli import CliProvider
from internal.service.tool_inventory_service import ToolCandidateCollector


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _Session:
    """只对 CliProvider 查询返回数据，其它模型返回空（保证 collect() 安全）。"""

    def __init__(self, providers):
        self._providers = providers

    def query(self, model):
        if model is CliProvider:
            return _Query(self._providers)
        return _Query([])


def _collector(providers) -> ToolCandidateCollector:
    return ToolCandidateCollector(session=_Session(providers))


def _cli_provider(**overrides) -> SimpleNamespace:
    base = dict(
        id="p1",
        name="videocaptioner",
        label="VideoCaptioner",
        description="provider-desc",
        is_public=False,
        enabled=True,
        task_keywords=["字幕"],
        tools=[
            SimpleNamespace(
                name="caption",
                description="一站式生成字幕并烧录",
                input_schema={},
                task_keywords=["caption"],
                enabled=True,
            )
        ],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_collect_cli_tools_uses_tool_level_description():
    cands = _collector([_cli_provider()])._collect_cli_tools("acct")

    assert len(cands) == 1
    c = cands[0]
    assert c["source_type"] == "cli"
    assert c["name"] == "caption"
    # 核心修复：用工具级 description，而非 provider 级
    assert c["description"] == "一站式生成字幕并烧录"
    assert c["provider_name"] == "VideoCaptioner"
    assert "caption" in c["task_keywords"]
    assert "字幕" in c["task_keywords"]


def test_collect_cli_tools_skips_disabled_provider():
    assert _collector([_cli_provider(enabled=False)])._collect_cli_tools("acct") == []


def test_collect_cli_tools_skips_disabled_tool():
    provider = _cli_provider(
        tools=[
            SimpleNamespace(
                name="caption",
                description="d",
                input_schema={},
                task_keywords=[],
                enabled=False,
            )
        ]
    )
    assert _collector([provider])._collect_cli_tools("acct") == []


def test_collect_registers_cli_candidates():
    cands = _collector([_cli_provider()]).collect("acct")

    cli_cands = [c for c in cands if c["source_type"] == "cli"]
    assert len(cli_cands) == 1
    assert cli_cands[0]["name"] == "caption"


def test_selector_can_pick_cli_candidate_by_keyword():
    """cli 候选进池后，复用既有选择器（真实入口 select_tools）即可命中。

    这条同时验证了候选字段（name/source_type/task_keywords）与
    `ToolSelectorService._normalize_candidates` 的规范化契约兼容。
    """
    from internal.service.tool_selector_service import ToolSelectorService

    candidates = [
        {
            "source_type": "cli",
            "provider_id": "p1",
            "provider_name": "VC",
            "name": "caption",
            "description": "一站式生成字幕并烧录",
            "task_keywords": ["caption", "字幕"],
        }
    ]
    selector = ToolSelectorService(builtin_tool_service=None, language_model_service=None)

    selected = selector.select_tools("请帮我做字幕 caption", candidates=candidates, max_tools=5)

    assert len(selected) == 1
    assert selected[0]["source_type"] == "cli"
    assert selected[0]["tool_name"] == "caption"
    assert selected[0]["match_type"] == "keyword"
