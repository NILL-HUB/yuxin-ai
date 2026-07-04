"""VariableParser 单元测试。"""

from __future__ import annotations

import pytest

from internal.core.workflow.variable_pool import VariablePool
from internal.core.workflow.variable_parser import VariableParser


@pytest.fixture
def parser():
    """提供 VariableParser 实例。"""
    return VariableParser()


@pytest.fixture
def pool():
    """提供预填充数据的 VariablePool。"""
    pool = VariablePool()
    pool.set_system_variable("query", "用户问题")
    pool.set_system_variable("user_id", 1001)
    pool.set_conversation_variable("count", 3)
    pool.set_node_output("start", {"query": "开始输入"})
    pool.set_node_output("llm_1", {
        "text": "LLM 回答",
        "score": 95,
        "choices": [
            {"message": {"content": "第一个选项"}},
            {"message": {"content": "第二个选项"}},
        ],
        "items": ["x", "y", "z"],
        "data": {"nested": {"value": 42}},
    })
    return pool


class TestVariableParserPureReference:
    """纯引用返回原始类型测试。"""

    def test_pure_reference_returns_int(self, parser, pool):
        """纯引用返回 int 类型。"""
        result = parser.parse("{{#llm_1.score#}}", pool)
        assert result == 95
        assert isinstance(result, int)

    def test_pure_reference_returns_dict(self, parser, pool):
        """纯引用返回 dict 类型。"""
        result = parser.parse("{{#llm_1.data#}}", pool)
        assert result == {"nested": {"value": 42}}
        assert isinstance(result, dict)

    def test_pure_reference_returns_list(self, parser, pool):
        """纯引用返回 list 类型。"""
        result = parser.parse("{{#llm_1.items#}}", pool)
        assert result == ["x", "y", "z"]
        assert isinstance(result, list)

    def test_pure_reference_returns_string(self, parser, pool):
        """纯引用返回 string 类型。"""
        result = parser.parse("{{#llm_1.text#}}", pool)
        assert result == "LLM 回答"
        assert isinstance(result, str)

    def test_pure_reference_returns_none_when_missing(self, parser, pool):
        """纯引用指向不存在的变量时返回 None。"""
        result = parser.parse("{{#missing_node.field#}}", pool)
        assert result is None

    def test_pure_reference_returns_whole_node_output(self, parser, pool):
        """纯引用仅含 node_id 时返回整个节点输出 dict。"""
        result = parser.parse("{{#llm_1#}}", pool)
        assert isinstance(result, dict)
        assert result["text"] == "LLM 回答"


class TestVariableParserMixedText:
    """混合文本返回字符串测试。"""

    def test_mixed_text_returns_string(self, parser, pool):
        """混合文本返回字符串。"""
        result = parser.parse("答案是 {{#llm_1.text#}}", pool)
        assert result == "答案是 LLM 回答"
        assert isinstance(result, str)

    def test_multiple_references_in_mixed_text(self, parser, pool):
        """多个引用混合文本返回字符串。"""
        result = parser.parse("答案是 {{#llm_1.text#}}, 得分 {{#llm_1.score#}}", pool)
        assert result == "答案是 LLM 回答, 得分 95"

    def test_multiple_references_without_text(self, parser, pool):
        """多个引用无其他文本仍返回字符串（多引用场景）。"""
        result = parser.parse("{{#llm_1.text#}}{{#llm_1.score#}}", pool)
        assert result == "LLM 回答95"

    def test_mixed_text_with_missing_reference(self, parser, pool):
        """混合文本中缺失引用替换为空字符串。"""
        result = parser.parse("值: {{#missing.field#}}!", pool)
        assert result == "值: !"

    def test_mixed_text_with_none_value_replaced_as_empty(self, parser, pool):
        """混合文本中值为 None 的引用替换为空字符串。"""
        pool.set_node_output("n", {"v": None})
        result = parser.parse("前缀 {{#n.v#}} 后缀", pool)
        assert result == "前缀  后缀"


