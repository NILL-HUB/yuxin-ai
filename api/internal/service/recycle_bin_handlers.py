"""系统资源回收站 - 各资源类型的快照/物理删除/恢复/销毁处理器。

统一约定：
- snapshot_resource: 删除前把资源完整数据（主记录 + 关联子记录）转成可 JSON 序列化的快照
- physical_delete_resource: 真正删除原表记录（含关联子表）
- restore_resource: 根据快照重建原表记录（固定原主键 ID）
- purge_resource: 到期彻底销毁时的收尾清理（存储文件/向量残留）

所有函数均为纯 DB 操作，不依赖各业务 Service，避免循环依赖。
"""
from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Any

from sqlalchemy import inspect

from internal.extension.database_extension import db
from internal.model import (
    App,
    AppConfig,
    AppConfigVersion,
    ApiTool,
    ApiToolProvider,
    Conversation,
    ConversationVariable,
    ExternalDataSource,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeSegment,
    McpProvider,
    McpTool,
    Message,
    MessageAgentThought,
    ScheduleTask,
    ScheduleTaskRun,
    SkillPackage,
    SkillPackageVersion,
    UploadFile,
    UserMemory,
    Workflow,
    WorkflowVersion,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 通用：基于 ORM 模型 + 子表配置的快照/恢复/删除
# ---------------------------------------------------------------------------
# 主表 → 关联子表配置：(Model, 外键列名)
_CHILD_TABLES: dict[str, list[tuple[Any, str]]] = {
    "app": [(AppConfig, "app_id"), (AppConfigVersion, "app_id")],
    "workflow": [(WorkflowVersion, "workflow_id")],
    "skill": [(SkillPackageVersion, "skill_package_id")],
    "mcp": [(McpTool, "provider_id")],
    "api_tool": [(ApiTool, "provider_id")],
}


def _main_model(resource_type: str):
    return {
        "app": App,
        "workflow": Workflow,
        "skill": SkillPackage,
        "mcp": McpProvider,
        "api_tool": ApiToolProvider,
    }[resource_type]


def _row_to_dict(row) -> dict[str, Any]:
    """把 ORM 行转成普通 dict（UUID/datetime 转字符串，JSONB 原样）。

    使用 column_attrs（Python 属性名，如 metadata_），避免列名/属性名
    不一致（metadata_ ↔ metadata）导致命中 ORM 类的 MetaData 类属性。
    """
    result = {}
    for col_attr in inspect(type(row)).mapper.column_attrs:
        key = col_attr.key
        value = getattr(row, key)
        if value is None:
            result[key] = None
        elif isinstance(value, (datetime, date)):
            result[key] = value.isoformat()
        elif hasattr(value, "hex"):  # UUID
            result[key] = str(value)
        else:
            result[key] = value
    return result


def _apply_column_value(model, row, col_name: str, value: Any) -> None:
    """把快照值写回 ORM 行（自动按列类型转换）。

    col_name 为快照 key（Python 属性名）。
    """
    if value is None:
        setattr(row, col_name, None)
        return
    col = inspect(model).columns.get(col_name)
    col_type = str(col.type).lower() if col is not None else ""
    if "datetime" in col_type and isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            pass
    setattr(row, col_name, value)


def snapshot_generic(resource_type: str, resource_id) -> dict[str, Any] | None:
    """通用快照：主表记录 + 关联子表记录。"""
    model = _main_model(resource_type)
    main = db.session.query(model).filter(model.id == resource_id).one_or_none()
    if main is None:
        return None
    snapshot: dict[str, Any] = {"main": _row_to_dict(main), "children": {}}
    for child_model, fk in _CHILD_TABLES.get(resource_type, []):
        rows = db.session.query(child_model).filter(
            getattr(child_model, fk) == resource_id,
        ).all()
        snapshot["children"][child_model.__tablename__] = [_row_to_dict(r) for r in rows]
    return snapshot


def physical_delete_generic(resource_type: str, resource_id) -> None:
    """通用物理删除：先删关联子表，再删主记录。"""
    model = _main_model(resource_type)
    for child_model, fk in _CHILD_TABLES.get(resource_type, []):
        db.session.query(child_model).filter(
            getattr(child_model, fk) == resource_id,
        ).delete(synchronize_session=False)
    db.session.query(model).filter(model.id == resource_id).delete(synchronize_session=False)


def restore_generic(resource_type: str, snapshot: dict[str, Any]) -> bool:
    """通用恢复：按快照重建主记录 + 关联子表（固定原主键）。"""
    model = _main_model(resource_type)
    main_data = snapshot.get("main") or {}
    if not main_data or not main_data.get("id"):
        return False
    if db.session.query(model).filter(model.id == main_data["id"]).one_or_none() is not None:
        return False  # 已被其他方式恢复
    main = model()
    for col_name, value in main_data.items():
        _apply_column_value(model, main, col_name, value)
    db.session.add(main)
    db.session.flush()
    for table_name, rows in (snapshot.get("children") or {}).items():
        child_model = next(
            (m for m, _ in _CHILD_TABLES.get(resource_type, []) if m.__tablename__ == table_name),
            None,
        )
        if child_model is None:
            continue
        for row_data in rows:
            child = child_model()
            for col_name, value in row_data.items():
                _apply_column_value(child_model, child, col_name, value)
            db.session.add(child)
    return True


# ---------------------------------------------------------------------------
# knowledge_base：特殊处理（含文档/分段/向量）
# ---------------------------------------------------------------------------
def snapshot_knowledge_base(resource_id) -> dict[str, Any] | None:
    base = db.session.query(KnowledgeBase).filter(KnowledgeBase.id == resource_id).one_or_none()
    if base is None:
        return None
    snapshot: dict[str, Any] = {
        "main": _row_to_dict(base),
        "documents": [],
    }
    docs = (
        db.session.query(KnowledgeDocument)
        .filter(KnowledgeDocument.knowledge_base_id == resource_id)
        .all()
    )
    for doc in docs:
        doc_data = _row_to_dict(doc)
        segments = (
            db.session.query(KnowledgeSegment)
            .filter(KnowledgeSegment.knowledge_document_id == doc.id)
            .order_by(KnowledgeSegment.position.asc())
            .all()
        )
        doc_data["_segments"] = [_row_to_dict(s) for s in segments]
        upload_file = None
        if getattr(doc, "upload_file_id", None) is not None:
            upload_file = (
                db.session.query(UploadFile)
                .filter(UploadFile.id == doc.upload_file_id)
                .one_or_none()
            )
        doc_data["_upload_file"] = _row_to_dict(upload_file) if upload_file is not None else None
        snapshot["documents"].append(doc_data)
    return snapshot


def physical_delete_knowledge_base(resource_id) -> None:
    """物理删除知识库：清向量 + 删分段/文档/上传文件记录/主记录。"""
    segments = (
        db.session.query(KnowledgeSegment)
        .filter(KnowledgeSegment.knowledge_base_id == resource_id)
        .all()
    )
    for segment in segments:
        try:
            from internal.service.knowledge_vector_service import KnowledgeVectorService
            KnowledgeVectorService().remove_segment(segment)
        except Exception as exc:
            logger.warning("清理知识库向量失败 segment=%s: %s", segment.id, exc)
    docs = (
        db.session.query(KnowledgeDocument)
        .filter(KnowledgeDocument.knowledge_base_id == resource_id)
        .all()
    )
    upload_file_ids = [d.upload_file_id for d in docs if getattr(d, "upload_file_id", None) is not None]
    db.session.query(KnowledgeSegment).filter(
        KnowledgeSegment.knowledge_base_id == resource_id,
    ).delete(synchronize_session=False)
    db.session.query(KnowledgeDocument).filter(
        KnowledgeDocument.knowledge_base_id == resource_id,
    ).delete(synchronize_session=False)
    if upload_file_ids:
        db.session.query(UploadFile).filter(
            UploadFile.id.in_(upload_file_ids),
        ).delete(synchronize_session=False)
    db.session.query(KnowledgeBase).filter(
        KnowledgeBase.id == resource_id,
    ).delete(synchronize_session=False)


def restore_knowledge_base(snapshot: dict[str, Any]) -> bool:
    main_data = snapshot.get("main") or {}
    if not main_data or not main_data.get("id"):
        return False
    if db.session.query(KnowledgeBase).filter(KnowledgeBase.id == main_data["id"]).one_or_none() is not None:
        return False
    base = KnowledgeBase()
    for col_name, value in main_data.items():
        _apply_column_value(KnowledgeBase, base, col_name, value)
    db.session.add(base)
    db.session.flush()
    for doc_data in snapshot.get("documents") or []:
        segments = doc_data.pop("_segments", [])
        upload_file_data = doc_data.pop("_upload_file", None) or {}
        if upload_file_data.get("id") is not None and db.session.query(UploadFile).filter(
            UploadFile.id == upload_file_data["id"],
        ).one_or_none() is None:
            upload_file = UploadFile()
            for col_name, value in upload_file_data.items():
                _apply_column_value(UploadFile, upload_file, col_name, value)
            db.session.add(upload_file)
            db.session.flush()
        doc = KnowledgeDocument()
        for col_name, value in doc_data.items():
            _apply_column_value(KnowledgeDocument, doc, col_name, value)
        db.session.add(doc)
        db.session.flush()
        for seg_data in segments:
            seg = KnowledgeSegment()
            for col_name, value in seg_data.items():
                _apply_column_value(KnowledgeSegment, seg, col_name, value)
            db.session.add(seg)
    return True


# ---------------------------------------------------------------------------
# system_prompt：系统内置提示词（存于「系统提示词库」知识库的文档）
# ---------------------------------------------------------------------------
def _system_prompt_base():
    return (
        db.session.query(KnowledgeBase)
        .filter(KnowledgeBase.name == "系统提示词库")
        .first()
    )


def _find_system_prompt_doc(prompt_key: str):
    base = _system_prompt_base()
    if base is None:
        return None
    return (
        db.session.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.knowledge_base_id == base.id,
            KnowledgeDocument.name == prompt_key,
        )
        .first()
    )


