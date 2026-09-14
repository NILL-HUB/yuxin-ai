"""create_knowledge_base 内置工具测试：参数校验 + 服务调用契约。"""

import importlib
import json
from types import SimpleNamespace
from uuid import uuid4

from internal.core.tools.builtin_tools.providers.knowledge_base_tools.create_knowledge_base import (
    CreateKnowledgeBaseTool,
    create_knowledge_base,
)


module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.knowledge_base_tools.create_knowledge_base"
)


class _FakeKnowledgeBaseService:
    def __init__(self, result=None, error=None):
        self.calls = []
        self._result = result or SimpleNamespace(id=uuid4(), name="视频素材库")
        self._error = error

    def create_user_content_base(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._result


def _patch(monkeypatch, *, account=None, service=None):
    monkeypatch.setattr(
        module, "_load_account", lambda account_id: account
    )
    monkeypatch.setattr(
        module, "_load_knowledge_base_service", lambda: service
    )


def test_create_knowledge_base_calls_service_with_normalized_params(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    service = _FakeKnowledgeBaseService()
    _patch(monkeypatch, account=account, service=service)

    tool = CreateKnowledgeBaseTool(account_id=str(account.id))
    result = json.loads(
        tool._run(
            name="  视频素材库  ",
            base_type="video",
            partition_mode="date_month",
            description="按月的视频库",
        )
    )

    assert result["ok"] is True
    assert len(service.calls) == 1
    captured = service.calls[0]
    assert captured["name"] == "视频素材库"
    assert captured["base_type"] == "video"
    assert captured["partition_mode"] == "date_month"
    assert captured["description"] == "按月的视频库"
    assert captured["operation_context"] == "user"
    assert captured["account"] is account


def test_create_knowledge_base_defaults_to_mixed_and_none(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    service = _FakeKnowledgeBaseService()
    _patch(monkeypatch, account=account, service=service)

    result = json.loads(CreateKnowledgeBaseTool(account_id=str(account.id))._run(name="通用库"))

    assert result["ok"] is True
    assert service.calls[0]["base_type"] == "mixed"
    assert service.calls[0]["partition_mode"] == "none"


def test_invalid_base_type_is_rejected_without_calling_service(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    service = _FakeKnowledgeBaseService()
    _patch(monkeypatch, account=account, service=service)

    result = json.loads(
        CreateKnowledgeBaseTool(account_id=str(account.id))._run(
            name="非法库", base_type="hologram"
        )
    )

    assert result["ok"] is False
    assert "hologram" in result["error"]
    assert service.calls == []


def test_invalid_partition_mode_is_rejected_without_calling_service(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    service = _FakeKnowledgeBaseService()
    _patch(monkeypatch, account=account, service=service)

    result = json.loads(
        CreateKnowledgeBaseTool(account_id=str(account.id))._run(
            name="非法库", partition_mode="weekly"
        )
    )

    assert result["ok"] is False
    assert "weekly" in result["error"]
    assert service.calls == []


def test_empty_name_is_rejected(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    service = _FakeKnowledgeBaseService()
    _patch(monkeypatch, account=account, service=service)

    result = json.loads(
        CreateKnowledgeBaseTool(account_id=str(account.id))._run(name="   ")
    )

    assert result["ok"] is False
    assert "名称" in result["error"]
    assert service.calls == []


def test_missing_account_returns_explicit_error(monkeypatch):
    service = _FakeKnowledgeBaseService()
    _patch(monkeypatch, account=None, service=service)

    result = json.loads(CreateKnowledgeBaseTool()._run(name="无账号库"))

    assert result["ok"] is False
    assert "账号" in result["error"]
    assert service.calls == []


def test_account_not_found_returns_explicit_error(monkeypatch):
    service = _FakeKnowledgeBaseService()
    _patch(monkeypatch, account=None, service=service)

    result = json.loads(CreateKnowledgeBaseTool(account_id="ghost")._run(name="孤儿库"))

    assert result["ok"] is False
    assert "账号" in result["error"]
    assert service.calls == []


def test_service_error_is_returned_as_readable_message(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    service = _FakeKnowledgeBaseService(error=RuntimeError("知识库名称已存在"))
    _patch(monkeypatch, account=account, service=service)

    result = json.loads(
        CreateKnowledgeBaseTool(account_id=str(account.id))._run(name="重名库")
    )

    assert result["ok"] is False
    assert "知识库名称已存在" in result["error"]


def test_tool_factory_binds_account_id(monkeypatch):
    tool = create_knowledge_base(account_id="acct-1")

    assert isinstance(tool, CreateKnowledgeBaseTool)
    assert tool.account_id == "acct-1"
    assert tool.name == "create_knowledge_base"


def test_tool_reports_created_knowledge_base_id(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    created = SimpleNamespace(id=uuid4(), name="视频素材库")
    service = _FakeKnowledgeBaseService(result=created)
    _patch(monkeypatch, account=account, service=service)

    result = json.loads(
        CreateKnowledgeBaseTool(account_id=str(account.id))._run(name="视频素材库")
    )

    assert result["knowledge_base_id"] == str(created.id)
