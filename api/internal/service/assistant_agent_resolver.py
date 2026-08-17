"""assistant agent 应用 ID 解析。

负责从 DB（app 表按名称）解析 assistant agent 应用 ID，替代直接依赖
环境变量 ASSISTANT_AGENT_ID 的旧逻辑，避免 .env 中占位符导致主链路静默失败。

独立成模块以规避 assistant_agent_service ↔ conversation_service 的循环导入。
"""

import logging
from uuid import UUID

from internal.context import current_app, has_app_context
from internal.entity.assistant_agent_entity import ASSISTANT_AGENT_DISPLAY_NAME
from internal.exception import NotFoundException

logger = logging.getLogger(__name__)

# 环境变量 ASSISTANT_AGENT_ID 的占位值（.env.example 默认值），用于识别"未真实配置"。
_ASSISTANT_AGENT_ID_PLACEHOLDER = "your-assistant-agent-id"


def resolve_assistant_agent_app_id(db) -> UUID:
    """按名称从 DB 解析 assistant agent 应用 ID。

    解析优先级：
    1. 按 name == ASSISTANT_AGENT_DISPLAY_NAME 查询 app 表（DB 链路，权威）；
    2. 兜底：env 配置的 ASSISTANT_AGENT_ID（兼容未建应用的历史部署 / 测试环境）；
    3. 仍未解析到或 env 为占位符时抛出异常，提示管理员先创建/标记应用。

    Args:
        db: SQLAlchemy 实例（含 session）。

    Returns:
        assistant agent 应用 id。

    Raises:
        NotFoundException: DB 与 env 均无法解析出有效的 assistant agent 应用 id。
    """
    if db is not None:
        try:
            from internal.model import App

            app = (
                db.session.query(App)
                .filter(App.name == ASSISTANT_AGENT_DISPLAY_NAME)
                .order_by(App.created_at.asc())
                .first()
            )
            if app is not None and app.id is not None:
                return app.id
        except Exception:
            logger.warning("按名称解析 assistant agent 应用失败，回退 env 配置", exc_info=True)

    configured = current_app.config.get("ASSISTANT_AGENT_ID") if has_app_context() else ""
    if configured and configured != _ASSISTANT_AGENT_ID_PLACEHOLDER:
        try:
            return UUID(str(configured))
        except (ValueError, TypeError):
            logger.warning("ASSISTANT_AGENT_ID 不是合法 UUID: %s", configured)

    raise NotFoundException(
        f"未找到名称为「{ASSISTANT_AGENT_DISPLAY_NAME}」的 assistant agent 应用，"
        "请先在后台创建该应用，或在环境变量 ASSISTANT_AGENT_ID 中配置其真实应用 ID"
    )


def try_resolve_assistant_agent_app_id(db) -> UUID | None:
    """安全版：解析失败时返回 None（用于展示类逻辑，不阻断主流程）。"""
    try:
        return resolve_assistant_agent_app_id(db)
    except Exception:
        logger.debug("assistant agent 应用 ID 解析失败，使用 None 兜底", exc_info=True)
        return None