def snapshot_system_prompt(prompt_key: str) -> dict[str, Any] | None:
    doc = _find_system_prompt_doc(prompt_key)
    if doc is None:
        return None
    segments = (
        db.session.query(KnowledgeSegment)
        .filter(KnowledgeSegment.knowledge_document_id == doc.id)
        .all()
    )
    return {
        "prompt_key": prompt_key,
        "document": _row_to_dict(doc),
        "segments": [_row_to_dict(s) for s in segments],
    }


def physical_delete_system_prompt(prompt_key: str) -> None:
    doc = _find_system_prompt_doc(prompt_key)
    if doc is None:
        return
    segments = (
        db.session.query(KnowledgeSegment)
        .filter(KnowledgeSegment.knowledge_document_id == doc.id)
        .all()
    )
    for segment in segments:
        try:
            from internal.service.knowledge_vector_service import KnowledgeVectorService
            KnowledgeVectorService().remove_segment(segment)
        except Exception as exc:
            logger.warning("清理提示词向量失败 segment=%s: %s", segment.id, exc)
    db.session.query(KnowledgeSegment).filter(
        KnowledgeSegment.knowledge_document_id == doc.id,
    ).delete(synchronize_session=False)
    db.session.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == doc.id,
    ).delete(synchronize_session=False)


