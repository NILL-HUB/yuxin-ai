import logging

logger = logging.getLogger(__name__)


class FallbackManager:
    def __init__(self, max_retries=3):
        self.max_retries = max_retries

    def fallback(self, error, context=None):
        try:
            error_type = type(error).__name__ if error is not None else "None"
            error_message = str(error) if error is not None else ""

            if error is None:
                return {
                    "strategy": "single_agent",
                    "reason": "无错误信息，降级为单智能体执行",
                    "error_type": error_type,
                    "context": context,
                }

            if self._is_rate_limit_error(error):
                return {
                    "strategy": "direct_answer",
                    "reason": f"触发限流，降级为直接回答: {error_message}",
                    "error_type": error_type,
                    "context": context,
                }

            if self._is_timeout_error(error):
                return {
                    "strategy": "single_agent",
                    "reason": f"执行超时，降级为单智能体执行: {error_message}",
                    "error_type": error_type,
                    "context": context,
                }

            return {
                "strategy": "single_agent",
                "reason": f"执行异常，降级为单智能体执行: {error_message}",
                "error_type": error_type,
                "context": context,
            }
        except Exception as e:
            logger.warning("FallbackManager fallback 失败: %s", e, exc_info=True)
            return {
                "strategy": "single_agent",
                "reason": "降级策略计算失败，默认单智能体执行",
                "error_type": "FallbackError",
                "context": context,
            }

    def should_retry(self, attempt, error):
        try:
            if attempt < 0:
                return False
            if attempt >= self.max_retries:
                return False
            if error is not None and self._is_permanent_error(error):
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def _is_timeout_error(error):
        name = type(error).__name__.lower()
        message = str(error).lower()
        return "timeout" in name or "timeout" in message

    @staticmethod
    def _is_rate_limit_error(error):
        name = type(error).__name__.lower()
        message = str(error).lower()
        return "rate" in name or "429" in message

    @staticmethod
    def _is_permanent_error(error):
        name = type(error).__name__.lower()
        message = str(error).lower()
        return (
            "auth" in name
            or "permission" in name
            or "unauthorized" in message
            or "forbidden" in message
        )
