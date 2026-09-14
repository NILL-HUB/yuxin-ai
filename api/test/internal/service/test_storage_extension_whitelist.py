"""存储层扩展名白名单应覆盖视频/音频，否则多模态上传不可用。"""
from internal.entity.upload_file_entity import allowed_extensions_for_base_type


def test_mixed_extensions_include_video_and_audio():
    allowed = allowed_extensions_for_base_type("mixed")
    for ext in ("mp4", "mov", "mp3", "wav", "pdf", "jpg"):
        assert ext in allowed


def test_storage_whitelist_source_uses_mixed_union():
    """三个存储后端应使用全类型并集而非仅图片+文档。"""
    from internal.service import cos_service
    from internal.service.storage import aliyun_oss_service, local_storage_service

    for module in (cos_service, local_storage_service, aliyun_oss_service):
        source = open(module.__file__, encoding="utf-8").read()
        assert "allowed_extensions_for_base_type" in source, f"{module.__name__} 未使用全类型并集"