def restore_system_prompt(snapshot: dict[str, Any]) -> bool:
    doc_data = snapshot.get("document") or {}
    if not doc_data.get("id"):
        return False
    if db.session.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == doc_data["id"],
    ).one_or_none() is not None:
        return False
    base = _system_prompt_base()
    if base is None:
        logger.warning("恢复系统提示词失败：系统提示词库不存在")
        return False
    doc = KnowledgeDocument()
    for col_name, value in doc_data.items():
        _apply_column_value(KnowledgeDocument, doc, col_name, value)
    db.session.add(doc)
    db.session.flush()
    for seg_data in snapshot.get("segments") or []:
        seg = KnowledgeSegment()
        for col_name, value in seg_data.items():
            _apply_column_value(KnowledgeSegment, seg, col_name, value)
        db.session.add(seg)
    return True


def snapshot_knowledge_document(resource_id) -> dict[str, Any] | None:
    """快照知识库文档：文档主体 + 分段 + 关联的上传文件记录。"""
    doc = (
        db.session.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == resource_id)
        .one_or_none()
    )
    if doc is None:
        return None
    segments = (
        db.session.query(KnowledgeSegment)
        .filter(KnowledgeSegment.knowledge_document_id == doc.id)
        .order_by(KnowledgeSegment.position.asc())
        .all()
    )
    upload_file = None
    if getattr(doc, "upload_file_id", None) is not None:
        upload_file = (
            db.session.query(UploadFile)
            .filter(UploadFile.id == doc.upload_file_id)
            .one_or_none()
        )
    return {
        "main": _row_to_dict(doc),
        "segments": [_row_to_dict(s) for s in segments],
        "upload_file": _row_to_dict(upload_file) if upload_file is not None else None,
    }


def physical_delete_knowledge_document(resource_id) -> None:
    """物理删除文档：清向量 + 删分段/文档记录 + 删除上传文件记录。

    底层存储对象保留到留存期结束，由 purge_knowledge_document 统一销毁，
    从而支持回收站「恢复」时仍可找回完整文件。
    """
    doc = (
        db.session.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == resource_id)
        .one_or_none()
    )
    if doc is None:
        return
    segments = (
        db.session.query(KnowledgeSegment)
        .filter(KnowledgeSegment.knowledge_document_id == doc.id)
        .all()
    )
    for segment in segments:
        try:
            from internal.service.knowledge_vector_service import KnowledgeVectorService
            KnowledgeVectorService().remove_segment(segment)
        except Exception as exc:
            logger.warning("清理文档向量失败 segment=%s: %s", segment.id, exc)
    upload_file_id = getattr(doc, "upload_file_id", None)
    db.session.query(KnowledgeSegment).filter(
        KnowledgeSegment.knowledge_document_id == doc.id,
    ).delete(synchronize_session=False)
    db.session.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == doc.id,
    ).delete(synchronize_session=False)
    if upload_file_id is not None:
        db.session.query(UploadFile).filter(
            UploadFile.id == upload_file_id,
        ).delete(synchronize_session=False)


