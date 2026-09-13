from internal.entity.upload_file_entity import (
    ALLOWED_AUDIO_EXTENSION,
    ALLOWED_IMAGE_EXTENSION,
    ALLOWED_VIDEO_EXTENSION,
    MEDIA_TYPE_EXTENSIONS,
    allowed_extensions_for_base_type,
    media_type_for_extension,
)


def test_video_extension_whitelist_contains_common_formats():
    for ext in ("mp4", "mov", "avi", "mkv", "webm"):
        assert ext in ALLOWED_VIDEO_EXTENSION


def test_audio_extension_whitelist_contains_common_formats():
    for ext in ("mp3", "wav", "m4a", "aac", "flac"):
        assert ext in ALLOWED_AUDIO_EXTENSION


def test_media_type_extensions_covers_four_types():
    assert set(MEDIA_TYPE_EXTENSIONS.keys()) == {"document", "image", "video", "audio"}


def test_video_base_type_allows_video_only():
    assert allowed_extensions_for_base_type("video") == ALLOWED_VIDEO_EXTENSION


def test_mixed_base_type_allows_everything():
    result = allowed_extensions_for_base_type("mixed")
    assert "mp4" in result and "jpg" in result and "pdf" in result


def test_unknown_base_type_falls_back_to_mixed():
    assert allowed_extensions_for_base_type("nonexistent") == allowed_extensions_for_base_type("mixed")


def test_media_type_for_extension_resolves_video():
    assert media_type_for_extension("mp4") == "video"
    assert media_type_for_extension(".MP4") == "video"


def test_media_type_for_extension_defaults_to_document():
    assert media_type_for_extension("pdf") == "document"
    assert media_type_for_extension("") == "document"


def test_media_type_keys_match_document_media_type_enum():
    from internal.entity.knowledge_entity import DocumentMediaType

    assert set(MEDIA_TYPE_EXTENSIONS.keys()) == {m.value for m in DocumentMediaType}


def test_allowed_extensions_return_value_is_safe_to_mutate():
    result = allowed_extensions_for_base_type("video")
    result.append("evil")
    assert "evil" not in ALLOWED_VIDEO_EXTENSION


def test_media_type_for_extension_handles_whitespace_and_uppercase():
    assert media_type_for_extension(" MP4 ") == "video"
    assert media_type_for_extension("PDF") == "document"


def test_media_type_for_extension_handles_extension_without_dot():
    assert media_type_for_extension("png") == "image"


def test_media_type_for_extension_handles_empty_and_none_like_input():
    assert media_type_for_extension("") == "document"


def test_image_base_type_allows_image_only():
    assert allowed_extensions_for_base_type("image") == ALLOWED_IMAGE_EXTENSION
