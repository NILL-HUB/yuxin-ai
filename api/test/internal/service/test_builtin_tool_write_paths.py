"""builtin_tool 写路径测试（P1b 的板块样板前置）。

两条不变式：
1. 启停内置工具必须有写路径（此前缺失，而权限点已存在且描述就是"启停"）；
2. admin 编辑后必须置 source='custom'，否则下次启动 YAML 同步会覆盖掉编辑。

测试通过真实构造 `BuiltinToolService(builtin_provider_manager=...,
builtin_category_manager=...)` 得到实例，只 monkeypatch 模块内延迟 import 的
`db`（与 `_get_builtin_tools_from_db` 内部 `from ... import db` 的方式一致），
不重写被测逻辑。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

import internal.service.builtin_tool_service as mod


class _QueryStub:
    def __init__(self, row):
        self._row = row

    def filter_by(self, **kw):
        return self

    def filter(self, *a, **kw):
        return self

    def first(self):
        return self._row


class _SessionStub:
    def __init__(self, row):
        self._row = row
        self.commits = 0

    def query(self, *a, **kw):
        return _QueryStub(self._row)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass


class _AutoCommit:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._session.commit()
        return False


def _tool(enabled=True, source="catalog"):
    """工具替身：字段集与 `tool_to_dict` 的读取面一致（它会被序列化）。"""
    return SimpleNamespace(
        id=uuid4(),
        provider_id=uuid4(),
        name="host_os_tool",
        label="本机文件操作",
        description="desc",
        params=[],
        task_keywords=[],
        python_module="internal.core.tools.builtin_tools.providers.host_os",
        source=source,
        enabled=enabled,
        updated_at=None,
        created_at=None,
    )


def _service(monkeypatch, tool):
    """真实构造 BuiltinToolService，仅替换 `database_extension.db`。

    `set_tool_enabled` / `_get_builtin_tools_from_db` 内部走
    `from internal.extension.database_extension import db`，因此 patch 目标
    必须是**该模块的属性**（patch 本模块的 `mod.db` 是无效的——本模块从不
    把 db import 到自身命名空间）。
    """
    import internal.extension.database_extension as dbext

    from internal.service.builtin_tool_service import BuiltinToolService

    session = _SessionStub(tool)
    monkeypatch.setattr(
        dbext,
        "db",
        SimpleNamespace(session=session, auto_commit=lambda: _AutoCommit(session)),
    )
    svc = BuiltinToolService(
        builtin_provider_manager=SimpleNamespace(),
        builtin_category_manager=SimpleNamespace(),
    )
    return svc, session


class TestSetToolEnabled:
    def test_updates_row_and_marks_custom(self, monkeypatch):
        tool = _tool(enabled=True, source="catalog")
        svc, session = _service(monkeypatch, tool)

        result = svc.set_tool_enabled(tool.id, False, set_custom_source=True)

        assert tool.enabled is False
        assert tool.source == "custom", (
            "编辑后必须置 custom，否则下次启动 YAML 同步会覆盖该行"
        )
        assert result is tool
        assert session.commits == 1

    def test_keeps_catalog_when_not_requested(self, monkeypatch):
        tool = _tool(enabled=True, source="catalog")
        svc, _ = _service(monkeypatch, tool)

        svc.set_tool_enabled(tool.id, False, set_custom_source=False)

        assert tool.enabled is False
        assert tool.source == "catalog"

    def test_raises_for_missing_tool(self, monkeypatch):
        from internal.exception import NotFoundException

        svc, _ = _service(monkeypatch, None)
        with pytest.raises(NotFoundException):
            svc.set_tool_enabled(uuid4(), False)


class _SessionWithGet:
    """支持 `db.session.get(model, pk)` 的会话替身（admin 编辑端点用 get 而非 query）。"""

    def __init__(self, tool, provider=None):
        self._tool = tool
        self._provider = provider
        self.commits = 0

    def get(self, model, pk):
        name = getattr(model, "__name__", "")
        if name == "BuiltinTool":
            return self._tool
        return self._provider

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass


class TestAdminEditMarksCustom:
    """`_builtin_tool_update` 直接调真实实现，不重写其逻辑。"""

    def _run(self, monkeypatch, data):
        import contextlib

        import internal.extension.database_extension as dbext
        from internal.model.builtin_tool import BuiltinTool, BuiltinToolProvider

        tool = _tool(enabled=True, source="catalog")
        provider = SimpleNamespace(
            id=uuid4(),
            name="host_os",
            label="本机文件操作",
            description="desc",
            icon="old.svg",
            background="#fff",
            category="tool",
        )
        session = _SessionWithGet(tool, provider)
        monkeypatch.setattr(dbext, "db", SimpleNamespace(session=session))

        # `_builtin_tool_update` 内部 import app_session_scope —— patch 其
        # 所属模块，使其退化为 nullcontext（不触碰真实 db 生命周期）。
        import internal.lib.runtime_context as rc

        monkeypatch.setattr(rc, "app_session_scope", contextlib.nullcontext)

        from app.http.admin_routes_8 import _builtin_tool_update

        return _builtin_tool_update(tool.id, data), tool, session

    def test_edit_marks_tool_custom(self, monkeypatch):
        """PATCH 编辑后必须落 source='custom'，否则重启被 YAML 覆盖。

        builtin 域此前从未写过 custom，即这层双源保护一直失效——管理员改了
        task_keywords 之后，下次启动 sync_yaml_to_db() 会用 YAML 值无条件覆盖；
        而 task_keywords 决定 ToolSelectorService 的关键词快通道，有功能影响。
        """
        result, tool, session = self._run(monkeypatch, {"task_keywords": ["x"]})
        assert tool.source == "custom"
        assert tool.task_keywords == ["x"]
        assert session.commits == 1

    def test_edit_can_toggle_enabled(self, monkeypatch):
        result, tool, _ = self._run(monkeypatch, {"enabled": False})
        assert tool.enabled is False
        assert tool.source == "custom"

    def test_edit_rejects_non_bool_enabled(self, monkeypatch):
        result, tool, _ = self._run(monkeypatch, {"enabled": "yes"})
        assert result["_errors"]["enabled"]
        # 校验失败时不得改动数据
        assert tool.enabled is True
        assert tool.source == "catalog"
