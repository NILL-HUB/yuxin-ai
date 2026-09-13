from internal.entity.upload_file_entity import (
    ALLOWED_AUDIO_EXTENSION,
    ALLOWED_VIDEO_EXTENSION,
    MEDIA_TYPE_EXTENSIONS,
    allowed_extensions_for_base_type,
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
    from internal.entity.upload_file_entity import media_type_for_extension

    assert media_type_for_extension("mp4") == "video"
    assert media_type_for_extension(".MP4") == "video"


def test_media_type_for_extension_defaults_to_document():
    from internal.entity.upload_file_entity import media_type_for_extension

    assert media_type_for_extension("pdf") == "document"
    assert media_type_for_extension("") == "document"
