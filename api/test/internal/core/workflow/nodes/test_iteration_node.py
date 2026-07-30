"""ITERATION 循环节点单元测试。

覆盖：
- IterationNodeData 实体校验（output_variable_name / index_variable_name / sub_nodes）
- IterationNode.invoke 执行逻辑（数组遍历、空数组、item/index 写入、非数组异常、NodeResult 返回、耗时）
- NodeType.ITERATION 枚举注册
"""
from uuid import uuid4

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
from internal.core.workflow.nodes.iteration.iteration_entity import IterationNodeData
from internal.core.workflow.nodes.iteration.iteration_node import IterationNode
from internal.exception import FailException, ValidateErrorException


def _ref_iterator(ref_node_id, ref_var_name="items"):
    """构造引用类型 iterator 变量"""
    return VariableEntity(
        name="iterator",
        type="string",
        value={
            "type": VariableValueType.REF.value,
            "content": {"ref_node_id": ref_node_id, "ref_var_name": ref_var_name},
        },
    )


def _literal_iterator(value):
    """构造字面值 iterator 变量"""
    return VariableEntity(
        name="iterator",
        type="string",
        value={
            "type": VariableValueType.LITERAL.value,
            "content": value,
        },
    )


def _make_node_data(
    iterator=None,
    output_variable_name="item",
    index_variable_name="index",
    sub_nodes=None,
    ref_node_id=None,
):
    """构造 IterationNodeData 测试数据"""
    if iterator is None:
        ref_node_id = ref_node_id or uuid4()
        iterator = _ref_iterator(ref_node_id)
    return IterationNodeData(
        id=uuid4(),
        node_type=NodeType.ITERATION.value,
        title="iteration",
        iterator=iterator,
        output_variable_name=output_variable_name,
        index_variable_name=index_variable_name,
        sub_nodes=sub_nodes if sub_nodes is not None else [
            CodeNodeData(
                id=uuid4(),
                node_type=NodeType.CODE.value,
                title="sub_code",
            )
        ],
    )


def _state_with_array(ref_node_id, array, ref_var_name="items"):
    """构造包含前序节点输出数组的 state"""
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
                outputs={ref_var_name: array},
            )
        ],
    }


class TestIterationNodeData:
    """IterationNodeData 实体校验"""

    def test_iteration_node_data_creation(self):
        """创建 IterationNodeData 实例，字段默认值与赋值正确"""
        node_id = uuid4()
        ref_node_id = uuid4()
        data = IterationNodeData(
            id=node_id,
            node_type=NodeType.ITERATION.value,
            title="iteration",
            iterator=_ref_iterator(ref_node_id),
            sub_nodes=[
                CodeNodeData(
                    id=uuid4(),
                    node_type=NodeType.CODE.value,
                    title="sub_code",
                )
            ],
        )
        assert data.node_type == NodeType.ITERATION
        assert data.output_variable_name == "item"
        assert data.index_variable_name == "index"
        assert len(data.sub_nodes) == 1
        assert data.sub_edges == []
        assert data.outputs == []

    def test_iteration_node_data_empty_output_variable_name_raises(self):
        """空输出变量名抛 ValidateErrorException"""
        with pytest.raises(ValidateErrorException, match="输出变量名不能为空"):
            _make_node_data(output_variable_name="")

    def test_iteration_node_data_empty_index_variable_name_raises(self):
        """空索引变量名抛 ValidateErrorException"""
        with pytest.raises(ValidateErrorException, match="索引变量名不能为空"):
            _make_node_data(index_variable_name="")

    def test_iteration_node_data_whitespace_output_variable_name_raises(self):
        """纯空白输出变量名抛异常（strip 后为空）"""
        with pytest.raises(ValidateErrorException, match="输出变量名不能为空"):
            _make_node_data(output_variable_name="   ")

    def test_iteration_node_data_empty_sub_nodes_raises(self):
        """空子节点列表抛 ValidateErrorException"""
        with pytest.raises(ValidateErrorException, match="至少需要1个子节点"):
            _make_node_data(sub_nodes=[])


