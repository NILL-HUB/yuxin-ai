"""ToolSelectorService 单元测试：关键词快通道 + LLM 兜底。

测试覆盖：
1. Pass 1: task_keywords 精确包含匹配（最高优先级）
2. Pass 2: tool_name 直接出现（次优先级）
3. Pass 3: description 子串匹配（最低优先级）
4. 三层优先级 + 跨 pass 去重
5. LLM 兜底（无关键词命中 / 关键词命中不足时补充）
6. LLM 不可用时的降级
7. 边界条件（短查询、空候选、max_tools 限制等）
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from internal.service.tool_selector_service import ToolSelectorService


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------

def _make_candidate(
    *,
    source_type: str = "builtin",
    name: str = "current_time",
    provider_id: str = "time",
    description: str = "Get current system time",
    task_keywords: list[str] | None = None,
) -> dict:
    """构造一个候选工具 dict（字段名遵循 ToolCandidateCollector 输出格式）。

    注意: ToolSelectorService._normalize_candidates 读取 "name" 字段并写入 "tool_name"。
    """
    return {
        "source_type": source_type,
        "name": name,
        "provider_id": provider_id,
        "provider_name": provider_id,
        "description": description,
        "task_keywords": task_keywords or [],
    }


def _build_service(*, language_model_service=None, builtin_tool_service=None):
    """直接构造 ToolSelectorService，绕过 @inject。"""
    return ToolSelectorService(
        builtin_tool_service=builtin_tool_service,
        language_model_service=language_model_service,
    )


# ---------------------------------------------------------------------------
# Pass 1: task_keywords 精确包含匹配
# ---------------------------------------------------------------------------

class TestPass1TaskKeywords:
    """测试第一层：task_keywords 关键词匹配。"""

    def test_task_keyword_hit_returns_keyword_match_type(self):
        """task_keywords 命中时 match_type 应为 "keyword"。"""
        svc = _build_service()
        candidates = [
            _make_candidate(
                name="current_time",
                task_keywords=["时间", "几点", "current_time"],
            ),
        ]
        result = svc.select_tools("现在几点了", candidates=candidates, max_tools=3)
        assert len(result) == 1
        assert result[0]["tool_name"] == "current_time"
        assert result[0]["match_type"] == "keyword"
        assert "keyword_hit" in result[0]["reason"]

    def test_multiple_task_keyword_hits(self):
        """多个工具同时命中 task_keywords。"""
        svc = _build_service()
        candidates = [
            _make_candidate(name="current_time", task_keywords=["时间"]),
            _make_candidate(
                name="weather_forecast",
                provider_id="weather",
                description="Get weather forecast",
                task_keywords=["时间"],  # 故意用相同关键词测试多命中
            ),
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=5)
        assert len(result) == 2
        assert all(r["match_type"] == "keyword" for r in result)

    def test_short_keyword_below_min_length_skipped(self):
        """长度 < 2 的关键词应被跳过。"""
        svc = _build_service()
        candidates = [
            _make_candidate(name="current_time", task_keywords=["时"]),  # 单字，太短
        ]
        # 查询长度 >= 4，但关键词太短，应走 LLM（LLM 不可用则返回空）
        result = svc.select_tools("现在几点了时间", candidates=candidates, max_tools=3)
        assert result == []

    def test_empty_task_keywords_list_skipped(self):
        """空 task_keywords 列表应被跳过。"""
        svc = _build_service()
        candidates = [
            _make_candidate(name="current_time", task_keywords=[]),
        ]
        result = svc.select_tools("现在几点了时间查询", candidates=candidates, max_tools=3)
        assert result == []

    def test_task_keyword_case_insensitive(self):
        """英文关键词应不区分大小写。"""
        svc = _build_service()
        candidates = [
            _make_candidate(
                name="web_search",
                provider_id="search",
                description="Search the web",
                task_keywords=["SEARCH", "搜索"],
            ),
        ]
        result = svc.select_tools("帮我search一下", candidates=candidates, max_tools=3)
        assert len(result) == 1
        assert result[0]["tool_name"] == "web_search"

    def test_early_return_when_keyword_hits_reach_max(self):
        """关键词命中达到 max_tools 时应提前返回，不调用 LLM。"""
        mock_lms = MagicMock()
        svc = _build_service(language_model_service=mock_lms)
        candidates = [
            _make_candidate(name="tool_a", task_keywords=["时间"]),
            _make_candidate(name="tool_b", task_keywords=["时间"]),
            _make_candidate(name="tool_c", task_keywords=["时间"]),
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=2)
        assert len(result) == 2
        # LLM 不应被调用
        mock_lms.get_feature_model.assert_not_called()


# ---------------------------------------------------------------------------
# Pass 2: tool_name 直接出现
# ---------------------------------------------------------------------------

class TestPass2ToolName:
    """测试第二层：tool_name 直接出现在查询中。"""

    def test_tool_name_appears_in_query(self):
        """tool_name（长度 >= 4）出现在查询中应命中。"""
        svc = _build_service()
        candidates = [
            _make_candidate(
                name="current_time",
                task_keywords=[],  # 无 task_keywords，强制走 Pass 2
            ),
        ]
        # "current_time" 出现在查询中
        result = svc.select_tools("请用 current_time 获取时间", candidates=candidates, max_tools=3)
        assert len(result) == 1
        assert result[0]["tool_name"] == "current_time"
        assert result[0]["match_type"] == "keyword"
        assert "tool_name_hit" in result[0]["reason"]

    def test_short_tool_name_below_min_length_skipped(self):
        """tool_name 长度 < 4 应被跳过。"""
        svc = _build_service()
        candidates = [
            _make_candidate(name="abc", task_keywords=[]),  # 3 字符，太短
        ]
        result = svc.select_tools("请用 abc 工具", candidates=candidates, max_tools=3)
        assert result == []

    def test_pass1_takes_priority_over_pass2(self):
        """Pass 1 命中应优先于 Pass 2，且不重复命中同一工具。"""
        svc = _build_service()
        candidates = [
            _make_candidate(
                name="current_time",
                task_keywords=["时间"],  # Pass 1 会命中
            ),
        ]
        result = svc.select_tools("current_time 时间", candidates=candidates, max_tools=3)
        # 只应命中一次（跨 pass 去重）
        assert len(result) == 1
        assert result[0]["reason"].startswith("keyword_hit:")


# ---------------------------------------------------------------------------
# Pass 3: description 子串匹配
# ---------------------------------------------------------------------------

class TestPass3DescriptionSubstring:
    """测试第三层：description 子串匹配。"""

    def test_description_substring_hit(self):
        """查询前 12 字符出现在 description 中应命中。

        Pass 3 逻辑: match_window = query[:12]，检查 match_window in desc。
        所以 description 必须包含 match_window 作为子串。
        """
        svc = _build_service()
        candidates = [
            _make_candidate(
                name="translate_tool",
                provider_id="translate",
                description="翻译文本内容查询翻译多语言工具",
                task_keywords=[],
            ),
        ]
        # 查询前 12 字符 = "翻译文本内容查询翻译多语"，是 description 的子串
        result = svc.select_tools("翻译文本内容查询翻译多语言工具怎么用", candidates=candidates, max_tools=3)
        assert len(result) == 1
        assert result[0]["tool_name"] == "translate_tool"
        assert result[0]["match_type"] == "keyword"
        assert result[0]["reason"] == "description_substring_hit"

    def test_short_query_skips_pass3(self):
        """查询长度 < 6 应跳过 Pass 3（但仍可走 Pass 1/2）。"""
        svc = _build_service()
        candidates = [
            _make_candidate(
                name="test_tool",
                description="abc",
                task_keywords=[],
            ),
        ]
        # 查询 "abcde" 长度 5 < 6，Pass 3 被跳过；tool_name "test_tool" 未出现
        result = svc.select_tools("abcde", candidates=candidates, max_tools=3)
        assert result == []


# ---------------------------------------------------------------------------
# 跨 pass 去重 + 优先级
# ---------------------------------------------------------------------------

class TestCrossPassDedup:
    """测试跨 pass 去重和优先级。"""

    def test_same_tool_not_hit_twice_across_passes(self):
        """同一工具在多个 pass 中命中只应出现一次。"""
        svc = _build_service()
        candidates = [
            _make_candidate(
                name="current_time",
                task_keywords=["时间"],  # Pass 1 命中
                description="current_time 时间工具",  # Pass 2/3 也会命中
            ),
        ]
        result = svc.select_tools("current_time 时间", candidates=candidates, max_tools=3)
        assert len(result) == 1

    def test_pass1_priority_over_pass2(self):
        """当 Pass 1 和 Pass 2 都能命中不同工具时，reason 应反映各自 pass。"""
        svc = _build_service()
        candidates = [
            _make_candidate(name="tool_a", task_keywords=["时间"]),
            _make_candidate(
                name="current_time",
                task_keywords=[],  # 无 task_keywords
            ),
        ]
        result = svc.select_tools("时间 current_time", candidates=candidates, max_tools=3)
        assert len(result) == 2
        reasons = {r["reason"] for r in result}
        assert any(r.startswith("keyword_hit:") for r in reasons)
        assert any(r.startswith("tool_name_hit:") for r in reasons)


# ---------------------------------------------------------------------------
# 边界条件
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """测试边界条件。"""

    def test_empty_query_returns_empty(self):
        """空查询应返回空列表。"""
        svc = _build_service()
        result = svc.select_tools("", candidates=[], max_tools=3)
        assert result == []

    def test_whitespace_only_query_returns_empty(self):
        """纯空格查询应返回空列表。"""
        svc = _build_service()
        result = svc.select_tools("   ", candidates=[], max_tools=3)
        assert result == []

    def test_short_query_below_min_length_skips_keyword_matching(self):
        """查询长度 < 4 应跳过关键词匹配（直接走 LLM 兜底）。"""
        mock_lms = MagicMock()
        mock_lms.get_feature_model.return_value = None
        mock_lms.get_cheap_chat_model.return_value = None
        svc = _build_service(language_model_service=mock_lms)
        candidates = [
            _make_candidate(name="current_time", task_keywords=["时间"]),
        ]
        # 查询 "时间" 长度 2 < 4，关键词匹配被跳过
        result = svc.select_tools("时间", candidates=candidates, max_tools=3)
        # LLM 不可用 → 空结果
        assert result == []

    def test_empty_candidates_returns_empty(self):
        """空候选列表应返回空。"""
        svc = _build_service()
        result = svc.select_tools("现在几点了", candidates=[], max_tools=3)
        assert result == []

    def test_max_tools_limits_result_count(self):
        """max_tools 应限制返回数量。"""
        svc = _build_service()
        candidates = [
            _make_candidate(name=f"tool_{i}", task_keywords=["时间"])
            for i in range(10)
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=2)
        assert len(result) <= 2

    def test_candidates_with_empty_source_type_filtered(self):
        """source_type 为空的候选应被过滤。"""
        svc = _build_service()
        candidates = [
            {
                "source_type": "",  # 空，应被过滤
                "name": "tool_a",
                "provider_id": "prov",
                "description": "desc",
                "task_keywords": ["时间"],
            },
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=3)
        assert result == []


# ---------------------------------------------------------------------------
# LLM 兜底
# ---------------------------------------------------------------------------

class TestLLMFallback:
    """测试 LLM 兜底逻辑。"""

    def test_llm_called_when_no_keyword_hits(self):
        """无关键词命中时应调用 LLM。"""
        mock_lms = MagicMock()
        mock_llm = MagicMock()
        mock_lms.get_feature_model.return_value = mock_llm
        mock_lms.invoke_messages_with_probe.return_value = (
            '[{"source_type":"builtin","provider_id":"time","tool_name":"current_time","reason":"llm selected"}]'
        )
        svc = _build_service(language_model_service=mock_lms)
        candidates = [
            _make_candidate(name="current_time", task_keywords=[]),  # 无关键词
        ]
        result = svc.select_tools("帮我查时间", candidates=candidates, max_tools=3)
        mock_lms.get_feature_model.assert_called_once_with("tool_selection")
        mock_lms.invoke_messages_with_probe.assert_called_once()
        assert len(result) == 1
        assert result[0]["tool_name"] == "current_time"
        assert result[0]["match_type"] == "llm"

    def test_llm_supplements_when_keyword_hits_below_max(self):
        """关键词命中不足 max_tools 时 LLM 补充。"""
        mock_lms = MagicMock()
        mock_llm = MagicMock()
        mock_lms.get_feature_model.return_value = mock_llm
        mock_lms.invoke_messages_with_probe.return_value = (
            '[{"source_type":"builtin","provider_id":"weather","tool_name":"forecast","reason":"llm"}]'
        )
        svc = _build_service(language_model_service=mock_lms)
        candidates = [
            _make_candidate(name="current_time", task_keywords=["时间"]),
            _make_candidate(
                name="forecast",
                provider_id="weather",
                description="weather forecast",
                task_keywords=[],  # 无关键词，走 LLM
            ),
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=3)
        assert len(result) == 2
        match_types = {r["match_type"] for r in result}
        assert "keyword" in match_types
        assert "llm" in match_types

    def test_llm_excludes_already_keyword_matched(self):
        """LLM 兜底应排除已关键词命中的工具。"""
        mock_lms = MagicMock()
        mock_llm = MagicMock()
        mock_lms.get_feature_model.return_value = mock_llm
        mock_lms.invoke_messages_with_probe.return_value = "[]"
        svc = _build_service(language_model_service=mock_lms)
        candidates = [
            _make_candidate(name="current_time", task_keywords=["时间"]),
            _make_candidate(name="other_tool", task_keywords=["时间"]),
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=3)
        # 两个都命中关键词，LLM 被调用但返回空
        assert len(result) == 2
        assert all(r["match_type"] == "keyword" for r in result)

    def test_llm_unavailable_returns_keyword_only(self):
        """LLM 不可用时只返回关键词命中。"""
        mock_lms = MagicMock()
        mock_lms.get_feature_model.return_value = None
        mock_lms.get_cheap_chat_model.return_value = None
        svc = _build_service(language_model_service=mock_lms)
        candidates = [
            _make_candidate(name="current_time", task_keywords=["时间"]),
            _make_candidate(name="other_tool", task_keywords=[]),
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=3)
        assert len(result) == 1
        assert result[0]["match_type"] == "keyword"

    def test_llm_fabricated_tool_filtered_out(self):
        """LLM 返回的不在候选列表中的工具应被过滤。"""
        mock_lms = MagicMock()
        mock_llm = MagicMock()
        mock_lms.get_feature_model.return_value = mock_llm
        mock_lms.invoke_messages_with_probe.return_value = (
            '[{"source_type":"builtin","provider_id":"fake","tool_name":"nonexistent","reason":"fake"}]'
        )
        svc = _build_service(language_model_service=mock_lms)
        candidates = [
            _make_candidate(name="current_time", task_keywords=["时间"]),
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=3)
        # 关键词命中 current_time，LLM 返回的 fake 工具不在候选中 → 被过滤
        tool_names = {r["tool_name"] for r in result}
        assert "nonexistent" not in tool_names
        assert "current_time" in tool_names

    def test_llm_malformed_json_returns_empty(self):
        """LLM 返回格式错误的 JSON 应返回空（从 LLM 路径）。"""
        mock_lms = MagicMock()
        mock_llm = MagicMock()
        mock_lms.get_feature_model.return_value = mock_llm
        mock_lms.invoke_messages_with_probe.return_value = "not valid json at all"
        svc = _build_service(language_model_service=mock_lms)
        candidates = [
            _make_candidate(name="current_time", task_keywords=[]),
        ]
        result = svc.select_tools("帮我查时间", candidates=candidates, max_tools=3)
        assert result == []

    def test_no_language_model_service_returns_keyword_only(self):
        """language_model_service 为 None 时只返回关键词命中。"""
        svc = _build_service(language_model_service=None)
        candidates = [
            _make_candidate(name="current_time", task_keywords=["时间"]),
            _make_candidate(name="other_tool", task_keywords=[]),
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=3)
        assert len(result) == 1
        assert result[0]["match_type"] == "keyword"

    def test_llm_exception_returns_keyword_only(self):
        """LLM 调用异常时应返回关键词命中（不崩溃）。"""
        mock_lms = MagicMock()
        mock_llm = MagicMock()
        mock_lms.get_feature_model.return_value = mock_llm
        mock_lms.invoke_messages_with_probe.side_effect = RuntimeError("LLM timeout")
        svc = _build_service(language_model_service=mock_lms)
        candidates = [
            _make_candidate(name="current_time", task_keywords=["时间"]),
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=3)
        assert len(result) == 1
        assert result[0]["match_type"] == "keyword"


# ---------------------------------------------------------------------------
# candidates=None 自动收集
# ---------------------------------------------------------------------------

class TestAutoCollectBuiltin:
    """测试 candidates=None 时自动收集 builtin 工具。"""

    def test_auto_collect_uses_builtin_tool_service(self):
        """candidates=None 时应调用 builtin_tool_service.get_builtin_tools()。"""
        mock_builtin = MagicMock()
        mock_builtin.get_builtin_tools.return_value = [
            {
                "name": "time",
                "label": "Time Provider",
                "tools": [
                    {
                        "name": "current_time",
                        "description": "Get current time",
                        "task_keywords": ["时间", "几点"],
                    }
                ],
            }
        ]
        svc = _build_service(builtin_tool_service=mock_builtin)
        result = svc.select_tools("现在几点了", candidates=None, max_tools=3)
        mock_builtin.get_builtin_tools.assert_called_once()
        assert len(result) >= 1
        assert result[0]["tool_name"] == "current_time"
        assert result[0]["match_type"] == "keyword"

    def test_auto_collect_no_builtin_service_returns_empty(self):
        """builtin_tool_service 为 None 且 candidates=None 时返回空。"""
        svc = _build_service(builtin_tool_service=None)
        result = svc.select_tools("现在几点了", candidates=None, max_tools=3)
        assert result == []

    def test_auto_collect_empty_builtin_returns_empty(self):
        """builtin_tool_service 返回空列表时返回空。"""
        mock_builtin = MagicMock()
        mock_builtin.get_builtin_tools.return_value = []
        svc = _build_service(builtin_tool_service=mock_builtin)
        result = svc.select_tools("现在几点了", candidates=None, max_tools=3)
        assert result == []


# ---------------------------------------------------------------------------
# 集成场景：多 source_type
# ---------------------------------------------------------------------------

class TestMultiSourceType:
    """测试多 source_type 候选混合匹配。"""

    def test_mixed_sources_all_match_by_keyword(self):
        """builtin/api/mcp/skill/workflow 候选都应支持关键词匹配。

        注意: _MAX_KEYWORD_HITS = 3 限制了关键词匹配最多返回 3 个结果，
        所以用 max_tools=3 测试 3 个 source_type。
        """
        svc = _build_service()
        candidates = [
            _make_candidate(
                source_type="builtin",
                name="builtin_time",
                provider_id="time",
                task_keywords=["时间"],
            ),
            _make_candidate(
                source_type="api",
                name="api_time",
                provider_id="api_time",
                task_keywords=["时间"],
            ),
            _make_candidate(
                source_type="mcp",
                name="mcp_time",
                provider_id="mcp_time",
                task_keywords=["时间"],
            ),
        ]
        result = svc.select_tools("时间查询", candidates=candidates, max_tools=3)
        assert len(result) == 3
        source_types = {r["source_type"] for r in result}
        assert source_types == {"builtin", "api", "mcp"}

    def test_no_match_returns_empty_with_llm_unavailable(self):
        """无匹配且 LLM 不可用时返回空。"""
        svc = _build_service()
        candidates = [
            _make_candidate(name="current_time", task_keywords=["时间"]),
        ]
        # 查询不含任何关键词
        result = svc.select_tools("你好世界", candidates=candidates, max_tools=3)
        assert result == []
