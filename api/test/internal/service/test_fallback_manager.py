from internal.service.fallback_manager import FallbackManager


class TestFallbackManager:
    def test_fallback_none_error_returns_single_agent_strategy(self):
        manager = FallbackManager()
        result = manager.fallback(None, context={"task": "x"})

        assert result["strategy"] == "single_agent"
        assert result["error_type"] == "None"
        assert result["context"] == {"task": "x"}

    def test_fallback_timeout_error_returns_single_agent_strategy(self):
        manager = FallbackManager()
        result = manager.fallback(TimeoutError("请求超时"))

        assert result["strategy"] == "single_agent"
        assert "超时" in result["reason"]
        assert result["error_type"] == "TimeoutError"

    def test_fallback_rate_limit_error_returns_direct_answer_strategy(self):
        manager = FallbackManager()
        result = manager.fallback(RuntimeError("rate limit exceeded 429"))

        assert result["strategy"] == "direct_answer"
        assert "限流" in result["reason"]
        assert result["error_type"] == "RuntimeError"

    def test_fallback_generic_error_returns_single_agent_strategy(self):
        manager = FallbackManager()
        result = manager.fallback(ValueError("参数错误"))

        assert result["strategy"] == "single_agent"
        assert result["error_type"] == "ValueError"
        assert "参数错误" in result["reason"]

    def test_should_retry_within_max_retries_returns_true(self):
        manager = FallbackManager(max_retries=3)
        assert manager.should_retry(0, RuntimeError("临时错误")) is True
        assert manager.should_retry(1, RuntimeError("临时错误")) is True
        assert manager.should_retry(2, RuntimeError("临时错误")) is True

    def test_should_retry_at_or_above_max_retries_returns_false(self):
        manager = FallbackManager(max_retries=3)
        assert manager.should_retry(3, RuntimeError("临时错误")) is False
        assert manager.should_retry(5, RuntimeError("临时错误")) is False

    def test_should_retry_returns_false_for_permanent_error(self):
        manager = FallbackManager(max_retries=3)
        assert manager.should_retry(0, PermissionError("forbidden")) is False
        assert manager.should_retry(0, RuntimeError("unauthorized access")) is False

    def test_should_retry_returns_false_for_negative_attempt(self):
        manager = FallbackManager(max_retries=3)
        assert manager.should_retry(-1, RuntimeError("x")) is False

    def test_should_retry_none_error_still_respects_max_retries(self):
        manager = FallbackManager(max_retries=2)
        assert manager.should_retry(0, None) is True
        assert manager.should_retry(1, None) is True
        assert manager.should_retry(2, None) is False

    def test_fallback_default_max_retries_is_three(self):
        manager = FallbackManager()
        assert manager.max_retries == 3
