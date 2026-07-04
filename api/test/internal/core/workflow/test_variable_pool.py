"""VariablePool 单元测试。"""

from __future__ import annotations

import pytest

from internal.core.workflow.variable_pool import VariablePool


class TestVariablePoolSystemVariable:
    """系统变量相关测试。"""

    def test_set_and_get_system_variable(self):
        """设置和获取系统变量。"""
        pool = VariablePool()
        pool.set_system_variable("query", "你好")
        pool.set_system_variable("user_id", 123)

        assert pool.get_system_variable("query") == "你好"
        assert pool.get_system_variable("user_id") == 123

    def test_get_system_variable_returns_none_when_not_set(self):
        """未设置的系统变量返回 None。"""
        pool = VariablePool()
        assert pool.get_system_variable("not_exist") is None

    def test_set_system_variable_overwrites(self):
        """同一系统变量多次设置会覆盖。"""
        pool = VariablePool()
        pool.set_system_variable("query", "v1")
        pool.set_system_variable("query", "v2")

        assert pool.get_system_variable("query") == "v2"


class TestVariablePoolNodeOutput:
    """节点输出变量相关测试。"""

    def test_set_and_get_node_output_with_field(self):
        """设置和获取节点输出（含字段返回）。"""
        pool = VariablePool()
        pool.set_node_output("llm_1", {"text": "hello", "usage": 10})

        assert pool.get_node_output("llm_1", "text") == "hello"
        assert pool.get_node_output("llm_1", "usage") == 10

    def test_get_node_output_returns_whole_dict_when_field_none(self):
        """field 为 None 时返回整个输出 dict。"""
        pool = VariablePool()
        output = {"text": "hi", "tokens": 5}
        pool.set_node_output("start", output)

        result = pool.get_node_output("start")
        assert result == {"text": "hi", "tokens": 5}
        # 返回的是副本，修改不影响内部存储
        result["text"] = "changed"
        assert pool.get_node_output("start", "text") == "hi"

    def test_get_node_output_returns_none_when_node_not_set(self):
        """节点不存在时返回 None。"""
        pool = VariablePool()
        assert pool.get_node_output("missing_node") is None
        assert pool.get_node_output("missing_node", "field") is None

    def test_get_node_output_returns_none_when_field_not_exist(self):
        """字段不存在时返回 None。"""
        pool = VariablePool()
        pool.set_node_output("llm_1", {"text": "hi"})

        assert pool.get_node_output("llm_1", "missing_field") is None

    def test_set_node_output_overwrites(self):
        """同一 node_id 多次 set_node_output 会覆盖。"""
        pool = VariablePool()
        pool.set_node_output("llm_1", {"text": "v1"})
        pool.set_node_output("llm_1", {"text": "v2", "extra": True})

        assert pool.get_node_output("llm_1", "text") == "v2"
        assert pool.get_node_output("llm_1", "extra") is True


class TestVariablePoolConversationVariable:
    """会话变量相关测试。"""

    def test_set_and_get_conversation_variable(self):
        """设置和获取会话变量。"""
        pool = VariablePool()
        pool.set_conversation_variable("count", 1)
        pool.set_conversation_variable("name", "test")

        assert pool.get_conversation_variable("count") == 1
        assert pool.get_conversation_variable("name") == "test"

    def test_get_conversation_variable_returns_none_when_not_set(self):
        """未设置的会话变量返回 None。"""
        pool = VariablePool()
        assert pool.get_conversation_variable("not_exist") is None


