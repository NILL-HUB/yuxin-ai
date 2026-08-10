"""技能详情查询工具（基因2, §8.6）。

LangChain BaseTool 包装器，让 Agent 可按需加载技能的 Tier1/Tier2 详情。
与 DigestManager._fetch_skills（Tier0 摘要注入）配合实现 Progressive Disclosure：

    Tier0: Digest 自动注入 name + description + use_count（每轮对话）
    Tier1: Agent 调用本工具查看 template + parameters（按需）
    Tier2: Agent 调用本工具查看 template + parameters + source_memories（深度按需）

设计参考: docs/prd/memory-system/03-consolidation-skill-policy-api.md §8.6
"""

from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field


class SkillDetailInput(BaseModel):
    """技能详情查询入参。"""

    skill_name: str = Field(
        description="要查询的技能名称（支持模糊匹配，如 '代码审查' 可匹配 '代码审查技能'）"
    )
    tier: int = Field(
        default=1,
        description=(
            "加载层级：1=模板+参数（默认），2=模板+参数+来源记忆。"
            "普通查询用 1，需要追溯技能来源时用 2"
        ),
    )


class SkillDetailTool(BaseTool):
    """Agent 可调用的技能详情查询工具。

    通过 Flask app context 获取 DigestManager，调用 get_skill_detail。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "get_skill_detail"
    description: str = (
        "查询已习得技能的模板与参数详情。"
        "当 Digest 中的技能摘要不足以完成任务时，调用此工具获取技能的完整模板。"
        "tier=2 可进一步获取技能的来源记忆。"
    )
    args_schema: type[BaseModel] = SkillDetailInput

    flask_app: Any = None
    account_id: Any = None

    def _run(self, skill_name: str, tier: int = 1, **kwargs: Any) -> str:
        if self.flask_app is None:
            return "技能详情不可用：缺少应用上下文"

        with self.flask_app.app_context():
            try:
                from app.http.app import injector
                from internal.service.memory.digest_manager import DigestManager

                dm = injector.get(DigestManager)
                return dm.get_skill_detail(
                    str(self.account_id), skill_name, tier
                )
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "SkillDetailTool._run: 查询失败", exc_info=True
                )
                return "技能详情查询失败"

    async def _arun(self, skill_name: str, tier: int = 1, **kwargs: Any) -> str:
        return self._run(skill_name, tier, **kwargs)


def create_skill_detail_tool(
    *,
    flask_app: Any,
    account_id: UUID,
) -> BaseTool:
    """创建技能详情查询工具实例。

    Args:
        flask_app: Flask 应用实例（用于在工具执行时 push app context）
        account_id: 用户账号 ID

    Returns:
        SkillDetailTool 实例
    """
    return SkillDetailTool(
        flask_app=flask_app,
        account_id=account_id,
    )
