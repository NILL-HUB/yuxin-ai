from __future__ import annotations

from types import SimpleNamespace

import pytest

from internal.model.cli import CliProvider, CliTool
from internal.service.cli_service import CliService


# ---------------------------------------------------------------------------
# expand_tool_schema：能力说明书 → cli_tool 行数据
# ---------------------------------------------------------------------------


def test_expand_tool_schema_expands_valid_entries():
    schema = {
        "caption": {
            "description": "一站式生成字幕并烧录",
            "parameters": {"type": "object", "properties": {"video": {"type": "string"}}},
        },
        "translate": {"description": "翻译字幕", "parameters": {"type": "object", "properties": {}}},
    }

    rows = CliService.expand_tool_schema(schema)

    assert sorted(r["name"] for r in rows) == ["caption", "translate"]
    caption = next(r for r in rows if r["name"] == "caption")
    assert caption["description"] == "一站式生成字幕并烧录"
    assert caption["input_schema"]["type"] == "object"
    assert caption["task_keywords"] == ["caption"]


def test_expand_tool_schema_ignores_malformed_entries():
    schema = {"ok": {"description": "d"}, "bad": "not-a-dict", "": {"description": "empty-key"}}

    rows = CliService.expand_tool_schema(schema)

    assert [r["name"] for r in rows] == ["ok"]


def test_expand_tool_schema_non_dict_inputs():
    assert CliService.expand_tool_schema(None) == []
    assert CliService.expand_tool_schema("nope") == []
    assert CliService.expand_tool_schema([]) == []


def test_expand_tool_schema_parameters_not_dict_falls_back_to_empty():
    rows = CliService.expand_tool_schema({"x": {"description": "d", "parameters": "bad"}})

    assert rows[0]["input_schema"] == {}


# ---------------------------------------------------------------------------
# build_mcp_shaped_bindings / build_selected_tools：复用 McpToolFactory 执行
# ---------------------------------------------------------------------------


def _provider(**overrides) -> SimpleNamespace:
    base = dict(
        id="p1",
        name="vc",
        label="VideoCaptioner",
        description="字幕一条龙",
        command="cli-anything-vc",
        args=["--json"],
        env={"API_KEY": "enc:xxx"},
        timeout_seconds=30,
        tool_schema={"caption": {"description": "一站式生成字幕并烧录", "parameters": {}}},
        enabled=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_mcp_shaped_bindings_forwards_cli_transport():
    bindings = CliService.build_mcp_shaped_bindings([_provider()], tool_names=["caption"])

    assert len(bindings) == 1
    b = bindings[0]
    assert b["transport"] == "cli"
    assert b["command"] == "cli-anything-vc"
    assert b["tool_names"] == ["caption"]
    assert b["tool_schema"] == {"caption": {"description": "一站式生成字幕并烧录", "parameters": {}}}
    assert b["env"] == {"API_KEY": "enc:xxx"}
    assert b["timeout_seconds"] == 30
    assert b["enabled"] is True


def test_build_mcp_shaped_bindings_empty_providers():
    assert CliService.build_mcp_shaped_bindings([]) == []


def test_build_selected_tools_forwards_to_mcp_factory(monkeypatch):
    captured: dict = {}

    class _FakeFactory:
        def get_tools(self, bindings, mcp_tool_snapshots=None):
            captured["bindings"] = bindings
            captured["snapshots"] = mcp_tool_snapshots
            return ["tool-obj"]

    import internal.service.cli_service as cli_service_module

    monkeypatch.setattr(cli_service_module, "McpToolFactory", _FakeFactory)

    tools = CliService.build_selected_tools([_provider()], tool_names=["caption"])

    assert tools == ["tool-obj"]
    assert captured["snapshots"] is None
    assert captured["bindings"][0]["transport"] == "cli"
    assert captured["bindings"][0]["tool_names"] == ["caption"]


def test_build_selected_tools_empty_providers_skips_factory(monkeypatch):
    called = {"n": 0}

    class _FakeFactory:
        def get_tools(self, bindings, mcp_tool_snapshots=None):
            called["n"] += 1
            return []

    import internal.service.cli_service as cli_service_module

    monkeypatch.setattr(cli_service_module, "McpToolFactory", _FakeFactory)

    assert CliService.build_selected_tools([]) == []
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# 写库路径：create_provider 展开 cli_tool
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, session: "_FakeSession", model):
        self._session = session
        self._model = model

    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        for row in self._session.added:
            if isinstance(row, self._model) and getattr(row, "id", None) == self._session._query_id:
                return row
        return None

    def delete(self):
        self._session.deleted.append(self._model)
        return 0


