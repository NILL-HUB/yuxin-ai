"""工具执行登记表：崩溃恢复时避免工具副作用重复执行。

背景与设计
----------
进程级 checkpoint（LangGraph RedisSaver）在图节点**完成后**保存状态。若进程在
``tools_node`` 内部执行工具期间崩溃（工具副作用已发生但节点未完成），恢复后
LangGraph 会重放整个 ``tools_node``——已执行的工具会被再次调用，造成副作用重复。

本模块提供「工具调用登记表」：工具执行**前**登记 ``running``，执行**后**登记
``done + 结果``。恢复后 ``tools_node`` 重跑时先查登记表：

- ``done``：跳过执行，直接重放已登记的结果（工具不重复执行，结果完整保留）；
- ``running`` / ``unknown``（崩溃残留）：不执行，向 LLM 返回「该工具调用已发起但
  进程中断、结果未知」的 ToolMessage，由 LLM 判断是否需要核实或重新执行；
- 无记录：正常执行（先登记 running，执行后更新 done+result）。

登记表命名空间使用**稳定 thread_id**（checkpoint 维度，跨崩溃稳定），而不是
task_id（恢复时是新生成的）。

TTL：与 AgentQueueManager 事件 TTL 对齐（24h），防止孤儿 key 堆积。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_KEY_PREFIX = "agent_tool_registry:"
_TTL_SECONDS = 24 * 60 * 60

STATUS_RUNNING = "running"
STATUS_DONE = "done"


def _key(thread_id: str) -> str:
    return f"{_KEY_PREFIX}{thread_id}"


def mark_running(redis_client: Any, thread_id: str, tool_call_id: str, tool_name: str, args: Any) -> None:
    """工具执行前登记 running（best-effort，绝不阻断执行）。"""
    if redis_client is None or not thread_id:
        return
    try:
        payload = json.dumps(
            {
                "status": STATUS_RUNNING,
                "tool_name": tool_name,
                "args": args if isinstance(args, (dict, list)) else {},
                "ts": time.time(),
            },
            ensure_ascii=False,
            default=str,
        )
        redis_client.hset(_key(thread_id), tool_call_id, payload)
        redis_client.expire(_key(thread_id), _TTL_SECONDS)
    except Exception:
        logger.warning("登记工具执行 running 失败 tool_call_id=%s", tool_call_id, exc_info=True)


def mark_done(redis_client: Any, thread_id: str, tool_call_id: str, tool_name: str, result: Any) -> None:
    """工具执行完成后登记 done + 结果（best-effort，绝不阻断执行）。"""
    if redis_client is None or not thread_id:
        return
    try:
        payload = json.dumps(
            {
                "status": STATUS_DONE,
                "tool_name": tool_name,
                "result": result,
                "ts": time.time(),
            },
            ensure_ascii=False,
            default=str,
        )
        redis_client.hset(_key(thread_id), tool_call_id, payload)
        redis_client.expire(_key(thread_id), _TTL_SECONDS)
    except Exception:
        logger.warning("登记工具执行 done 失败 tool_call_id=%s", tool_call_id, exc_info=True)


def get_status(redis_client: Any, thread_id: str, tool_call_id: str) -> dict[str, Any] | None:
    """查询单个 tool_call 的登记状态；无记录返回 None。"""
    if redis_client is None or not thread_id:
        return None
    try:
        raw = redis_client.hget(_key(thread_id), tool_call_id)
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        logger.warning("查询工具登记状态失败 tool_call_id=%s", tool_call_id, exc_info=True)
        return None


def mark_unknown(redis_client: Any, thread_id: str, tool_call_id: str, tool_name: str) -> None:
    """崩溃恢复时把 running 残留标记为 unknown（结果未知，交由 LLM 核实）。"""
    if redis_client is None or not thread_id:
        return
    try:
        payload = json.dumps(
            {
                "status": "unknown",
                "tool_name": tool_name,
                "ts": time.time(),
            },
            ensure_ascii=False,
            default=str,
        )
        redis_client.hset(_key(thread_id), tool_call_id, payload)
        redis_client.expire(_key(thread_id), _TTL_SECONDS)
    except Exception:
        logger.warning("标记工具登记 unknown 失败 tool_call_id=%s", tool_call_id, exc_info=True)


def cleanup_thread(redis_client: Any, thread_id: str) -> None:
    """清理某 thread 的全部登记（任务正常结束后调用，释放 Redis 内存）。"""
    if redis_client is None or not thread_id:
        return
    try:
        redis_client.delete(_key(thread_id))
    except Exception:
        logger.debug("清理工具登记表失败 thread_id=%s", thread_id, exc_info=True)
