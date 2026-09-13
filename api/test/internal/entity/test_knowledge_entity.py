from internal.entity.knowledge_entity import (
    DocumentMediaType,
    KnowledgeBaseType,
    KnowledgeCreatedFrom,
    PartitionMode,
)


def test_base_type_enum_has_five_values():
    assert {member.value for member in KnowledgeBaseType} == {
        "document", "image", "video", "audio", "mixed",
    }


def test_partition_mode_enum_has_four_values():
    assert {member.value for member in PartitionMode} == {
        "none", "date_month", "date_day", "custom",
    }


def test_document_media_type_enum_has_four_values():
    assert {member.value for member in DocumentMediaType} == {
        "document", "image", "video", "audio",
    }


def test_base_type_str_mixin_compares_with_plain_string():
    assert KnowledgeBaseType.VIDEO == "video"


def test_existing_created_from_enum_is_untouched():
    assert KnowledgeCreatedFrom.WORKFLOW_IMPORT.value == "workflow_import"