def restore_knowledge_document(snapshot: dict[str, Any]) -> bool:
    """恢复文档：重建上传文件记录 + 文档主体 + 分段（底层文件留存期内仍存在）。"""
    main_data = snapshot.get("main") or {}
    if not main_data.get("id"):
        return False
    if db.session.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == main_data["id"],
    ).one_or_none() is not None:
        return False
    upload_file_data = snapshot.get("upload_file") or {}
    if upload_file_data.get("id") is not None and db.session.query(UploadFile).filter(
        UploadFile.id == upload_file_data["id"],
    ).one_or_none() is None:
        upload_file = UploadFile()
        for col_name, value in upload_file_data.items():
            _apply_column_value(UploadFile, upload_file, col_name, value)
        db.session.add(upload_file)
        db.session.flush()
    doc = KnowledgeDocument()
    for col_name, value in main_data.items():
        _apply_column_value(KnowledgeDocument, doc, col_name, value)
    db.session.add(doc)
    db.session.flush()
    for seg_data in snapshot.get("segments") or []:
        seg = KnowledgeSegment()
        for col_name, value in seg_data.items():
            _apply_column_value(KnowledgeSegment, seg, col_name, value)
        db.session.add(seg)
    return True


def purge_knowledge_document(snapshot: dict[str, Any]) -> None:
    """留存期结束彻底销毁：删除底层存储对象（local 物理文件 / COS、OSS 对象）。"""
    upload_file_data = snapshot.get("upload_file") or {}
    key = upload_file_data.get("key")
    if not key:
        return
    backend = (upload_file_data.get("storage_backend") or "local").strip() or "local"
    try:
        from internal.service.storage.storage_migration_service import _delete_object
        _delete_object(backend, key)
        logger.info("回收站销毁文档存储文件 key=%s backend=%s", key, backend)
    except Exception:
        logger.warning("回收站销毁文档存储文件失败 key=%s", key, exc_info=True)


def purge_knowledge_base(snapshot: dict[str, Any]) -> None:
    """留存期结束彻底销毁知识库关联的底层存储对象。"""
    for doc_data in snapshot.get("documents") or []:
        upload_file_data = doc_data.get("_upload_file") or {}
        key = upload_file_data.get("key")
        if not key:
            continue
        backend = (upload_file_data.get("storage_backend") or "local").strip() or "local"
        try:
            from internal.service.storage.storage_migration_service import _delete_object
            _delete_object(backend, key)
            logger.info("回收站销毁知识库存储文件 key=%s backend=%s", key, backend)
        except Exception:
            logger.warning("回收站销毁知识库存储文件失败 key=%s", key, exc_info=True)


def snapshot_upload_file(resource_id) -> dict[str, Any] | None:
    """快照单个上传文件记录（底层对象在留存期内保留）。"""
    upload_file = (
        db.session.query(UploadFile)
        .filter(UploadFile.id == resource_id)
        .one_or_none()
    )
    if upload_file is None:
        return None
    return {"main": _row_to_dict(upload_file)}


def physical_delete_upload_file(resource_id) -> None:
    """删除上传文件记录，底层对象保留到留存期结束。"""
    db.session.query(UploadFile).filter(
        UploadFile.id == resource_id,
    ).delete(synchronize_session=False)


def restore_upload_file(snapshot: dict[str, Any]) -> bool:
    """按快照重建上传文件记录。"""
    main_data = snapshot.get("main") or {}
    if not main_data.get("id"):
        return False
    if db.session.query(UploadFile).filter(
        UploadFile.id == main_data["id"],
    ).one_or_none() is not None:
        return False
    upload_file = UploadFile()
    for col_name, value in main_data.items():
        _apply_column_value(UploadFile, upload_file, col_name, value)
    db.session.add(upload_file)
    return True


def purge_upload_file(snapshot: dict[str, Any]) -> None:
    """留存期结束彻底销毁上传文件的底层存储对象。"""
    main_data = snapshot.get("main") or {}
    key = main_data.get("key")
    if not key:
        return
    backend = (main_data.get("storage_backend") or "local").strip() or "local"
    try:
        from internal.service.storage.storage_migration_service import _delete_object
        _delete_object(backend, key)
        logger.info("回收站销毁上传文件 key=%s backend=%s", key, backend)
    except Exception:
        logger.warning("回收站销毁上传文件失败 key=%s", key, exc_info=True)


