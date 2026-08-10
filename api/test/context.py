"""Test-only runtime/request context helpers (replaces the Flask bridge in tests)."""

from __future__ import annotations

import os
from contextlib import AbstractContextManager
from types import SimpleNamespace
from typing import Any

from internal import context as runtime_context
from werkzeug.datastructures import FileStorage, MultiDict


class TestApp:
    """Minimal runtime container compatible with ``internal.context`` proxies."""

    __test__ = False

    def __init__(
        self,
        name: str = "schema-tests",
        config: dict[str, Any] | None = None,
        root_path: str | None = None,
    ) -> None:
        self.name = name
        self.config = dict(config or {})
        self.root_path = root_path or os.getcwd()
        self.extensions: dict[str, Any] = {}
        self.injector: Any = None
        self.debug = False

    def app_context(self) -> "TestRuntimeContext":
        return TestRuntimeContext(self)

    def test_request_context(
        self,
        path: str = "/",
        **kwargs: Any,
    ) -> "TestRequestContext":
        return TestRequestContext(self, path=path, **kwargs)


class TestRuntimeContext(AbstractContextManager):
    __test__ = False

    def __init__(self, app: TestApp) -> None:
        self.app = app
        self._previous: Any = None

    def __enter__(self) -> TestApp:
        self._previous = runtime_context._app_container
        runtime_context.init_runtime(self.app)
        return self.app

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        runtime_context.init_runtime(self._previous)


class TestRequestContext(AbstractContextManager):
    __test__ = False

    def __init__(
        self,
        app: TestApp,
        *,
        path: str = "/",
        method: str = "GET",
        headers: dict[str, str] | None = None,
        environ_base: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
        json: Any = None,
        content_type: str | None = None,
        form: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        args: dict[str, Any] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> None:
        self.app = app
        self.content_type = content_type
        self._previous: Any = None
        normalized_files = dict(files or {})
        normalized_form = dict(form or {})
        if form is None and data is not None:
            for key, value in data.items():
                if (
                    isinstance(value, tuple)
                    and len(value) == 2
                    and hasattr(value[0], "read")
                ):
                    normalized_files[key] = FileStorage(
                        stream=value[0],
                        filename=value[1],
                    )
                elif hasattr(value, "filename"):
                    normalized_files[key] = value
                else:
                    normalized_form[key] = value
        self.scope = SimpleNamespace(
            headers=dict(headers or {}),
            remote_addr=(environ_base or {}).get("REMOTE_ADDR", ""),
            method=method,
            args=dict(args or {}),
            json=json,
            form=MultiDict(normalized_form),
            files=MultiDict(normalized_files),
            cookies=dict(cookies or {}),
        )

    def __enter__(self) -> SimpleNamespace:
        self._previous = runtime_context._app_container
        runtime_context.init_runtime(self.app)
        runtime_context.set_request_scope(self.scope)
        return self.scope

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        runtime_context.clear_request_scope()
        runtime_context.init_runtime(self._previous)
