from __future__ import annotations

import internal.entity as entity_pkg
from internal.entity.app_entity import (
    AppConfigType,
    AppStatus,
    DEFAULT_APP_CONFIG,
)
from internal.entity.audio_entity import ALLOWED_AUDIO_VOICES
from internal.entity.cache_entity import (
    LOCK_DOCUMENT_UPDATE_ENABLED,
    LOCK_EXPIRE_TIME,
    LOCK_KEYWORD_TABLE_UPDATE_KEYWORD_TABLE,
    LOCK_SEGMENT_UPDATE_ENABLED,
)
from internal.entity.conversation_entity import (
    InvokeFrom,
    MessageStatus,
)
from internal.entity.dataset_entity import (
    DocumentStatus,
    RetrievalSource,
    RetrievalStrategy,
    SegmentStatus,
)
from internal.entity.jieba_entity import STOPWORD_SET
from internal.entity.platform_entity import WechatConfigStatus
from internal.entity.upload_file_entity import ALLOWED_DOCUMENT_EXTENSION, ALLOWED_IMAGE_EXTENSION
from internal.entity.workflow_entity import DEFAULT_WORKFLOW_CONFIG, WorkflowResultStatus, WorkflowStatus


def _enum_values(enum_cls):
    return [item.value for item in enum_cls]


def test_entity_package_should_be_importable():
    # internal/entity/__init__.py 当前为空文件，但需保证包导入稳定。
    assert entity_pkg.__name__ == "internal.entity"
    assert hasattr(entity_pkg, "__file__")


def test_app_entity_should_keep_expected_defaults_and_enums():
    assert _enum_values(AppStatus) == ["draft", "published"]
    assert _enum_values(AppConfigType) == ["draft", "published"]

    from internal.service.system_prompt_library_service import SystemPromptLibraryService
    icon_template = SystemPromptLibraryService().get_prompt_or_default("app_icon_generate_prompt")
    assert "{name}" in icon_template
    assert "{description}" in icon_template

    required_keys = {
        "model_config",
        "dialog_round",
        "preset_prompt",
        "tools",
        "mcp_bindings",
        "mcp_tool_snapshots",
        "skills",
        "workflows",
        "knowledge_base_ids",
        "retrieval_config",
        "long_term_memory",
        "opening_statement",
        "opening_questions",
        "speech_to_text",
        "text_to_speech",
        "suggested_after_answer",
        "review_config",
    }
    assert required_keys.issubset(DEFAULT_APP_CONFIG.keys())
    assert DEFAULT_APP_CONFIG["dialog_round"] == 3
    # 模型配置由管理员在模型池统一管理，默认配置不内嵌具体模型
    assert DEFAULT_APP_CONFIG["model_config"] == {}
    assert DEFAULT_APP_CONFIG["text_to_speech"]["voice"] in ALLOWED_AUDIO_VOICES


def test_dataset_entity_should_keep_expected_enums():
    assert _enum_values(DocumentStatus) == ["waiting", "parsing", "splitting", "indexing", "completed", "error"]
    assert _enum_values(SegmentStatus) == ["waiting", "indexing", "completed", "error"]
    assert _enum_values(RetrievalStrategy) == ["full_text", "semantic", "hybrid"]
    assert _enum_values(RetrievalSource) == ["hit_testing", "app"]


def test_workflow_entity_should_keep_expected_defaults_and_enums():
    assert _enum_values(WorkflowStatus) == ["draft", "published"]
    assert _enum_values(WorkflowResultStatus) == ["running", "succeeded", "failed"]
    assert DEFAULT_WORKFLOW_CONFIG == {
        "graph": {},
        "draft_graph": {"nodes": [], "edges": []},
    }


def test_platform_and_audio_and_upload_entities_should_keep_whitelists():
    assert _enum_values(WechatConfigStatus) == ["configured", "unconfigured"]

    assert "alex" in ALLOWED_AUDIO_VOICES
    assert len(ALLOWED_AUDIO_VOICES) == len(set(ALLOWED_AUDIO_VOICES))
    assert all(voice == voice.lower() for voice in ALLOWED_AUDIO_VOICES)

    assert "png" in ALLOWED_IMAGE_EXTENSION
    assert "txt" in ALLOWED_DOCUMENT_EXTENSION
    assert len(ALLOWED_IMAGE_EXTENSION) == len(set(ALLOWED_IMAGE_EXTENSION))
    assert len(ALLOWED_DOCUMENT_EXTENSION) == len(set(ALLOWED_DOCUMENT_EXTENSION))
    assert all(ext == ext.lower() for ext in ALLOWED_IMAGE_EXTENSION + ALLOWED_DOCUMENT_EXTENSION)


def test_cache_entity_lock_patterns_should_support_formatting():
    assert LOCK_EXPIRE_TIME == 600

    document_lock = LOCK_DOCUMENT_UPDATE_ENABLED.format(document_id="doc-id")
    dataset_lock = LOCK_KEYWORD_TABLE_UPDATE_KEYWORD_TABLE.format(dataset_id="dataset-id")
    segment_lock = LOCK_SEGMENT_UPDATE_ENABLED.format(segment_id="seg-id")

    assert document_lock == "lock:document:update:enabled_doc-id"
    assert dataset_lock == "lock:keyword_table:update:keyword_table_dataset-id"
    assert segment_lock == "lock:segment:update:enabled_seg-id"


def test_conversation_and_jieba_entities_should_keep_expected_values():
    assert _enum_values(InvokeFrom) == ["service_api", "web_app", "debugger", "assistant_agent", "schedule"]
    assert _enum_values(MessageStatus) == ["normal", "stop", "timeout", "error"]

    # stopword 集合很大，这里断言关键中英文停用词与标点存在，避免资源文件被误删或截断。
    assert len(STOPWORD_SET) > 500
    for token in {"的", "and", "\n", "", ".", "!"}:
        assert token in STOPWORD_SET
