"""RetryExecutor 单元测试。

覆盖：
- 首次成功 / 重试后成功 / 全部失败
- retry_on_fail 关闭时只执行 1 次
- 返回正确的尝试次数
- 重试间隔被遵守（mock time.sleep）
- max_tries 上限
- 重试与最终失败时的日志输出
- retry_interval=0 时不 sleep
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from internal.core.workflow.entities.retry_entity import RetryConfig
from internal.core.workflow.utils.retry_executor import RetryExecutor


class TestRetryExecutor:
    """RetryExecutor 相关测试。"""

    def test_execute_success_first_try(self):
        """首次执行成功，attempts=1。"""
        config = RetryConfig(retry_on_fail=True, max_tries=3, retry_interval=0.1)
        func = MagicMock(return_value="ok")

        result, attempts = RetryExecutor.execute_with_retry(
            func, config, node_title="test_node"
        )

        assert result == "ok"
        assert attempts == 1
        assert func.call_count == 1

    def test_execute_success_after_retry(self):
        """首次失败，重试后成功。"""
        config = RetryConfig(retry_on_fail=True, max_tries=3, retry_interval=0.0)
        func = MagicMock(side_effect=[RuntimeError("fail_1"), "ok"])

        result, attempts = RetryExecutor.execute_with_retry(
            func, config, node_title="test_node"
        )

        assert result == "ok"
        assert attempts == 2
        assert func.call_count == 2

    def test_execute_all_retries_failed(self):
        """所有重试都失败时抛出最后一次异常。"""
        config = RetryConfig(retry_on_fail=True, max_tries=3, retry_interval=0.0)
        error = RuntimeError("always_fail")
        func = MagicMock(side_effect=[RuntimeError("fail_1"), RuntimeError("fail_2"), error])

        with pytest.raises(RuntimeError, match="always_fail"):
            RetryExecutor.execute_with_retry(func, config, node_title="test_node")

        assert func.call_count == 3

    def test_execute_no_retry_when_disabled(self):
        """retry_on_fail=False 时只执行 1 次（即使失败也不重试）。"""
        config = RetryConfig(retry_on_fail=False, max_tries=5, retry_interval=0.1)
        func = MagicMock(side_effect=RuntimeError("fail"))

        with pytest.raises(RuntimeError, match="fail"):
            RetryExecutor.execute_with_retry(func, config, node_title="test_node")

        assert func.call_count == 1

    def test_execute_returns_attempts(self):
        """返回正确的尝试次数（重试 2 次后成功 -> attempts=3）。"""
        config = RetryConfig(retry_on_fail=True, max_tries=5, retry_interval=0.0)
        func = MagicMock(side_effect=[RuntimeError("e1"), RuntimeError("e2"), "success"])

        result, attempts = RetryExecutor.execute_with_retry(
            func, config, node_title="test_node"
        )

        assert result == "success"
        assert attempts == 3

    @patch("internal.core.workflow.utils.retry_executor.time.sleep")
    def test_execute_retry_interval_respected(self, mock_sleep):
        """重试间隔被遵守，调用 time.sleep。"""
        config = RetryConfig(retry_on_fail=True, max_tries=3, retry_interval=1.5)
        func = MagicMock(side_effect=[RuntimeError("e1"), "ok"])

        RetryExecutor.execute_with_retry(func, config, node_title="test_node")

        # 应该被调用 1 次（首次失败后等待），参数为 retry_interval
        mock_sleep.assert_called_once_with(1.5)

    @patch("internal.core.workflow.utils.retry_executor.time.sleep")
    def test_execute_max_tries_respected(self, mock_sleep):
        """最多执行 max_tries 次。"""
        config = RetryConfig(retry_on_fail=True, max_tries=4, retry_interval=0.5)
        func = MagicMock(side_effect=RuntimeError("fail"))

        with pytest.raises(RuntimeError):
            RetryExecutor.execute_with_retry(func, config, node_title="test_node")

        assert func.call_count == 4
        # 失败 4 次但只重试 3 次，sleep 应调用 3 次
        assert mock_sleep.call_count == 3

    def test_execute_logs_warning_on_retry(self, caplog):
        """重试时记录 warning 日志。"""
        config = RetryConfig(retry_on_fail=True, max_tries=3, retry_interval=0.0)
        func = MagicMock(side_effect=[RuntimeError("fail_once"), "ok"])

        with caplog.at_level(logging.WARNING, logger="internal.core.workflow.utils.retry_executor"):
            RetryExecutor.execute_with_retry(func, config, node_title="my_node")

        # 应该有 warning 日志记录重试信息
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 1
        # 日志应包含节点标题与失败信息
        log_msg = warning_records[0].getMessage()
        assert "my_node" in log_msg
        assert "fail_once" in log_msg

    def test_execute_logs_error_on_final_failure(self, caplog):
        """所有重试都失败时记录 error 日志。"""
        config = RetryConfig(retry_on_fail=True, max_tries=2, retry_interval=0.0)
        func = MagicMock(side_effect=RuntimeError("final_fail"))

        with caplog.at_level(logging.ERROR, logger="internal.core.workflow.utils.retry_executor"):
            with pytest.raises(RuntimeError):
                RetryExecutor.execute_with_retry(func, config, node_title="err_node")

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) == 1
        log_msg = error_records[0].getMessage()
        assert "err_node" in log_msg
        assert "final_fail" in log_msg
        assert "最大尝试次数" in log_msg

    @patch("internal.core.workflow.utils.retry_executor.time.sleep")
    def test_execute_zero_interval_no_sleep(self, mock_sleep):
        """retry_interval=0 时不调用 time.sleep。"""
        config = RetryConfig(retry_on_fail=True, max_tries=3, retry_interval=0.0)
        func = MagicMock(side_effect=RuntimeError("fail"))

        with pytest.raises(RuntimeError):
            RetryExecutor.execute_with_retry(func, config, node_title="test_node")

        # retry_interval=0 时不应 sleep
        assert mock_sleep.call_count == 0

    def test_execute_logs_info_on_retry_success(self, caplog):
        """重试后成功时记录 info 日志。"""
        config = RetryConfig(retry_on_fail=True, max_tries=3, retry_interval=0.0)
        func = MagicMock(side_effect=[RuntimeError("e1"), "ok"])

        with caplog.at_level(logging.INFO, logger="internal.core.workflow.utils.retry_executor"):
            result, attempts = RetryExecutor.execute_with_retry(
                func, config, node_title="retry_node"
            )

        assert result == "ok"
        assert attempts == 2
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) == 1
        log_msg = info_records[0].getMessage()
        assert "retry_node" in log_msg
        assert "成功" in log_msg