class TestVariableParserNestedAndIndex:
    """嵌套字段与数组索引测试。"""

    def test_nested_field_reference(self, parser, pool):
        """嵌套字段引用。"""
        result = parser.parse("{{#llm_1.choices[0].message.content#}}", pool)
        assert result == "第一个选项"

    def test_nested_field_second_index(self, parser, pool):
        """嵌套字段第二个数组索引。"""
        result = parser.parse("{{#llm_1.choices[1].message.content#}}", pool)
        assert result == "第二个选项"

    def test_array_index_reference(self, parser, pool):
        """数组索引引用。"""
        assert parser.parse("{{#llm_1.items[0]#}}", pool) == "x"
        assert parser.parse("{{#llm_1.items[2]#}}", pool) == "z"

    def test_deep_nested_dict(self, parser, pool):
        """深层嵌套 dict 访问。"""
        result = parser.parse("{{#llm_1.data.nested.value#}}", pool)
        assert result == 42

    def test_out_of_range_index_returns_none_for_pure_ref(self, parser, pool):
        """纯引用中数组越界返回 None。"""
        result = parser.parse("{{#llm_1.items[10]#}}", pool)
        assert result is None

    def test_nonexistent_nested_field_returns_none_for_pure_ref(self, parser, pool):
        """纯引用中嵌套字段不存在返回 None。"""
        result = parser.parse("{{#llm_1.choices[0].missing.field#}}", pool)
        assert result is None


class TestVariableParserSystemAndConversation:
    """系统变量与会话变量引用测试。"""

    def test_system_variable_reference(self, parser, pool):
        """系统变量引用。"""
        result = parser.parse("{{#sys.query#}}", pool)
        assert result == "用户问题"

    def test_system_variable_in_mixed_text(self, parser, pool):
        """系统变量在混合文本中。"""
        result = parser.parse("输入: {{#sys.query#}}, 用户: {{#sys.user_id#}}", pool)
        assert result == "输入: 用户问题, 用户: 1001"

    def test_conversation_variable_reference(self, parser, pool):
        """会话变量引用。"""
        result = parser.parse("{{#conversation.count#}}", pool)
        assert result == 3

    def test_conversation_variable_in_mixed_text(self, parser, pool):
        """会话变量在混合文本中。"""
        result = parser.parse("对话次数: {{#conversation.count#}}", pool)
        assert result == "对话次数: 3"


class TestVariableParserExtractAndCheck:
    """extract_references 与 has_reference 测试。"""

    def test_extract_references_single(self, parser):
        """提取单个引用。"""
        refs = parser.extract_references("你好 {{#llm_1.text#}}")
        assert refs == ["llm_1.text"]

    def test_extract_references_multiple(self, parser):
        """提取多个引用。"""
        refs = parser.extract_references("{{#start.query#}} 和 {{#llm_1.text#}}")
        assert refs == ["start.query", "llm_1.text"]

    def test_extract_references_empty_when_no_match(self, parser):
        """无引用时返回空列表。"""
        refs = parser.extract_references("普通文本无引用")
        assert refs == []

    def test_extract_references_handles_non_string(self, parser):
        """非字符串输入返回空列表。"""
        assert parser.extract_references(123) == []  # type: ignore[arg-type]
        assert parser.extract_references(None) == []  # type: ignore[arg-type]

    def test_has_reference_true(self, parser):
        """包含引用时返回 True。"""
        assert parser.has_reference("{{#llm_1.text#}}") is True
        assert parser.has_reference("前缀 {{#llm_1.text#}} 后缀") is True

    def test_has_reference_false(self, parser):
        """不包含引用时返回 False。"""
        assert parser.has_reference("普通文本") is False
        assert parser.has_reference("") is False

    def test_has_reference_handles_non_string(self, parser):
        """非字符串输入返回 False。"""
        assert parser.has_reference(123) is False  # type: ignore[arg-type]
        assert parser.has_reference(None) is False  # type: ignore[arg-type]


