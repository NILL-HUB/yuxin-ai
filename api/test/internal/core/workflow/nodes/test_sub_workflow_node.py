"""SubWorkflow 子流程节点单元测试。

覆盖：
- SubWorkflowNodeData 实体校验（workflow_id 字符串转 UUID、空值抛异常、inputs/outputs 默认值）
- SubWorkflowNode.invoke 执行逻辑（占位输出、inputs 解析、NodeResult 返回、耗时、状态）
- NodeType.SUB_WORKFLOW 枚举注册
- NodeClasses 中注册 sub_workflow
"""
from uuid import UUID, uuid4

import pytest

from internal.core.workflow.entities.node_entity import (
    NodeResult,
    NodeStatus,
    NodeType,
)
from internal.core.workflow.entities.variable_entity import (
    VariableEntity,
    VariableValueType,
)
from internal.core.workflow.nodes.code.code_entity import CodeNodeData
from internal.core.workflow.nodes.sub_workflow.sub_workflow_entity import (
    SubWorkflowNodeData,
)
from internal.core.workflow.nodes.sub_workflow.sub_workflow_node import (
    SubWorkflowNode,
)
from internal.exception import ValidateErrorException


def _literal_input(name: str, value: str = "hello") -> VariableEntity:
    """构造字面值类型的输入变量"""
    return VariableEntity(
        name=name,
        type="string",
        value={
            "type": VariableValueType.LITERAL.value,
            "content": value,
        },
    )


def _ref_input(name: str, ref_node_id, ref_var_name: str = "out") -> VariableEntity:
    """构造引用类型的输入变量"""
    return VariableEntity(
        name=name,
        type="string",
        value={
            "type": VariableValueType.REF.value,
            "content": {"ref_node_id": ref_node_id, "ref_var_name": ref_var_name},
        },
    )


def _make_node_data(
    workflow_id=None,
    inputs=None,
    outputs=None,
):
    """构造 SubWorkflowNodeData 测试数据"""
    return SubWorkflowNodeData(
        id=uuid4(),
        node_type=NodeType.SUB_WORKFLOW.value,
        title="sub_workflow",
        workflow_id=workflow_id if workflow_id is not None else uuid4(),
        inputs=inputs if inputs is not None else [],
        outputs=outputs if outputs is not None else [],
    )


def _state_with_ref_output(ref_node_id, ref_var_name, value):
    """构造包含前序节点输出的 state"""
    return {
        "inputs": {},
        "outputs": {},
        "node_results": [
            NodeResult(
                node_data=CodeNodeData(
                    id=ref_node_id,
                    node_type=NodeType.CODE.value,
                    title="prev",
                ),
                outputs={ref_var_name: value},
            )
        ],
    }


class TestSubWorkflowNodeData:
    """SubWorkflowNodeData 实体校验"""

    def test_sub_workflow_node_data_creation(self):
        """创建 SubWorkflowNodeData 实例，字段默认值与赋值正确"""
        wf_id = uuid4()
        data = SubWorkflowNodeData(
            id=uuid4(),
            node_type=NodeType.SUB_WORKFLOW.value,
            title="sub_workflow",
            workflow_id=wf_id,
        )
        assert data.node_type == NodeType.SUB_WORKFLOW
        assert data.workflow_id == wf_id
        assert data.inputs == []
        assert data.outputs == []

    def test_sub_workflow_node_data_string_workflow_id_converted_to_uuid(self):
        """字符串 workflow_id 自动转为 UUID"""
        wf_id = uuid4()
        data = SubWorkflowNodeData(
            id=uuid4(),
            node_type=NodeType.SUB_WORKFLOW.value,
            title="sub_workflow",
            workflow_id=str(wf_id),
        )
        assert isinstance(data.workflow_id, UUID)
        assert data.workflow_id == wf_id

    def test_sub_workflow_node_data_empty_workflow_id_raises(self):
        """空 workflow_id 抛 ValidateErrorException"""
        with pytest.raises(ValidateErrorException, match="workflow_id 不能为空"):
            SubWorkflowNodeData(
                id=uuid4(),
                node_type=NodeType.SUB_WORKFLOW.value,
                title="sub_workflow",
                workflow_id="",
            )

    def test_sub_workflow_node_data_none_workflow_id_raises(self):
        """None workflow_id 抛 ValidateErrorException"""
        with pytest.raises(ValidateErrorException, match="workflow_id 不能为空"):
            SubWorkflowNodeData(
                id=uuid4(),
                node_type=NodeType.SUB_WORKFLOW.value,
                title="sub_workflow",
                workflow_id=None,
            )

    def test_sub_workflow_node_data_with_inputs(self):
        """带 inputs 的节点数据创建"""
        data = SubWorkflowNodeData(
            id=uuid4(),
            node_type=NodeType.SUB_WORKFLOW.value,
            title="sub_workflow",
            workflow_id=uuid4(),
            inputs=[_literal_input("query", "world"), _literal_input("count", "3")],
        )
        assert len(data.inputs) == 2
        assert data.inputs[0].name == "query"
        assert data.inputs[1].name == "count"

    def test_sub_workflow_node_data_with_outputs(self):
        """带 outputs 的节点数据创建"""
        data = SubWorkflowNodeData(
            id=uuid4(),
            node_type=NodeType.SUB_WORKFLOW.value,
            title="sub_workflow",
            workflow_id=uuid4(),
            outputs=[_literal_input("result"), _literal_input("status")],
        )
        assert len(data.outputs) == 2
        assert data.outputs[0].name == "result"
        assert data.outputs[1].name == "status"


