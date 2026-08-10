"""Agent 主动记忆策展工具（基因4, §2.5）。

三个 LangChain BaseTool，让 Agent 可主动管理用户记忆：
    - memory_add:    新增记忆（调用 LedgerWriter.write_agent_curated）
    - memory_replace: 替换记忆（标记旧记忆 superseded + 写入新记忆）
    - memory_remove:  移除记忆（标记 deprecated）

与系统自动写入路径形成双路径：
    - 系统路径：对话后自动提取，source="system"
    - Agent 路径：Agent 调用本工具主动记录，source="agent_curated"

配额控制：每会话最多 memory_add_max_per_session 次（默认 5），通过 Redis 计数。

设计参考: docs/prd/memory-system/03-consolidation-skill-policy-api.md §2.5
"""

import logging
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# 会话级配额 Redis 键前缀
_QUOTA_KEY_PREFIX = "memory:agent_curated:quota:"


class MemoryAddInput(BaseModel):
    """memory_add 入参。"""

    content: str = Field(description="要记录的记忆内容（如用户偏好、习惯、重要事实）")
    memory_type: str = Field(
        default="preference",
        description=(
            "记忆类型：preference(偏好)/habit(习惯)/identity(身份)/"
            "goal(目标)/capability(能力)/episode(事件)"
        ),
    )


class MemoryReplaceInput(BaseModel):
    """memory_replace 入参。"""

    old_memory_id: str = Field(description="要替换的旧记忆 ID")
    new_content: str = Field(description="替换后的新记忆内容")
    memory_type: str = Field(
        default="preference",
        description="新记忆的类型（同 memory_add 的 memory_type）",
    )


class MemoryRemoveInput(BaseModel):
    """memory_remove 入参。"""

    memory_id: str = Field(description="要移除的记忆 ID")


def _check_quota(flask_app: Any, account_id: Any) -> bool:
    """检查会话级配额（每会话最多 memory_add_max_per_session 次）。

    通过 Redis 计数，TTL=24h（会话级）。降级时允许通过。
    """
    try:
        with flask_app.app_context():
            from internal.context import current_app
            from internal.config.memory_settings import settings

            max_per_session = settings.write.memory_add_max_per_session
            redis_client = current_app.extensions.get("redis")
            if redis_client is None:
                return True  # Redis 不可用时降级允许

            key = f"{_QUOTA_KEY_PREFIX}{account_id}"
            current = redis_client.incr(key)
            if current == 1:
                redis_client.expire(key, 86400)  # 24h TTL
            return current <= max_per_session
    except Exception:
        logger.warning("_check_quota: 配额检查失败，降级允许", exc_info=True)
        return True


