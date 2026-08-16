"""系统资源回收站服务。

所有 admin 可管理的系统资源删除时先进入回收站：
- 删除 = 写入 recycle_bin（完整快照 + 留存期） + 物理删除原表记录
- 恢复 = 按快照重建原表记录（固定原主键，同名自动加后缀由调用方处理）
- 到期销毁 = celery 定时任务扫描 expire_at 到期记录，标记 expired
- 回收站不可手动清空；admin 回收站仅管理员可查看/恢复，
  用户回收站（含 agent 代删）仅归属账号可查看/恢复

删除来源（deleted_by_type）：
- ``admin``：管理员删除（前端选择留存天数，默认 30 天）
- ``user``：用户侧删除（前端选择留存天数，默认 30 天，用户端回收站可见/恢复）
- ``agent``：agent 代理删除（默认留存 7 天，到期自动销毁，期间用户可随时恢复）
"""
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from injector import inject

from internal.exception import ForbiddenException, NotFoundException, ValidateErrorException
from internal.model import Account, AdminUser, RecycleBin
from internal.service.recycle_bin_handlers import (
    physical_delete_resource,
    purge_resource,
    restore_resource,
    snapshot_resource,
)
from internal.extension.database_extension import db

logger = logging.getLogger(__name__)

# agent 代理删除的固定留存天数（用户侧回收站中 agent 删的内容一律 7 天）
AGENT_RETENTION_DAYS = 7


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@inject
@dataclass
class RecycleBinService:
    """系统资源回收站服务。"""

    RESOURCE_TYPES = (
        "knowledge_base",
        "system_prompt",
        "app",
        "workflow",
        "skill",
        "mcp",
        "api_tool",
        "knowledge_document",
        "upload_file",
        "os_file",
        "schedule_task",
        "external_data_source",
        "conversation",
        "memory",
    )
    # 用户端回收站可见类型：用户端（C 端）可删除/产生以下类型的条目——
    # 知识库/文档（用户删除）、本机文件（agent 代删）、定时任务/外部数据源/
    # 会话/个人记忆（用户删除）；app/workflow/skill/mcp/api_tool/system_prompt 等仅
    # admin 端管理，普通用户 JWT 已被拦截，回收站中不会出现这些条目。
    USER_VISIBLE_RESOURCE_TYPES = (
        "knowledge_base",
        "knowledge_document",
        "os_file",
        "schedule_task",
        "external_data_source",
        "conversation",
        "memory",
    )
    DEFAULT_RETENTION_DAYS = 30
    AGENT_RETENTION_DAYS = AGENT_RETENTION_DAYS
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
        agent_id=None,
    ) -> bool:
        """把资源放入回收站并物理删除原记录。

        Args:
            deleted_by_type: 删除来源。
                - ``admin``：管理员删除（调用方负责在前端提示并选择留存天数）
                - ``user``：用户侧删除（前端选择留存天数，默认 30 天，用户端回收站可见/恢复）
                - ``agent``：agent 代理删除（固定留存 7 天，用户端回收站可见/恢复）
            agent_id: agent 代理删除时的 agent 应用 ID（写入快照，便于审计/展示）
            retention_days: 留存天数；agent 来源时固定使用 7 天，忽略该参数。

        Returns:
            True 成功入站；False 资源不存在
        """
        if resource_type not in self.RESOURCE_TYPES:
            raise ValidateErrorException(f"不支持的资源类型: {resource_type}")
        deleted_by_type = (deleted_by_type or "admin").strip().lower()
        if deleted_by_type not in ("admin", "user", "agent"):
            deleted_by_type = "admin"
        if (
            deleted_by_type in ("user", "agent")
            and resource_type not in self.USER_VISIBLE_RESOURCE_TYPES
        ):
            raise ValidateErrorException(
                f"资源类型 {resource_type} 仅支持管理员删除，不能进入用户回收站"
            )
        if deleted_by_type == "agent":
            retention_days = self.AGENT_RETENTION_DAYS
        else:
            retention_days = int(retention_days or self.DEFAULT_RETENTION_DAYS)
            if retention_days not in self.RETENTION_CHOICES:
                retention_days = self.DEFAULT_RETENTION_DAYS

        snapshot = snapshot_resource(resource_type, resource_id, resource_key)
        if snapshot is None:
            return False
        if deleted_by_type == "agent" and agent_id is not None:
            snapshot["_agent_id"] = str(agent_id)

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
        """把删除人 ID 批量解析为账号名（admin=管理员账号，user/agent=用户账号）。

        仅查询合法 UUID 的 ID，避免历史脏数据（非 UUID 的 deleted_by）导致列表接口报错。
        """
        import uuid as _uuid

        def _valid_uuid(value: str) -> bool:
            try:
                _uuid.UUID(value)
                return True
            except (ValueError, TypeError, AttributeError):
                return False

        admin_ids = {
            str(item.deleted_by)
            for item in items
            if item.deleted_by_type == "admin"
            and item.deleted_by
            and _valid_uuid(str(item.deleted_by))
        }
        user_ids = {
            str(item.deleted_by)
            for item in items
            if item.deleted_by_type in ("user", "agent")
            and item.deleted_by
            and _valid_uuid(str(item.deleted_by))
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
            elif item.deleted_by_type in ("user", "agent"):
                item.deleted_by_name = user_names.get(str(item.deleted_by))
            else:
                item.deleted_by_name = None

    def get_item(self, item_id: int) -> RecycleBin:
        item = db.session.query(RecycleBin).filter(RecycleBin.id == item_id).one_or_none()
        if item is None:
            raise NotFoundException("回收站条目不存在")
        return item

    def _check_user_owned(self, item: RecycleBin, account_id) -> None:
        """校验回收站条目归属当前账号（user/agent 来源才可被用户端操作）。"""
        if item.resource_type not in self.USER_VISIBLE_RESOURCE_TYPES:
            raise ForbiddenException("无权限操作该回收站条目")
        if item.deleted_by_type not in ("user", "agent"):
            raise ForbiddenException("无权限操作该回收站条目")
        if str(item.deleted_by) != str(account_id):
            raise ForbiddenException("无权限操作该回收站条目")

    def restore_item(self, item_id: int, admin_user_id=None, operator_type: str = "admin") -> RecycleBin:
        """恢复回收站条目（按快照重建原表记录）。

        Args:
            operator_type: 操作来源（admin=管理员恢复 / user=用户恢复）。
        """
        item = self.get_item(item_id)
        if item.status != "pending":
            raise ValidateErrorException("该条目已恢复或已销毁，不能重复恢复")
        ok = restore_resource(item.resource_type, item.snapshot)
        if not ok:
            raise ValidateErrorException("恢复失败：目标资源已存在或系统提示词库不存在")
        item.status = "restored"
        if operator_type == "user":
            item.remark = f"已由用户恢复（{_utcnow_naive().isoformat()}）"
        else:
            item.remark = f"已由管理员恢复（{_utcnow_naive().isoformat()}）"
        db.session.commit()
        logger.info("回收站条目已恢复 id=%s type=%s by=%s", item_id, item.resource_type, operator_type)
        return item

    def list_user_items(
        self,
        *,
        account_id,
        page: int = 1,
        page_size: int = 20,
        resource_type: str | None = None,
        status: str = "pending",
        search_word: str = "",
        deleted_by_type: str | None = None,
    ) -> dict:
        """分页列出当前账号可见的回收站条目（user/agent 来源且归属于该账号）。

        resource_type 仅支持用户端可见类型（知识库/文档/本机文件/定时任务等）；
        admin 专属类型（app/workflow/skill/mcp/api_tool/system_prompt 等）会被过滤，
        即使历史数据误标为 user/agent 来源也不会出现在用户回收站。
        """
        page = max(int(page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = db.session.query(RecycleBin).filter(
            RecycleBin.deleted_by == str(account_id),
            RecycleBin.deleted_by_type.in_(("user", "agent")),
            RecycleBin.resource_type.in_(self.USER_VISIBLE_RESOURCE_TYPES),
        )
        if deleted_by_type in ("user", "agent"):
            query = query.filter(RecycleBin.deleted_by_type == deleted_by_type)
        if resource_type in self.USER_VISIBLE_RESOURCE_TYPES:
            query = query.filter(RecycleBin.resource_type == resource_type)
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

    def restore_user_item(
        self,
        item_id: int,
        account_id,
        *,
        target_path: str = "",
        confirm_device_mismatch: bool = False,
    ) -> RecycleBin:
        """用户端恢复回收站条目（校验归属，agent 代删内容同样可恢复）。

        os_file 恢复时启用设备校验：删除设备与当前设备不一致且未确认时抛
        DeviceMismatchException，由路由转换为 device_mismatch 响应供前端提示；
        target_path 用于「自选路径恢复」。
        """
        item = self.get_item(item_id)
        self._check_user_owned(item, account_id)
        if item.status != "pending":
            raise ValidateErrorException("该条目已恢复或已销毁，不能重复恢复")
        if item.resource_type == "os_file":
            ok = restore_resource(
                item.resource_type,
                item.snapshot,
                target_path=target_path,
                check_device=True,
                confirm_device_mismatch=confirm_device_mismatch,
            )
        else:
            ok = restore_resource(item.resource_type, item.snapshot)
        if not ok:
            raise ValidateErrorException("恢复失败：目标资源已存在或系统提示词库不存在")
        item.status = "restored"
        item.remark = f"已由用户恢复（{_utcnow_naive().isoformat()}）"
        db.session.commit()
        logger.info(
            "用户端回收站条目已恢复 id=%s type=%s account=%s",
            item_id, item.resource_type, account_id,
        )
        return item

    def record_os_file_deletion(
        self,
        *,
        entries: list[dict],
        deleted_by,
        deleted_by_type: str = "agent",
        agent_id=None,
        task_id: str = "",
        reason: str = "",
    ) -> list[int]:
        """记录 agent 本机文件删除到平台回收站（resource_type=os_file）。

        本机文件已被 worker 移入宿主机回收站，此处仅记录快照（含 entry_id /
        original_path / moved_to / recycle_root），便于用户端统一查看与恢复。
        """
        if not entries:
            return []
        deleted_by_type = (deleted_by_type or "agent").strip().lower()
        if deleted_by_type not in ("user", "agent"):
            deleted_by_type = "agent"
        now = _utcnow_naive()
        created_ids: list[int] = []
        for entry in entries:
            if not entry or not entry.get("entry_id"):
                continue
            original_path = str(entry.get("original_path") or "")
            item = RecycleBin(
                resource_type="os_file",
                resource_id=str(entry.get("entry_id") or ""),
                resource_key=str(entry.get("entry_id") or ""),
                resource_name=original_path.split(os.sep)[-1] or original_path,
                snapshot={
                    "os_entries": [entry],
                    "entry_id": entry.get("entry_id"),
                    "original_path": original_path,
                    "moved_to": entry.get("moved_to"),
                    "recycle_root": entry.get("recycle_root"),
                    "device_info": entry.get("device_info") or {},
                    "task_id": task_id,
                    "reason": reason,
                    "retention_days": entry.get("retention_days"),
                    "_agent_id": str(agent_id) if agent_id is not None else None,
                    "_deleted_by_type": deleted_by_type,
                },
                deleted_by=str(deleted_by) if deleted_by else None,
                deleted_by_type=deleted_by_type,
                deleted_at=now,
                retention_days=AGENT_RETENTION_DAYS,
                expire_at=now + timedelta(days=AGENT_RETENTION_DAYS),
                status="pending",
            )
            db.session.add(item)
            db.session.flush()
            created_ids.append(item.id)
        if created_ids:
            db.session.commit()
            logger.info(
                "本机文件删除已记录到平台回收站 count=%s by=%s type=%s",
                len(created_ids), deleted_by, deleted_by_type,
            )
        return created_ids

    def mark_os_file_restored(self, entry_ids: list[str], *, remark: str = "已由 agent 恢复") -> int:
        """把本机文件回收站记录标记为已恢复（agent 通过 os_recycle_bin restore 后调用）。"""
        if not entry_ids:
            return 0
        rows = (
            db.session.query(RecycleBin)
            .filter(
                RecycleBin.resource_type == "os_file",
                RecycleBin.resource_id.in_(list(entry_ids)),
                RecycleBin.status == "pending",
            )
            .all()
        )
        for row in rows:
            row.status = "restored"
            row.remark = f"{remark}（{_utcnow_naive().isoformat()}）"
        if rows:
            db.session.commit()
            logger.info("本机文件回收站记录已标记恢复 count=%s", len(rows))
        return len(rows)

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


RecycleBinService.ADMIN_ONLY_RESOURCE_TYPES = tuple(
    resource_type
    for resource_type in RecycleBinService.RESOURCE_TYPES
    if resource_type not in RecycleBinService.USER_VISIBLE_RESOURCE_TYPES
)
