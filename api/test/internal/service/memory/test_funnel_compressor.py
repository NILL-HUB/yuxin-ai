"""B5 FunnelCompressor 单元测试。"""

from datetime import datetime

import pytest

from internal.model.memory_models import RetrievalResult
from internal.service.memory.funnel_compressor import FunnelCompressor


def _make_result(content: str, score: float = 0.8) -> RetrievalResult:
    return RetrievalResult(
        memory_id=f"mem-{content[:8]}",
        content=content,
        score=score,
        source="vector",
    )


class TestFunnelCompressor:
    def test_compress_should_return_empty_when_no_candidates(self):
        """空候选列表应返回空字符串。"""
        compressor = FunnelCompressor()
        result = compressor.compress([], budget_tokens=2000)

        assert result == ""

    def test_compress_should_return_single_candidate_content(self):
        """单条候选应直接返回其内容（无需压缩）。"""
        compressor = FunnelCompressor()
        candidates = [_make_result("用户喜欢 Python 编程语言。")]

        result = compressor.compress(candidates, budget_tokens=2000)

        assert "Python" in result

    def test_compress_should_return_nonempty_for_multiple_candidates(self):
        """多候选拼接后应返回非空结果。"""
        compressor = FunnelCompressor()
        candidates = [
            _make_result(f"事实 {i}: " + "内容" * 50, score=0.9 - i * 0.1)
            for i in range(10)
        ]

        result = compressor.compress(candidates, budget_tokens=200)

        # 结果不应为空
        assert len(result) > 0
        assert "事实" in result

    def test_compress_should_handle_zero_budget(self):
        """budget_tokens=0 应降级返回空或最小结果。"""
        compressor = FunnelCompressor()
        candidates = [_make_result("测试内容")]

        result = compressor.compress(candidates, budget_tokens=0)

        # 不抛异常即可
        assert isinstance(result, str)
