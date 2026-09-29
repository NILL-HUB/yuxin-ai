"""用户文件中心服务：虚拟目录树的读取与组织操作。

只做「组织层」：物理对象归 RuntimeStorageProxy，删除/恢复归 RecycleBinService。
"""
from dataclasses import dataclass, field

from injector import inject

from internal.core.ports.storage_port import ObjectStoragePort
from internal.exception import NotFoundException, ValidateErrorException
from internal.extension.database_extension import db
from internal.model import FileCenterEntry, UploadFile
from internal.service.file_center_paths import ensure_path
from internal.service.recycle_bin_service import RecycleBinService

_MAX_NAME_LEN = 512


@inject
@dataclass
class FileCenterService:
    """文件中心虚拟目录树服务。"""

    recycle_bin_service: RecycleBinService = field(default=None)
    storage: ObjectStoragePort = field(default=None)

    # ------------------------------------------------------------------ #
    #  读取
    # ------------------------------------------------------------------ #
    def list_children(self, account_id, parent_id=None) -> list[FileCenterEntry]:
        """列出某目录下的直接子节点；parent_id 为 None 时列账号根。"""
        query = db.session.query(FileCenterEntry).filter(
            FileCenterEntry.account_id == account_id
        )
        if parent_id is None:
            query = query.filter(FileCenterEntry.parent_id.is_(None))
        else:
            query = query.filter(FileCenterEntry.parent_id == parent_id)
        return query.order_by(
            FileCenterEntry.is_folder.desc(), FileCenterEntry.name.asc()
        ).all()

    def list_all_files(self, *, account_id, page: int = 1, page_size: int = 20) -> dict:
        """「全部文件」视图：账号下已入树的文件节点（分页）。"""
        import math

        page = max(int(page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = db.session.query(FileCenterEntry).filter(
            FileCenterEntry.account_id == account_id,
            FileCenterEntry.is_folder.is_(False),
        )
        total = query.count()
        rows = (
            query.order_by(FileCenterEntry.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [
            {
                "entry_id": str(row.id),
                "upload_file_id": str(row.upload_file_id) if row.upload_file_id else None,
                "name": row.name,
                "source": row.source,
                "origin": row.origin,
                "organized": True,
            }
            for row in rows
        ]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total else 0,
            "total_record": total,
        }

    # ------------------------------------------------------------------ #
    #  组织操作
    # ------------------------------------------------------------------ #
    def mkdir(self, account_id, *, parent_id=None, name: str) -> FileCenterEntry:
        """在 parent_id 下新建目录。"""
        name = self._validate_name(name)
        if parent_id is not None:
            self._get_owned_entry(account_id, parent_id, expect_folder=True)
        self._assert_no_conflict(account_id, parent_id, name)
        entry = FileCenterEntry(
            account_id=account_id,
            parent_id=parent_id,
            name=name,
            is_folder=True,
            source="upload",
        )
        db.session.add(entry)
        db.session.commit()
        return entry

    def rename(self, account_id, entry_id, new_name: str) -> FileCenterEntry:
        """重命名节点（只改展示名，不动物理对象）。"""
        entry = self._get_owned_entry(account_id, entry_id)
        new_name = self._validate_name(new_name)
        if new_name == entry.name:
            return entry
        self._assert_no_conflict(account_id, entry.parent_id, new_name, exclude_id=entry.id)
        entry.name = new_name
        db.session.commit()
        return entry

    def move(self, account_id, entry_id, new_parent_id) -> FileCenterEntry:
        """把节点移动到 new_parent_id 目录下（禁止移动到自身子孙）。"""
        entry = self._get_owned_entry(account_id, entry_id)
        target_parent_id = None if new_parent_id in (None, "") else new_parent_id
        if target_parent_id is not None:
            self._get_owned_entry(account_id, target_parent_id, expect_folder=True)
            self._assert_not_cycle(entry, target_parent_id)
        self._assert_no_conflict(account_id, target_parent_id, entry.name, exclude_id=entry.id)
        entry.parent_id = target_parent_id
        db.session.commit()
        return entry

    def import_upload_file(
        self,
        account_id,
        *,
        upload_file_id,
        parent_id=None,
        name: str,
        source: str = "upload",
        origin: str | None = None,
    ) -> FileCenterEntry:
        """把一个 UploadFile 挂到指定目录下（已存在则直接返回其节点）。"""
        if parent_id is not None:
            self._get_owned_entry(account_id, parent_id, expect_folder=True)
        existing = (
            db.session.query(FileCenterEntry)
            .filter(
                FileCenterEntry.account_id == account_id,
                FileCenterEntry.upload_file_id == upload_file_id,
            )
            .one_or_none()
        )
        if existing is not None:
            return existing
        name = self._validate_name(name)
        self._assert_no_conflict(account_id, parent_id, name)
        entry = FileCenterEntry(
            account_id=account_id,
            parent_id=parent_id,
            name=name,
            is_folder=False,
            upload_file_id=upload_file_id,
            source=source,
            origin=origin,
        )
        db.session.add(entry)
        db.session.commit()
        return entry

    def delete_node(
        self,
        account_id,
        entry_id,
        *,
        deleted_by_type: str = "user",
        retention_days: int | None = None,
    ) -> None:
        """删除节点：文件节点 → 底层 upload_file 入回收站；目录节点 → 递归。"""
        entry = self._get_owned_entry(account_id, entry_id)
        if entry.is_folder:
            file_entries = self._collect_descendant_file_entries(account_id, entry.id)
            folder_ids = [entry.id] + [
                e.id for e in self._collect_descendant_folder_entries(account_id, entry.id)
            ]
            for file_entry in file_entries:
                self._recycle_file(account_id, file_entry, deleted_by_type, retention_days)
            db.session.query(FileCenterEntry).filter(
                FileCenterEntry.id.in_(folder_ids)
            ).delete(synchronize_session=False)
            db.session.commit()
        else:
            self._recycle_file(account_id, entry, deleted_by_type, retention_days)
            db.session.query(FileCenterEntry).filter(
                FileCenterEntry.id == entry.id
            ).delete(synchronize_session=False)
            db.session.commit()

    # ------------------------------------------------------------------ #
    #  文件内容（读 / 存）
    # ------------------------------------------------------------------ #
    def read_file(self, account_id, entry_id, *, limit: int = 0) -> dict:
        """读取文件节点对应的文本内容（UTF-8 尽力解码；超长按 limit 截断行数）。"""
        import os
        import tempfile

        entry = self._get_owned_entry(account_id, entry_id)
        if entry.is_folder or not entry.upload_file_id:
            raise ValidateErrorException("不是可读取的文件")
        if self.storage is None:
            raise ValidateErrorException("存储服务不可用")
        upload_file = (
            db.session.query(UploadFile)
            .filter(UploadFile.id == entry.upload_file_id)
            .one_or_none()
        )
        if upload_file is None:
            raise NotFoundException("文件不存在")
        fd, tmp_path = tempfile.mkstemp()
        os.close(fd)
        try:
            self.storage.download_file(upload_file.key, tmp_path)
            with open(tmp_path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if limit and limit > 0:
            text = "\n".join(text.splitlines()[:limit])
        return {"ok": True, "name": upload_file.name, "content": text}

    def save_artifact(
        self,
        account_id,
        *,
        name: str,
        content: str,
        parent_id=None,
        folder: str = "产物",
    ) -> dict:
        """把一段文本保存为文件中心的产物（默认落 `产物/` 目录，不存在则创建）。"""
        if self.storage is None:
            raise ValidateErrorException("存储服务不可用")
        if parent_id is None:
            parent_id = ensure_path(account_id, [folder])
        upload_file = self.storage.upload_bytes(
            filename=self._validate_name(name),
            content=str(content).encode("utf-8"),
            account_id=account_id,
            folder="artifacts",
        )
        entry = self.import_upload_file(
            account_id,
            upload_file_id=upload_file.id,
            parent_id=parent_id,
            name=upload_file.name,
            source="artifact",
        )
        return {
            "ok": True,
            "entry_id": str(entry.id),
            "upload_file_id": str(upload_file.id),
            "name": entry.name,
        }

    def save_generated_asset(
        self,
        account_id,
        *,
        filename: str,
        content: bytes,
        folder: str = "generated-images",
        asset_folder: str = "产物",
    ) -> dict:
        """把生成的媒体资产落库并挂入文件中心，返回 upload_file / entry / url。

        供图片、视频等产物写入点**统一调用**：避免各处各写一套「建记录 + 入树」。
        """
        if self.storage is None:
            raise ValidateErrorException("存储服务不可用")
        upload_file = self.storage.upload_bytes(
            filename=filename,
            content=content,
            account_id=account_id,
            folder=folder,
        )
        parent_id = ensure_path(account_id, [asset_folder])
        entry = self.import_upload_file(
            account_id,
            upload_file_id=upload_file.id,
            parent_id=parent_id,
            name=upload_file.name,
            source="artifact",
        )
        return {
            "upload_file": upload_file,
            "entry": entry,
            "url": self.storage.get_file_url(
                upload_file.key, download_name=upload_file.name
            ),
        }

    # ------------------------------------------------------------------ #
    #  内部工具
    # ------------------------------------------------------------------ #
    def _recycle_file(
        self, account_id, entry: FileCenterEntry, deleted_by_type: str, retention_days
    ) -> None:
        if entry.upload_file_id and self.recycle_bin_service is not None:
            self.recycle_bin_service.delete_resource(
                resource_type="upload_file",
                resource_id=entry.upload_file_id,
                resource_name=entry.name,
                deleted_by=account_id,
                deleted_by_type=deleted_by_type,
                retention_days=retention_days,
            )

    def _collect_descendant_folder_entries(self, account_id, root_id) -> list[FileCenterEntry]:
        result: list[FileCenterEntry] = []
        frontier = [root_id]
        while frontier:
            rows = (
                db.session.query(FileCenterEntry)
                .filter(
                    FileCenterEntry.account_id == account_id,
                    FileCenterEntry.parent_id.in_(frontier),
                    FileCenterEntry.is_folder.is_(True),
                )
                .all()
            )
            result.extend(rows)
            frontier = [r.id for r in rows]
        return result

    def _collect_descendant_file_entries(self, account_id, root_id) -> list[FileCenterEntry]:
        folder_ids = [root_id] + [
            e.id for e in self._collect_descendant_folder_entries(account_id, root_id)
        ]
        return (
            db.session.query(FileCenterEntry)
            .filter(
                FileCenterEntry.account_id == account_id,
                FileCenterEntry.parent_id.in_(folder_ids),
                FileCenterEntry.is_folder.is_(False),
            )
            .all()
        )

    @staticmethod
    def _validate_name(name: str) -> str:
        text = str(name or "").strip()
        if not text:
            raise ValidateErrorException("名称不能为空")
        if len(text) > _MAX_NAME_LEN:
            raise ValidateErrorException("名称过长")
        if "/" in text or "\\" in text:
            raise ValidateErrorException("名称不能包含路径分隔符")
        return text

    def _get_owned_entry(
        self, account_id, entry_id, *, expect_folder: bool = False
    ) -> FileCenterEntry:
        entry = (
            db.session.query(FileCenterEntry)
            .filter(
                FileCenterEntry.id == entry_id,
                FileCenterEntry.account_id == account_id,
            )
            .one_or_none()
        )
        if entry is None:
            raise NotFoundException("目标不存在")
        if expect_folder and not entry.is_folder:
            raise ValidateErrorException("目标不是目录")
        return entry

    def _assert_no_conflict(
        self, account_id, parent_id, name: str, *, exclude_id=None
    ) -> None:
        query = db.session.query(FileCenterEntry).filter(
            FileCenterEntry.account_id == account_id,
            FileCenterEntry.name == name,
        )
        if parent_id is None:
            query = query.filter(FileCenterEntry.parent_id.is_(None))
        else:
            query = query.filter(FileCenterEntry.parent_id == parent_id)
        if exclude_id is not None:
            query = query.filter(FileCenterEntry.id != exclude_id)
        if query.one_or_none() is not None:
            raise ValidateErrorException("同级已存在同名节点")

    def _assert_not_cycle(self, entry: FileCenterEntry, new_parent_id) -> None:
        """沿 new_parent_id 向上回溯，若遇到 entry 自身即为成环。"""
        cursor = new_parent_id
        seen = set()
        while cursor is not None:
            if str(cursor) == str(entry.id):
                raise ValidateErrorException("不能移动到自身或其子目录下")
            if cursor in seen:
                raise ValidateErrorException("目录结构异常（存在环）")
            seen.add(cursor)
            parent = (
                db.session.query(FileCenterEntry.parent_id)
                .filter(
                    FileCenterEntry.id == cursor,
                    FileCenterEntry.account_id == entry.account_id,
                )
                .one_or_none()
            )
            cursor = parent[0] if parent is not None else None
