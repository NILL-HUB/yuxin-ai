"""预置（内置）管理端 Agent 的幂等补建（设计 §10.3）。

为什么不复用 Agent 池：池成员是用户端 `app`（`agent_pool_config.app_id`
NOT NULL）+ 启停/健康元数据，**没有任何授权字段**；而治理 Agent 的授权
（`granted_permissions` / `automation_policy`）挂在 `admin_agent` 表。
把治理 Agent 塞进池要么伪造 `app` 行（正好落进用户端候选收集域 = 污染），
要么改池的数据模型。故预置 Agent 落 `admin_agent`，池继续只做用户端路由。

权限策略：预置**不下放任何权限**（`granted_permissions=[]`）。权限必须由
管理员显式下放（设计 §4.3「显式下放」）；`automation_policy={}` 由
`automation_level_for` 兜底为 `supervised`（fail closed）。
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

from injector import inject
from sqlalchemy.exc import IntegrityError

from internal.model import AdminAgent
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

# 预置 Agent 的幂等键：`internal/model/admin_agent.py` 中声明的部分唯一索引名。
# 只有来自该索引的冲突才代表"并发下已被另一请求建成"，才可跳过。
BUILTIN_UNIQUE_CONSTRAINT = "admin_agent_owner_builtin_uniq"

# PostgreSQL 唯一违规的 SQLSTATE。
UNIQUE_VIOLATION_SQLSTATE = "23505"


@lru_cache(maxsize=1)
def _unique_violation_classes() -> tuple[type, ...]:
    """各驱动暴露的"唯一违规"异常类（缺驱动则跳过，返回空元组 = 不上报）。"""
    classes: list[type] = []
    for module_name, attr in (
        ("psycopg2.errors", "UniqueViolation"),
        ("asyncpg.exceptions", "UniqueViolationError"),
    ):
        try:
            module = importlib.import_module(module_name)
        except ImportError:  # pragma: no cover - 驱动缺失时不该命中唯一冲突判定
            continue
        cls = getattr(module, attr, None)
        if isinstance(cls, type):
            classes.append(cls)
    return tuple(classes)


def _constraint_name_of(orig) -> str | None:
    """读取冲突约束名，兼容 psycopg2 与 asyncpg 的属性差异。

    - psycopg2：`exc.orig.diag.constraint_name`（`Error.diag` 服务端诊断对象）
    - asyncpg：只有 `exc.orig.constraint_name`（**没有** `diag`）
    """
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    if name:
        return name
    return getattr(orig, "constraint_name", None)


def _is_unique_violation(orig) -> bool:
    """确认底层异常**确为**唯一违规（SQLSTATE 23505）。取不到 pgcode 时退化为类型判定。"""
    pgcode = getattr(orig, "pgcode", None)
    if pgcode is not None:
        return pgcode == UNIQUE_VIOLATION_SQLSTATE
    return any(isinstance(orig, cls) for cls in _unique_violation_classes())


# 预置清单。新增项只需在此追加 + 在 prompts/index.yaml 登记对应 prompt_key。
BUILTIN_ADMIN_AGENTS: list[dict[str, str]] = [
    {
        "builtin_key": "ops_agent",
        "name": "运维 Agent",
        "description": "系统运维与工具治理：先查现状再动手，写操作按自动化级别分流",
        "prompt_key": "admin_agent_ops_agent",
    },
    {
        "builtin_key": "marketing_agent",
        "name": "运营 Agent",
        "description": "运营配置维护：套餐/兑换码/分销等，涉及计费字段最高谨慎",
        "prompt_key": "admin_agent_marketing_agent",
    },
]


# 必须带 @inject（否则 `a._get_service(AdminAgentBuiltinService)` 运行时 CallError）
@inject
@dataclass
class AdminAgentBuiltinService:
    db: SQLAlchemy

    def ensure_builtin_agents(self, admin_user_id: UUID) -> int:
        """为该管理员补齐缺失的预置 Agent，返回新建条数（幂等）。

        并发安全：靠 `admin_agent_owner_builtin_uniq`（部分唯一索引）兜底；
        **仅**该索引的唯一约束冲突被当作"另一请求已建成"而跳过，其余异常
        一律上抛——表结构未迁移、列缺失一类的硬错误必须显式失败，不能被
        伪装成"并发已存在"而静默吞掉。

        入参归一化：服务层契约为 `UUID`（与 `AdminAgentConversationService`
        等一致），路由层可能传字符串。字符串与 UUID 列比较在 DB 侧可比较，
        但入库字段类型会随入参漂移，故入口统一 `UUID(str(...))` 归一化，
        保证落库的 `owner_admin_user_id` 恒为 UUID 实例。
        """
        admin_user_id = UUID(str(admin_user_id))
        existing = {
            row.builtin_key
            for row in self.db.session.query(AdminAgent)
            .filter_by(owner_admin_user_id=admin_user_id)
            .all()
            if getattr(row, "builtin_key", None)
        }
        created = 0
        for item in BUILTIN_ADMIN_AGENTS:
            if item["builtin_key"] in existing:
                continue
            try:
                with self.db.auto_commit():
                    self.db.session.add(
                        AdminAgent(
                            owner_admin_user_id=admin_user_id,
                            name=item["name"],
                            description=item["description"],
                            prompt_key=item["prompt_key"],
                            granted_permissions=[],
                            automation_policy={},
                            budget_config={},
                            builtin_key=item["builtin_key"],
                            enabled=True,
                        )
                    )
                created += 1
            except IntegrityError as exc:
                if not self._is_builtin_conflict(exc):
                    raise
                # 并发下已被另一请求建成：auto_commit() 的异常路径已 rollback
                # 并 remove 了该 session（见 `pkg/sqlalchemy` 的 `_DualAutoCommit`），
                # 此处无需再 rollback。
                logger.info(
                    "预置 Agent 已存在（并发），跳过 builtin_key=%s", item["builtin_key"]
                )
        return created

    @staticmethod
    def _is_builtin_conflict(exc: IntegrityError) -> bool:
        """判断 IntegrityError 是否来自预置 Agent 的幂等唯一索引。

        必须**先确证底层错误是唯一违规**（SQLSTATE 23505），再校验约束名：

        - `pgcode`：psycopg2 原文提供；asyncpg 由 SQLAlchemy 方言在异常翻译时
          从 `sqlstate` 回填，故优先取 `exc.orig.pgcode`。
        - 取不到 `pgcode` 时退化为 `isinstance(exc.orig, UniqueViolation)` 类型判定。
        - 约束名读取需兼容两个驱动：psycopg2 走 `exc.orig.diag.constraint_name`，
          asyncpg **没有 `diag`**、只有 `exc.orig.constraint_name`。

        只有"确证唯一违规 **且**（约束名 == `admin_agent_owner_builtin_uniq`
        或约束名不可得）"才返回 True。凡是无法确证唯一违规的——包括
        `constraint_name=None` 且拿不到 pgcode 的（实测 NOT NULL 违规 23502
        就命中此形态）、以及 23503/23514 等——一律返回 False 让异常上抛。

        核心原则：宁可让真并发冲突上抛（调用方可重试），也不要把表结构
        未迁移、列缺失一类的硬错误静默吞成"创建成功"。
        """
        orig = getattr(exc, "orig", None)
        if orig is None:
            return False
        if not _is_unique_violation(orig):
            logger.warning(
                "IntegrityError 非唯一违规（pgcode=%s），按硬错误上抛：%s",
                getattr(orig, "pgcode", None),
                exc,
            )
            return False
        constraint_name = _constraint_name_of(orig)
        if constraint_name is None:
            logger.warning(
                "IntegrityError 确为唯一违规但缺少 constraint_name 诊断信息，"
                "按预置 Agent 并发冲突处理：%s",
                exc,
            )
            return True
        return constraint_name == BUILTIN_UNIQUE_CONSTRAINT
