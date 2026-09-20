"""upload_to_knowledge_base 工具（小钰帮传：对话内把素材文件建档入用户知识库）。

小钰在对话里帮用户把「平台已生成的文件（file_id，来自对话附件/先前上传）」存进
用户资料库：板块媒体类型硬约束 + 触发索引，与用户自传走同一链路、同一份数据。

安全边界：只接受 ``file_id``（平台 UploadFile），**不接受任意本地/远程路径**——
api 容器读不到用户本机文件，盲目读取会引入任意文件读取洞。文件字节的上传本身
由既有上传链路（chunked_upload / upload_file_service）完成并在上传阶段计入配额。
额外校验文件归属（``upload_file.account_id`` 必须等于当前账号），防止越权引用
他人文件建档。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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


def _load_upload_file_manager():
    """获取 UploadFile 管理服务（BaseService.get(model, pk) 按主键查询）。"""
    from app.http.module import injector
    from internal.service.upload_file_service import UploadFileService

    return injector.get(UploadFileService)


def _load_knowledge_base_service():
    """获取知识库服务单例。"""
    from app.http.module import injector
    from internal.service.knowledge_base_service import KnowledgeBaseService

    return injector.get(KnowledgeBaseService)


class UploadToKnowledgeBaseInput(BaseModel):
    """把平台已有文件建档进用户知识库的输入。"""

    knowledge_base_id: str = Field(..., description="目标知识库板块 id（用户自有板块）")
    file_id: str = Field(..., description="平台已生成的文件 id（对话附件或先前上传的文件）")
    partition_id: str = Field("", description="目标分区 id（可选；分区模式下建议提供）")


class UploadToKnowledgeBaseTool(BaseTool):
    """在对话内把素材文件建档进用户知识库。"""

    name: str = "upload_to_knowledge_base"
    description: str = (
        "当用户要求把文件/素材存入某个知识库板块时调用（如「把这个文件传到视频素材库」）。"
        "file_id 必须是平台已生成的文件 id（来自对话附件或先前上传）；会把该文件建档入"
        "目标知识库并触发解析索引，之后可被检索。仅能为当前登录用户操作其自有板块。"
    )
    args_schema: type[BaseModel] = UploadToKnowledgeBaseInput
    account_id: str = ""

    def _run(
        self,
        knowledge_base_id: str = "",
        file_id: str = "",
        partition_id: str = "",
        **kwargs: Any,
    ) -> str:
        kb_id = str(knowledge_base_id or "").strip()
        fid = str(file_id or "").strip()
        if not kb_id or not fid:
            return json.dumps(
                {"ok": False, "error": "需要同时提供知识库 id 与文件 id"},
                ensure_ascii=False,
            )

        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps(
                {"ok": False, "error": "缺少当前账号信息，无法上传素材"},
                ensure_ascii=False,
            )

        account = _load_account(account_id)
        if account is None:
            return json.dumps(
                {"ok": False, "error": f"账号不存在或不可用：{account_id}"},
                ensure_ascii=False,
            )

        try:
            from internal.model import UploadFile

            upload_file = _load_upload_file_manager().get(UploadFile, UUID(fid))
        except Exception:
            upload_file = None
        if upload_file is None:
            return json.dumps(
                {"ok": False, "error": "文件不存在或不可用"},
                ensure_ascii=False,
            )

        # 文件归属校验：防止引用他人文件建档（上传阶段已按账号记录 account_id）
        file_owner = str(getattr(upload_file, "account_id", "") or "")
        if file_owner and str(account.id) != file_owner:
            return json.dumps(
                {"ok": False, "error": "文件不存在或不可用"},
                ensure_ascii=False,
            )

        try:
            service = _load_knowledge_base_service()
            document = service.create_document_from_upload_file(
                knowledge_base_id=kb_id,
                upload_file=upload_file,
                account=account,
                partition_id=str(partition_id or "").strip() or None,
            )
        except Exception as exc:
            logger.warning("建档入知识库失败 kb=%s file=%s", kb_id, fid, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"上传素材失败：{exc}"},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": True,
                "document_id": str(getattr(document, "id", "")),
                "knowledge_base_id": kb_id,
                "file_id": fid,
                "message": "素材已存入知识库，正在解析索引",
            },
            ensure_ascii=False,
        )

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


def upload_to_knowledge_base(**kwargs: Any) -> BaseTool:
    """工厂函数：返回把文件建档进用户知识库的 LangChain 工具。"""
    return UploadToKnowledgeBaseTool(
        account_id=str(kwargs.get("account_id") or "").strip(),
    )