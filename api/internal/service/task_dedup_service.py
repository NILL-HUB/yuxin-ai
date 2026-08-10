import hashlib
import logging
from datetime import UTC, datetime, timedelta

from internal.extension.database_extension import db
from internal.extension.redis_extension import redis_client
from internal.model import Message


logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    """返回无时区的 UTC 时间，兼容数据库 DateTime 列。"""
    return datetime.now(UTC).replace(tzinfo=None)


class TaskDedupService:
    """基于记忆/会话数据的重复任务检测：同一用户对同一应用的相似 query 高频出现时给出定时任务建议"""

    MIN_FREQUENCY = 3               # 相似 query 出现次数阈值
    SIMILARITY_THRESHOLD = 0.75     # 相似度阈值
    WINDOW_DAYS = 30                # 统计窗口天数
    SUGGEST_TTL = 7 * 24 * 3600     # 建议去重 TTL（7 天）
    CONSUMED_TTL = 180 * 24 * 3600  # 已消费建议去重 TTL（180 天）

    def check_suggestion(self, account_id, app_id, query: str, conversation_id=None) -> dict | None:
        """检测是否应建议创建定时任务。命中返回建议 payload，否则 None。"""
        normalized = self._normalize(query)
        if len(normalized) < 6:
            return None

        window_start = _utcnow_naive() - timedelta(days=self.WINDOW_DAYS)
        recent = (
            db.session.query(Message)
            .filter(
                Message.created_by == account_id,
                Message.app_id == app_id,
                Message.created_at >= window_start,
            )
            .order_by(Message.created_at.desc())
            .limit(200)
            .all()
        )
        if len(recent) < self.MIN_FREQUENCY:
            return None

        similar_count = sum(
            1 for m in recent
            if self._similarity(m.query or "", query) >= self.SIMILARITY_THRESHOLD
        )
        if similar_count < self.MIN_FREQUENCY:
            return None

        fingerprint = hashlib.md5(f"{account_id}:{app_id}:{normalized}".encode()).hexdigest()
        dedup_key = f"schedule_suggestion:{fingerprint}"
        if (
            redis_client.get(dedup_key)
            or redis_client.get(f"schedule_suggestion_consumed:{fingerprint}")
            or redis_client.get(f"schedule_suggestion_rejected:{fingerprint}")
        ):
            return None
        redis_client.setex(dedup_key, self.SUGGEST_TTL, "1")

        return {
            "app_id": str(app_id),
            "query": query,
            "similar_count": similar_count,
            "suggested_prompt": query,
            "fingerprint": fingerprint,
        }

    def mark_consumed(self, fingerprint: str) -> None:
        """建议已消费（任务已创建）：长期去重不再提示"""
        redis_client.setex(f"schedule_suggestion_consumed:{fingerprint}", self.CONSUMED_TTL, "1")

    def mark_rejected(self, fingerprint: str) -> None:
        """建议被拒绝：7 天内不再提示"""
        redis_client.setex(f"schedule_suggestion_rejected:{fingerprint}", 7 * 24 * 3600, "1")

    @staticmethod
    def _normalize(text: str) -> str:
        """归一化：去除全部空白并转小写"""
        return "".join(text.split()).lower()

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """基于字符集合的简易相似度（0~1），用于同义快速判断"""
        if not a or not b:
            return 0.0
        na, nb = TaskDedupService._normalize(a), TaskDedupService._normalize(b)
        if na == nb:
            return 1.0
        set_a, set_b = set(na), set(nb)
        if not set_a or not set_b:
            return 0.0
        inter = len(set_a & set_b)
        return inter / max(len(set_a), len(set_b))
