import asyncio
from types import SimpleNamespace

from app.http.support import _to_thread
from internal.context import (
    clear_request_scope,
    has_request_context,
    request,
    set_request_scope,
)


def test_to_thread_preserves_request_context():
    request_scope = SimpleNamespace(
        headers={"User-Agent": "UA-Test"},
        remote_addr="1.2.3.4",
        method="GET",
        args={},
        json=None,
        files={},
        form={},
        cookies={},
    )
    set_request_scope(request_scope)
    try:
        result = asyncio.run(
            _to_thread(
                lambda: (
                    has_request_context(),
                    request.headers.get("User-Agent"),
                    request.remote_addr,
                )
            )
        )
    finally:
        clear_request_scope()

    assert result == (True, "UA-Test", "1.2.3.4")
