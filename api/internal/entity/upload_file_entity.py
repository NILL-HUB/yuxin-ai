# 允许上传的文件类型
ALLOWED_IMAGE_EXTENSION = ["jpg", "jpeg", "png", "webp", "gif", "svg"]
ALLOWED_DOCUMENT_EXTENSION = ["markdown", "md", "doc", "docx", "txt", "pdf", "csv", "xlsx", "xls", "html", "htm"]
ALLOWED_VIDEO_EXTENSION = ["mp4", "mov", "avi", "mkv", "webm"]
ALLOWED_AUDIO_EXTENSION = ["mp3", "wav", "m4a", "aac", "flac"]

# 媒体类型 -> 允许的扩展名列表
MEDIA_TYPE_EXTENSIONS = {
    "document": ALLOWED_DOCUMENT_EXTENSION,
    "image": ALLOWED_IMAGE_EXTENSION,
    "video": ALLOWED_VIDEO_EXTENSION,
    "audio": ALLOWED_AUDIO_EXTENSION,
}


def allowed_extensions_for_base_type(base_type: str) -> list[str]:
    """按知识库板块类型返回允许的扩展名列表。

    mixed 或不认识的类型返回全部扩展名的并集，保证存量库可继续上传。
    """
    if base_type in MEDIA_TYPE_EXTENSIONS:
        return list(MEDIA_TYPE_EXTENSIONS[base_type])
    merged: list[str] = []
    for extensions in MEDIA_TYPE_EXTENSIONS.values():
        for ext in extensions:
            if ext not in merged:
                merged.append(ext)
    return merged


def media_type_for_extension(extension: str) -> str:
    """根据扩展名反查媒体类型；未知类型归入 document。"""
    ext = (extension or "").strip().lower().lstrip(".")
    for media_type, extensions in MEDIA_TYPE_EXTENSIONS.items():
        if ext in extensions:
            return media_type
    return "document"


def _assert_media_type_keys_consistent() -> None:
    """确认 MEDIA_TYPE_EXTENSIONS 的键与 DocumentMediaType 枚举值不漂移。"""
    from internal.entity.knowledge_entity import DocumentMediaType

    expected = {member.value for member in DocumentMediaType}
    actual = set(MEDIA_TYPE_EXTENSIONS.keys())
    if actual != expected:
        raise RuntimeError(
            f"MEDIA_TYPE_EXTENSIONS 与 DocumentMediaType 不一致：{actual} != {expected}"
        )

