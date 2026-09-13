"""存储配额服务。

统一负责：
- 解析账号的总配额（默认基线 vs 生效套餐权益 + 已购扩展包）
- 读取 / 累加账号已用存储
- 上传前的配额校验（所有上传路径的统一收口点）

配额规则：
    total_quota = max(基线 5GB, 生效套餐 storage_quota_gb) + sum(已购扩展包 GB)
"""
from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.storage_quota_entity import (
    BYTES_PER_GB,
    DEFAULT_STORAGE_QUOTA_GB,
    STORAGE_QUOTA_FEATURE_KEY,
    StorageAddonPlanType,
)
from internal.exception import ForbiddenException
from internal.model import AccountStorageUsage, Membership, PlanEntitlement, PurchaseOrder
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class StorageQuotaService(BaseService):
    """存储配额与用量服务。"""

    db: SQLAlchemy

    def resolve_total_quota_bytes(self, account_id: UUID) -> int:
        """解析账号的总配额（字节）。

        取「生效套餐的存储权益」与「默认基线」的较大值，再累加已购扩展包。
        """
        base_quota_gb = DEFAULT_STORAGE_QUOTA_GB
        plan_quota_gb = self._resolve_active_plan_quota_gb(account_id)
        if plan_quota_gb > base_quota_gb:
            base_quota_gb = plan_quota_gb
        addon_gb = self._resolve_purchased_addon_gb(account_id)
        return (base_quota_gb + addon_gb) * BYTES_PER_GB

    def _resolve_active_plan_quota_gb(self, account_id: UUID) -> int:
        """取当前生效会员套餐的 storage_quota_gb；无生效套餐返回 0。"""
        membership = (
            self.db.session.query(Membership)
            .filter_by(account_id=account_id, status="active")
            .order_by(Membership.expires_at.desc())
            .first()
        )
        if membership is None:
            return 0
        entitlements = (
            self.db.session.query(PlanEntitlement)
            .filter_by(plan_id=membership.plan_id, feature_key=STORAGE_QUOTA_FEATURE_KEY)
            .all()
        )
        if not entitlements:
            return 0
        try:
            return int(entitlements[0].feature_value)
        except (TypeError, ValueError):
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
            try:
                total_gb += int(entitlement.feature_value)
            except (TypeError, ValueError):
                continue
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

        所有上传路径（用户页面上传 / 小钰帮传 / 外部数据源同步）必须调用本方法。
        """
        total = self.resolve_total_quota_bytes(account_id)
        used = self.get_used_bytes(account_id)
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
