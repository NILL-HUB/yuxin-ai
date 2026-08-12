"""文件迁移服务。

支持将旧存储后端中的文件**选择性一次性迁移**到目标存储后端：
- 按源后端、文件扩展名、关键字搜索筛选候选文件（分页）
- 勾选部分文件或全部文件执行迁移
- 迁移 = 从源后端读取字节 → 写入目标后端（保持同一 key）→ 更新
  ``upload_file.storage_backend`` 字段
- 可选在迁移成功后删除源后端对象（默认保留，安全兜底）

历史文件（``storage_backend IS NULL``）归属到 ``STORAGE_BACKEND``
环境变量指定的旧后端，保证迁移列表准确不重复。
"""
import logging
import math
import os
from dataclasses import dataclass
from types import SimpleNamespace

from injector import inject
from sqlalchemy import or_

from internal.exception import FailException, ValidateErrorException
from internal.model import UploadFile
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


def _legacy_backend() -> str:
    """历史文件（storage_backend IS NULL）归属的旧后端。"""
    return (os.getenv("STORAGE_BACKEND") or "local").strip().lower()


def _resolve_file_backend(file) -> str:
    """解析文件的真实后端：storage_backend 为空时按历史后端处理。"""
    return (file.storage_backend or _legacy_backend()).strip().lower()


# ----------------------------------------------------------------------
# 底层对象读写（不创建 UploadFile 记录）
# ----------------------------------------------------------------------
def _read_bytes(backend: str, key: str) -> bytes:
    """从指定后端读取对象字节。"""
    if backend == "local":
        from internal.service.storage.local_storage_service import _get_local_storage_root, _safe_join
        path = _safe_join(_get_local_storage_root(), key)
        with open(path, "rb") as f:
            return f.read()

    if backend == "cos":
        from internal.service.cos_service import CosService
        client = CosService._get_client()
        bucket = CosService._get_bucket()
        resp = client.get_object(bucket, key)
        return resp["Body"].read()

    if backend == "oss":
        from internal.service.storage.aliyun_oss_service import AliyunOSSService
        bucket = AliyunOSSService._get_bucket()
        return bucket.get_object(key).read()

    raise FailException(f"不支持的存储后端: {backend}")


def _write_bytes(backend: str, key: str, content: bytes, mime_type: str | None = None) -> None:
    """向指定后端写入对象字节（保持同一 key）。"""
    if backend == "local":
        from internal.service.storage.local_storage_service import _get_local_storage_root, _safe_join
        path = _safe_join(_get_local_storage_root(), key)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return

    if backend == "cos":
        from internal.service.cos_service import CosService
        client = CosService._get_client()
        bucket = CosService._get_bucket()
        client.put_object(bucket, content, key)
        return

    if backend == "oss":
        from internal.service.storage.aliyun_oss_service import AliyunOSSService
        bucket = AliyunOSSService._get_bucket()
        bucket.put_object(key, content)
        return

    raise FailException(f"不支持的存储后端: {backend}")


def _delete_object(backend: str, key: str) -> None:
    """从指定后端删除对象（迁移成功后可选调用）。"""
    if backend == "local":
        from internal.service.storage.local_storage_service import _get_local_storage_root, _safe_join
        path = _safe_join(_get_local_storage_root(), key)
        if os.path.isfile(path):
            os.remove(path)
        return

    if backend == "cos":
        from internal.service.cos_service import CosService
        client = CosService._get_client()
        bucket = CosService._get_bucket()
        client.delete_object(bucket, key)
        return

    if backend == "oss":
        from internal.service.storage.aliyun_oss_service import AliyunOSSService
        bucket = AliyunOSSService._get_bucket()
        bucket.delete_object(key)
        return

    raise FailException(f"不支持的存储后端: {backend}")


def _object_exists(backend: str, key: str) -> bool:
    """判断对象是否真实存在（local 检查文件，cos/oss 做 HEAD 探测）。"""
    if backend == "local":
        from internal.service.storage.local_storage_service import _get_local_storage_root, _safe_join
        try:
            path = _safe_join(_get_local_storage_root(), key)
            return os.path.isfile(path)
        except Exception:
            return False

    if backend == "cos":
        try:
            from internal.service.cos_service import CosService
            client = CosService._get_client()
            bucket = CosService._get_bucket()
            client.head_object(bucket, key)
            return True
        except Exception:
            return False

    if backend == "oss":
        try:
            from internal.service.storage.aliyun_oss_service import AliyunOSSService
            bucket = AliyunOSSService._get_bucket()
            return bucket.object_exists(key)
        except Exception:
            return False

    return False


