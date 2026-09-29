"""文件中心路径工具。

抽出为独立模块：回收站处理器（recycle_bin_handlers）与 FileCenterService 都要用它，
若放在 FileCenterService 内会造成 handlers → service → handlers 的循环导入。
"""
from internal.extension.database_extension import db
from internal.model import FileCenterEntry


def build_parent_path_names(entry) -> list[str]:
    """返回 entry 所在目录的路径名数组（root 在前，不含 entry 自身）。"""
    names: list[str] = []
    cursor = getattr(entry, "parent_id", None)
    while cursor is not None:
        parent = (
            db.session.query(FileCenterEntry)
            .filter(FileCenterEntry.id == cursor)
            .one_or_none()
        )
        if parent is None:
            break
        names.append(parent.name)
        cursor = parent.parent_id
    return list(reversed(names))


def ensure_path(account_id, path_names: list[str]):
    """逐级确保目录存在（存在则复用），返回最深目录 id；path_names 为空返回 None。"""
    parent_id = None
    for name in path_names:
        query = db.session.query(FileCenterEntry).filter(
            FileCenterEntry.account_id == account_id,
            FileCenterEntry.name == name,
            FileCenterEntry.is_folder.is_(True),
        )
        if parent_id is None:
            query = query.filter(FileCenterEntry.parent_id.is_(None))
        else:
            query = query.filter(FileCenterEntry.parent_id == parent_id)
        folder = query.one_or_none()
        if folder is None:
            folder = FileCenterEntry(
                account_id=account_id,
                parent_id=parent_id,
                name=name,
                is_folder=True,
                source="upload",
            )
            db.session.add(folder)
            db.session.flush()
        parent_id = folder.id
    return parent_id


def delete_entries_by_upload_file(upload_file_id) -> int:
    """删除所有指向该 upload_file 的节点（物理销毁时的残留清理）。"""
    return (
        db.session.query(FileCenterEntry)
        .filter(FileCenterEntry.upload_file_id == upload_file_id)
        .delete(synchronize_session=False)
    )