class TestVariablePoolGetVariableRouting:
    """get_variable 路由测试。"""

    def test_get_variable_routes_to_system(self):
        """sys. 前缀路由到系统变量。"""
        pool = VariablePool()
        pool.set_system_variable("query", "用户输入")

        assert pool.get_variable("sys.query") == "用户输入"

    def test_get_variable_routes_to_conversation(self):
        """conversation. 前缀路由到会话变量。"""
        pool = VariablePool()
        pool.set_conversation_variable("count", 42)

        assert pool.get_variable("conversation.count") == 42

    def test_get_variable_routes_to_node_output(self):
        """无特殊前缀时路由到节点输出。"""
        pool = VariablePool()
        pool.set_node_output("llm_1", {"text": "回答"})

        assert pool.get_variable("llm_1.text") == "回答"

    def test_get_variable_returns_whole_node_output_without_field(self):
        """ref 仅含 node_id 时返回整个节点输出 dict。"""
        pool = VariablePool()
        pool.set_node_output("start", {"query": "hi", "user": "u1"})

        result = pool.get_variable("start")
        assert result == {"query": "hi", "user": "u1"}

    def test_get_variable_with_nested_field(self):
        """支持嵌套字段路径访问。"""
        pool = VariablePool()
        pool.set_node_output("llm_1", {
            "choices": [
                {"message": {"content": "嵌套内容"}},
                {"message": {"content": "第二项"}},
            ],
        })

        assert pool.get_variable("llm_1.choices[0].message.content") == "嵌套内容"
        assert pool.get_variable("llm_1.choices[1].message.content") == "第二项"

    def test_get_variable_with_array_index(self):
        """支持数组索引访问。"""
        pool = VariablePool()
        pool.set_node_output("data", {"items": ["a", "b", "c"]})

        assert pool.get_variable("data.items[0]") == "a"
        assert pool.get_variable("data.items[2]") == "c"

    def test_get_variable_returns_none_for_nonexistent_nested_field(self):
        """嵌套字段不存在时返回 None。"""
        pool = VariablePool()
        pool.set_node_output("llm_1", {"text": "hi"})

        assert pool.get_variable("llm_1.choices[0].message.content") is None
        assert pool.get_variable("llm_1.missing") is None

    def test_get_variable_returns_none_for_nonexistent_node(self):
        """节点不存在时返回 None。"""
        pool = VariablePool()
        assert pool.get_variable("missing_node.field") is None
        assert pool.get_variable("missing_node") is None

    def test_get_variable_returns_none_for_out_of_range_index(self):
        """数组索引越界时返回 None。"""
        pool = VariablePool()
        pool.set_node_output("data", {"items": ["a"]})

        assert pool.get_variable("data.items[5]") is None


class TestVariablePoolClearAndSerialize:
    """清理与序列化测试。"""

    def test_clear_node_outputs_preserves_system_and_conversation(self):
        """clear_node_outputs 只清除节点输出，保留系统/会话变量。"""
        pool = VariablePool()
        pool.set_system_variable("query", "q")
        pool.set_conversation_variable("count", 1)
        pool.set_node_output("llm_1", {"text": "hi"})
        pool.set_node_output("start", {"query": "input"})

        pool.clear_node_outputs()

        # 节点输出被清除
        assert pool.get_node_output("llm_1") is None
        assert pool.get_node_output("start") is None
        # 系统变量和会话变量保留
        assert pool.get_system_variable("query") == "q"
        assert pool.get_conversation_variable("count") == 1

    def test_to_dict_serializes_all_variables(self):
        """to_dict 序列化所有变量。"""
        pool = VariablePool()
        pool.set_system_variable("query", "q")
        pool.set_system_variable("user_id", 1)
        pool.set_conversation_variable("count", 5)
        pool.set_node_output("llm_1", {"text": "hi"})
        pool.set_node_output("start", {"query": "input"})

        result = pool.to_dict()

        assert result == {
            "system_variables": {"query": "q", "user_id": 1},
            "node_outputs": {
                "llm_1": {"text": "hi"},
                "start": {"query": "input"},
            },
            "conversation_variables": {"count": 5},
        }

    def test_to_dict_does_not_mutate_internal_state(self):
        """to_dict 返回的字典修改后不影响内部状态。"""
        pool = VariablePool()
        pool.set_node_output("llm_1", {"text": "hi"})

        result = pool.to_dict()
        result["node_outputs"]["llm_1"]["text"] = "changed"
        result["system_variables"]["injected"] = True

        assert pool.get_node_output("llm_1", "text") == "hi"
        assert pool.get_system_variable("injected") is None


class TestVariablePoolContains:
    """__contains__ 测试。"""

    def test_contains_system_variable(self):
        """检查系统变量是否存在。"""
        pool = VariablePool()
        pool.set_system_variable("query", "q")

        assert "sys.query" in pool
        assert "sys.user_id" not in pool

    def test_contains_conversation_variable(self):
        """检查会话变量是否存在。"""
        pool = VariablePool()
        pool.set_conversation_variable("count", 1)

        assert "conversation.count" in pool
        assert "conversation.name" not in pool

    def test_contains_node_output(self):
        """检查节点输出是否存在。"""
        pool = VariablePool()
        pool.set_node_output("llm_1", {"text": "hi"})

        assert "llm_1" in pool
        assert "llm_1.text" in pool
        assert "llm_1.missing" not in pool
        assert "missing_node" not in pool
        assert "missing_node.field" not in pool

    def test_contains_nested_field(self):
        """检查嵌套字段是否存在。"""
        pool = VariablePool()
        pool.set_node_output("llm_1", {"choices": [{"message": {"content": "x"}}]})

        assert "llm_1.choices[0].message.content" in pool
        assert "llm_1.choices[1].message.content" not in pool
        assert "llm_1.choices[0].missing" not in pool