@inject
@dataclass
class StorageMigrationService:
    """文件迁移服务。"""

    db: SQLAlchemy

    @staticmethod
    def _build_source_filter(source_backend: str):
        """构建按源后端筛选的条件：历史 NULL 文件归属 legacy 后端。

        ``all`` 表示不做后端过滤（查看全部存储的文件）。
        """
        if (source_backend or "").strip().lower() == "all":
            return or_(True)
        condition = UploadFile.storage_backend == source_backend
        if source_backend == _legacy_backend():
            condition = or_(condition, UploadFile.storage_backend.is_(None))
        return condition

    def _query(
        self,
        source_backend: str,
        extension: str | None = None,
        search_word: str = "",
        file_ids: list | None = None,
    ):
        query = self.db.session.query(UploadFile).filter(self._build_source_filter(source_backend))
        if file_ids:
            query = query.filter(UploadFile.id.in_(file_ids))
        if extension:
            query = query.filter(UploadFile.extension == extension)
        if search_word:
            query = query.filter(UploadFile.name.ilike(f"%{search_word}%"))
        return query

    def list_files(
        self,
        *,
        source_backend: str,
        page: int = 1,
        page_size: int = 20,
        extension: str | None = None,
        search_word: str = "",
    ) -> dict:
        """分页列出可迁移文件（source_backend=all 时列出全部后端文件）。"""
        source_backend = (source_backend or "").strip().lower()
        if source_backend not in ("local", "cos", "oss", "all"):
            raise ValidateErrorException("源存储后端必须为 local / cos / oss / all")
        page = max(int(page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)

        base = self._query(source_backend, extension=extension, search_word=search_word)
        total = base.count()
        items = (
            base.order_by(UploadFile.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        all_records = (
            base.with_entities(
                UploadFile.id,
                UploadFile.hash,
                UploadFile.key,
                UploadFile.created_at,
            )
            .all()
        )
        dedupe_groups, _ = self.build_dedupe_meta(
            [
                SimpleNamespace(
                    id=record.id,
                    hash=record.hash,
                    key=record.key,
                    created_at=record.created_at,
                )
                for record in all_records
            ]
        )
        distinct_content = len(
            {
                (record.hash or "").strip() or (record.key or "")
                for record in all_records
                if (record.hash or "").strip() or (record.key or "")
            }
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total else 0,
            "total_record": total,
            "dedupe_groups": dedupe_groups,
            "summary": {
                "total": total,
                "distinct_content": distinct_content,
                "duplicate_records": max(total - distinct_content, 0),
            },
        }

    def list_extensions(self, source_backend: str) -> list[str]:
        """列出源后端下存在的文件扩展名（用于筛选下拉）。"""
        source_backend = (source_backend or "").strip().lower()
        rows = (
            self.db.session.query(UploadFile.extension)
            .filter(self._build_source_filter(source_backend))
            .group_by(UploadFile.extension)
            .order_by(UploadFile.extension.asc())
            .all()
        )
        return [r[0] for r in rows if r[0]]

    def migrate(
        self,
        *,
        source_backend: str,
        target_backend: str,
        file_ids: list | None = None,
        extension: str | None = None,
        search_word: str = "",
        delete_source: bool = False,
    ) -> dict:
        """迁移文件：全部或勾选 ID。

        Args:
            source_backend: 源后端（旧存储）
            target_backend: 目标后端（新存储）
            file_ids: 勾选迁移的文件 ID 列表；为空时迁移所有匹配文件
            extension: 扩展名筛选（配合"全部迁移"使用）
            search_word: 关键字筛选
            delete_source: 迁移成功后是否删除源对象（默认保留）

        Returns:
            {"total": n, "succeeded": n, "failed": n, "failures": [...]}
        """
        source_backend = (source_backend or "").strip().lower()
        target_backend = (target_backend or "").strip().lower()
        if source_backend not in ("local", "cos", "oss"):
            raise ValidateErrorException("源存储后端必须为 local / cos / oss")
        if target_backend not in ("local", "cos", "oss"):
            raise ValidateErrorException("目标存储后端必须为 local / cos / oss")
        if source_backend == target_backend:
            raise ValidateErrorException("源存储与目标存储不能相同")

        query = self._query(
            source_backend,
            extension=extension,
            search_word=search_word,
            file_ids=file_ids,
        )
        files = query.all()
        if not files:
            return {"total": 0, "succeeded": 0, "failed": 0, "failures": []}

        succeeded = 0
        failures = []
        for file in files:
            key = file.key or ""
            if not key:
                failures.append({"id": str(file.id), "name": file.name, "reason": "缺少对象 key"})
                continue
            try:
                content = _read_bytes(source_backend, key)
                _write_bytes(target_backend, key, content, file.mime_type)
                with self.db.auto_commit():
                    file.storage_backend = target_backend
                if delete_source:
                    try:
                        _delete_object(source_backend, key)
                    except Exception:
                        logger.warning(
                            "migrate: 源对象删除失败（保留源对象）backend=%s key=%s",
                            source_backend,
                            key,
                        )
                succeeded += 1
            except Exception as e:
                logger.warning(
                    "migrate failed: id=%s name=%s backend=%s->%s error=%s",
                    file.id, file.name, source_backend, target_backend, e,
                )
                failures.append({"id": str(file.id), "name": file.name, "reason": str(e)})

        logger.info(
            "storage migrate done: %s -> %s total=%s succeeded=%s failed=%s",
            source_backend, target_backend, len(files), succeeded, len(failures),
        )
        return {
            "total": len(files),
            "succeeded": succeeded,
            "failed": len(failures),
            "failures": failures,
        }

    def delete_files(
        self,
        *,
        file_ids: list,
        force: bool = False,
        deleted_by=None,
        retention_days: int | None = None,
    ) -> dict:
        """把文件移入回收站（记录入站，底层对象留存期结束后销毁）。

        force=False 时，仍被知识库文档引用的文件会被跳过并返回 in_use 列表。
        """
        file_ids = [str(fid) for fid in (file_ids or []) if str(fid).strip()]
        if not file_ids:
            raise ValidateErrorException("file_ids 不能为空")

        files = (
            self.db.session.query(UploadFile)
            .filter(UploadFile.id.in_(file_ids))
            .all()
        )
        succeeded = 0
        failures = []
        in_use = []
        from internal.service.recycle_bin_service import RecycleBinService

        recycle_service = RecycleBinService()
        for file in files:
            key = file.key or ""
            if not key:
                failures.append({"id": str(file.id), "name": file.name, "reason": "缺少对象 key"})
                continue

            if not force and self._is_file_in_use(file.id):
                in_use.append({"id": str(file.id), "name": file.name, "reason": "被知识库文档引用"})
                continue

            try:
                ok = recycle_service.delete_resource(
                    resource_type="upload_file",
                    resource_id=file.id,
                    resource_key=key,
                    resource_name=file.name,
                    deleted_by=deleted_by,
                    deleted_by_type="admin",
                    retention_days=retention_days,
                )
                if not ok:
                    failures.append({"id": str(file.id), "name": file.name, "reason": "文件不存在"})
                    continue
                succeeded += 1
            except Exception as exc:
                logger.warning("文件移入回收站失败: id=%s key=%s", file.id, key, exc_info=True)
                failures.append({"id": str(file.id), "name": file.name, "reason": str(exc)})

        return {
            "total": len(files),
            "succeeded": succeeded,
            "failed": len(failures),
            "in_use": in_use,
            "failures": failures,
        }

    def _is_file_in_use(self, file_id) -> bool:
        from internal.model import KnowledgeDocument
        return (
            self.db.session.query(KnowledgeDocument.id)
            .filter(KnowledgeDocument.upload_file_id == file_id)
            .first()
            is not None
        )

    def resolve_file_sources(self, file_ids: list) -> dict[str, dict]:
        """解析文件来源：知识库文档 / 对话图片 / 其他。"""
        from internal.model import KnowledgeBase, KnowledgeDocument, Message

        normalized_ids = [str(fid) for fid in file_ids]
        result: dict[str, dict] = {
            fid: {"type": "unknown", "label": "直接上传 / 未知"}
            for fid in normalized_ids
        }
        if not normalized_ids:
            return result

        rows = (
            self.db.session.query(
                KnowledgeDocument.upload_file_id,
                KnowledgeBase.name,
                KnowledgeDocument.name,
            )
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
            .filter(KnowledgeDocument.upload_file_id.in_(normalized_ids))
            .all()
        )
        for upload_file_id, base_name, doc_name in rows:
            if upload_file_id:
                result[str(upload_file_id)] = {
                    "type": "knowledge_document",
                    "label": f"知识库：{base_name or '-'} / {doc_name or '-'}",
                }

        # 对话消息图片引用（按 key 精确匹配，避免全表扫描）
        from internal.model import UploadFile
        key_by_id = {
            str(f.id): f.key
            for f in self.db.session.query(UploadFile.id, UploadFile.key)
            .filter(UploadFile.id.in_(normalized_ids))
            .all()
        }
        for fid, key in key_by_id.items():
            if not key or result.get(fid, {}).get("type") != "unknown":
                continue
            hit = (
                self.db.session.query(Message.id)
                .filter(
                    or_(
                        Message.image_urls.contains([key]),
                        Message.image_urls.contains([f"/storage/local/{key}"]),
                    )
                )
                .first()
            )
            if hit is not None:
                result[fid] = {"type": "chat_message", "label": "对话消息图片"}

        return result

    def list_valid_file_ids(self, files: list) -> set[str]:
        """返回底层对象真实存在的文件 ID 集合。"""
        valid_ids: set[str] = set()
        for file in files:
            key = file.key or ""
            if key and _object_exists(_resolve_file_backend(file), key):
                valid_ids.add(str(file.id))
        return valid_ids

    def build_dedupe_meta(self, files: list) -> tuple[dict, dict]:
        """按内容哈希（无哈希时按 key）计算重复分组与最新版本。"""
        groups: dict[str, dict] = {}
        latest_ids: dict[str, str] = {}
        for file in files:
            group_key = (file.hash or "").strip() or (file.key or "")
            if not group_key:
                continue
            group = groups.setdefault(
                group_key,
                {"size": 0, "latest_id": "", "latest_at": None},
            )
            group["size"] += 1
            created_at = file.created_at
            if created_at is not None and (
                group["latest_at"] is None or created_at > group["latest_at"]
            ):
                group["latest_at"] = created_at
                group["latest_id"] = str(file.id)
        for group_key, group in groups.items():
            latest_ids[group["latest_id"]] = group_key
        return groups, latest_ids
