import importlib
import json

import pytest

from internal.core.tools.builtin_tools.providers.host_os.os_workspace_scope import (
    OsWorkspaceScopeTool,
    os_workspace_scope,
)


module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.host_os.os_workspace_scope"
)


class _FakeRecord:
    expires_at = "2026-10-04 22:00:00"


class _FakeScopeService:
    def __init__(self):
        self.calls = []

    def grant(self, *, account_id, session_id, scope_root, granted_via=""):
        self.calls.append(
            {
                "account_id": account_id,
                "session_id": session_id,
                "scope_root": scope_root,
                "granted_via": granted_via,
            }
        )
        return _FakeRecord()


def test_os_workspace_scope_grants_and_returns_message(monkeypatch):
    """批准后写入会话授权并给出"重试原操作"的引导。"""
    fake = _FakeScopeService()

    class _FakeInjector:
        def get(self, _service):
            return fake

    monkeypatch.setattr(module, "injector", _FakeInjector(), raising=False)
    import app.http.module as module_app

    monkeypatch.setattr(module_app, "injector", _FakeInjector(), raising=False)

    result = json.loads(
        OsWorkspaceScopeTool(requester="acct-1", session_id="conv-9")._run(
            path="D:\\proj-x", reason="需要在该目录构建项目"
        )
    )

    assert result["ok"] is True
    assert result["scope_root"] == "D:\\proj-x"
    assert "重试" in result["message"]
    assert fake.calls == [
        {
            "account_id": "acct-1",
            "session_id": "conv-9",
            "scope_root": "D:\\proj-x",
            "granted_via": "os_workspace_scope",
        }
    ]


def test_os_workspace_scope_rejects_empty_path():
    result = json.loads(OsWorkspaceScopeTool(requester="a", session_id="s")._run(path="  "))

    assert result["ok"] is False
    assert "path" in result["error"]


def test_os_workspace_scope_reports_grant_failure(monkeypatch):
    """服务层拒绝（如非绝对路径/会话缺失）时返回可读错误而不是抛异常。"""
    from internal.exception import ValidateErrorException

    class _FailingInjector:
        def get(self, _service):
            class _Failing:
                def grant(self, **_kwargs):
                    raise ValidateErrorException("scope_root 必须是绝对路径")

            return _Failing()

    import app.http.module as module_app

    monkeypatch.setattr(module_app, "injector", _FailingInjector(), raising=False)

    result = json.loads(
        OsWorkspaceScopeTool(requester="a", session_id="s")._run(path="relative/dir")
    )

    assert result["ok"] is False
    assert "绝对路径" in result["error"]


def test_os_workspace_scope_factory_binds_context():
    tool = os_workspace_scope(requester="acct-1", session_id="conv-9")

    assert tool.name == "os_workspace_scope"
    assert tool.requester == "acct-1"
    assert tool.session_id == "conv-9"


@pytest.mark.parametrize(
    "path,expected",
    [("D:\\proj-x", True), ("/data/proj", True), ("relative/path", False), ("", False)],
)
def test_scope_service_absolute_path_validation(path, expected):
    """路径格式校验（服务端在容器内，不能依赖 os.path.isabs 判断 Windows 路径）。"""
    from internal.service.session_scope_service import _is_absolute_path

    assert _is_absolute_path(path) is expected
