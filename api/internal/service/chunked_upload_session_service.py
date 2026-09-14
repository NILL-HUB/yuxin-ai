"""分片上传会话状态服务。

API 以多 uvicorn worker 运行，分片会话状态必须放在 Redis 而非进程内存。
本服务负责会话的创建、读取、分片登记、断点续传查询与销毁，
以及秒传指纹的登记与查询。
"""
import json
import logging
from dataclasses import asdict, dataclass, field
from uuid import uuid4

from injector import inject
from redis import Redis

logger = logging.getLogger(__name__)

# 会话与指纹的默认 TTL（秒）
_SESSION_TTL_SECONDS = 86400
_FINGERPRINT_TTL_SECONDS = 86400 * 7


@dataclass
class ChunkedUploadSession:
    """分片上传会话（可序列化到 Redis）。"""

    session_id: str
    account_id: str
    filename: str
    total_size: int
    chunk_size: int
    total_chunks: int
    fingerprint: str = ""
    received_chunks: list[int] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """所有分片都已收到。"""
        return len(self.received_chunks) >= self.total_chunks


@inject
@dataclass
class ChunkedUploadSessionService:
    """Redis 支撑的分片会话与秒传指纹管理。"""

    redis: Redis

    @staticmethod
    def _key(session_id: str) -> str:
        return f"chunked_upload:session:{session_id}"

    @staticmethod
    def _fingerprint_key(account_id: str, fingerprint: str) -> str:
        return f"chunked_upload:fingerprint:{account_id}:{fingerprint}"

    @staticmethod
    def _received_key(session_id: str) -> str:
        return f"chunked_upload:received:{session_id}"

    @staticmethod
    def _sessions_key() -> str:
        return "chunked_upload:sessions"

    @staticmethod
    def _claim_key(session_id: str) -> str:
        return f"chunked_upload:claim:{session_id}"

    def create(
        self,
        *,
        account_id: str,
        filename: str,
        total_size: int,
        chunk_size: int,
        total_chunks: int,
        fingerprint: str = "",
        session_id: str | None = None,
    ) -> ChunkedUploadSession:
        """创建并持久化会话。"""
        session = ChunkedUploadSession(
            session_id=session_id or str(uuid4()),
            account_id=account_id,
            filename=filename,
            total_size=total_size,
            chunk_size=chunk_size,
            total_chunks=total_chunks,
            fingerprint=fingerprint,
        )
        self._save(session)
        self.redis.sadd(self._sessions_key(), session.session_id)
        return session

    def _save(self, session: ChunkedUploadSession) -> None:
        """持久化会话元数据（不含已收分片集合，集合独立存 Redis Set）。"""
        payload = asdict(session)
        payload.pop("received_chunks", None)
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.redis.setex(self._key(session.session_id), _SESSION_TTL_SECONDS, encoded)

    def get(self, session_id: str) -> ChunkedUploadSession | None:
        """读取会话；不存在或损坏时返回 None。已收分片从 Redis Set 回填。"""
        raw = self.redis.get(self._key(session_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            data["received_chunks"] = self._load_received(session_id)
            return ChunkedUploadSession(**data)
        except (ValueError, TypeError):
            logger.warning("分片会话数据损坏 session_id=%s", session_id, exc_info=True)
            return None

    def _load_received(self, session_id: str) -> list[int]:
        """读取已收分片下标（排序后返回）。"""
        members = self.redis.smembers(self._received_key(session_id))
        indices: list[int] = []
        for member in members or []:
            raw = member.decode("utf-8") if isinstance(member, bytes) else str(member)
            try:
                indices.append(int(raw))
            except (TypeError, ValueError):
                continue
        indices.sort()
        return indices

    def mark_received(self, session_id: str, index: int) -> ChunkedUploadSession | None:
        """登记某分片已收到（SADD 原子且幂等，避免并发丢更新）。"""
        session = self.get(session_id)
        if session is None:
            return None
        received_key = self._received_key(session_id)
        self.redis.sadd(received_key, index)
        self.redis.expire(received_key, _SESSION_TTL_SECONDS)
        session.received_chunks = self._load_received(session_id)
        return session

    def missing_chunks(self, session_id: str) -> list[int]:
        """返回尚未收到的分片下标（用于断点续传）。"""
        session = self.get(session_id)
        if session is None:
            return []
        received = set(session.received_chunks)
        return [index for index in range(session.total_chunks) if index not in received]

    def abort(self, session_id: str) -> None:
        """销毁会话与已收分片集合（分片文件清理由编排服务负责）。"""
        self.redis.delete(self._key(session_id), self._received_key(session_id))
        self.redis.srem(self._sessions_key(), session_id)

    def active_sessions(self) -> list[str]:
        """返回仍在跟踪中的会话 id 列表（可能含已过期项，由调用方二次校验）。"""
        members = self.redis.smembers(self._sessions_key()) or []
        result = []
        for member in members:
            result.append(member.decode("utf-8") if isinstance(member, bytes) else str(member))
        return result

    def is_alive(self, session_id: str) -> bool:
        """会话元数据是否仍存在（未被 TTL 过期、未 abort）。"""
        return bool(self.redis.exists(self._key(session_id)))

    def forget_session(self, session_id: str) -> None:
        """从跟踪集合中移除会话（清理任务用）。"""
        self.redis.srem(self._sessions_key(), session_id)

    def claim_for_completion(self, session_id: str, ttl_seconds: int = 300) -> bool:
        """原子占用会话以防并发 complete；成功返回 True。"""
        return bool(
            self.redis.set(self._claim_key(session_id), b"1", nx=True, ex=ttl_seconds)
        )

    def release_claim(self, session_id: str) -> None:
        """释放占用（失败路径调用，便于用户重试）。"""
        self.redis.delete(self._claim_key(session_id))

    def register_fingerprint(self, account_id: str, fingerprint: str, upload_file_id: str) -> None:
        """登记秒传指纹 → UploadFile 映射（同账号有效）。"""
        if not fingerprint:
            return
        self.redis.setex(
            self._fingerprint_key(account_id, fingerprint),
            _FINGERPRINT_TTL_SECONDS,
            upload_file_id.encode("utf-8"),
        )

    def lookup_fingerprint(self, account_id: str, fingerprint: str) -> str | None:
        """按秒传指纹查同账号既有的 UploadFile id。"""
        if not fingerprint:
            return None
        raw = self.redis.get(self._fingerprint_key(account_id, fingerprint))
        if raw is None:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
