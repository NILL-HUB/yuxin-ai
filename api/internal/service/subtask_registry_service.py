"""子任务执行状态注册表。

让多 Agent 执行过程中的子任务状态可被实时查询（生命周期 API 后端），
对齐 Hermes 的 “/agents 实时子任务状态”。Redis 优先（每个子任务独立 key，
避免多 worker 读改写竞争），Redis 不可用时进程内兜底，带 TTL 清理。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from injector import inject
from redis import Redis

logger = logging.getLogger(__name__)


@dataclass
class SubtaskStatus:
    task_id: str
    title: str
    agent_pool: str = "general"
    status: str = "pending"  # pending / running / completed / failed
    depends_on: list[str] = field(default_factory=list)
    execution_order: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    answer_preview: str = ""
    errors: list[str] = field(default_factory=list)
    timeout_seconds: float = 0.0
    last_activity_at: float = 0.0
    stall_warning: bool = False
    timed_out: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubtaskStatus":
        return cls(
            task_id=str(data.get("task_id") or ""),
            title=str(data.get("title") or ""),
            agent_pool=str(data.get("agent_pool") or "general"),
            status=str(data.get("status") or "pending"),
            depends_on=list(data.get("depends_on") or []),
            execution_order=int(data.get("execution_order") or 0),
            started_at=float(data.get("started_at") or 0),
            finished_at=float(data.get("finished_at") or 0),
            answer_preview=str(data.get("answer_preview") or ""),
            errors=list(data.get("errors") or []),
            timeout_seconds=float(data.get("timeout_seconds") or 0),
            last_activity_at=float(data.get("last_activity_at") or 0),
            stall_warning=bool(data.get("stall_warning")),
            timed_out=bool(data.get("timed_out")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "agent_pool": self.agent_pool,
            "status": self.status,
            "depends_on": self.depends_on,
            "execution_order": self.execution_order,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "answer_preview": self.answer_preview,
            "errors": self.errors,
            "timeout_seconds": self.timeout_seconds,
            "last_activity_at": self.last_activity_at,
            "stall_warning": self.stall_warning,
            "timed_out": self.timed_out,
        }


@inject
@dataclass
class SubtaskRegistryService:
    """子任务状态注册表：Redis 优先、进程内兜底。"""

    redis_client: Redis | None = None
    _force_memory: bool = False
    _TTL_SECONDS = 3600
    _STALL_THRESHOLD_SECONDS = 120

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._memory_runs: dict[str, dict[str, SubtaskStatus]] = {}
        self._memory_meta: dict[str, dict[str, Any]] = {}
        self._cancel_tokens: dict[str, Any] = {}

    @classmethod
    def _meta_key(cls, request_id: str) -> str:
        return f"agent:subtask:{request_id}:meta"

    @classmethod
    def _item_key(cls, request_id: str, task_id: str) -> str:
        return f"agent:subtask:{request_id}:item:{task_id}"

    @classmethod
    def _item_pattern(cls, request_id: str) -> str:
        return f"agent:subtask:{request_id}:item:*"

    def _client(self) -> Redis | None:
        if self._force_memory:
            return None
        if self.redis_client is not None:
            return self.redis_client
        try:
            from app.http.module import injector

            return injector.get(Redis)
        except Exception:
            return None

    def register_plan(
        self,
        *,
        request_id: str,
        execution_mode: str,
        original_query: str,
        items: list[Any],
    ) -> None:
        """注册整个计划的初始状态。"""
        statuses = [
            SubtaskStatus(
                task_id=item.task_id,
                title=item.title,
                agent_pool=item.agent_pool,
                depends_on=list(item.depends_on),
                execution_order=item.execution_order,
                timeout_seconds=float(getattr(item, "timeout_seconds", 0) or 0),
            )
            for item in items
        ]
        meta = {
            "execution_mode": execution_mode,
            "original_query": original_query,
            "created_at": time.time(),
            "task_ids": [status.task_id for status in statuses],
        }
        client = self._client()
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.delete(self._meta_key(request_id))
                for key in client.scan_iter(match=self._item_pattern(request_id), count=100):
                    pipe.delete(key)
                pipe.setex(
                    self._meta_key(request_id),
                    self._TTL_SECONDS,
                    json.dumps(meta, ensure_ascii=False),
                )
                for status in statuses:
                    pipe.setex(
                        self._item_key(request_id, status.task_id),
                        self._TTL_SECONDS,
                        json.dumps(status.to_dict(), ensure_ascii=False),
                    )
                pipe.execute()
                return
            except Exception:
                logger.warning("子任务计划写入 Redis 失败，回退内存", exc_info=True)

        with self._lock:
            self._memory_runs[request_id] = {status.task_id: status for status in statuses}
            self._memory_meta[request_id] = meta
            self._cleanup_locked()

    def mark_running(self, request_id: str, task_id: str) -> None:
        client = self._client()
        if client is not None:
            try:
                raw = client.get(self._item_key(request_id, task_id))
                if raw:
                    status = json.loads(raw)
                    status["status"] = "running"
                    status["started_at"] = time.time()
                    status["last_activity_at"] = time.time()
                    status["timed_out"] = False
                    status["stall_warning"] = False
                    client.setex(
                        self._item_key(request_id, task_id),
                        self._TTL_SECONDS,
                        json.dumps(status, ensure_ascii=False),
                    )
                    return
            except Exception:
                logger.warning("标记子任务 running 写 Redis 失败，回退内存", exc_info=True)
        with self._lock:
            status = self._memory_runs.get(request_id, {}).get(task_id)
            if status is not None:
                status.status = "running"
                status.started_at = time.time()
                status.last_activity_at = time.time()
                status.timed_out = False
                status.stall_warning = False

    def mark_completed(
        self,
        request_id: str,
        task_id: str,
        *,
        answer_preview: str = "",
        errors: list[str] | None = None,
    ) -> None:
        client = self._client()
        if client is not None:
            try:
                raw = client.get(self._item_key(request_id, task_id))
                if raw:
                    status = json.loads(raw)
                    status["status"] = "failed" if errors else "completed"
                    status["finished_at"] = time.time()
                    status["last_activity_at"] = time.time()
                    status["timed_out"] = False
                    status["stall_warning"] = False
                    status["answer_preview"] = (answer_preview or "")[:200]
                    status["errors"] = list(errors or [])
                    client.setex(
                        self._item_key(request_id, task_id),
                        self._TTL_SECONDS,
                        json.dumps(status, ensure_ascii=False),
                    )
                    return
            except Exception:
                logger.warning("标记子任务 completed 写 Redis 失败，回退内存", exc_info=True)
        with self._lock:
            status = self._memory_runs.get(request_id, {}).get(task_id)
            if status is None:
                return
            status.status = "failed" if errors else "completed"
            status.finished_at = time.time()
            status.last_activity_at = time.time()
            status.timed_out = False
            status.stall_warning = False
            status.answer_preview = answer_preview[:200]
            status.errors = list(errors or [])

    def mark_activity(self, request_id: str, task_id: str) -> None:
        """子任务流式期间上报活跃时间，用于 stall 判断。"""
        client = self._client()
        if client is not None:
            try:
                raw = client.get(self._item_key(request_id, task_id))
                if raw:
                    status = json.loads(raw)
                    status["last_activity_at"] = time.time()
                    status["stall_warning"] = False
                    client.setex(
                        self._item_key(request_id, task_id),
                        self._TTL_SECONDS,
                        json.dumps(status, ensure_ascii=False),
                    )
                    return
            except Exception:
                logger.warning("标记子任务活跃时间写 Redis 失败，回退内存", exc_info=True)
        with self._lock:
            status = self._memory_runs.get(request_id, {}).get(task_id)
            if status is not None:
                status.last_activity_at = time.time()
                status.stall_warning = False

    def register_cancel_token(self, request_id: str, cancel_token: Any) -> None:
        """注册一次执行的取消令牌，供生命周期 API 取消。"""
        with self._lock:
            self._cancel_tokens[str(request_id)] = cancel_token

    def cancel(self, request_id: str) -> bool:
        """取消一次执行；令牌不存在时返回 False。"""
        with self._lock:
            token = self._cancel_tokens.pop(str(request_id), None)
        if token is None:
            return False
        try:
            cancel = getattr(token, "cancel", None)
            if callable(cancel):
                cancel()
        except Exception:
            logger.warning("取消子任务执行失败: %s", request_id, exc_info=True)
            return False
        return True

    def snapshot(self, request_id: str) -> dict[str, Any] | None:
        client = self._client()
        if client is not None:
            try:
                raw_meta = client.get(self._meta_key(request_id))
                if raw_meta:
                    meta = json.loads(raw_meta)
                    task_ids = list(meta.get("task_ids") or [])
                    raw_items = client.mget(
                        [self._item_key(request_id, task_id) for task_id in task_ids]
                    )
                    items = [
                        json.loads(raw) for raw in raw_items if raw
                    ]
                    items = self._with_health(items)
                    return {
                        "request_id": request_id,
                        "execution_mode": meta.get("execution_mode", ""),
                        "original_query": meta.get("original_query", ""),
                        "task_count": len(items),
                        "items": items,
                    }
            except Exception:
                logger.warning("读取子任务快照 Redis 失败，回退内存", exc_info=True)
        return self._memory_snapshot(request_id)

    def _memory_snapshot(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._cleanup_locked()
            tasks = self._memory_runs.get(request_id)
            if tasks is None:
                return None
            meta = self._memory_meta.get(request_id, {})
            items = self._with_health(
                [status.to_dict() for status in tasks.values()]
            )
            return {
                "request_id": request_id,
                "execution_mode": meta.get("execution_mode", ""),
                "original_query": meta.get("original_query", ""),
                "task_count": len(tasks),
                "items": items,
            }

    def _with_health(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = time.time()
        for item in items:
            if item.get("status") != "running":
                item["timed_out"] = False
                item["stall_warning"] = False
                continue
            started_at = float(item.get("started_at") or 0)
            last_activity_at = float(item.get("last_activity_at") or started_at)
            timeout_seconds = float(item.get("timeout_seconds") or 0)
            timed_out = (
                timeout_seconds > 0
                and started_at > 0
                and now - started_at > timeout_seconds
            )
            stall_warning = (
                not timed_out
                and started_at > 0
                and now - last_activity_at > self._STALL_THRESHOLD_SECONDS
            )
            item["timed_out"] = timed_out
            item["stall_warning"] = stall_warning
        return items

    def _cleanup_locked(self) -> None:
        now = time.time()
        stale = [
            rid
            for rid, meta in self._memory_meta.items()
            if now - float(meta.get("created_at", 0)) > self._TTL_SECONDS
        ]
        for rid in stale:
            self._memory_runs.pop(rid, None)
            self._memory_meta.pop(rid, None)
