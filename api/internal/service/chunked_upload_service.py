"""分片上传编排服务。

职责：
- init：校验单文件上限与配额、创建分片会话、秒传命中则直接复用
- save_chunk：把分片交给存储后端暂存并登记会话
- complete：流式合并分片 → 落盘到激活后端 → 落 UploadFile 记录 → 清理暂存 → 登记秒传指纹
- abort：清理暂存与会话
- status：查询进度（断点续传）

存储后端支持（P2B-2 已落地）：
- **分片暂存永远在本地磁盘**：分片是逐块到达的临时数据，与最终后端无关；
- **合并产物落到运行时激活后端**（admin 可切换 local/cos/oss）：合并先在本地
  临时文件完成（流式、不进内存），再由激活后端通过 ``upload_local_file``
  流式上传（COS 多分片 / OSS 文件流 / local 原子 move）。
"""
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from injector import inject

from internal.entity.storage_quota_entity import PARSE_RESERVE_BYTES
from internal.exception import FailException, ValidateErrorException
from internal.model import UploadFile
from internal.service.chunked_upload_session_service import ChunkedUploadSessionService
from internal.service.storage.local_storage_service import LocalStorageService
from internal.service.storage.runtime_storage_service import RuntimeStorageProxy
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
    """分片上传编排。

    ``storage`` 仅用于**分片暂存与合并**（永远是本地磁盘）；
    ``runtime_storage`` 负责**最终产物的落盘与对象管理**，跟随运行时激活的后端。
    二者职责分离是 P2B-2 的核心：分片是临时数据，产物才需要跟随存储策略。
    """

    db: SQLAlchemy
    storage: LocalStorageService
    runtime_storage: RuntimeStorageProxy
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

    def save_chunk(self, *, session_id: str, index: int, content: bytes, account) -> dict:
        """暂存一个分片并登记会话。"""
        session = self.session_service.get(session_id)
        if session is None:
            raise FailException("上传会话不存在或已过期，请重新开始上传")
        if session.account_id != str(account.id):
            raise FailException("无权上传该会话的分片")
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

        if not self.session_service.claim_for_completion(session_id):
            raise FailException("该上传正在处理中，请稍候重试")
        try:
            # 第一层防御：合并前预校验板块类型，避免白传大文件（用户把视频传图片库的场景）
            knowledge_service = None
            if knowledge_base_id:
                knowledge_service = self._knowledge_base_service()
                pre_extension = (
                    session.filename.rsplit(".", 1)[-1].lower() if "." in session.filename else ""
                )
                knowledge_service.assert_upload_allowed(knowledge_base_id, pre_extension, account)

            # 原子预占配额：在行锁内完成「校验 + 累加」，关闭并发超卖窗口
            # （init 的 check_quota 只是快速预检，两个会话可同时通过）。
            # 放在合并之前，避免超额时白合并 GB 级文件。
            quota_consumed = False
            self.storage_quota_service.consume_quota(
                account.id, session.total_size, reserve_bytes=PARSE_RESERVE_BYTES
            )
            quota_consumed = True
            try:
                return self._materialize(
                    session=session,
                    account=account,
                    knowledge_base_id=knowledge_base_id,
                    knowledge_service=knowledge_service,
                )
            except Exception:
                if quota_consumed:
                    # 合并/落库/建档失败：释放预占配额，会话保留以便用户重试
                    try:
                        self.storage_quota_service.release_usage(account.id, session.total_size)
                    except Exception:
                        logger.warning(
                            "释放分片上传预占配额失败 account_id=%s", account.id, exc_info=True
                        )
                raise
        except Exception:
            self.session_service.release_claim(session_id)
            raise

    def _materialize(self, *, session, account, knowledge_base_id: str, knowledge_service) -> dict:
        """合并分片 → 落到激活后端 → 落 UploadFile → （可选）建档 → 收尾。

        配额已在此之前预占。分片暂存在本地，产物落到 runtime 激活的后端：
        合并先在本地临时文件完成（流式，不进内存），再流式上传到目标后端。
        """
        target_key = _build_object_key(session.filename)
        backend = self.runtime_storage.active_backend()
        temp_path = self._new_temp_path(session.filename)
        try:
            # 合并到本地临时文件（流式，不进内存），再流式落到激活后端。
            # 无论成功失败都清理临时文件（finally），避免磁盘泄漏。
            total_size, digest = self.storage.merge_chunks_to_file(
                session_id=session.session_id,
                total_chunks=session.total_chunks,
                target_path=temp_path,
            )
            self.runtime_storage.upload_local_file(
                source_path=temp_path, target_key=target_key
            )
        except Exception:
            logger.exception(
                "分片合并/落盘失败 backend=%s key=%s", backend, target_key, exc_info=True
            )
            self._safe_delete_object(target_key)
            raise
        finally:
            self._discard_temp_file(temp_path)

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
                storage_backend=backend,
            )
        except Exception:
            # 落库失败：回收已合并的目标对象，避免孤儿文件；会话保留以便重试
            logger.exception("分片合并产物落库失败，回收目标对象 key=%s", target_key)
            self._safe_delete_object(target_key)
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
                self._safe_delete_object(target_key)
                try:
                    self.upload_file_service.delete(upload_file)
                except Exception:
                    logger.warning("回滚 UploadFile 记录失败 id=%s", upload_file.id, exc_info=True)
                raise
            result["document_id"] = str(document.id)

        # 全部成功后才执行破坏性收尾（配额已在合并前预占）
        self.storage.cleanup_session(session.session_id)
        self.session_service.abort(session.session_id)
        self.session_service.register_fingerprint(
            str(account.id), session.fingerprint, str(upload_file.id)
        )

        return result

    def _safe_delete_object(self, key: str) -> None:
        """尽力删除对象，失败仅告警（不掩盖原始异常）。按文件记录/激活后端路由。"""
        try:
            self.runtime_storage.delete_object(key)
        except Exception:
            logger.warning("删除对象失败 key=%s", key, exc_info=True)

    @staticmethod
    def _new_temp_path(filename: str) -> str:
        """为合并产物创建本地临时文件路径（延后到合并时写入）。"""
        extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
        suffix = f".{extension}" if extension else ""
        fd, path = tempfile.mkstemp(prefix="chunk-merge-", suffix=suffix)
        os.close(fd)
        return path

    @staticmethod
    def _discard_temp_file(path: str) -> None:
        """删除本地合并临时文件（幂等，失败不抛）。"""
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            logger.warning("清理合并临时文件失败 path=%s", path, exc_info=True)

    def _copy_source_to_active_backend(self, source) -> tuple[str, int, str]:
        """把秒传源对象复制到激活后端，返回 (target_key, 字节数, 目标后端)。

        同后端时走服务端复制（快、不落本地）；跨后端时下载到本地临时文件后
        流式上传到激活后端——与激活后端策略保持一致，避免历史文件永久留在旧后端。
        """
        active = self.runtime_storage.active_backend()
        source_backend = (getattr(source, "storage_backend", None) or "").strip().lower() or active
        target_key = _build_object_key(source.name or "material.bin")

        if source_backend == active:
            size = self.runtime_storage.copy_object(
                source.key, target_key, backend=source_backend
            )
            return target_key, size, active

        temp_path = self._new_temp_path(source.name or "material.bin")
        try:
            self.runtime_storage.download_file(source.key, temp_path, backend=source_backend)
            size = os.path.getsize(temp_path)
            self.runtime_storage.upload_local_file(
                source_path=temp_path, target_key=target_key
            )
        except Exception:
            self._safe_delete_object(target_key)
            raise
        finally:
            self._discard_temp_file(temp_path)
        return target_key, size, active

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

        # 秒传会真实复制一份占用存储，必须原子预占配额（锁内校验+累加，防并发超卖）；
        # 复制前预占，避免复制完才被拒造成残留。
        source_size = int(getattr(source, "size", 0) or 0)
        self.storage_quota_service.consume_quota(
            account.id, source_size, reserve_bytes=PARSE_RESERVE_BYTES
        )
        try:
            target_key, size, target_backend = self._copy_source_to_active_backend(source)

            upload_file = self.upload_file_service.create_upload_file(
                account_id=account.id,
                name=source.name,
                key=target_key,
                size=size,
                extension=source.extension,
                mime_type=source.mime_type,
                hash=source.hash,
                storage_backend=target_backend,
            )

            # 第二层防御：建档失败则回滚复制产物与 UploadFile 记录，并释放预占配额
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
                    self._safe_delete_object(target_key)
                    try:
                        self.upload_file_service.delete(upload_file)
                    except Exception:
                        logger.warning("回滚秒传 UploadFile 失败 id=%s", upload_file.id, exc_info=True)
                    raise
                result["document_id"] = str(document.id)

            # 全部成功后才登记指纹（配额已在复制前预占）
            self.session_service.register_fingerprint(
                str(account.id), fingerprint, str(upload_file.id)
            )
            return result
        except Exception:
            # 任一步失败：释放预占配额，避免用户被自己失败的上传扣容量
            try:
                self.storage_quota_service.release_usage(account.id, source_size)
            except Exception:
                logger.warning("释放秒传预占配额失败 account_id=%s", account.id, exc_info=True)
            raise

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
