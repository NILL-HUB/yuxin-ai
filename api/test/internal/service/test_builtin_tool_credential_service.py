# api/test/internal/service/test_builtin_tool_credential_service.py
"""内置工具凭证：解析器优先级（DB→env）+ 服务白名单/掩码/探测。"""
import pytest

from internal.exception import NotFoundException, ValidateErrorException
from internal.service import tool_credential_resolver as resolver
from internal.service.builtin_tool_credential_service import (
    BuiltinToolCredentialService,
)


class _Provider:
    def __init__(self, name, credentials=None, label=""):
        self.name = name
        self.credentials = dict(credentials or {})
        self.label = label


class _FakeSession:
    def __init__(self, providers):
        self._providers = providers
        self._name = None
        self.commits = 0

    def query(self, _model):
        return self

    def filter_by(self, **kwargs):
        self._name = kwargs.get("name")
        return self

    def one_or_none(self):
        return next((p for p in self._providers if p.name == self._name), None)

    def all(self):
        return list(self._providers)

    def commit(self):
        self.commits += 1


class _FakeDB:
    def __init__(self, providers):
        self.session = _FakeSession(providers)


# ----------------------------------------------------------------------
# 解析器：DB 优先 → env 兜底
# ----------------------------------------------------------------------
def test_resolver_prefers_db(monkeypatch):
    monkeypatch.setattr(resolver, "_read_from_db", lambda name: "db-value" if name == "TAVILY_API_KEY" else "")
    monkeypatch.setenv("TAVILY_API_KEY", "env-value")
    assert resolver.get_tool_credential("TAVILY_API_KEY") == "db-value"


def test_resolver_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(resolver, "_read_from_db", lambda name: "")
    monkeypatch.setenv("TAVILY_API_KEY", "env-value")
    assert resolver.get_tool_credential("TAVILY_API_KEY") == "env-value"


def test_resolver_empty_when_absent(monkeypatch):
    monkeypatch.setattr(resolver, "_read_from_db", lambda name: "")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert resolver.get_tool_credential("TAVILY_API_KEY") == ""


def test_resolver_alias_order(monkeypatch):
    monkeypatch.setattr(resolver, "_read_from_db", lambda name: "db" if name == "ATLAS_CLOUD_API_KEY" else "")
    assert resolver.get_tool_credential("ATLASCLOUD_API_KEY", "ATLAS_CLOUD_API_KEY") == "db"


# ----------------------------------------------------------------------
# 服务：白名单 / 加密 / 掩码 / 探测
# ----------------------------------------------------------------------
def _service(providers):
    return BuiltinToolCredentialService(db=_FakeDB(providers))


def test_update_rejects_unknown_key():
    svc = _service([_Provider("tavily")])
    with pytest.raises(ValidateErrorException):
        svc.update_provider_credentials("tavily", {"NOT_ALLOWED_KEY": "x"})


def test_update_rejects_unknown_provider():
    svc = _service([])
    with pytest.raises(NotFoundException):
        svc.update_provider_credentials("no-such-provider", {})


def test_update_encrypts_and_masks():
    provider = _Provider("tavily", label="Tavily")
    svc = _service([provider])
    result = svc.update_provider_credentials("tavily", {"TAVILY_API_KEY": "tvly-secret-123456"})
    # 落库为密文，返回为掩码
    assert provider.credentials["TAVILY_API_KEY"].startswith("gAAAAA")
    assert result["credentials"]["TAVILY_API_KEY"].startswith("tvly")
    assert "*" in result["credentials"]["TAVILY_API_KEY"]


def test_update_empty_value_clears_key():
    provider = _Provider("tavily", credentials={"TAVILY_API_KEY": "gAAAAA-old"})
    svc = _service([provider])
    svc.update_provider_credentials("tavily", {"TAVILY_API_KEY": ""})
    assert "TAVILY_API_KEY" not in provider.credentials


def test_get_credential_roundtrip():
    provider = _Provider("tavily")
    svc = _service([provider])
    svc.update_provider_credentials("tavily", {"TAVILY_API_KEY": "tvly-secret-123456"})
    assert svc.get_credential("TAVILY_API_KEY") == "tvly-secret-123456"


def test_list_providers_reports_source(monkeypatch):
    provider = _Provider("tavily", credentials={"TAVILY_API_KEY": "gAAAAA-not-valid-but-nonempty"})
    svc = _service([provider])
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    rows = {row["provider"]: row for row in svc.list_providers()}
    tavily_keys = {k["key"]: k for k in rows["tavily"]["keys"]}
    assert tavily_keys["TAVILY_API_KEY"]["configured"] is True
    assert tavily_keys["TAVILY_API_KEY"]["source"] == "db"


def test_probe_reports_missing(monkeypatch):
    svc = _service([_Provider("tavily")])
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    result = svc.probe_provider("tavily")
    assert result["ok"] is False
    assert result["missing"] == ["TAVILY_API_KEY"]


def test_probe_web_tools_all_missing_is_ok(monkeypatch):
    svc = _service([_Provider("web_tools")])
    for key in ("TAVILY_API_KEY", "EXA_API_KEY", "SERPAPI_API_KEY", "BRAVE_SEARCH_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    result = svc.probe_provider("web_tools")
    # web_tools 允许全缺（免费 ddgs 兜底）
    assert result["ok"] is True


# ----------------------------------------------------------------------
# 依赖联动（P1-1）
# ----------------------------------------------------------------------
def test_dependency_status_without_requirements():
    svc = _service([])
    result = svc.dependency_status("time")
    assert result == {"has_requirements": False, "status": "ready", "missing": []}


def test_dependency_status_missing_required_key(monkeypatch):
    svc = _service([_Provider("tavily")])
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    result = svc.dependency_status("tavily")
    assert result["status"] == "not_configured"
    assert result["missing"] == ["TAVILY_API_KEY"]


def test_dependency_status_web_tools_always_ready(monkeypatch):
    svc = _service([_Provider("web_tools")])
    for key in ("TAVILY_API_KEY", "EXA_API_KEY", "SERPAPI_API_KEY", "BRAVE_SEARCH_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    result = svc.dependency_status("web_tools")
    # 键"任一即可" + ddgs 兜底 → 恒 ready
    assert result["status"] == "ready"
    assert len(result["missing"]) == 4


def test_placeholder_env_treated_as_not_configured(monkeypatch):
    svc = _service([_Provider("tavily")])
    # `.env.example` 风格占位符不算已配置
    monkeypatch.setenv("TAVILY_API_KEY", "your-tavily-key-here")
    result = svc.dependency_status("tavily")
    assert result["status"] == "not_configured"
    assert result["missing"] == ["TAVILY_API_KEY"]