class TestVariableParserRecursive:
    """parse_dict 与 parse_list 递归解析测试。"""

    def test_parse_dict_recursive(self, parser, pool):
        """parse_dict 递归解析字典中的字符串值。"""
        data = {
            "prompt": "问: {{#sys.query#}}",
            "context": "{{#llm_1.text#}}",
            "meta": {
                "score": "{{#llm_1.score#}}",
                "label": "固定标签",
            },
            "count": 10,
            "flag": True,
        }
        result = parser.parse_dict(data, pool)

        assert result["prompt"] == "问: 用户问题"
        assert result["context"] == "LLM 回答"
        # score 是纯引用，应返回原始 int 类型
        assert result["meta"]["score"] == 95
        assert isinstance(result["meta"]["score"], int)
        assert result["meta"]["label"] == "固定标签"
        assert result["count"] == 10
        assert result["flag"] is True

    def test_parse_dict_returns_new_dict(self, parser, pool):
        """parse_dict 不修改原字典。"""
        data = {"key": "{{#llm_1.text#}}"}
        original = dict(data)

        result = parser.parse_dict(data, pool)
        assert data == original
        assert result is not data

    def test_parse_dict_nested_list(self, parser, pool):
        """parse_dict 递归处理嵌套 list。"""
        data = {
            "items": [
                "{{#llm_1.text#}}",
                {"inner": "{{#llm_1.score#}}"},
            ],
        }
        result = parser.parse_dict(data, pool)

        assert result["items"][0] == "LLM 回答"
        assert result["items"][1]["inner"] == 95

    def test_parse_list_recursive(self, parser, pool):
        """parse_list 递归解析列表中的字符串值。"""
        data = [
            "{{#llm_1.text#}}",
            "前缀 {{#llm_1.score#}}",
            {"nested": "{{#sys.query#}}"},
            ["{{#conversation.count#}}", "固定"],
            42,
        ]
        result = parser.parse_list(data, pool)

        assert result[0] == "LLM 回答"
        assert result[1] == "前缀 95"
        assert result[2] == {"nested": "用户问题"}
        # 纯引用返回原始 int 类型
        assert result[3] == [3, "固定"]
        assert isinstance(result[3][0], int)
        assert result[4] == 42

    def test_parse_list_returns_new_list(self, parser, pool):
        """parse_list 不修改原列表。"""
        data = ["{{#llm_1.text#}}"]
        original = list(data)

        result = parser.parse_list(data, pool)
        assert data == original
        assert result is not data


class TestVariableParserEdgeCases:
    """边界情况测试。"""

    def test_no_reference_text_returned_as_is(self, parser, pool):
        """无引用文本原样返回。"""
        result = parser.parse("普通文本，无任何引用", pool)
        assert result == "普通文本，无任何引用"

    def test_empty_string_returned_as_is(self, parser, pool):
        """空字符串原样返回。"""
        assert parser.parse("", pool) == ""

    def test_non_string_input_returned_as_is(self, parser, pool):
        """非字符串输入原样返回。"""
        assert parser.parse(123, pool) == 123  # type: ignore[arg-type]
        assert parser.parse(None, pool) is None  # type: ignore[arg-type]
        assert parser.parse(["a"], pool) == ["a"]  # type: ignore[arg-type]

    def test_reference_with_surrounding_whitespace_is_pure(self, parser, pool):
        """引用前后无其他文本但有空格则视为混合文本。"""
        # 注意：这里前后有空格，所以不是纯引用
        result = parser.parse(" {{#llm_1.text#}} ", pool)
        assert result == " LLM 回答 "
        assert isinstance(result, str)

    def test_adjacent_references_treated_as_mixed(self, parser, pool):
        """相邻的多个引用视为混合文本。"""
        result = parser.parse("{{#llm_1.text#}}{{#llm_1.score#}}", pool)
        assert result == "LLM 回答95"
        assert isinstance(result, str)
