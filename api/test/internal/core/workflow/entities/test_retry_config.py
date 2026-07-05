"""RetryConfig 实体单元测试。

覆盖：
- 默认配置
- 自定义配置
- max_tries 边界校验（最小值/超过 10/0 抛异常）
- retry_interval 边界校验（负数/超过 60）
- retry_count 属性（开启/关闭）
"""

from __future__ import annotations

import pytest

from internal.core.workflow.entities.retry_entity import RetryConfig
from internal.exception import ValidateErrorException


class TestRetryConfig:
    """RetryConfig 实体相关测试。"""

    def test_default_config(self):
        """默认配置：retry_on_fail=False, max_tries=3, retry_interval=1.0。"""
        config = RetryConfig()

        assert config.retry_on_fail is False
        assert config.max_tries == 3
        assert config.retry_interval == 1.0

    def test_custom_config(self):
        """自定义配置可正确赋值。"""
        config = RetryConfig(retry_on_fail=True, max_tries=5, retry_interval=2.5)

        assert config.retry_on_fail is True
        assert config.max_tries == 5
        assert config.retry_interval == 2.5

    def test_max_tries_minimum_1(self):
        """max_tries=1 是最小有效值。"""
        config = RetryConfig(max_tries=1)

        assert config.max_tries == 1

    def test_max_tries_zero_raises(self):
        """max_tries=0 抛 ValidateErrorException。"""
        with pytest.raises(ValidateErrorException, match="不能小于1"):
            RetryConfig(max_tries=0)

    def test_max_tries_negative_raises(self):
        """max_tries=-1 抛 ValidateErrorException。"""
        with pytest.raises(ValidateErrorException, match="不能小于1"):
            RetryConfig(max_tries=-1)

    def test_max_tries_exceeds_10_raises(self):
        """max_tries=11 抛 ValidateErrorException。"""
        with pytest.raises(ValidateErrorException, match="不能超过10"):
            RetryConfig(max_tries=11)

    def test_retry_interval_negative_raises(self):
        """retry_interval 为负数抛 ValidateErrorException。"""
        with pytest.raises(ValidateErrorException, match="不能为负数"):
            RetryConfig(retry_interval=-0.5)

    def test_retry_interval_exceeds_60_raises(self):
        """retry_interval 超过 60 抛 ValidateErrorException。"""
        with pytest.raises(ValidateErrorException, match="不能超过60秒"):
            RetryConfig(retry_interval=61)

    def test_retry_interval_zero_allowed(self):
        """retry_interval=0 是有效的（立即重试，不等待）。"""
        config = RetryConfig(retry_interval=0)

        assert config.retry_interval == 0

    def test_retry_interval_60_allowed(self):
        """retry_interval=60 是有效上限。"""
        config = RetryConfig(retry_interval=60)

        assert config.retry_interval == 60

    def test_retry_count_property_disabled(self):
        """retry_on_fail=False 时 retry_count=0。"""
        config = RetryConfig(retry_on_fail=False, max_tries=5)

        assert config.retry_count == 0

    def test_retry_count_property_enabled(self):
        """retry_on_fail=True 时 retry_count=max_tries-1。"""
        config = RetryConfig(retry_on_fail=True, max_tries=4)

        assert config.retry_count == 3

    def test_retry_count_property_when_max_tries_is_1(self):
        """retry_on_fail=True 且 max_tries=1 时 retry_count=0（不重试）。"""
        config = RetryConfig(retry_on_fail=True, max_tries=1)

        assert config.retry_count == 0
