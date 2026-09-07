"""LangGraph RedisSaver 工厂（AsyncRedisSaver 统一承载 + 跨事件循环自适应）。

为 Agent 图执行提供基于 Redis 的 checkpoint 持久化能力
（对话状态保存、断点恢复、进程级崩溃续跑的基础设施）。

设计原则：
- 懒加载 + 模块级单例：避免每次请求重复创建 Redis 连接
- 异常降级：Redis 不可用或依赖缺失时返回 None（不启用持久化，Agent 照常执行）
- **AsyncRedisSaver 统一承载**：langgraph-checkpoint-redis 的 AsyncRedisSaver
  同时实现 async（aget_tuple/aput…）与 sync（get_tuple/put…）方法，可被
  ``astream``（事件循环内）与 ``stream``（子线程 + ``asyncio.run``）两条链路复用。

跨事件循环问题与解决：
    base_agent 同步链路（``stream``）每请求在子线程内 ``asyncio.run`` 新建事件
    循环；AsyncRedisSaver 底层 redis.asyncio 连接绑定首个事件循环，跨循环复用
    会抛 "Event loop is closed"。``LoopAwareAsyncRedisSaver`` 继承
    AsyncRedisSaver（天然是 BaseCheckpointSaver，可通过 graph.compile 类型校验），
    在每次读写前检测当前事件循环是否变化，变化则先断开旧连接池再 ``asetup()``
    重建，使单例 saver 可在任意线程/循环安全复用（已用真实 Redis 8 验证）。
"""
import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_async_redis_saver: Any = None
_async_redis_saver_attempted: bool = False

# 顶层 import AsyncRedisSaver 作为子类基类（仅当依赖可用时；缺失时整个
# get_async_checkpointer 在 try 内降级，但类定义需要基类存在——因此 import
# 放在函数内不可行，这里用 try 兜底，缺依赖时降级到最小基类不可用标记）。
try:
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver as _AsyncRedisSaverBase
except Exception:  # pragma: no cover - 依赖缺失时
    _AsyncRedisSaverBase = None  # type: ignore[assignment,misc]


def _redis_connection_args() -> dict[str, Any]:
    """从环境变量构造 Redis 连接参数（与 redis_extension 同源）。"""
    return {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", 6379) or 6379),
        "username": os.getenv("REDIS_USERNAME", None),
        "password": os.getenv("REDIS_PASSWORD", None),
        "db": int(os.getenv("REDIS_DB", 0) or 0),
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
        "health_check_interval": 30,
        "decode_responses": False,
    }


if _AsyncRedisSaverBase is not None:

    class LoopAwareAsyncRedisSaver(_AsyncRedisSaverBase):  # type: ignore[misc,valid-type]
        """AsyncRedisSaver 子类：checkpoint 读写前自适应当前事件循环。

        Agent 同步链路每个请求用独立 ``asyncio.run``（新事件循环），redis.asyncio
        连接绑定旧循环后在新循环复用会报 "Event loop is closed"。本子类在每次
        checkpoint 读写前比较当前 loop 与上次绑定的 loop，不一致则断开旧连接池
        并重新 ``asetup()``（幂等建索引），保证单例在跨线程/跨循环场景安全复用。
        """

        def __init__(self) -> None:
            connection_args = _redis_connection_args()
            connection_args.pop("decode_responses", None)
            import redis.asyncio as aioredis

            redis_client = aioredis.Redis(**connection_args)
            super().__init__(redis_client=redis_client)
            self._bound_loop_id: int | None = None

        async def _ensure_loop(self) -> None:
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                return
            if self._bound_loop_id == id(current):
                return
            redis_client = getattr(self, "_redis", None)
            if redis_client is not None:
                try:
                    pool = getattr(redis_client, "connection_pool", None)
                    if pool is not None:
                        await pool.disconnect()
                except Exception:
                    logger.debug("断开旧事件循环 Redis 连接池失败", exc_info=True)
            try:
                await self.asetup()
            except Exception:
                logger.debug("checkpoint asetup 重建失败（可能索引已存在）", exc_info=True)
            self._bound_loop_id = id(current)

        async def aget_tuple(self, config: Any) -> Any:
            await self._ensure_loop()
            return await super().aget_tuple(config)

        async def aput(self, *args: Any, **kwargs: Any) -> Any:
            await self._ensure_loop()
            return await super().aput(*args, **kwargs)

        async def aput_writes(self, *args: Any, **kwargs: Any) -> Any:
            await self._ensure_loop()
            return await super().aput_writes(*args, **kwargs)

        async def a_delete_thread(self, *args: Any, **kwargs: Any) -> Any:
            await self._ensure_loop()
            return await super().a_delete_thread(*args, **kwargs)

        def get_tuple(self, config: Any) -> Any:
            """同步读取 checkpoint（供 has_pending_checkpoint 等非事件循环上下文）。

            底层是 AsyncRedisSaver（连接绑定事件循环）。此处用独立 ``asyncio.run``
            一次性事件循环完成查询——避免跨循环复用；该路径非热路径（仅在执行
            开始/恢复判定时调用一两次），开销可接受。
            """
            return asyncio.run(self._async_get_tuple(config))

        async def _async_get_tuple(self, config: Any) -> Any:
            await self._ensure_loop()
            return await super().aget_tuple(config)

else:  # pragma: no cover - 依赖缺失
    LoopAwareAsyncRedisSaver = None  # type: ignore[assignment,misc]


def get_async_checkpointer() -> Any:
    """获取 LangGraph LoopAwareAsyncRedisSaver 单例（失败返回 None）。

    Redis 不可用/缺 RediSearch 时返回 None，Agent 照常执行（编译时不挂
    checkpointer，退化为无持久化）。这是全部执行链路（同步 stream 子线程 +
    异步 astream 事件循环）统一的 checkpoint 实现。
    """
    global _async_redis_saver, _async_redis_saver_attempted
    if _async_redis_saver_attempted:
        return _async_redis_saver
    _async_redis_saver_attempted = True
    try:
        _async_redis_saver = LoopAwareAsyncRedisSaver()
        logger.info("LangGraph LoopAwareAsyncRedisSaver 初始化成功（进程级 checkpoint 已启用，跨循环自适应）")
    except Exception:
        logger.warning("LangGraph AsyncRedisSaver 初始化失败，checkpoint 持久化未启用", exc_info=True)
        _async_redis_saver = None
    return _async_redis_saver


def get_sync_checkpointer() -> Any:
    """获取同步 RedisSaver 单例（兼容层）。

    说明：同步 RedisSaver 只提供同步方法，无法驱动 async 化节点（LangGraph
    同步 invoke 遇到 async 节点会报错），不适合本仓库「async 节点 + ainvoke」
    的执行形态。统一推荐 :func:`get_async_checkpointer`；本函数保留仅为兼容
    历史引用（等价返回 async checkpointer）。
    """
    return get_async_checkpointer()
