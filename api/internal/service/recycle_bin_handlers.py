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
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeSegment,
    McpProvider,
    McpTool,
    SkillPackage,
    SkillPackageVersion,
    UploadFile,
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
    return snapshot_generic(resource_type, resource_id)


def physical_delete_resource(resource_type: str, resource_id, resource_key: str = "") -> None:
    if resource_type == "knowledge_base":
        physical_delete_knowledge_base(resource_id)
    elif resource_type == "system_prompt":
        physical_delete_system_prompt(resource_key)
    elif resource_type == "knowledge_document":
        physical_delete_knowledge_document(resource_id)
    else:
        physical_delete_generic(resource_type, resource_id)


def restore_resource(resource_type: str, snapshot: dict[str, Any]) -> bool:
    if resource_type == "knowledge_base":
        return restore_knowledge_base(snapshot)
    if resource_type == "system_prompt":
        return restore_system_prompt(snapshot)
    if resource_type == "knowledge_document":
        return restore_knowledge_document(snapshot)
    return restore_generic(resource_type, snapshot)


def purge_resource(resource_type: str, snapshot: dict[str, Any]) -> None:
    """到期销毁收尾：knowledge_base/system_prompt 的资源记录在删除时已物理删除，
    其余类型的存储文件残留由对应业务清理；此处预留扩展点。"""
    if resource_type == "knowledge_document":
        purge_knowledge_document(snapshot)
    elif resource_type == "knowledge_base":
        purge_knowledge_base(snapshot)
    elif resource_type in ("app", "workflow", "skill", "mcp", "api_tool"):
        # 删除时已通过 physical_delete 清掉 DB 记录，预留文件清理扩展位
        pass
