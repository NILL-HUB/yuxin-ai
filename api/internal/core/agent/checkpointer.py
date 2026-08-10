"""LangGraph AsyncRedisSaver 工厂。

为 Agent 图执行提供基于 Redis 的 checkpoint 持久化能力
（对话状态保存、断点恢复、time travel 的基础设施）。

设计原则：
- 懒加载 + 模块级单例：避免每次请求重复创建 Redis 连接
- 异常降级：Redis 不可用或依赖缺失时返回 None（不启用持久化，Agent 照常执行）
"""
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_async_redis_saver: Any = None
_async_redis_saver_attempted: bool = False


def get_async_checkpointer() -> Any:
    """获取 LangGraph AsyncRedisSaver 单例（失败返回 None，不启用持久化）。

    Returns:
        AsyncRedisSaver 实例，或 None（Redis 不可用 / 依赖缺失时）
    """
    global _async_redis_saver, _async_redis_saver_attempted
    if _async_redis_saver_attempted:
        return _async_redis_saver
    _async_redis_saver_attempted = True
    try:
        import redis.asyncio as aioredis
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        connection_args = {
            "host": os.getenv("REDIS_HOST", "localhost"),
            "port": int(os.getenv("REDIS_PORT", 6379) or 6379),
            "username": os.getenv("REDIS_USERNAME", None),
            "password": os.getenv("REDIS_PASSWORD", None),
            "db": int(os.getenv("REDIS_DB", 0) or 0),
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            "health_check_interval": 30,
        }
        redis_client = aioredis.Redis(**connection_args)
        saver = AsyncRedisSaver(redis_client=redis_client)
        _async_redis_saver = saver
        logger.info("LangGraph AsyncRedisSaver 初始化成功（Redis checkpoint 持久化已启用）")
    except Exception:
        logger.warning("LangGraph AsyncRedisSaver 初始化失败，checkpoint 持久化未启用", exc_info=True)
        _async_redis_saver = None
    return _async_redis_saver
