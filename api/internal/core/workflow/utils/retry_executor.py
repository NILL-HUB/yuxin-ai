"""重试执行器工具模块。

根据 ``RetryConfig`` 执行带重试逻辑的函数，提供节点级失败重试能力。
执行流程：
1. 首次执行
2. 如果失败且 ``retry_on_fail=True``，等待 ``retry_interval`` 后重试
3. 重复直到成功或达到 ``max_tries``
4. 返回执行结果或抛出最后一次异常
"""

import logging
import time
from typing import Callable, TypeVar

from internal.core.workflow.entities.retry_entity import RetryConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryExecutor:
    """重试执行器，根据 RetryConfig 执行带重试的逻辑。

    执行流程：
    1. 首次执行
    2. 如果失败且 retry_on_fail=True，等待 retry_interval 后重试
    3. 重复直到成功或达到 max_tries
    4. 返回执行结果或抛出最后一次异常
    """

    @staticmethod
    def execute_with_retry(
        func: Callable[[], T],
        config: RetryConfig,
        node_title: str = "",
    ) -> tuple[T, int]:
        """执行带重试的函数。

        Args:
            func: 要执行的函数（无参数，返回任意类型）
            config: 重试配置
            node_title: 节点标题（用于日志）

        Returns:
            tuple: (执行结果, 实际尝试次数)

        Raises:
            最后一次执行的异常（如果所有重试都失败）
        """
        max_tries = config.max_tries if config.retry_on_fail else 1
        last_error: Exception | None = None
        attempts = 0

        for attempt in range(1, max_tries + 1):
            attempts = attempt
            try:
                result = func()
                if attempt > 1:
                    logger.info(
                        "节点[%s]第%d次尝试成功（重试了%d次）",
                        node_title, attempt, attempt - 1,
                    )
                return result, attempts
            except Exception as e:
                last_error = e
                if attempt < max_tries:
                    logger.warning(
                        "节点[%s]第%d次尝试失败: %s，%.1f秒后重试",
                        node_title, attempt, str(e), config.retry_interval,
                    )
                    if config.retry_interval > 0:
                        time.sleep(config.retry_interval)
                else:
                    logger.error(
                        "节点[%s]第%d次尝试失败（已达最大尝试次数）: %s",
                        node_title, attempt, str(e),
                    )

        raise last_error  # type: ignore