class _FakeSession:
    def __init__(self):
        self.added: list = []
        self.deleted: list = []
        self._query_id = None
        self.commits = 0

    def query(self, model):
        return _FakeQuery(self, model)

    def add(self, row):
        self.added.append(row)

    def flush(self):
        return None

    def commit(self):
        self.commits += 1


class _FakeDb:
    def __init__(self):
        self.session = _FakeSession()

    def auto_commit(self):
        db = self

        class _Ctx:
            def __enter__(self):
                return None

            def __exit__(self, *exc):
                db.session.commits += 1
                return False

        return _Ctx()


def _service_with_fake_db() -> tuple[CliService, _FakeDb]:
    db = _FakeDb()
    return CliService(db=db), db


def test_create_provider_expands_cli_tools():
    svc, db = _service_with_fake_db()

    provider = svc.create_provider(
        account_id="acct-1",
        name="vc",
        label="VideoCaptioner",
        description="字幕一条龙",
        category="video",
        command="cli-anything-vc",
        args=["--json"],
        env={"API_KEY": "plain"},
        tool_schema={"caption": {"description": "一站式生成字幕并烧录", "parameters": {"type": "object"}}},
        task_keywords=["字幕"],
        timeout_seconds=45,
    )

    assert provider.name == "vc"
    assert provider.source_type == "cli"
    assert provider.label == "VideoCaptioner"
    assert provider.timeout_seconds == 45
    assert provider.task_keywords == ["字幕"]
    # cli_tool 由 tool_schema 展开而来（候选唯一事实源）
    tool_rows = [r for r in db.session.added if isinstance(r, CliTool)]
    assert [t.name for t in tool_rows] == ["caption"]
    assert tool_rows[0].description == "一站式生成字幕并烧录"
    assert db.session.commits == 1


def test_create_provider_encrypts_env(monkeypatch):
    calls: list[dict] = []

    import internal.service.cli_service as cli_service_module

    def _fake_ensure(env):
        calls.append(env)
        return {"API_KEY": "enc:xxx"}

    monkeypatch.setattr(cli_service_module, "ensure_encrypted_env", _fake_ensure)

    svc, _ = _service_with_fake_db()
    provider = svc.create_provider(
        account_id="acct-1",
        name="vc",
        label="",
        description="d",
        category="video",
        command="c",
        args=[],
        env={"API_KEY": "plain"},
        tool_schema={},
        task_keywords=[],
        timeout_seconds=30,
    )

    assert calls == [{"API_KEY": "plain"}]
    assert provider.env == {"API_KEY": "enc:xxx"}
    # label 为空时回退 name
    assert provider.label == "vc"


def test_create_provider_propagates_encryption_failure(monkeypatch):
    """env 加密失败必须显式抛出，不能静默存空 env（否则"配了却不生效"难查）。"""

    import internal.service.cli_service as cli_service_module

    def _boom(env):
        raise ValueError("encryption unavailable")

    monkeypatch.setattr(cli_service_module, "ensure_encrypted_env", _boom)

    svc, _ = _service_with_fake_db()
    with pytest.raises(ValueError, match="encryption unavailable"):
        svc.create_provider(
            account_id="acct-1",
            name="vc",
            label="VC",
            description="d",
            category="video",
            command="c",
            args=[],
            env={"API_KEY": "plain"},
            tool_schema={},
            task_keywords=[],
            timeout_seconds=30,
        )


def test_sync_tools_uses_tool_schema_as_single_source():
    svc, db = _service_with_fake_db()
    provider = CliProvider(
        name="vc",
        label="VC",
        description="d",
        command="c",
        tool_schema={
            "caption": {"description": "一站式", "parameters": {}},
            "bad": "not-a-dict",
        },
    )

    svc._sync_tools(provider)

    # 先删后建：tool_schema 是唯一权威
    assert db.session.deleted == [CliTool]
    added_tools = [r for r in db.session.added if isinstance(r, CliTool)]
    assert [t.name for t in added_tools] == ["caption"]


@pytest.mark.parametrize("tool_names", [None, ["caption"]])
def test_build_selected_tools_defaults_tool_names(tool_names):
    bindings = CliService.build_mcp_shaped_bindings([_provider()], tool_names=tool_names)

    assert bindings[0]["tool_names"] == (tool_names or [])
