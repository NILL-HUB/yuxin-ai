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

import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject
from sqlalchemy.exc import IntegrityError

from internal.model import AdminAgent
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

# 预置 Agent 的幂等键：`internal/model/admin_agent.py` 中声明的部分唯一索引名。
# 只有来自该索引的冲突才代表"并发下已被另一请求建成"，才可跳过。
BUILTIN_UNIQUE_CONSTRAINT = "admin_agent_owner_builtin_uniq"

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

        约束名经 `exc.orig.diag.constraint_name` 读取（asyncpg/psycopg2 的
        服务端诊断字段）；取不到时（驱动版本差异 / 非 DBAPI 异常）按
        IntegrityError 处理并记 warning——宁可放过一次真冲突，也不要让
        "并发已建"退化成对用户的报错。
        """
        diag = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = getattr(diag, "constraint_name", None)
        if constraint_name is None:
            logger.warning(
                "IntegrityError 缺少 constraint_name 诊断信息，按预置 Agent 并发冲突处理：%s",
                exc,
            )
            return True
        return constraint_name == BUILTIN_UNIQUE_CONSTRAINT
