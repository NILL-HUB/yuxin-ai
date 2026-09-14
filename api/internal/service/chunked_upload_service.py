"""分片上传编排服务。

职责：
- init：校验单文件上限与配额、创建分片会话、秒传命中则直接复用
- save_chunk：把分片交给存储后端暂存并登记会话
- complete：流式合并分片 → 落 UploadFile 记录 → 清理暂存 → 登记秒传指纹
- abort：清理暂存与会话
- status：查询进度（断点续传）

仅支持 local 后端（云后端原生 multipart 属后续 P2B-2）。
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from injector import inject

from internal.exception import FailException, ValidateErrorException
from internal.model import UploadFile
from internal.service.chunked_upload_session_service import ChunkedUploadSessionService
from internal.service.storage.local_storage_service import LocalStorageService
from internal.service.storage_quota_service import StorageQuotaService
from internal.service.upload_file_service import UploadFileService
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _build_object_key(filename: str) -> str:
    """与 local 后端一致的最终对象 key：{yyyy}/{mm}/{dd}/{uuid}.{ext}。"""
    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
    random_filename = str(uuid.uuid4()) + (f".{extension}" if extension else "")
    now = _utcnow_naive()
    return f"{now.year}/{now.month:02d}/{now.day:02d}/{random_filename}"


@inject
@dataclass
class ChunkedUploadService(BaseService):
    """分片上传编排。"""

    db: SQLAlchemy
    storage: LocalStorageService
    session_service: ChunkedUploadSessionService
    upload_file_service: UploadFileService
    storage_quota_service: StorageQuotaService

    def init(
        self,
        *,
        account,
        filename: str,
        total_size: int,
        chunk_size: int,
        total_chunks: int,
        fingerprint: str = "",
    ) -> dict:
        """创建分片上传会话；命中秒传指纹时直接返回既有文件。"""
        if total_size <= 0:
            raise ValidateErrorException("文件大小必须大于 0")
        if chunk_size <= 0:
            raise ValidateErrorException("分片大小必须大于 0")
        if total_chunks <= 0:
            raise ValidateErrorException("分片数量必须大于 0")

        max_bytes = self.storage_quota_service.resolve_max_file_size_bytes(account.id)
        if total_size > max_bytes:
            raise ValidateErrorException(
                f"单个文件不能超过 {max_bytes // (1024 * 1024)}MB，请升级套餐后重试",
                {"file": [f"当前上限 {max_bytes} 字节"]},
            )

        expected_chunks = (total_size + chunk_size - 1) // chunk_size
        if total_chunks != expected_chunks:
            raise ValidateErrorException(
                "分片数量与文件大小不匹配",
                {"total_chunks": [f"期望 {expected_chunks}"]},
            )

        existing_id = self.session_service.lookup_fingerprint(str(account.id), fingerprint)
        if existing_id:
            return {"instant": True, "upload_file_id": existing_id}

        self.storage_quota_service.check_quota(account.id, total_size)

        session_id = str(uuid.uuid4())
        session = self.session_service.create(
            account_id=str(account.id),
            filename=filename,
            total_size=total_size,
            chunk_size=chunk_size,
            total_chunks=total_chunks,
            fingerprint=fingerprint,
            session_id=session_id,
        )
        return {
            "instant": False,
            "session_id": session.session_id,
            "chunk_size": chunk_size,
            "total_chunks": total_chunks,
            "received_chunks": [],
        }

    def save_chunk(self, *, session_id: str, index: int, content: bytes) -> dict:
        """暂存一个分片并登记会话。"""
        session = self.session_service.get(session_id)
        if session is None:
            raise FailException("上传会话不存在或已过期，请重新开始上传")
        if index < 0 or index >= session.total_chunks:
            raise ValidateErrorException(
                "分片下标越界", {"index": [f"应在 0~{session.total_chunks - 1}"]}
            )
        if not content:
            raise ValidateErrorException("分片内容为空")

        self.storage.save_chunk(session_id, index, content)
        updated = self.session_service.mark_received(session_id, index)
        received = len(updated.received_chunks) if updated is not None else 0
        return {
            "received": received,
            "total_chunks": session.total_chunks,
            "missing_chunks": self.session_service.missing_chunks(session_id),
        }

    def complete(self, *, session_id: str, account, knowledge_base_id: str = "") -> dict:
        """合并分片、落库并清理暂存。"""
        session = self.session_service.get(session_id)
        if session is None:
            raise FailException("上传会话不存在或已过期，请重新开始上传")

        if session.account_id != str(account.id):
            raise FailException("无权完成该上传会话")

        missing = self.session_service.missing_chunks(session_id)
        if missing:
            raise FailException(f"仍有 {len(missing)} 个分片未上传，无法完成")

        # 第一层防御：合并前预校验板块类型，避免白传大文件（用户把视频传图片库的场景）
        knowledge_service = None
        if knowledge_base_id:
            knowledge_service = self._knowledge_base_service()
            pre_extension = (
                session.filename.rsplit(".", 1)[-1].lower() if "." in session.filename else ""
            )
            knowledge_service.assert_upload_allowed(knowledge_base_id, pre_extension, account)

        target_key = _build_object_key(session.filename)
        try:
            total_size, digest = self.storage.merge_chunks(
                session_id, session.total_chunks, target_key
            )
        except Exception:
            logger.exception("分片合并失败 session_id=%s", session_id)
            raise

        extension = (
            session.filename.rsplit(".", 1)[-1].lower() if "." in session.filename else ""
        )
        try:
            upload_file = self.upload_file_service.create_upload_file(
                account_id=account.id,
                name=session.filename,
                key=target_key,
                size=total_size,
                extension=extension,
                mime_type="",
                hash=digest,
                storage_backend="local",
            )
        except Exception:
            # 落库失败：回收已合并的目标对象，避免孤儿文件；会话保留以便重试
            logger.exception("分片合并产物落库失败，回收目标对象 key=%s", target_key)
            try:
                self.storage.delete_object(target_key)
            except Exception:
                logger.warning("回收合并产物失败 key=%s", target_key, exc_info=True)
            raise

        # 第二层防御：建档前移到破坏性操作之前；失败则回滚对象与 UploadFile 记录并保留会话
        result = {
            "upload_file_id": str(upload_file.id),
            "size": total_size,
            "hash": digest,
            "key": target_key,
            "name": session.filename,
        }
        if knowledge_base_id and knowledge_service is not None:
            try:
                document = knowledge_service.create_document_from_upload_file(
                    knowledge_base_id=knowledge_base_id,
                    upload_file=upload_file,
                    account=account,
                )
            except Exception:
                logger.exception(
                    "分片上传建档失败，回滚已合并对象与文件记录 upload_file_id=%s",
                    upload_file.id,
                )
                try:
                    self.storage.delete_object(target_key)
                except Exception:
                    logger.warning("回滚合并产物失败 key=%s", target_key, exc_info=True)
                try:
                    self.upload_file_service.delete(upload_file)
                except Exception:
                    logger.warning("回滚 UploadFile 记录失败 id=%s", upload_file.id, exc_info=True)
                raise
            result["document_id"] = str(document.id)

        # 全部成功后才执行破坏性收尾与计量
        self.storage_quota_service.add_usage(account.id, total_size)
        self.storage.cleanup_session(session_id)
        self.session_service.abort(session_id)
        self.session_service.register_fingerprint(
            str(account.id), session.fingerprint, str(upload_file.id)
        )

        return result

    def instant_upload(
        self, *, account, upload_file_id: str, fingerprint: str, knowledge_base_id: str = ""
    ) -> dict:
        """秒传：服务端复制既有对象、生成新的 UploadFile 记录并（可选）建档。"""
        try:
            file_uuid = uuid.UUID(upload_file_id)
        except (TypeError, ValueError):
            raise ValidateErrorException("秒传源文件标识非法")

        source = (
            self.db.session.query(UploadFile)
            .filter(UploadFile.id == file_uuid)
            .first()
        )
        if source is None:
            raise FailException("秒传源文件不存在")
        if getattr(source, "account_id", None) != account.id:
            raise FailException("无权秒传他人的文件")

        # 第一层防御：复制前预校验板块类型，避免复制后无法建档造成残留
        knowledge_service = None
        if knowledge_base_id:
            knowledge_service = self._knowledge_base_service()
            knowledge_service.assert_upload_allowed(
                knowledge_base_id, source.extension or "", account
            )

        # 秒传会真实复制一份占用存储，必须先校验配额
        self.storage_quota_service.check_quota(account.id, int(getattr(source, "size", 0) or 0))

        target_key = _build_object_key(source.name or "material.bin")
        size = self.storage.copy_object(source.key, target_key)

        upload_file = self.upload_file_service.create_upload_file(
            account_id=account.id,
            name=source.name,
            key=target_key,
            size=size,
            extension=source.extension,
            mime_type=source.mime_type,
            hash=source.hash,
            storage_backend="local",
        )

        # 第二层防御：建档失败则回滚复制产物与 UploadFile 记录，不累加用量
        result = {
            "instant": True,
            "upload_file_id": str(upload_file.id),
            "size": size,
            "key": target_key,
            "name": source.name,
        }
        if knowledge_base_id and knowledge_service is not None:
            try:
                document = knowledge_service.create_document_from_upload_file(
                    knowledge_base_id=knowledge_base_id,
                    upload_file=upload_file,
                    account=account,
                )
            except Exception:
                logger.exception(
                    "秒传建档失败，回滚复制产物与文件记录 upload_file_id=%s", upload_file.id
                )
                try:
                    self.storage.delete_object(target_key)
                except Exception:
                    logger.warning("回滚秒传产物失败 key=%s", target_key, exc_info=True)
                try:
                    self.upload_file_service.delete(upload_file)
                except Exception:
                    logger.warning("回滚秒传 UploadFile 失败 id=%s", upload_file.id, exc_info=True)
                raise
            result["document_id"] = str(document.id)

        # 全部成功后才计量与登记指纹
        self.storage_quota_service.add_usage(account.id, size)
        self.session_service.register_fingerprint(
            str(account.id), fingerprint, str(upload_file.id)
        )
        return result

    def abort(self, *, session_id: str, account) -> None:
        """放弃上传：清理暂存与会话。"""
        session = self.session_service.get(session_id)
        if session is None:
            return
        if session.account_id != str(account.id):
            raise FailException("无权取消该上传会话")
        self.storage.cleanup_session(session_id)
        self.session_service.abort(session_id)

    def status(self, *, session_id: str, account) -> dict:
        """查询会话进度（断点续传用）。"""
        session = self.session_service.get(session_id)
        if session is None:
            raise FailException("上传会话不存在或已过期")
        if session.account_id != str(account.id):
            raise FailException("无权查询该上传会话")
        return {
            "session_id": session.session_id,
            "filename": session.filename,
            "total_chunks": session.total_chunks,
            "chunk_size": session.chunk_size,
            "received_chunks": session.received_chunks,
            "missing_chunks": self.session_service.missing_chunks(session_id),
            "is_complete": len(session.received_chunks) >= session.total_chunks,
        }

    def _knowledge_base_service(self):
        """延迟获取知识库服务（避免与 knowledge_base_service 循环导入）。"""
        from app.http.module import injector

        from internal.service.knowledge_base_service import KnowledgeBaseService

        return injector.get(KnowledgeBaseService)
