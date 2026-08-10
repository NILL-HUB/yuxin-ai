"""IntentClassifier 意图识别节点单元测试。

覆盖：
- IntentClassifierNodeData 实体校验（创建、空分类、单分类、重复分类名称）
- IntentClassifierNode.invoke 执行逻辑（NodeResult 返回、class_name/confidence 输出、占位实现、耗时、状态）
- NodeType.INTENT_CLASSIFIER 枚举注册
- NodeClasses 中注册 intent_classifier
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
from internal.core.workflow.nodes.intent_classifier.intent_classifier_entity import (
    IntentClass,
    IntentClassifierNodeData,
)
from internal.core.workflow.nodes.intent_classifier.intent_classifier_node import (
    IntentClassifierNode,
)
from internal.exception import ValidateErrorException


def _literal_input(name: str = "query", value: str = "hello") -> VariableEntity:
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
    input_variable=None,
    classes=None,
    llm_config=None,
    outputs=None,
    ref_node_id=None,
):
    """构造 IntentClassifierNodeData 测试数据"""
    if input_variable is None:
        ref_node_id = ref_node_id or uuid4()
        input_variable = _ref_input("query", ref_node_id)
    if classes is None:
        classes = [
            IntentClass(name="greeting", description="打招呼类"),
            IntentClass(name="question", description="提问类"),
        ]
    return IntentClassifierNodeData(
        id=uuid4(),
        node_type=NodeType.INTENT_CLASSIFIER.value,
        title="intent_classifier",
        input_variable=input_variable,
        classes=classes,
        llm_config=llm_config if llm_config is not None else {},
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


class TestIntentClassifierNodeData:
    """IntentClassifierNodeData 实体校验"""

    def test_intent_classifier_node_data_creation(self):
        """创建 IntentClassifierNodeData 实例，字段默认值与赋值正确"""
        node_id = uuid4()
        ref_node_id = uuid4()
        data = IntentClassifierNodeData(
            id=node_id,
            node_type=NodeType.INTENT_CLASSIFIER.value,
            title="intent_classifier",
            input_variable=_ref_input("query", ref_node_id),
            classes=[
                IntentClass(name="greeting", description="打招呼类"),
                IntentClass(name="question", description="提问类"),
            ],
        )
        assert data.node_type == NodeType.INTENT_CLASSIFIER
        assert len(data.classes) == 2
        assert data.classes[0].name == "greeting"
        assert data.classes[1].description == "提问类"
        assert data.llm_config == {}
        assert data.outputs == []

    def test_intent_classifier_node_data_empty_classes_raises(self):
        """空分类列表抛 ValidateErrorException"""
        with pytest.raises(ValidateErrorException, match="至少需要1个分类"):
            _make_node_data(classes=[])

    def test_intent_classifier_node_data_single_class_raises(self):
        """只有1个分类抛 ValidateErrorException"""
        with pytest.raises(ValidateErrorException, match="至少需要2个分类"):
            _make_node_data(classes=[IntentClass(name="only", description="唯一分类")])

    def test_intent_classifier_node_data_duplicate_class_names_raises(self):
        """分类名称重复抛 ValidateErrorException"""
        with pytest.raises(ValidateErrorException, match="分类名称不能重复"):
            _make_node_data(classes=[
                IntentClass(name="same", description="分类1"),
                IntentClass(name="same", description="分类2"),
            ])

    def test_intent_classifier_node_data_accepts_dict_classes(self):
        """classes 字段也接受 dict 输入（pydantic 自动转 IntentClass）"""
        data = _make_node_data(classes=[
            {"name": "a", "description": "分类A"},
            {"name": "b", "description": "分类B"},
        ])
        assert len(data.classes) == 2
        assert all(isinstance(c, IntentClass) for c in data.classes)
        assert data.classes[0].name == "a"


class TestIntentClassifierNodeInvoke:
    """IntentClassifierNode.invoke 执行逻辑（真实实现，LLM 调用降级）"""

    def test_intent_classifier_node_invoke_returns_node_result(self):
        """invoke 返回包含 NodeResult 的 state"""
        node_data = _make_node_data(
            input_variable=_literal_input("query", "你好"),
        )
        node = IntentClassifierNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        assert "node_results" in result
        assert len(result["node_results"]) == 1
        node_result = result["node_results"][0]
        assert isinstance(node_result, NodeResult)
        assert node_result.node_data is node_data

    def test_intent_classifier_node_invoke_returns_class_name(self):
        """返回的 outputs 包含 class_name 字段"""
        node_data = _make_node_data(
            input_variable=_literal_input("query", "你好"),
        )
        node = IntentClassifierNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert "class_name" in node_result.outputs
        assert isinstance(node_result.outputs["class_name"], str)

    def test_intent_classifier_node_invoke_returns_confidence(self):
        """返回的 outputs 包含 confidence 字段"""
        node_data = _make_node_data(
            input_variable=_literal_input("query", "你好"),
        )
        node = IntentClassifierNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert "confidence" in node_result.outputs
        assert isinstance(node_result.outputs["confidence"], float)

    def test_intent_classifier_node_invoke_degradation_returns_first_class(self, monkeypatch):
        """LLM 不可用时降级返回第一个分类，confidence 为 0.0"""
        node_data = _make_node_data(
            input_variable=_literal_input("query", "你好"),
            classes=[
                IntentClass(name="first_class", description="第一个分类"),
                IntentClass(name="second_class", description="第二个分类"),
            ],
        )
        node = IntentClassifierNode(node_data=node_data)

        def _raise_load_language_model(self, *_args, **_kwargs):
            raise RuntimeError("llm unavailable")

        monkeypatch.setattr(
            "internal.service.language_model_service.LanguageModelService.load_language_model",
            _raise_load_language_model,
        )

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert node_result.outputs["class_name"] == "first_class"
        assert node_result.outputs["confidence"] == 0.0

    def test_intent_classifier_node_invoke_elapsed_time_positive(self):
        """耗时 latency 大于 0"""
        node_data = _make_node_data(
            input_variable=_literal_input("query", "你好"),
        )
        node = IntentClassifierNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert node_result.latency > 0

    def test_intent_classifier_node_invoke_status_succeeded(self):
        """节点状态为 succeeded"""
        node_data = _make_node_data(
            input_variable=_literal_input("query", "你好"),
        )
        node = IntentClassifierNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert node_result.status == NodeStatus.SUCCEEDED.value

    def test_intent_classifier_node_invoke_resolves_literal_input(self):
        """LITERAL 类型 input_variable 被解析到 NodeResult.inputs"""
        node_data = _make_node_data(
            input_variable=_literal_input("query", "world"),
        )
        node = IntentClassifierNode(node_data=node_data)

        result = node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

        node_result = result["node_results"][0]
        assert node_result.inputs == {"input_text": "world"}

    def test_intent_classifier_node_invoke_resolves_ref_input(self):
        """REF 类型 input_variable 从前序节点输出中提取"""
        ref_node_id = uuid4()
        node_data = _make_node_data(
            input_variable=_ref_input("query", ref_node_id, "out"),
            ref_node_id=ref_node_id,
        )
        node = IntentClassifierNode(node_data=node_data)
        state = _state_with_ref_output(ref_node_id, "out", "resolved-text")

        result = node.invoke(state)

        node_result = result["node_results"][0]
        assert node_result.inputs == {"input_text": "resolved-text"}

    def test_intent_classifier_node_invoke_empty_input_raises(self):
        """输入文本为空时抛 FailException"""
        from internal.exception import FailException

        node_data = _make_node_data(
            input_variable=_literal_input("query", ""),
        )
        node = IntentClassifierNode(node_data=node_data)

        with pytest.raises(FailException, match="输入文本不能为空"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []})

    def test_intent_classifier_node_invoke_ref_missing_raises(self):
        """REF 引用的节点不存在时 input_text 为 None，抛 FailException"""
        from internal.exception import FailException

        ref_node_id = uuid4()
        node_data = _make_node_data(
            input_variable=_ref_input("query", ref_node_id, "out"),
            ref_node_id=ref_node_id,
        )
        node = IntentClassifierNode(node_data=node_data)

        with pytest.raises(FailException, match="输入文本不能为空"):
            node.invoke({"inputs": {}, "outputs": {}, "node_results": []})


class TestIntentClassifierNodeRegistered:
    """NodeType.INTENT_CLASSIFIER 枚举与节点注册校验"""

    def test_node_type_intent_classifier_registered(self):
        """NodeType.INTENT_CLASSIFIER 枚举存在且值为 'intent_classifier'"""
        assert hasattr(NodeType, "INTENT_CLASSIFIER")
        assert NodeType.INTENT_CLASSIFIER.value == "intent_classifier"

    def test_intent_classifier_node_registered_in_node_classes(self):
        """NodeClasses 中注册了 intent_classifier"""
        from internal.core.workflow.workflow import NodeClasses

        assert NodeType.INTENT_CLASSIFIER.value in NodeClasses
        assert NodeClasses[NodeType.INTENT_CLASSIFIER.value] is IntentClassifierNode

    def test_intent_classifier_node_data_registered_in_workflow_config(self):
        """IntentClassifierNodeData 在 workflow_entity 的 node_data_classes 中注册"""
        from internal.core.workflow.nodes import (
            IntentClassifierNodeData as RegisteredData,
        )

        assert RegisteredData is IntentClassifierNodeData