# ---------------------------------------------------------------------------
# os_file：宿主机本机文件（由 OS automation worker 移入宿主机回收站）
# ---------------------------------------------------------------------------
def _worker_recycle_endpoint() -> str:
    """解析 worker 回收站端点与令牌。"""
    import os as _os

    bridge_url = _os.getenv("DESKTOP_BRIDGE_URL", "").strip()
    bridge_token = _os.getenv("DESKTOP_BRIDGE_TOKEN", "").strip()
    if bridge_url and bridge_token:
        return bridge_url.rstrip("/") + "/recycle", bridge_token
    endpoint = _os.getenv("OS_AUTOMATION_URL", "").strip()
    token = _os.getenv("OS_AUTOMATION_TOKEN", "").strip()
    return endpoint.rstrip("/") + "/recycle" if endpoint else "", token


def _call_worker_recycle(payload: dict[str, Any]) -> dict[str, Any]:
    """调用宿主机 OS automation worker 的回收站接口（best-effort）。"""
    import json as _json
    import os as _os
    import urllib.error
    import urllib.request

    endpoint, token = _worker_recycle_endpoint()
    if not endpoint or not token:
        return {"ok": False, "error": "OS_AUTOMATION_URL/TOKEN 或 DESKTOP_BRIDGE_URL/TOKEN 未配置"}
    body = _json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return _json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            error_payload = _json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            error_payload = {"error": str(exc)}
        return {"ok": False, "error": error_payload.get("error", str(exc))}
    except Exception as exc:
        return {"ok": False, "error": f"调用本机回收站失败: {exc}"}


def restore_os_file(
    snapshot: dict[str, Any],
    *,
    target_path: str = "",
    check_device: bool = False,
    confirm_device_mismatch: bool = False,
) -> bool:
    """恢复本机文件：调用 worker 把文件移回原处（或自选目标路径）。

    check_device=True 时要求 worker 校验删除设备与当前设备是否一致：
    不一致且未确认时抛 DeviceMismatchException（由路由转换为 device_mismatch 响应，
    前端提示「这并非本机删除的文件」并提供两种恢复方式）。
    """
    from internal.exception import DeviceMismatchException, ValidateErrorException

    entry_id = str((snapshot or {}).get("entry_id") or "").strip()
    if not entry_id:
        logger.warning("恢复本机文件失败：缺少 entry_id")
        raise ValidateErrorException("恢复本机文件失败：缺少文件标识")
    result = _call_worker_recycle(
        {
            "op": "restore",
            "entry_id": entry_id,
            "target_path": str(target_path or "").strip(),
            "check_device": bool(check_device),
            "confirm_device_mismatch": bool(confirm_device_mismatch),
        }
    )
    if not result.get("ok"):
        if result.get("code") == "device_mismatch":
            raise DeviceMismatchException(
                recorded_device=result.get("recorded_device") or {},
                current_device=result.get("current_device") or {},
                entry_id=entry_id,
            )
        error = result.get("error") or "恢复本机文件失败：worker 不可用"
        logger.warning("恢复本机文件失败 entry_id=%s: %s", entry_id, error)
        raise ValidateErrorException(f"恢复本机文件失败：{error}")
    return True


def purge_os_file(snapshot: dict[str, Any]) -> None:
    """本机文件到期销毁：调用 worker 物理清理过期条目（best-effort）。"""
    result = _call_worker_recycle({"op": "purge"})
    if not result.get("ok"):
        logger.warning("本机回收站 purge 调用失败: %s", result.get("error"))


# ---------------------------------------------------------------------------
# schedule_task：用户定时任务（物理删除，快照含运行记录）
# ---------------------------------------------------------------------------
def snapshot_schedule_task(resource_id) -> dict[str, Any] | None:
    task = (
        db.session.query(ScheduleTask)
        .filter(ScheduleTask.id == resource_id)
        .one_or_none()
    )
    if task is None:
        return None
    runs = (
        db.session.query(ScheduleTaskRun)
        .filter(ScheduleTaskRun.schedule_task_id == task.id)
        .all()
    )
    return {"main": _row_to_dict(task), "runs": [_row_to_dict(r) for r in runs]}


def physical_delete_schedule_task(resource_id) -> None:
    db.session.query(ScheduleTaskRun).filter(
        ScheduleTaskRun.schedule_task_id == resource_id,
    ).delete(synchronize_session=False)
    db.session.query(ScheduleTask).filter(
        ScheduleTask.id == resource_id,
    ).delete(synchronize_session=False)


