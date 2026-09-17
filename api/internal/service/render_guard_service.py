"""渲染闸门服务（4C4G 单机资源保护）。

渲染是分钟级、单次峰值 ~1.5G 内存的重任务。4C4G 单机上若不设闸门，
「多用户同时点渲染」会线性叠加内存（实测：1 个 1470MB / 2 个 2567MB /
3 个 2679MB）而吞吐不增——直接把服务器打爆。本服务提供三层入口约束：

1. **每账号并发上限**（默认 1）：同一账号同时只允许 1 个渲染在跑，
   挡住「用户连点多次」。
2. **防重锁**（composition 指纹 + 账号，Redis SETNX）：同一脚本重复提交时
   直接复用进行中的任务，避免重复派发。
3. **队列积压阈值**：待渲染任务超过阈值时拒绝新请求并提示稍后重试，
   避免任务无限堆积、用户误以为卡死。

设计取舍：用 Redis 计数器而非 DB 查询——渲染是「进行中」的瞬时状态，
DB 无对应记录，且计数需原子（INCR/DECR）。计数器带 TTL 兜底，
防止进程崩溃后计数永不释放（与 `ScheduleExecutionService` 同一口径）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from injector import inject
from redis import Redis

logger = logging.getLogger(__name__)

# 每账号同时进行的渲染上限。4C4G 上渲染并发=1 是硬约束（V8 堆 + 内存双重限制），
# 故此处为 1；调大需同时确认渲染 worker 的 -c 与内存限额。
MAX_CONCURRENT_RENDERS_PER_ACCOUNT = 1

# 队列积压阈值：待渲染任务超过该值即拒绝新请求。
# 建议 5——4C4G 上单渲染最长约 15 分钟（900s 超时），5 个积压已约 1 小时排队。
MAX_QUEUED_RENDERS = 5

# 进行中计数器的 TTL：兜底防止崩溃后计数不释放。
# 必须覆盖最长渲染时长（RENDER_TIMEOUT_SEC=900s），留足余量。
RENDER_SLOT_TTL_SECONDS = 1800

# 防重锁 TTL：同一脚本重复提交的短窗口（分钟级），避免用户连点。
RENDER_DEDUPE_TTL_SECONDS = 300

_ACCOUNT_SLOT_PREFIX = "render:slot:"
_DEDUPE_PREFIX = "render:dedupe:"
_QUEUE_COUNT_KEY = "render:queue:count"


@dataclass
class RenderAdmission:
    """渲染准入结果。``allowed=False`` 时 ``reason`` 为面向用户的提示。"""

    allowed: bool
    reason: str = ""
    existing_task_id: str = ""


@inject
@dataclass
class RenderGuardService:
    """渲染闸门：并发上限 + 防重锁 + 队列积压保护。"""

    redis_client: Redis

    @staticmethod
    def _slot_key(account_id: str) -> str:
        return f"{_ACCOUNT_SLOT_PREFIX}{account_id}"

    @staticmethod
    def _dedupe_key(account_id: str, fingerprint: str) -> str:
        return f"{_DEDUPE_PREFIX}{account_id}:{fingerprint}"

    def admit(self, *, account_id: str, fingerprint: str) -> RenderAdmission:
        """申请渲染准入。

        顺序：先查队列积压（全局），再占用账号槽位与防重锁（原子 INCR + SETNX）。
        任一环节拒绝时，回滚本方法已占用的资源，避免泄漏额度。
        """
        if not account_id:
            return RenderAdmission(allowed=False, reason="缺少账号信息，无法渲染")

        # 1) 队列积压保护：全局阈值，防止任务无限堆积
        try:
            queued = int(self.redis_client.get(_QUEUE_COUNT_KEY) or 0)
        except Exception:
            logger.warning("读取渲染队列积压失败，放行本次请求", exc_info=True)
            queued = 0
        if queued >= MAX_QUEUED_RENDERS:
            return RenderAdmission(
                allowed=False,
                reason=f"当前渲染任务较多（排队 {queued} 个），请稍后再试",
            )

        # 2) 每账号并发上限：INCR 后判断，超限立即回滚
        slot_key = self._slot_key(account_id)
        try:
            current = int(self.redis_client.incr(slot_key))
            self.redis_client.expire(slot_key, RENDER_SLOT_TTL_SECONDS)
        except Exception:
            logger.warning("渲染并发计数失败，放行本次请求 account_id=%s", account_id, exc_info=True)
            current = 1
        if current > MAX_CONCURRENT_RENDERS_PER_ACCOUNT:
            self._safe_decr(slot_key)
            return RenderAdmission(
                allowed=False,
                reason="你已有渲染任务正在进行，请等它完成后再试",
            )

        # 3) 防重锁：同一脚本重复提交时复用进行中的任务
        dedupe_key = self._dedupe_key(account_id, fingerprint)
        try:
            acquired = bool(
                self.redis_client.set(
                    dedupe_key, b"1", nx=True, ex=RENDER_DEDUPE_TTL_SECONDS
                )
            )
        except Exception:
            logger.warning("渲染防重锁失败，放行 account_id=%s", account_id, exc_info=True)
            acquired = True
        if not acquired:
            existing = ""
            try:
                raw = self.redis_client.get(dedupe_key)
                existing = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw or "")
            except Exception:
                existing = ""
            self._safe_decr(slot_key)
            return RenderAdmission(
                allowed=False,
                reason="相同内容的渲染任务已在进行中，请勿重复提交",
                existing_task_id=existing,
            )

        return RenderAdmission(allowed=True)

    def release(self, *, account_id: str, fingerprint: str = "") -> None:
        """释放账号槽位与防重锁（渲染结束或派发失败时调用）。"""
        if account_id:
            self._safe_decr(self._slot_key(account_id))
        if account_id and fingerprint:
            try:
                self.redis_client.delete(self._dedupe_key(account_id, fingerprint))
            except Exception:
                logger.warning("释放渲染防重锁失败 account_id=%s", account_id, exc_info=True)

    def _safe_decr(self, key: str) -> None:
        """递减计数，失败仅告警；减到 0 时删除键避免长期残留。"""
        try:
            remaining = int(self.redis_client.decr(key))
            if remaining <= 0:
                self.redis_client.delete(key)
        except Exception:
            logger.warning("释放渲染槽位失败 key=%s", key, exc_info=True)

    def mark_enqueued(self) -> None:
        """登记一个待渲染任务（入队时调用）。"""
        try:
            self.redis_client.incr(_QUEUE_COUNT_KEY)
        except Exception:
            logger.warning("登记渲染队列计数失败", exc_info=True)

    def mark_dequeued(self) -> None:
        """注销一个待渲染任务（任务开始执行时调用）。"""
        self._safe_decr(_QUEUE_COUNT_KEY)
