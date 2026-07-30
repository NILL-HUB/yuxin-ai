"""P0-4 AppRuntimeService 治理注入 端到端集成测试。

验证环节：
    AppRuntimeService.build_runtime_tools_for_config 在 return 前注入 RuntimeToolGovernanceGate，
    对 BaseTool 列表进行治理过滤。governance_gate=None 时行为不变。

测试场景：
    1. governance_gate=None 行为不变（返回 tools 列表与不注入治理时一致）
    2. governance_gate 非 None + observe_only=True 不阻断（tools 不被过滤，gate.apply 被调用）
    3. governance_gate 非 None + block_all 阻断高风险（只含 safe 工具）
    4. build_tool_id_hints 生成正确（agent_bindings → {runtime_name: "agent_binding:{app_id}"}）
    5. governance_context=None 时自动构建默认 context（observe_only=True 阶段1）
"""

from types import SimpleNamespace
from uuid import uuid4

from internal.service.app_runtime_service import AppRuntimeService


# ------------------------------------------------------------------ #
#  Stub                                                               #
# ------------------------------------------------------------------ #

class _MockGovernanceGate:
    """记录 apply() 调用并返回可配置结果的治理门桩。"""

    def __init__(self, *, return_tools=None, return_audit=None):
        self.apply_calls = []
        self._return_tools = return_tools
        self._return_audit = return_audit or {
            "accepted": [], "filtered_out": [], "composite_resolved": {},
            "observe_only": False, "block_sensitive_only": False,
            "input_tool_count": 0, "output_tool_count": 0,
        }

    def apply(self, tools, **kwargs):
        self.apply_calls.append({"tools": list(tools), "kwargs": kwargs})
        if self._return_tools is not None:
            return self._return_tools, self._return_audit
        # 默认：observe_only 时原样返回，否则返回空（模拟全量阻断）
        if kwargs.get("observe_only"):
            return list(tools), self._return_audit
        return [], self._return_audit


def _tool(name, description="", metadata=None):
    """构造 BaseTool 桩（SimpleNamespace 模拟）。"""
    return SimpleNamespace(name=name, description=description, metadata=metadata)


def _account():
    return SimpleNamespace(id=uuid4())


def _app_config_service(tools_by_config=None, mcp_tools=None, workflow_tools=None):
    """构造 AppConfigService 桩。"""
    return SimpleNamespace(
        get_langchain_tools_by_tools_config=lambda _tools: tools_by_config or [],
        get_langchain_tools_by_mcp_bindings=lambda _mcp, _snapshots=None: mcp_tools or [],
        get_langchain_tools_by_workflow_ids=lambda _ids: workflow_tools or [],
    )


def _build_inputs(
    *,
    tools_by_config=None,
    mcp_tools=None,
    workflow_tools=None,
    skill_tools=None,
    agent_binding_tools=None,
    draft_app_config=None,
    governance_gate=None,
    governance_context=None,
    app_id=None,
):
    """构造 _build_runtime_tools_for_config 的入参。"""
    account = _account()
    app_config_service = _app_config_service(
        tools_by_config=tools_by_config,
        mcp_tools=mcp_tools,
        workflow_tools=workflow_tools,
    )
    retrieval_service = SimpleNamespace()
    skill_service = SimpleNamespace(
        get_langchain_tools_by_skill_bindings=lambda _skills, runtime_context=None: skill_tools or []
    )
    app_service = SimpleNamespace(
        get_langchain_tools_by_agent_bindings=lambda _bindings, **_kwargs: agent_binding_tools or []
    )
    return {
        "app_config_service": app_config_service,
        "retrieval_service": retrieval_service,
        "skill_service": skill_service,
        "app_service": app_service,
        "account": account,
        "app_id": app_id or uuid4(),
        "draft_app_config": draft_app_config or {
            "tools": [],
            "mcp_bindings": [],
            "skills": [],
            "workflows": [],
            "agent_bindings": [],
            "knowledge_base_ids": [],
        },
        "governance_gate": governance_gate,
        "governance_context": governance_context,
    }


# ------------------------------------------------------------------ #
#  测试用例                                                           #
# ------------------------------------------------------------------ #

def test_governance_gate_none_keeps_behavior_unchanged():
    """场景1：governance_gate=None 行为不变。

    调用 _build_runtime_tools_for_config 不传 governance_gate，返回的 tools 列表
    与不注入治理时完全一致。
    """
    tool_a = _tool("tool_a")
    tool_b = _tool("tool_b")
    inputs = _build_inputs(
        tools_by_config=[tool_a],
        mcp_tools=[tool_b],
        draft_app_config={
            "tools": [{"type": "builtin_tool"}],
            "mcp_bindings": [{"name": "mcp"}],
            "skills": [],
            "workflows": [],
            "agent_bindings": [],
            "knowledge_base_ids": [],
        },
        # governance_gate=None（默认）
    )

    tools = AppRuntimeService.build_runtime_tools_for_config(**inputs)

    # 返回的 tools 列表与 services 返回的完全一致，未被过滤
    assert tools == [tool_a, tool_b]


