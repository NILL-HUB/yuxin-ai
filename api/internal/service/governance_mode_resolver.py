"""池治理模式解析器：根据 OrchestrationFeatureFlag 解析当前治理模式。

三阶段渐进式启用：
    - 阶段1 observe_only：只观测不阻断（默认启用）
    - 阶段2 block_sensitive：observe_only=False，仅对 sensitive/dangerous 工具阻断
    - 阶段3 block_all：observe_only=False，全量策略过滤

优先级：block_all > block_sensitive > observe_only（高阶段启用时忽略低阶段）。

开关通过管理员在功能开关页面操作，不改代码即可在阶段间切换。
表不存在或查询失败时降级为阶段1（observe_only），保证安全默认。
"""

from dataclasses import dataclass
from typing import Any

from injector import inject
from pkg.sqlalchemy import SQLAlchemy

from internal.entity.orchestration_feature_flag_entity import (
    POOL_GOVERNANCE_FLAG_BLOCK_ALL,
    POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE,
    POOL_GOVERNANCE_FLAG_OBSERVE_ONLY,
    POOL_GOVERNANCE_MODE_BLOCK_ALL,
    POOL_GOVERNANCE_MODE_BLOCK_SENSITIVE,
    POOL_GOVERNANCE_MODE_OBSERVE_ONLY,
)
from internal.model.orchestration_feature_flag import OrchestrationFeatureFlagModel


@inject
@dataclass
class GovernanceModeResolver:
    """根据 OrchestrationFeatureFlag 解析池治理当前模式。

    依赖：
        db: SQLAlchemy 数据库实例，用于查询 OrchestrationFeatureFlagModel
    """

    db: SQLAlchemy

    def resolve_mode(self) -> dict[str, Any]:
        """返回当前池治理模式。

        Returns:
            {
                "observe_only": bool,
                "block_sensitive": bool,
                "block_all": bool,
                "mode": str,
            }

        mode 取值：
            - "observe_only"：阶段1（observe_only=True，不阻断）
            - "block_sensitive"：阶段2（observe_only=False，仅 sensitive/dangerous 阻断）
            - "block_all"：阶段3（observe_only=False，全量过滤）

        优先级：block_all > block_sensitive > observe_only。
        查询异常或表缺失时降级为阶段1（安全默认）。
        """
        flags = self._query_flags()
        block_all = bool(flags.get(POOL_GOVERNANCE_FLAG_BLOCK_ALL, False))
        block_sensitive = bool(flags.get(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, False))
        observe_only_flag = bool(flags.get(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, True))

        if block_all:
            # 阶段3：全量阻断，observe_only=False, block_sensitive_only=False
            return {
                "observe_only": False,
                "block_sensitive": False,
                "block_all": True,
                "mode": POOL_GOVERNANCE_MODE_BLOCK_ALL,
            }
        if block_sensitive:
            # 阶段2：仅敏感工具阻断，observe_only=False, block_sensitive_only=True
            return {
                "observe_only": False,
                "block_sensitive": True,
                "block_all": False,
                "mode": POOL_GOVERNANCE_MODE_BLOCK_SENSITIVE,
            }
        if not observe_only_flag:
            # 观测门关闭且未开启阻断：完全跳过治理（不观测不阻断）
            return {
                "observe_only": False,
                "block_sensitive": False,
                "block_all": False,
                "mode": "disabled",
            }
        # 阶段1：只观测不阻断（默认启用）
        return {
            "observe_only": True,
            "block_sensitive": False,
            "block_all": False,
            "mode": POOL_GOVERNANCE_MODE_OBSERVE_ONLY,
        }

    def build_governance_context(self, **overrides: Any) -> dict[str, Any]:
        """构建 governance_context，供 AppRuntimeService.build_runtime_tools_for_config 使用。

        默认包含：
            - observe_only: bool（阶段1为True，阶段2/3为False）
            - block_sensitive_only: bool（阶段2为True，阶段3为False）
            - mode: str

        其他 overrides 透传（account_id/app_id/agent_pool/budget_level 等），
        调用方提供同名字段时以调用方为准（不覆盖调用方意图）。
        """
        mode_info = self.resolve_mode()
        context: dict[str, Any] = {
            "observe_only": mode_info["observe_only"],
            "block_sensitive_only": mode_info["block_sensitive"],
            "mode": mode_info["mode"],
        }
        # overrides 透传，且调用方显式提供的字段优先（覆盖默认）
        context.update(overrides)
        return context

    # ------------------------------------------------------------------ #
    #  私有方法                                                           #
    # ------------------------------------------------------------------ #

    def _query_flags(self) -> dict[str, bool]:
        """查询三个池治理开关的 enabled 状态。

        表不存在或查询异常时返回空 dict，调用方按默认值降级
        （observe_only=True, block_sensitive=False, block_all=False）。
        """
        codes = (
            POOL_GOVERNANCE_FLAG_OBSERVE_ONLY,
            POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE,
            POOL_GOVERNANCE_FLAG_BLOCK_ALL,
        )
        try:
            rows = (
                self.db.session.query(OrchestrationFeatureFlagModel)
                .filter(OrchestrationFeatureFlagModel.code.in_(codes))
                .all()
            )
        except Exception:
            return {}
        result: dict[str, bool] = {}
        for row in rows:
            result[row.code] = bool(row.enabled)
        return result