class MemoryAddTool(BaseTool):
    """Agent 主动新增记忆工具。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "memory_add"
    description: str = (
        "主动记录用户的重要信息到长期记忆。"
        "适用于：用户明确表达的偏好/习惯/目标、重要事实、需要记住的约定。"
        "不要记录琐碎或临时的信息。每会话有次数限制，请谨慎使用。"
    )
    args_schema: type[BaseModel] = MemoryAddInput

    flask_app: Any = None
    account_id: Any = None

    def _run(self, content: str, memory_type: str = "preference", **kwargs: Any) -> str:
        if self.flask_app is None:
            return "记忆写入不可用：缺少应用上下文"

        with self.flask_app.app_context():
            # 配额检查
            if not _check_quota(self.flask_app, self.account_id):
                return "已达本会话记忆写入上限，请下次对话再记录"

            try:
                from app.http.app import injector
                from internal.service.memory.ledger_writer import LedgerWriter

                writer = injector.get(LedgerWriter)
                memory_id = writer.write_agent_curated(
                    account_id=self.account_id,
                    content=content,
                    memory_type=memory_type,
                )
                if memory_id:
                    return f"记忆已记录（ID: {memory_id}）"
                return "记忆写入失败"
            except Exception:
                logger.warning("MemoryAddTool._run: 失败", exc_info=True)
                return "记忆写入失败"

    async def _arun(self, content: str, memory_type: str = "preference", **kwargs: Any) -> str:
        return self._run(content, memory_type, **kwargs)


class MemoryReplaceTool(BaseTool):
    """Agent 主动替换记忆工具。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "memory_replace"
    description: str = (
        "替换已有记忆。旧记忆标记为已过时，新记忆写入。"
        "适用于：用户偏好改变、信息更新、纠正错误记忆。"
    )
    args_schema: type[BaseModel] = MemoryReplaceInput

    flask_app: Any = None
    account_id: Any = None

    def _run(self, old_memory_id: str, new_content: str, memory_type: str = "preference", **kwargs: Any) -> str:
        if self.flask_app is None:
            return "记忆替换不可用：缺少应用上下文"

        with self.flask_app.app_context():
            try:
                from app.http.app import injector
                from internal.service.memory.ledger_writer import LedgerWriter

                writer = injector.get(LedgerWriter)

                # 1. 标记旧记忆为 superseded
                ok = writer.invalidate_agent_curated(
                    account_id=self.account_id,
                    memory_id=old_memory_id,
                    action="replace",
                )
                if not ok:
                    return f"旧记忆 {old_memory_id} 不存在或无权操作"

                # 2. 写入新记忆
                new_id = writer.write_agent_curated(
                    account_id=self.account_id,
                    content=new_content,
                    memory_type=memory_type,
                    metadata={"replaces": old_memory_id},
                )
                if new_id:
                    return f"记忆已替换（新 ID: {new_id}，旧 ID: {old_memory_id}）"
                return "新记忆写入失败，旧记忆已标记为过时"
            except Exception:
                logger.warning("MemoryReplaceTool._run: 失败", exc_info=True)
                return "记忆替换失败"

    async def _arun(self, old_memory_id: str, new_content: str, memory_type: str = "preference", **kwargs: Any) -> str:
        return self._run(old_memory_id, new_content, memory_type, **kwargs)


class MemoryRemoveTool(BaseTool):
    """Agent 主动移除记忆工具。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "memory_remove"
    description: str = (
        "移除已有记忆（标记为已废弃）。"
        "适用于：用户要求忘记某事、记忆过时且无需替换。"
        "此操作不可逆，请确认后再调用。"
    )
    args_schema: type[BaseModel] = MemoryRemoveInput

    flask_app: Any = None
    account_id: Any = None

    def _run(self, memory_id: str, **kwargs: Any) -> str:
        if self.flask_app is None:
            return "记忆移除不可用：缺少应用上下文"

        with self.flask_app.app_context():
            try:
                from app.http.app import injector
                from internal.service.memory.ledger_writer import LedgerWriter

                writer = injector.get(LedgerWriter)
                ok = writer.invalidate_agent_curated(
                    account_id=self.account_id,
                    memory_id=memory_id,
                    action="remove",
                )
                if ok:
                    return f"记忆 {memory_id} 已移除"
                return f"记忆 {memory_id} 不存在或无权操作"
            except Exception:
                logger.warning("MemoryRemoveTool._run: 失败", exc_info=True)
                return "记忆移除失败"

    async def _arun(self, memory_id: str, **kwargs: Any) -> str:
        return self._run(memory_id, **kwargs)


def create_agent_memory_tools(
    *,
    flask_app: Any,
    account_id: UUID,
) -> list[BaseTool]:
    """创建 Agent 记忆策展工具集（memory_add + memory_replace + memory_remove）。

    Args:
        flask_app: Flask 应用实例
        account_id: 用户账号 ID

    Returns:
        包含三个 BaseTool 的列表
    """
    return [
        MemoryAddTool(flask_app=flask_app, account_id=account_id),
        MemoryReplaceTool(flask_app=flask_app, account_id=account_id),
        MemoryRemoveTool(flask_app=flask_app, account_id=account_id),
    ]