def restore_schedule_task(snapshot: dict[str, Any]) -> bool:
    """按快照重建定时任务 + 运行记录（固定原主键）。"""
    main_data = snapshot.get("main") or {}
    if not main_data.get("id"):
        return False
    if db.session.query(ScheduleTask).filter(
        ScheduleTask.id == main_data["id"],
    ).one_or_none() is not None:
        return False
    task = ScheduleTask()
    for col_name, value in main_data.items():
        _apply_column_value(ScheduleTask, task, col_name, value)
    db.session.add(task)
    db.session.flush()
    for run_data in snapshot.get("runs") or []:
        run = ScheduleTaskRun()
        for col_name, value in run_data.items():
            _apply_column_value(ScheduleTaskRun, run, col_name, value)
        db.session.add(run)
    return True


def purge_schedule_task(_snapshot: dict[str, Any]) -> None:
    # 删除时已物理删除任务与运行记录，无残留
    pass


# ---------------------------------------------------------------------------
# external_data_source：用户外部数据源（物理删除，含授权配置快照）
# ---------------------------------------------------------------------------
def snapshot_external_data_source(resource_id) -> dict[str, Any] | None:
    data_source = (
        db.session.query(ExternalDataSource)
        .filter(ExternalDataSource.id == resource_id)
        .one_or_none()
    )
    if data_source is None:
        return None
    return {"main": _row_to_dict(data_source)}


def physical_delete_external_data_source(resource_id) -> None:
    db.session.query(ExternalDataSource).filter(
        ExternalDataSource.id == resource_id,
    ).delete(synchronize_session=False)


def restore_external_data_source(snapshot: dict[str, Any]) -> bool:
    """按快照重建外部数据源记录（固定原主键）。"""
    main_data = snapshot.get("main") or {}
    if not main_data.get("id"):
        return False
    if db.session.query(ExternalDataSource).filter(
        ExternalDataSource.id == main_data["id"],
    ).one_or_none() is not None:
        return False
    data_source = ExternalDataSource()
    for col_name, value in main_data.items():
        _apply_column_value(ExternalDataSource, data_source, col_name, value)
    db.session.add(data_source)
    return True


def purge_external_data_source(_snapshot: dict[str, Any]) -> None:
    # 删除时已物理删除记录，无残留
    pass


# ---------------------------------------------------------------------------
# conversation：用户会话（软删除模式）
# 删除 = 标记 is_deleted（数据保留） + 入回收站；恢复 = 翻转 is_deleted；
# 留存期到期 purge 时才物理删除消息/思考/变量/会话。
# ---------------------------------------------------------------------------
def snapshot_conversation(resource_id) -> dict[str, Any] | None:
    conversation = (
        db.session.query(Conversation)
        .filter(Conversation.id == resource_id)
        .one_or_none()
    )
    if conversation is None:
        return None
    return {"main": _row_to_dict(conversation)}


def physical_delete_conversation(resource_id) -> None:
    # 软删除模式：会话数据保留（service 删除时已标记 is_deleted），
    # 恢复时翻转标记；到期销毁由 purge_conversation 物理清理。
    pass


def restore_conversation(snapshot: dict[str, Any]) -> bool:
    """恢复会话：翻转 is_deleted（消息/变量数据删除时已保留，随会话一并恢复）。"""
    main_data = snapshot.get("main") or {}
    conversation_id = main_data.get("id")
    if not conversation_id:
        return False
    conversation = (
        db.session.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .one_or_none()
    )
    if conversation is None:
        return False  # 已到期销毁
    if not conversation.is_deleted:
        return False  # 已恢复
    conversation.is_deleted = False
    return True


def purge_conversation(snapshot: dict[str, Any]) -> None:
    """留存期结束彻底销毁会话：删除思考/消息/变量/会话记录。"""
    main_data = snapshot.get("main") or {}
    conversation_id = main_data.get("id")
    if not conversation_id:
        return
    message_ids = db.session.query(Message.id).filter(
        Message.conversation_id == conversation_id,
    )
    db.session.query(MessageAgentThought).filter(
        MessageAgentThought.message_id.in_(message_ids),
    ).delete(synchronize_session=False)
    db.session.query(Message).filter(
        Message.conversation_id == conversation_id,
    ).delete(synchronize_session=False)
    db.session.query(ConversationVariable).filter(
        ConversationVariable.conversation_id == conversation_id,
    ).delete(synchronize_session=False)
    db.session.query(Conversation).filter(
        Conversation.id == conversation_id,
    ).delete(synchronize_session=False)