class TestSubWorkflowNodeInvoke:
    """SubWorkflowNode.invoke 执行逻辑（占位实现）"""

    def test_sub_workflow_node_invoke_returns_node_result(self):
        """invoke 返回包含 NodeResult 的 state"""
        node_data = _make_node_data()
        node = SubWorkflowNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        assert "node_results" in result
        assert len(result["node_results"]) == 1
        node_result = result["node_results"][0]
        assert isinstance(node_result, NodeResult)
        assert node_result.node_data is node_data

    def test_sub_workflow_node_invoke_outputs_match_declaration(self):
        """输出与 outputs 声明匹配（占位值为 None）"""
        node_data = _make_node_data(
            outputs=[_literal_input("result"), _literal_input("status")],
        )
        node = SubWorkflowNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert node_result.outputs == {"result": None, "status": None}

    def test_sub_workflow_node_invoke_outputs_none_when_not_declared(self):
        """无 outputs 声明时返回空 dict"""
        node_data = _make_node_data(outputs=[])
        node = SubWorkflowNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert node_result.outputs == {}

    def test_sub_workflow_node_invoke_elapsed_time_positive(self):
        """耗时 latency 大于 0"""
        node_data = _make_node_data()
        node = SubWorkflowNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert node_result.latency > 0

    def test_sub_workflow_node_invoke_status_succeeded(self):
        """节点状态为 succeeded"""
        node_data = _make_node_data()
        node = SubWorkflowNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert node_result.status == NodeStatus.SUCCEEDED.value

    def test_sub_workflow_node_invoke_resolves_literal_inputs(self):
        """LITERAL 类型 inputs 被解析到 NodeResult.inputs"""
        node_data = _make_node_data(
            inputs=[_literal_input("query", "world")],
        )
        node = SubWorkflowNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert node_result.inputs == {"query": "world"}

    def test_sub_workflow_node_invoke_resolves_ref_inputs(self):
        """REF 类型 inputs 从前序节点输出中提取"""
        ref_node_id = uuid4()
        node_data = _make_node_data(
            inputs=[_ref_input("query", ref_node_id, "out")],
        )
        node = SubWorkflowNode(node_data=node_data)
        state = _state_with_ref_output(ref_node_id, "out", "resolved-value")

        result = node.invoke(state)

        node_result = result["node_results"][0]
        assert node_result.inputs == {"query": "resolved-value"}

    def test_sub_workflow_node_invoke_ref_missing_returns_none(self):
        """REF 引用的节点不存在时返回 None"""
        ref_node_id = uuid4()
        node_data = _make_node_data(
            inputs=[_ref_input("query", ref_node_id, "out")],
        )
        node = SubWorkflowNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert node_result.inputs == {"query": None}


class TestSubWorkflowNodeRegistered:
    """NodeType.SUB_WORKFLOW 枚举与节点注册校验"""

    def test_node_type_sub_workflow_registered(self):
        """NodeType.SUB_WORKFLOW 枚举存在且值为 'sub_workflow'"""
        assert hasattr(NodeType, "SUB_WORKFLOW")
        assert NodeType.SUB_WORKFLOW.value == "sub_workflow"

    def test_sub_workflow_node_registered_in_node_classes(self):
        """NodeClasses 中注册了 sub_workflow"""
        from internal.core.workflow.workflow import NodeClasses

        assert NodeType.SUB_WORKFLOW.value in NodeClasses
        assert NodeClasses[NodeType.SUB_WORKFLOW.value] is SubWorkflowNode

    def test_sub_workflow_node_data_registered_in_workflow_config(self):
        """SubWorkflowNodeData 在 workflow_entity 的 node_data_classes 中注册"""
        from internal.core.workflow.nodes import (
            SubWorkflowNodeData as RegisteredData,
        )

        assert RegisteredData is SubWorkflowNodeData
