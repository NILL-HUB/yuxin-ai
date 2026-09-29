"""文件中心工具：让 Agent 在用户文件中心（虚拟目录树）上操作。

与用户**同一命名空间**：Agent 建目录/移动/删除/保存产物的结果，用户侧
`/space/files` 立即可见；删除同样进回收站可恢复；配额同样收口。
"""
import json
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class FileCenterInput(BaseModel):
    """文件中心操作输入。"""

    op: Literal["list", "mkdir", "move", "rename", "delete", "read", "save_artifact"] = Field(
        ...,
        description=(
            "list=列目录；mkdir=建目录；move=移动；rename=重命名；"
            "delete=删除（进入回收站，可恢复）；read=读取文本文件；save_artifact=保存文本产物"
        ),
    )
    parent_id: str = Field(
        "", description="目标目录节点 id；空表示账号根（list/mkdir/move/save_artifact）"
    )
    entry_id: str = Field("", description="目标节点 id（rename/move/delete/read）")
    name: str = Field("", description="名称（mkdir/rename/save_artifact）")
    content: str = Field("", description="文本内容（save_artifact）")
    limit: int = Field(0, ge=0, description="read 时读取的最大行数；0 表示默认")
    requester: str = Field("", description="调用方账号 ID，由平台注入")


class FileCenterTool(BaseTool):
    """在用户文件中心上操作（与用户同一命名空间）。"""

    name: str = "file_center"
    description: str = (
        "在用户的文件中心（虚拟目录树）上操作：列目录 / 建目录 / 移动 / 重命名 / "
        "删除 / 读取 / 保存文本产物。删除会进入用户回收站可恢复。"
        "所有操作只作用于当前账号自己的文件中心。"
    )
    args_schema: type[BaseModel] = FileCenterInput
    requester: str = ""

    def _run(self, **kwargs: Any) -> str:
        from app.http.module import injector

        from internal.service.file_center_service import FileCenterService

        op = str(kwargs.get("op") or "list").strip().lower()
        account_id = str(kwargs.get("requester") or self.requester or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少调用方账号"}, ensure_ascii=False)
        service = injector.get(FileCenterService)
        try:
            if op == "list":
                items = service.list_children(
                    account_id, parent_id=kwargs.get("parent_id") or None
                )
                return json.dumps(
                    {
                        "ok": True,
                        "items": [
                            {
                                "id": str(e.id),
                                "name": e.name,
                                "is_folder": bool(e.is_folder),
                                "upload_file_id": str(e.upload_file_id)
                                if e.upload_file_id
                                else None,
                            }
                            for e in items
                        ],
                    },
                    ensure_ascii=False,
                )
            if op == "mkdir":
                entry = service.mkdir(
                    account_id,
                    parent_id=kwargs.get("parent_id") or None,
                    name=str(kwargs.get("name") or ""),
                )
                return json.dumps(
                    {"ok": True, "id": str(entry.id), "name": entry.name}, ensure_ascii=False
                )
            if op == "move":
                entry = service.move(
                    account_id, kwargs.get("entry_id"), kwargs.get("parent_id") or None
                )
                return json.dumps({"ok": True, "id": str(entry.id)}, ensure_ascii=False)
            if op == "rename":
                entry = service.rename(
                    account_id, kwargs.get("entry_id"), str(kwargs.get("name") or "")
                )
                return json.dumps(
                    {"ok": True, "id": str(entry.id), "name": entry.name}, ensure_ascii=False
                )
            if op == "delete":
                service.delete_node(account_id, kwargs.get("entry_id"))
                return json.dumps(
                    {"ok": True, "message": "已移入回收站"}, ensure_ascii=False
                )
            if op == "read":
                result = service.read_file(
                    account_id, kwargs.get("entry_id"), limit=int(kwargs.get("limit") or 0)
                )
                return json.dumps(result, ensure_ascii=False, default=str)
            if op == "save_artifact":
                result = service.save_artifact(
                    account_id,
                    name=str(kwargs.get("name") or ""),
                    content=str(kwargs.get("content") or ""),
                    parent_id=kwargs.get("parent_id") or None,
                )
                return json.dumps(result, ensure_ascii=False, default=str)
            return json.dumps({"ok": False, "error": f"未知操作: {op}"}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 - 工具层统一转结构化错误
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def file_center(**kwargs: Any) -> BaseTool:
    """工厂函数：返回文件中心工具实例（注入 requester=账号 ID）。"""
    return FileCenterTool(requester=str(kwargs.get("requester") or ""))