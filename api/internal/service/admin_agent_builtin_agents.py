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

from injector import inject

from internal.model import AdminAgent
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

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

    def ensure_builtin_agents(self, admin_user_id) -> int:
        """为该管理员补齐缺失的预置 Agent，返回新建条数（幂等）。

        并发安全：靠 `admin_agent_owner_builtin_uniq`（部分唯一索引）兜底；
        冲突时忽略该条（另一个请求已建），不抛错。
        """
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
            except Exception:
                # 并发下已被另一请求建成：回滚该条并继续
                logger.info(
                    "预置 Agent 已存在（并发），跳过 builtin_key=%s", item["builtin_key"]
                )
                self.db.session.rollback()
        return created