def test_governance_gate_with_observe_only_does_not_filter_but_records_audit():
    """场景2：governance_gate 非 None + observe_only=True 不阻断。

    mock governance_gate，observe_only=True。_build_runtime_tools_for_config 传入
    governance_gate，返回的 tools 列表不被过滤（observe_only），但 gate.apply 被调用。
    """
    tool_a = _tool("tool_a")
    tool_b = _tool("tool_b")
    gate = _MockGovernanceGate()  # observe_only 时原样返回
    inputs = _build_inputs(
        tools_by_config=[tool_a, tool_b],
        draft_app_config={
            "tools": [{"type": "builtin_tool"}],
            "mcp_bindings": [],
            "skills": [],
            "workflows": [],
            "agent_bindings": [],
            "knowledge_base_ids": [],
        },
        governance_gate=gate,
        governance_context={"observe_only": True, "block_sensitive_only": False, "mode": "observe_only"},
    )

    tools = AppRuntimeService.build_runtime_tools_for_config(**inputs)

    # observe_only：tools 不被过滤
    assert tools == [tool_a, tool_b]
    # gate.apply 被调用
    assert len(gate.apply_calls) == 1
    call = gate.apply_calls[0]
    assert call["kwargs"]["observe_only"] is True
    assert call["kwargs"]["block_sensitive_only"] is False
    # tool_id_hints 被传入（空 dict，因为无 agent_bindings）
    assert call["kwargs"]["tool_id_hints"] == {}


def test_governance_gate_with_block_all_filters_high_risk_tool():
    """场景3：governance_gate 非 None + block_all 阻断高风险。

    mock governance_gate，observe_only=False。构造 1 个 safe 工具 + 1 个 high risk
    工具，返回的 tools 列表只含 safe 工具。
    """
    safe_tool = _tool("search")
    high_tool = _tool("delete")
    # gate 在非 observe_only 时返回空（模拟阻断），这里手动指定只返回 safe_tool
    gate = _MockGovernanceGate(return_tools=[safe_tool])
    inputs = _build_inputs(
        tools_by_config=[safe_tool, high_tool],
        draft_app_config={
            "tools": [{"type": "builtin_tool"}],
            "mcp_bindings": [],
            "skills": [],
            "workflows": [],
            "agent_bindings": [],
            "knowledge_base_ids": [],
        },
        governance_gate=gate,
        governance_context={"observe_only": False, "block_sensitive_only": False, "mode": "block_all"},
    )

    tools = AppRuntimeService.build_runtime_tools_for_config(**inputs)

    # 只含 safe 工具（gate 过滤了 high risk）
    assert tools == [safe_tool]
    assert len(gate.apply_calls) == 1
    call = gate.apply_calls[0]
    assert call["kwargs"]["observe_only"] is False
    assert call["kwargs"]["block_sensitive_only"] is False


def test_build_tool_id_hints_generates_agent_binding_mapping():
    """场景4：_build_tool_id_hints 生成正确。

    构造 AppConfig 含 agent_bindings，_build_tool_id_hints 返回
    {runtime_name: "agent_binding:{app_id}"}。
    """
    bound_app_id = "11111111-1111-1111-1111-111111111111"
    draft_app_config = {
        "agent_bindings": [
            {"app_id": bound_app_id},
            {"app_id": "22222222-2222-2222-2222-222222222222"},
        ],
        # 其他类别暂不提取 hints
        "tools": [{"type": "builtin_tool", "provider_id": "p", "tool_id": "t"}],
        "mcp_bindings": [{"name": "mcp"}],
        "workflows": [{"id": "wf-1"}],
        "skills": [{"skill_id": "skill-1"}],
        "knowledge_base_ids": [],
    }

    hints = AppRuntimeService.build_tool_id_hints(draft_app_config)

    # agent_bindings 的 runtime_name = f"agent_app_{app_id去横线}"
    assert hints == {
        "agent_app_11111111111111111111111111111111": "agent_binding:11111111-1111-1111-1111-111111111111",
        "agent_app_22222222222222222222222222222222": "agent_binding:22222222-2222-2222-2222-222222222222",
    }


def test_governance_context_none_auto_builds_default_observe_only_context():
    """场景5：governance_context=None 时自动构建默认 context（observe_only=True 阶段1）。

    不传 governance_context，传 governance_gate。内部应调
    GovernanceModeResolver 构建默认 context（observe_only=True 阶段1）。
    解析异常或表缺失时降级为 {"observe_only": True}。
    """
    tool_a = _tool("tool_a")
    gate = _MockGovernanceGate()  # observe_only 时原样返回
    inputs = _build_inputs(
        tools_by_config=[tool_a],
        draft_app_config={
            "tools": [{"type": "builtin_tool"}],
            "mcp_bindings": [],
            "skills": [],
            "workflows": [],
            "agent_bindings": [],
            "knowledge_base_ids": [],
        },
        governance_gate=gate,
        # governance_context=None（默认）→ 内部调 _resolve_default_governance_context
    )

    tools = AppRuntimeService.build_runtime_tools_for_config(**inputs)

    # 默认 context 应为 observe_only=True（阶段1 或异常降级），tools 不被过滤
    assert tools == [tool_a]
    assert len(gate.apply_calls) == 1
    call = gate.apply_calls[0]
    # observe_only 应为 True（阶段1 安全默认）
    assert call["kwargs"]["observe_only"] is True
