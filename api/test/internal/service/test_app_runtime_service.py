from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.dataset_entity import RetrievalStrategy
from internal.service.app_runtime_service import AppRuntimeService


def _build_app_config_service():
    """构建测试用的 app_config_service 替身，提供空的工具加载方法。"""
    return SimpleNamespace(
        get_langchain_tools_by_tools_config=lambda *_args, **_kwargs: [],
        get_langchain_tools_by_mcp_bindings=lambda *_args, **_kwargs: [],
        get_langchain_tools_by_workflow_ids=lambda *_args, **_kwargs: [],
    )


class TestAppRuntimeServiceBuildTools:
    """覆盖 build_runtime_tools_for_config 对新版 knowledge_base_ids 的接入。"""

    def test_knowledge_base_ids_should_create_knowledge_retrieval_tool(self):
        """knowledge_base_ids 非空时调用 create_knowledge_retrieval_tool 并附带检索配置。"""
        kb_id = uuid4()
        retrieval_capture = {}
        retrieval_service = SimpleNamespace(
            create_knowledge_retrieval_tool=lambda **kwargs: retrieval_capture.update(kwargs) or "kb-tool",
        )
        account = SimpleNamespace(id=uuid4())

        tools = AppRuntimeService.build_runtime_tools_for_config(
            app_config_service=_build_app_config_service(),
            retrieval_service=retrieval_service,
            account=account,
            app_id=uuid4(),
            draft_app_config={
                "knowledge_base_ids": [str(kb_id)],
                "retrieval_config": {"retrieval_strategy": "semantic", "k": 6, "score": 0.2},
            },
            flask_app="flask-app",
        )

        # 新版检索工具应被加入工具列表
        assert "kb-tool" in tools
        # account_id 透传
        assert retrieval_capture["account_id"] == account.id
        assert retrieval_capture["flask_app"] == "flask-app"
        # 字符串 id 被转换为 UUID
        assert retrieval_capture["knowledge_base_ids"] == [kb_id]
        # retrieval_strategy 与 k 从 retrieval_config 透传
        assert retrieval_capture["retrieval_strategy"] == "semantic"
        assert retrieval_capture["k"] == 6

    def test_empty_knowledge_base_ids_should_skip_retrieval(self):
        """knowledge_base_ids 为空时不构建任何检索工具。"""
        retrieval_service = SimpleNamespace()
        account = SimpleNamespace(id=uuid4())

        tools = AppRuntimeService.build_runtime_tools_for_config(
            app_config_service=_build_app_config_service(),
            retrieval_service=retrieval_service,
            account=account,
            app_id=uuid4(),
            draft_app_config={},
            flask_app="flask-app",
        )

        assert tools == []

    def test_knowledge_base_ids_default_strategy_should_be_hybrid(self):
        """retrieval_config 缺失 retrieval_strategy 时默认使用 hybrid 策略。"""
        kb_id = uuid4()
        capture = {}
        retrieval_service = SimpleNamespace(
            create_knowledge_retrieval_tool=lambda **kwargs: capture.update(kwargs) or "kb-tool",
        )
        account = SimpleNamespace(id=uuid4())

        AppRuntimeService.build_runtime_tools_for_config(
            app_config_service=_build_app_config_service(),
            retrieval_service=retrieval_service,
            account=account,
            app_id=uuid4(),
            draft_app_config={
                "knowledge_base_ids": [str(kb_id)],
                "retrieval_config": {"k": 5},
            },
            flask_app="flask-app",
        )

        assert capture["retrieval_strategy"] == RetrievalStrategy.HYBRID.value
        assert capture["k"] == 5

    def test_invalid_knowledge_base_id_should_be_skipped(self):
        """非法 knowledge_base_id 字符串应被跳过，不阻断工具构建。"""
        valid_id = uuid4()
        capture = {}
        retrieval_service = SimpleNamespace(
            create_knowledge_retrieval_tool=lambda **kwargs: capture.update(kwargs) or "kb-tool",
        )
        account = SimpleNamespace(id=uuid4())

        tools = AppRuntimeService.build_runtime_tools_for_config(
            app_config_service=_build_app_config_service(),
            retrieval_service=retrieval_service,
            account=account,
            app_id=uuid4(),
            draft_app_config={
                "knowledge_base_ids": ["not-a-uuid", str(valid_id)],
            },
            flask_app="flask-app",
        )

        # 非法 id 被跳过，仅保留有效 id
        assert "kb-tool" in tools
        assert capture["knowledge_base_ids"] == [valid_id]