# ---------------------------------------------------------------------------
# memory：个人记忆（软删除模式，存于 Neo4j + pgvector user_memory 表）
# 删除 = 软删标记 is_active=false（service 已执行）+ 入回收站；恢复 = 翻转
# is_active；留存期到期 purge 时才物理清理（DETACH DELETE + 删除 user_memory 行）。
# ---------------------------------------------------------------------------
def _memory_driver():
    """获取 Neo4j driver（不可用时返回 None，调用方需降级处理）。"""
    try:
        from internal.extension.neo4j_extension import get_driver
        return get_driver()
    except Exception:
        return None


def _memory_row(memory_id):
    """按 memory_id 查找 user_memory 表记录（embedding_node_id 或 id 关联）。

    id 为 UUID 而 memory_id 可能为 Neo4j 节点 ID，分开查询避免混合类型比较异常。
    """
    row = (
        db.session.query(UserMemory)
        .filter(UserMemory.embedding_node_id == str(memory_id))
        .one_or_none()
    )
    if row is not None:
        return row
    return (
        db.session.query(UserMemory)
        .filter(UserMemory.id == memory_id)
        .one_or_none()
    )


def _memory_neo4j_props(memory_id):
    """读取 Neo4j 记忆节点属性（快照用于恢复时判断与展示）。"""
    driver = _memory_driver()
    if driver is None:
        return None
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity)
                  AND (n.node_id = $memory_id OR n.id = $memory_id)
                RETURN n AS node
                """,
                memory_id=str(memory_id),
            ).single()
            if result is None:
                return None
            node = result.get("node")
            if node is None:
                return None
            props = {}
            for key, value in dict(node).items():
                if value is None:
                    props[key] = None
                elif hasattr(value, "isoformat"):
                    props[key] = value.isoformat()
                elif hasattr(value, "hex"):
                    props[key] = str(value)
                else:
                    props[key] = value
            return props
    except Exception:
        logger.warning("读取记忆节点属性失败 memory=%s", memory_id, exc_info=True)
        return None


def snapshot_memory(resource_id) -> dict[str, Any] | None:
    row = _memory_row(resource_id)
    if row is None:
        return None
    snapshot = {
        "main": _row_to_dict(row),
        "neo4j": _memory_neo4j_props(resource_id),
    }
    return snapshot


def physical_delete_memory(_resource_id) -> None:
    # 软删除模式：user_memory 行与 Neo4j 节点数据保留（service 已标记 is_active=false），
    # 恢复时翻转；到期销毁由 purge_memory 物理清理。
    pass


def restore_memory(snapshot: dict[str, Any]) -> bool:
    """恢复个人记忆：翻转 Neo4j 节点 is_active=true；重建 user_memory 行。"""
    main_data = snapshot.get("main") or {}
    memory_id = main_data.get("id") or main_data.get("embedding_node_id")
    if not memory_id:
        return False
    restored = False

    # 1. Neo4j 翻转 is_active
    driver = _memory_driver()
    if driver is not None:
        try:
            with driver.session() as session:
                result = session.run(
                    """
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity)
                      AND (n.node_id = $memory_id OR n.id = $memory_id)
                    SET n.is_active = true
                    RETURN count(n) AS cnt
                    """,
                    memory_id=str(memory_id),
                ).single()
                if result is not None and (result.get("cnt") or 0) > 0:
                    restored = True
        except Exception:
            logger.warning("恢复记忆节点失败 memory=%s", memory_id, exc_info=True)
    else:
        logger.warning("恢复记忆：Neo4j 不可用 memory=%s", memory_id)

    # 2. 重建 user_memory 行（软删时行已被 service 删除）
    if main_data.get("id") is not None:
        row = db.session.query(UserMemory).filter(UserMemory.id == main_data["id"]).one_or_none()
        if row is None:
            row = UserMemory()
            for col_name, value in main_data.items():
                _apply_column_value(UserMemory, row, col_name, value)
            db.session.add(row)
            restored = True
    return restored


def purge_memory(snapshot: dict[str, Any]) -> None:
    """留存期结束彻底销毁记忆：删除 user_memory 行 + Neo4j 节点 DETACH DELETE。"""
    main_data = snapshot.get("main") or {}
    memory_id = main_data.get("id") or main_data.get("embedding_node_id")
    if not memory_id:
        return
    try:
        row = _memory_row(memory_id)
        if row is not None:
            db.session.delete(row)
    except Exception:
        logger.warning("销毁记忆 user_memory 行失败 memory=%s", memory_id, exc_info=True)
    driver = _memory_driver()
    if driver is not None:
        try:
            with driver.session() as session:
                session.run(
                    """
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity)
                      AND (n.node_id = $memory_id OR n.id = $memory_id)
                    DETACH DELETE n
                    """,
                    memory_id=str(memory_id),
                ).consume()
            logger.info("回收站销毁记忆节点 memory=%s", memory_id)
        except Exception:
            logger.warning("销毁记忆节点失败 memory=%s", memory_id, exc_info=True)


# ---------------------------------------------------------------------------
# 统一分发入口
# ---------------------------------------------------------------------------
def snapshot_resource(resource_type: str, resource_id, resource_key: str = "") -> dict[str, Any] | None:
    if resource_type == "knowledge_base":
        return snapshot_knowledge_base(resource_id)
    if resource_type == "system_prompt":
        return snapshot_system_prompt(resource_key)
    if resource_type == "knowledge_document":
        return snapshot_knowledge_document(resource_id)
    if resource_type == "upload_file":
        return snapshot_upload_file(resource_id)
    if resource_type == "os_file":
        # 本机文件记录不依赖 DB 快照（快照由 record_os_file_deletion 直接构造）
        return {}
    if resource_type == "schedule_task":
        return snapshot_schedule_task(resource_id)
    if resource_type == "external_data_source":
        return snapshot_external_data_source(resource_id)
    if resource_type == "conversation":
        return snapshot_conversation(resource_id)
    if resource_type == "memory":
        return snapshot_memory(resource_id)
    return snapshot_generic(resource_type, resource_id)


def physical_delete_resource(resource_type: str, resource_id, resource_key: str = "") -> None:
    if resource_type == "knowledge_base":
        physical_delete_knowledge_base(resource_id)
    elif resource_type == "system_prompt":
        physical_delete_system_prompt(resource_key)
    elif resource_type == "knowledge_document":
        physical_delete_knowledge_document(resource_id)
    elif resource_type == "upload_file":
        physical_delete_upload_file(resource_id)
    elif resource_type == "os_file":
        # 本机文件已由 worker 移入宿主机回收站，无平台 DB 记录可删
        pass
    elif resource_type == "schedule_task":
        physical_delete_schedule_task(resource_id)
    elif resource_type == "external_data_source":
        physical_delete_external_data_source(resource_id)
    elif resource_type == "conversation":
        # 软删除模式：数据保留（service 已标记 is_deleted），恢复时翻转
        physical_delete_conversation(resource_id)
    elif resource_type == "memory":
        # 软删除模式：user_memory 行与 Neo4j 节点数据保留（service 已标记 is_active=false）
        physical_delete_memory(resource_id)
    else:
        physical_delete_generic(resource_type, resource_id)


def restore_resource(
    resource_type: str,
    snapshot: dict[str, Any],
    *,
    target_path: str = "",
    check_device: bool = False,
    confirm_device_mismatch: bool = False,
) -> bool:
    if resource_type == "knowledge_base":
        return restore_knowledge_base(snapshot)
    if resource_type == "system_prompt":
        return restore_system_prompt(snapshot)
    if resource_type == "knowledge_document":
        return restore_knowledge_document(snapshot)
    if resource_type == "upload_file":
        return restore_upload_file(snapshot)
    if resource_type == "os_file":
        return restore_os_file(
            snapshot,
            target_path=target_path,
            check_device=check_device,
            confirm_device_mismatch=confirm_device_mismatch,
        )
    if resource_type == "schedule_task":
        return restore_schedule_task(snapshot)
    if resource_type == "external_data_source":
        return restore_external_data_source(snapshot)
    if resource_type == "conversation":
        return restore_conversation(snapshot)
    if resource_type == "memory":
        return restore_memory(snapshot)
    return restore_generic(resource_type, snapshot)


def purge_resource(resource_type: str, snapshot: dict[str, Any]) -> None:
    """到期销毁收尾：knowledge_base/system_prompt 的资源记录在删除时已物理删除，
    其余类型的存储文件残留由对应业务清理；此处预留扩展点。"""
    if resource_type == "knowledge_document":
        purge_knowledge_document(snapshot)
    elif resource_type == "knowledge_base":
        purge_knowledge_base(snapshot)
    elif resource_type == "upload_file":
        purge_upload_file(snapshot)
    elif resource_type == "os_file":
        purge_os_file(snapshot)
    elif resource_type == "schedule_task":
        purge_schedule_task(snapshot)
    elif resource_type == "external_data_source":
        purge_external_data_source(snapshot)
    elif resource_type == "conversation":
        purge_conversation(snapshot)
    elif resource_type == "memory":
        purge_memory(snapshot)
    elif resource_type in ("app", "workflow", "skill", "mcp", "api_tool"):
        # 删除时已通过 physical_delete 清掉 DB 记录，预留文件清理扩展位
        pass
