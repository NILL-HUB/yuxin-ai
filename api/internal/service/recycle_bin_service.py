"""系统资源回收站服务。

所有 admin 可管理的系统资源删除时先进入回收站：
- 删除 = 写入 recycle_bin（完整快照 + 留存期） + 物理删除原表记录
- 恢复 = 按快照重建原表记录（固定原主键，同名自动加后缀由调用方处理）
- 到期销毁 = celery 定时任务扫描 expire_at 到期记录，标记 expired
- 回收站不可手动清空，仅管理员可查看/恢复
"""
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from injector import inject

from internal.exception import NotFoundException, ValidateErrorException
from internal.model import Account, AdminUser, RecycleBin
from internal.service.recycle_bin_handlers import (
    physical_delete_resource,
    purge_resource,
    restore_resource,
    snapshot_resource,
)
from internal.extension.database_extension import db

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@inject
@dataclass
class RecycleBinService:
    """系统资源回收站服务。"""

    RESOURCE_TYPES = ("knowledge_base", "system_prompt", "app", "workflow", "skill", "mcp", "api_tool", "knowledge_document")
    DEFAULT_RETENTION_DAYS = 30
    RETENTION_CHOICES = (7, 30, 90, 180)

    def delete_resource(
        self,
        *,
        resource_type: str,
        resource_id,
        resource_key: str = "",
        resource_name: str = "",
        deleted_by=None,
        deleted_by_type: str = "admin",
        retention_days: int | None = None,
    ) -> bool:
        """把资源放入回收站并物理删除原记录。

        Args:
            deleted_by_type: 删除来源。
                - ``admin``：管理员删除（调用方负责在前端提示并选择留存天数）
                - ``user``：用户侧删除（静默入站，默认留存 30 天，仅管理员可见/恢复）

        Returns:
            True 成功入站；False 资源不存在
        """
        if resource_type not in self.RESOURCE_TYPES:
            raise ValidateErrorException(f"不支持的资源类型: {resource_type}")
        deleted_by_type = (deleted_by_type or "admin").strip().lower()
        if deleted_by_type not in ("admin", "user"):
            deleted_by_type = "admin"
        retention_days = int(retention_days or self.DEFAULT_RETENTION_DAYS)
        if retention_days not in self.RETENTION_CHOICES:
            retention_days = self.DEFAULT_RETENTION_DAYS

        snapshot = snapshot_resource(resource_type, resource_id, resource_key)
        if snapshot is None:
            return False

        now = _utcnow_naive()
        item = RecycleBin(
            resource_type=resource_type,
            resource_id=str(resource_id),
            resource_key=resource_key or str(resource_id),
            resource_name=resource_name,
            snapshot=snapshot,
            deleted_by=str(deleted_by) if deleted_by else None,
            deleted_by_type=deleted_by_type,
            deleted_at=now,
            retention_days=retention_days,
            expire_at=now + timedelta(days=retention_days),
            status="pending",
        )
        db.session.add(item)
        db.session.flush()
        physical_delete_resource(resource_type, resource_id, resource_key)
        db.session.commit()
        logger.info(
            "资源进入回收站 type=%s id=%s key=%s retention=%s天",
            resource_type, resource_id, resource_key, retention_days,
        )
        return True

    def list_items(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        resource_type: str | None = None,
        status: str = "pending",
        search_word: str = "",
        deleted_by_type: str | None = None,
    ) -> dict:
        """分页列出回收站条目。"""
        page = max(int(page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = db.session.query(RecycleBin)
        if resource_type:
            query = query.filter(RecycleBin.resource_type == resource_type)
        if deleted_by_type:
            query = query.filter(RecycleBin.deleted_by_type == deleted_by_type)
        if status:
            query = query.filter(RecycleBin.status == status)
        if search_word:
            query = query.filter(RecycleBin.resource_name.ilike(f"%{search_word}%"))
        total = query.count()
        items = (
            query.order_by(RecycleBin.deleted_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        self._attach_deleted_by_names(items)
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total else 0,
            "total_record": total,
        }

    def _attach_deleted_by_names(self, items: list[RecycleBin]) -> None:
        """把删除人 ID 批量解析为账号名（admin=管理员账号，user=用户账号）。"""
        admin_ids = {
            str(item.deleted_by)
            for item in items
            if item.deleted_by_type == "admin" and item.deleted_by
        }
        user_ids = {
            str(item.deleted_by)
            for item in items
            if item.deleted_by_type == "user" and item.deleted_by
        }
        admin_names: dict[str, str] = {}
        if admin_ids:
            rows = (
                db.session.query(AdminUser.id, AdminUser.name, AdminUser.username)
                .filter(AdminUser.id.in_(list(admin_ids)))
                .all()
            )
            admin_names = {str(row.id): (row.name or row.username) for row in rows}
        user_names: dict[str, str] = {}
        if user_ids:
            rows = (
                db.session.query(Account.id, Account.name, Account.username)
                .filter(Account.id.in_(list(user_ids)))
                .all()
            )
            user_names = {str(row.id): (row.name or row.username) for row in rows}
        for item in items:
            if not item.deleted_by:
                item.deleted_by_name = None
                continue
            if item.deleted_by_type == "admin":
                item.deleted_by_name = admin_names.get(str(item.deleted_by))
            elif item.deleted_by_type == "user":
                item.deleted_by_name = user_names.get(str(item.deleted_by))
            else:
                item.deleted_by_name = None

    def get_item(self, item_id: int) -> RecycleBin:
        item = db.session.query(RecycleBin).filter(RecycleBin.id == item_id).one_or_none()
        if item is None:
            raise NotFoundException("回收站条目不存在")
        return item

    def restore_item(self, item_id: int, admin_user_id=None) -> RecycleBin:
        """恢复回收站条目（按快照重建原表记录）。"""
        item = self.get_item(item_id)
        if item.status != "pending":
            raise ValidateErrorException("该条目已恢复或已销毁，不能重复恢复")
        ok = restore_resource(item.resource_type, item.snapshot)
        if not ok:
            raise ValidateErrorException("恢复失败：目标资源已存在或系统提示词库不存在")
        item.status = "restored"
        item.remark = f"已由管理员恢复（{_utcnow_naive().isoformat()}）"
        db.session.commit()
        logger.info("回收站条目已恢复 id=%s type=%s", item_id, item.resource_type)
        return item

    def purge_expired(self) -> dict:
        """扫描到期条目并彻底销毁（celery 定时任务调用）。

        只标记 expired，不做物理清理——资源记录在入站时已物理删除。
        """
        now = _utcnow_naive()
        expired = (
            db.session.query(RecycleBin)
            .filter(
                RecycleBin.status == "pending",
                RecycleBin.expire_at <= now,
            )
            .all()
        )
        purged = 0
        failed = 0
        for item in expired:
            try:
                purge_resource(item.resource_type, item.snapshot)
                item.status = "expired"
                item.remark = f"留存期已到，已彻底销毁（{now.isoformat()}）"
                purged += 1
            except Exception:
                failed += 1
                item.remark = "销毁失败"
                logger.exception("回收站到期销毁失败 id=%s type=%s", item.id, item.resource_type)
        if expired:
            db.session.commit()
        return {"purged": purged, "failed": failed, "total": len(expired)}