class TestIterationNodeInvoke:
    """IterationNode.invoke 执行逻辑（真实实现，子节点通过 GraphEngine 执行）"""

    def test_iteration_node_invoke_with_array(self):
        """遍历数组返回 result 列表（无真实子节点逻辑时每项为空 dict）"""
        ref_node_id = uuid4()
        node_data = _make_node_data(ref_node_id=ref_node_id)
        node = IterationNode(node_data=node_data)
        array = ["a", "b", "c"]

        result = node.invoke(_state_with_array(ref_node_id, array))

        node_result = result["node_results"][0]
        # 子节点无真实执行逻辑，每次迭代返回空 dict
        assert node_result.outputs["result"] == [{}, {}, {}]
        assert node_result.status == NodeStatus.SUCCEEDED.value

    def test_iteration_node_invoke_with_empty_array(self):
        """空数组返回空 result 列表"""
        ref_node_id = uuid4()
        node_data = _make_node_data(ref_node_id=ref_node_id)
        node = IterationNode(node_data=node_data)

        result = node.invoke(_state_with_array(ref_node_id, []))

        node_result = result["node_results"][0]
        assert node_result.outputs["result"] == []
        assert node_result.outputs["item"] == []
        assert node_result.outputs["index"] == []

    def test_iteration_node_invoke_writes_item_to_state(self):
        """每次迭代的元素被记录到 outputs[output_variable_name]"""
        ref_node_id = uuid4()
        node_data = _make_node_data(
            ref_node_id=ref_node_id,
            output_variable_name="element",
        )
        node = IterationNode(node_data=node_data)
        array = [1, 2, 3]

        result = node.invoke(_state_with_array(ref_node_id, array))

        node_result = result["node_results"][0]
        assert node_result.outputs["element"] == [1, 2, 3]

    def test_iteration_node_invoke_writes_index_to_state(self):
        """每次迭代的索引被记录到 outputs[index_variable_name]"""
        ref_node_id = uuid4()
        node_data = _make_node_data(
            ref_node_id=ref_node_id,
            index_variable_name="idx",
        )
        node = IterationNode(node_data=node_data)
        array = ["x", "y", "z"]

        result = node.invoke(_state_with_array(ref_node_id, array))

        node_result = result["node_results"][0]
        assert node_result.outputs["idx"] == [0, 1, 2]

    def test_iteration_node_invoke_non_array_iterator_raises(self):
        """非数组 iterator 抛 FailException"""
        ref_node_id = uuid4()
        node_data = _make_node_data(ref_node_id=ref_node_id)
        node = IterationNode(node_data=node_data)

        with pytest.raises(FailException, match="必须是数组类型"):
            node.invoke(_state_with_array(ref_node_id, "not-an-array"))

    def test_iteration_node_invoke_returns_node_result(self):
        """返回的 state 包含 node_results 且字段完整"""
        ref_node_id = uuid4()
        node_data = _make_node_data(ref_node_id=ref_node_id)
        node = IterationNode(node_data=node_data)
        array = [10, 20]

        result = node.invoke(_state_with_array(ref_node_id, array))

        assert "node_results" in result
        assert len(result["node_results"]) == 1
        node_result = result["node_results"][0]
        assert node_result.node_data is node_data
        assert node_result.status == NodeStatus.SUCCEEDED.value
        assert node_result.inputs == {"iterator": array, "count": len(array)}
        assert "result" in node_result.outputs

    def test_iteration_node_invoke_elapsed_time(self):
        """耗时 latency 大于 0"""
        ref_node_id = uuid4()
        node_data = _make_node_data(ref_node_id=ref_node_id)
        node = IterationNode(node_data=node_data)

        result = node.invoke(_state_with_array(ref_node_id, [1, 2, 3]))

        node_result = result["node_results"][0]
        assert node_result.latency > 0

    def test_iteration_node_invoke_with_literal_iterator_raises_non_array(self):
        """LITERAL 类型的 iterator 直接使用字面值，非数组时抛 FailException

        说明：VariableEntity.Value.content 仅支持 str/int/float/bool/Content，
        不支持 list，因此 LITERAL 类型 iterator 只能是标量，会触发非数组异常。
        真正的数组遍历通过 REF 类型引用前序节点的 list 输出实现。
        """
        node_data = _make_node_data(iterator=_literal_iterator("not-an-array"))
        node = IterationNode(node_data=node_data)

        with pytest.raises(FailException, match="必须是数组类型"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

    def test_iteration_node_invoke_missing_ref_returns_none_array_raises(self):
        """REF 引用的节点不存在时返回 None，触发非数组异常"""
        ref_node_id = uuid4()
        node_data = _make_node_data(ref_node_id=ref_node_id)
        node = IterationNode(node_data=node_data)

        # state 中无匹配 node_result
        with pytest.raises(FailException, match="必须是数组类型"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []})


class TestIterationNodeTypeRegistered:
    """NodeType.ITERATION 枚举注册校验"""

    def test_node_type_iteration_registered(self):
        """NodeType.ITERATION 枚举存在且值为 'iteration'"""
        assert hasattr(NodeType, "ITERATION")
        assert NodeType.ITERATION.value == "iteration"

    def test_iteration_node_data_class_in_workflow_registry(self):
        """IterationNodeData 在 workflow_entity 的 node_data_classes 中注册"""
        from internal.core.workflow.nodes import IterationNodeData as RegisteredData

        assert RegisteredData is IterationNodeData

    def test_iteration_node_class_in_workflow_node_classes(self):
        """IterationNode 在 workflow.NodeClasses 中注册"""
        from internal.core.workflow.workflow import NodeClasses

        assert NodeClasses[NodeType.ITERATION.value] is IterationNode
