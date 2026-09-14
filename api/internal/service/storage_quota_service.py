"""存储配额服务。

统一负责：
- 解析账号的总配额（默认基线 vs 生效套餐权益 + 已购扩展包）
- 读取 / 累加账号已用存储
- 上传前的配额校验（所有上传路径的统一收口点）

配额规则：
    total_quota = max(基线 5GB, 生效套餐 storage_quota_gb) + sum(已购扩展包 GB)
"""
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject
from sqlalchemy.exc import IntegrityError

from internal.entity.storage_quota_entity import (
    BYTES_PER_GB,
    DEFAULT_MAX_SINGLE_FILE_BYTES,
    DEFAULT_STORAGE_QUOTA_GB,
    MAX_SINGLE_FILE_FEATURE_KEY,
    STORAGE_QUOTA_FEATURE_KEY,
    StorageAddonPlanType,
)
from internal.exception import ForbiddenException
from internal.model import AccountStorageUsage, Membership, PlanEntitlement, PurchaseOrder
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

logger = logging.getLogger(__name__)


@inject
@dataclass
class StorageQuotaService(BaseService):
    """存储配额与用量服务。"""

    db: SQLAlchemy

    def resolve_total_quota_bytes(self, account_id: UUID) -> int:
        """解析账号的总配额（字节）。

        取「生效套餐的存储权益」与「默认基线」的较大值，再累加已购扩展包。
        """
        effective_base_gb = DEFAULT_STORAGE_QUOTA_GB
        plan_quota_gb = self._resolve_entitlement_gb(account_id, STORAGE_QUOTA_FEATURE_KEY)
        if plan_quota_gb > effective_base_gb:
            effective_base_gb = plan_quota_gb
        addon_gb = self._resolve_purchased_addon_gb(account_id)
        return (effective_base_gb + addon_gb) * BYTES_PER_GB

    def resolve_max_file_size_bytes(self, account_id: UUID) -> int:
        """解析账号的单文件上传上限（字节）。

        取「生效套餐的 max_single_file_gb 权益」，无权益时回退默认 15MB。
        分片上传的单个分片不受此限制；本上限约束单次上传的总字节数。
        """
        plan_quota_gb = self._resolve_entitlement_gb(account_id, MAX_SINGLE_FILE_FEATURE_KEY)
        if plan_quota_gb > 0:
            return plan_quota_gb * BYTES_PER_GB
        return DEFAULT_MAX_SINGLE_FILE_BYTES

    def _resolve_entitlement_gb(self, account_id: UUID, feature_key: str) -> int:
        """取当前生效会员套餐指定权益的整数值（GB）；无生效套餐返回 0。

        与 Membership.is_active 保持一致的生效判定：status=active 且未过期。
        """
        now = datetime.now(UTC).replace(tzinfo=None)
        membership = (
            self.db.session.query(Membership)
            .filter(
                Membership.account_id == account_id,
                Membership.status == "active",
                Membership.expires_at >= now,
            )
            .order_by(Membership.expires_at.desc())
            .first()
        )
        if membership is None:
            return 0
        entitlements = (
            self.db.session.query(PlanEntitlement)
            .filter_by(plan_id=membership.plan_id, feature_key=feature_key)
            .all()
        )
        if not entitlements:
            return 0
        return self._entitlement_gb(entitlements[0])

    @staticmethod
    def _entitlement_gb(entitlement) -> int:
        """把套餐权益解析为整数 GB；解析失败返回 0 并记日志。"""
        try:
            return int(entitlement.parsed_value)
        except (TypeError, ValueError, ArithmeticError):
            logger.warning(
                "解析 storage_quota_gb 权益失败，按 0 处理：feature_value=%r",
                getattr(entitlement, "feature_value", None),
            )
            return 0

    def _resolve_purchased_addon_gb(self, account_id: UUID) -> int:
        """累加账号所有已支付存储扩展包的容量（GB）。

        单次 JOIN 查询取回扩展包套餐的全部 storage_quota_gb 权益，避免 N+1。
        """
        entitlements = (
            self.db.session.query(PlanEntitlement)
            .join(PurchaseOrder, PurchaseOrder.plan_id == PlanEntitlement.plan_id)
            .filter(
                PurchaseOrder.account_id == account_id,
                PurchaseOrder.status == "paid",
                PurchaseOrder.plan_type == StorageAddonPlanType.STORAGE_ADDON.value,
                PlanEntitlement.feature_key == STORAGE_QUOTA_FEATURE_KEY,
            )
            .all()
        )
        total_gb = 0
        for entitlement in entitlements:
            total_gb += self._entitlement_gb(entitlement)
        return total_gb

    def get_used_bytes(self, account_id: UUID) -> int:
        """读取账号已用存储字节数；无记录视为 0。"""
        usage = (
            self.db.session.query(AccountStorageUsage)
            .filter_by(account_id=account_id)
            .one_or_none()
        )
        if usage is None:
            return 0
        return int(usage.used_bytes or 0)

    def get_usage_summary(self, account_id: UUID) -> dict:
        """返回配额概览，用于前端用量面板。"""
        total = self.resolve_total_quota_bytes(account_id)
        used = self.get_used_bytes(account_id)
        return {
            "total_bytes": total,
            "used_bytes": used,
            "remaining_bytes": max(total - used, 0),
            "usage_percent": round(used / total * 100, 2) if total > 0 else 0.0,
        }

    def check_quota(self, account_id: UUID, incoming_bytes: int) -> None:
        """上传前校验：超出配额时抛 ForbiddenException。

        仅做读校验，校验与后续写入之间不持锁，**存在并发超卖窗口**；
        需要强一致的场景请改用 ``consume_quota``（校验+累加在同一行锁内完成）。
        所有上传路径（用户页面上传 / 小钰帮传 / 外部数据源同步）必须调用本方法
        或 ``consume_quota``。
        """
        total = self.resolve_total_quota_bytes(account_id)
        used = self.get_used_bytes(account_id)
        self._assert_within_quota(total, used, incoming_bytes)

    def consume_quota(self, account_id: UUID, incoming_bytes: int) -> int:
        """原子预占：在同一把行锁内完成「校验 + 累加」，返回累加后的已用字节数。

        与 ``check_quota`` + ``add_usage`` 两步走的区别：本方法先对
        ``account_storage_usage`` 行加 ``FOR UPDATE`` 锁，再校验配额并写入，
        因此并发上传不会同时通过校验（关闭超卖窗口）。超配额时抛
        ``ForbiddenException`` 且不写入任何用量。

        无用量记录时新建；并发创建撞唯一约束时回退为累加。
        """
        if incoming_bytes <= 0:
            return self.get_used_bytes(account_id)

        total = self.resolve_total_quota_bytes(account_id)
        usage = (
            self.db.session.query(AccountStorageUsage)
            .filter_by(account_id=account_id)
            .with_for_update()
            .one_or_none()
        )
        if usage is None:
            self._assert_within_quota(total, 0, incoming_bytes)
            try:
                created = self.create(
                    AccountStorageUsage, account_id=account_id, used_bytes=incoming_bytes
                )
                return int(created.used_bytes)
            except IntegrityError:
                # 并发下另一事务已创建该账号用量记录，回退为加锁累加
                self.db.session.rollback()
                usage = (
                    self.db.session.query(AccountStorageUsage)
                    .filter_by(account_id=account_id)
                    .with_for_update()
                    .one_or_none()
                )
                if usage is None:
                    return self.get_used_bytes(account_id)

        used = int(usage.used_bytes or 0)
        self._assert_within_quota(total, used, incoming_bytes)
        new_value = used + incoming_bytes
        self.update(usage, used_bytes=new_value)
        return new_value

    @staticmethod
    def _assert_within_quota(total: int, used: int, incoming_bytes: int) -> None:
        """校验 used + incoming 是否超总量；超出则抛 ForbiddenException。"""
        if used + incoming_bytes > total:
            raise ForbiddenException(
                "存储空间不足，请购买存储扩展包后重试",
                {
                    "total_bytes": total,
                    "used_bytes": used,
                    "incoming_bytes": incoming_bytes,
                    "reason_code": "storage_quota_exceeded",
                },
            )

    def add_usage(self, account_id: UUID, bytes_delta: int) -> int:
        """累加账号已用存储；无记录时自动创建。返回累加后的已用字节数。"""
        if bytes_delta <= 0:
            return self.get_used_bytes(account_id)
        usage = (
            self.db.session.query(AccountStorageUsage)
            .filter_by(account_id=account_id)
            .with_for_update()
            .one_or_none()
        )
        if usage is None:
            try:
                created = self.create(AccountStorageUsage, account_id=account_id, used_bytes=bytes_delta)
                return int(created.used_bytes)
            except IntegrityError:
                # 并发下另一事务已创建该账号用量记录，回退为累加
                self.db.session.rollback()
                usage = (
                    self.db.session.query(AccountStorageUsage)
                    .filter_by(account_id=account_id)
                    .with_for_update()
                    .one_or_none()
                )
                if usage is None:
                    return self.get_used_bytes(account_id)
        new_value = int(usage.used_bytes or 0) + bytes_delta
        self.update(usage, used_bytes=new_value)
        return new_value

    def release_usage(self, account_id: UUID, bytes_delta: int) -> int:
        """释放账号已用存储（删除 / 销毁时调用）；下限为 0。返回释放后的字节数。"""
        if bytes_delta <= 0:
            return self.get_used_bytes(account_id)
        usage = (
            self.db.session.query(AccountStorageUsage)
            .filter_by(account_id=account_id)
            .with_for_update()
            .one_or_none()
        )
        if usage is None:
            return 0
        new_value = max(int(usage.used_bytes or 0) - bytes_delta, 0)
        self.update(usage, used_bytes=new_value)
        return new_value

