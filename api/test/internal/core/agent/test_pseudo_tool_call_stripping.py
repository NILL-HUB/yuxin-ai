# api/test/internal/core/agent/test_pseudo_tool_call_stripping.py
"""伪工具调用标签剥离测试。

覆盖历史故障：模型未真正绑定工具却按 prompt 编造 XML 工具调用，
导致 `<search_knowledge_base>...</search_knowledge_base>` 泄漏到用户可见回复。
"""
from internal.core.agent.entities.agent_text_sanitizer import (
    PseudoToolCallStreamFilter,
    strip_pseudo_tool_call_markup,
)

TOOL_NAMES = ["search_knowledge_base", "dataset_retrieval", "web_search"]


class TestStripPseudoToolCallMarkup:
    def test_strip_whole_block(self):
        text = "<search_knowledge_base>\n<query>jev模型</query>\n</search_knowledge_base>"
        assert strip_pseudo_tool_call_markup(text, TOOL_NAMES) == ""

    def test_strip_keeps_surrounding_text(self):
        text = "好的<search_knowledge_base><query>x</query></search_knowledge_base>，我来查"
        assert strip_pseudo_tool_call_markup(text, TOOL_NAMES) == "好的，我来查"

    def test_strip_multiple_blocks(self):
        text = (
            "<search_knowledge_base><query>a</query></search_knowledge_base>"
            "中间"
            "<dataset_retrieval><query>b</query></dataset_retrieval>"
        )
        assert strip_pseudo_tool_call_markup(text, TOOL_NAMES) == "中间"

    def test_strip_generic_tags(self):
        text = "前<tool_call><invoke>xx</invoke></tool_call>后"
        assert strip_pseudo_tool_call_markup(text, TOOL_NAMES) == "前后"

    def test_non_tool_tags_preserved(self):
        text = "使用 <div> 标签与 <query> 关键字，以及 x < 3 的判断"
        assert strip_pseudo_tool_call_markup(text, TOOL_NAMES) == text

    def test_unclosed_known_tag_dropped_tail(self):
        text = "答案<search_knowledge_base><query>未闭合"
        assert strip_pseudo_tool_call_markup(text, TOOL_NAMES) == "答案"


class TestPseudoToolCallStreamFilter:
    def test_cross_chunk_block_removed(self):
        f = PseudoToolCallStreamFilter(TOOL_NAMES)
        chunks = ["<", "search", "_knowledge_base>", "<query>", "jev模型</query>", "</search_knowledge", "_base>"]
        emitted = "".join(f.feed(c) for c in chunks) + f.flush()
        assert emitted == ""

    def test_plain_text_passthrough(self):
        f = PseudoToolCallStreamFilter(TOOL_NAMES)
        out = f.feed("北京") + f.feed("今天天气") + f.flush()
        assert out == "北京今天天气"

    def test_partial_angle_not_tag_is_preserved(self):
        f = PseudoToolCallStreamFilter(TOOL_NAMES)
        out = f.feed("x <") + f.feed("3") + f.flush()
        assert out == "x <3"

    def test_text_before_block_is_emitted(self):
        f = PseudoToolCallStreamFilter(TOOL_NAMES)
        out = f.feed("结论：") + f.feed("<search_") + f.feed("knowledge_base><query>q</query></search_knowledge_base>") + f.flush()
        assert out == "结论："
