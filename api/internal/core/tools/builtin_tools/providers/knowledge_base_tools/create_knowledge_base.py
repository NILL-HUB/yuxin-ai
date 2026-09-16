"""创建知识库板块工具（对话内建库）。

小钰在对话里帮用户建知识库板块：校验参数后调用
``KnowledgeBaseService.create_user_content_base`` 落库（用户资料库，
``operation_context="user"``）。

account 获取方式：与 ``computer_control`` / ``host_os`` 保持一致——
由运行时挂载点通过工厂参数 ``account_id`` 注入当前账号，工具内部再用
``AccountService`` 加载真实 ``Account`` 实例（服务层内部依赖 ``account.id``）。
builtin 工具没有全局 ``g.account``，因此不使用上下文穿透。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from internal.entity.knowledge_entity import (
    KnowledgeBaseType,
    OperationContext,
    PartitionMode,
)

logger = logging.getLogger(__name__)

VALID_BASE_TYPES = tuple(member.value for member in KnowledgeBaseType)
VALID_PARTITION_MODES = tuple(member.value for member in PartitionMode)


def _load_account(account_id: Any):
    """按账号 ID 加载真实 Account 实例，无法解析/不存在时返回 None。"""
    normalized = str(account_id or "").strip()
    if not normalized:
        return None
    try:
        account_uuid = UUID(normalized)
    except (ValueError, TypeError, AttributeError):
        return None
    try:
        from app.http.module import injector
        from internal.service.account_service import AccountService

        return injector.get(AccountService).get_account(account_uuid)
    except Exception:
        logger.warning("加载账号失败 account_id=%s", normalized, exc_info=True)
        return None


def _load_knowledge_base_service():
    """获取知识库服务单例。"""
    from app.http.module import injector
    from internal.service.knowledge_base_service import KnowledgeBaseService

    return injector.get(KnowledgeBaseService)


class CreateKnowledgeBaseInput(BaseModel):
    """创建知识库板块的输入模型。"""

    name: str = Field(..., description="知识库板块名称，不能为空，例如「视频素材库」")
    base_type: str = Field(
        "mixed",
        description=(
            "板块类型，决定允许的素材媒体类型，可选 document/image/video/audio/mixed，"
            "默认 mixed（通用库）"
        ),
    )
    partition_mode: str = Field(
        "none",
        description=(
            "分区模式，可选 none/date_month/date_day/custom，默认 none（不分区）；"
            "date_month 按月自动分区、date_day 按日自动分区、custom 手动分区"
        ),
    )
    description: str = Field("", description="板块描述，可选")


class CreateKnowledgeBaseTool(BaseTool):
    """在对话内为用户创建知识库板块。"""

    name: str = "create_knowledge_base"
    description: str = (
        "当用户明确要求创建/新建知识库、素材库、资料库板块时调用。"
        "支持指定板块类型（document/image/video/audio/mixed）与分区模式"
        "（none/date_month/date_day/custom），仅能为当前登录用户创建其私有板块。"
    )
    args_schema: type[BaseModel] = CreateKnowledgeBaseInput
    account_id: str = ""

    def _run(
        self,
        name: str = "",
        base_type: str = "mixed",
        partition_mode: str = "none",
        description: str = "",
        **kwargs: Any,
    ) -> str:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return json.dumps(
                {"ok": False, "error": "知识库名称不能为空"},
                ensure_ascii=False,
            )

        normalized_base_type = str(base_type or "").strip().lower()
        if normalized_base_type not in VALID_BASE_TYPES:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"不支持的板块类型：{normalized_base_type}，"
                        f"可选值：{list(VALID_BASE_TYPES)}"
                    ),
                },
                ensure_ascii=False,
            )

        normalized_partition_mode = str(partition_mode or "").strip().lower()
        if normalized_partition_mode not in VALID_PARTITION_MODES:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"不支持的分区模式：{normalized_partition_mode}，"
                        f"可选值：{list(VALID_PARTITION_MODES)}"
                    ),
                },
                ensure_ascii=False,
            )

        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps(
                {"ok": False, "error": "缺少当前账号信息，无法创建知识库"},
                ensure_ascii=False,
            )

        account = _load_account(account_id)
        if account is None:
            return json.dumps(
                {"ok": False, "error": f"账号不存在或不可用：{account_id}"},
                ensure_ascii=False,
            )

        try:
            service = _load_knowledge_base_service()
            knowledge_base = service.create_user_content_base(
                name=normalized_name,
                account=account,
                operation_context=OperationContext.USER.value,
                description=str(description or "").strip(),
                base_type=normalized_base_type,
                partition_mode=normalized_partition_mode,
            )
        except Exception as exc:
            logger.warning("创建知识库失败 name=%s", normalized_name, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"创建知识库失败：{exc}"},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": True,
                "knowledge_base_id": str(getattr(knowledge_base, "id", "")),
                "name": normalized_name,
                "base_type": normalized_base_type,
                "partition_mode": normalized_partition_mode,
                "message": f"已创建知识库板块「{normalized_name}」",
            },
            ensure_ascii=False,
        )

    async def _arun(
        self,
        name: str = "",
        base_type: str = "mixed",
        partition_mode: str = "none",
        description: str = "",
        **kwargs: Any,
    ) -> str:
        return self._run(
            name=name,
            base_type=base_type,
            partition_mode=partition_mode,
            description=description,
            **kwargs,
        )


def create_knowledge_base(**kwargs: Any) -> BaseTool:
    """工厂函数：返回创建知识库板块的 LangChain 工具。"""
    return CreateKnowledgeBaseTool(
        account_id=str(kwargs.get("account_id") or "").strip(),
    )
